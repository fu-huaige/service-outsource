"""Version-bound ARX training for the confirmed-model Worker."""

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import numpy as np
from algorithms.identifiability.regressor import IdentifiabilityError, build_regressor
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dataset import DatasetVersion, ProcessingRun
from app.schemas.experiment_spec import (
    ArxExperimentContract,
    ExperimentSpec,
    FeatureSpec,
    OeExperimentContract,
    RowRange,
    RowSet,
    SplitSpec,
    TimeAxis,
)
from app.schemas.model_catalog import ModelArtifactManifest
from app.schemas.modeling import ArxFitRequest
from app.services.experiment_spec_service import (
    bind_experiment_spec,
    compact_rows,
    sha256_file,
    spec_hash,
)
from app.services.model_registry import get_model, validate_parameters
from app.services.modeling_service import (
    ModelingDomainError,
    _persist_artifact,
    _split_indices,
    _structure,
    fit_arx_core,
    to_validation_data,
)
from app.services.version_data import (
    VersionSeries,
    attach_model_input_context,
    load_version_series,
    model_input_arrays,
)

ARX_IMPLEMENTATION = "arx-platform-1"
FIR_IMPLEMENTATION = "fir-platform-1"
OE_IMPLEMENTATION = "oe-platform-1"
DYNAMIC_IMPLEMENTATIONS = {"arx": ARX_IMPLEMENTATION, "fir": FIR_IMPLEMENTATION, "oe": OE_IMPLEMENTATION}


def dynamic_parameters(params: ArxFitRequest) -> dict:
    excluded = {"na", "simulation_horizons", "simulation_max_nfev"} if params.model_type == "FIR" else None
    return params.model_dump(mode="json", exclude=excluded)


async def _lag_version(session: AsyncSession, version: DatasetVersion, inputs: tuple[str, ...]) -> UUID | None:
    visited = set()
    current = version
    while current is not None:
        if current.id in visited or current.dataset_id != version.dataset_id:
            raise ValueError("ARX Lag lineage is invalid")
        visited.add(current.id)
        if current.operation_name == "preprocessing.lag_compensation":
            mapping = current.parameters.get("lag_map", {})
            if not isinstance(mapping, dict) or any(
                type(mapping.get(name)) is not int or mapping[name] < 0 for name in inputs
            ):
                raise ValueError("ARX Lag lineage does not cover the selected inputs")
            return current.id
        if current.parent_version_id is None:
            return None
        current = await session.get(DatasetVersion, current.parent_version_id)
    raise ValueError("ARX Lag lineage is incomplete")


async def validate_lag_reference(session: AsyncSession, spec: ExperimentSpec) -> None:
    contract = spec.arx_contract or spec.fir_contract or spec.oe_contract
    version = await session.get(DatasetVersion, spec.dataset_version_id)
    if contract is None or version is None or version.dataset_id != spec.dataset_id:
        raise ValueError("ARX requires bound Lag evidence")
    if await _lag_version(session, version, spec.input_columns) != contract.lag_compensation_version_id:
        raise ValueError("ARX Lag lineage differs from the bound contract")


def _feature(structure, parameters: ArxFitRequest) -> FeatureSpec:
    return FeatureSpec(
        kind="dynamic_lags",
        input_lags={
            name: tuple(range(structure.nk[name], structure.nk[name] + structure.nb[name]))
            for name in structure.input_columns
        },
        target_lags=tuple(range(1, structure.na + 1)),
        history_window=structure.max_history,
        initialization_policy=parameters.initialization_policy,
    )


def _split(count: int, params: ArxFitRequest, history: int) -> SplitSpec:
    bounds = _split_indices(count, params)
    return SplitSpec(
        train=(RowRange(start=0, stop=bounds.train_end),),
        validation=(RowRange(start=bounds.train_end, stop=bounds.val_end),),
        test=(RowRange(start=bounds.val_end, stop=count),),
        history_guard=max(history, params.history_guard or 0),
    )


async def build_dynamic_spec(
    session, *, kind, version, inputs, target, axis: TimeAxis, runs, overrides, series=None,
) -> ExperimentSpec:
    if kind not in DYNAMIC_IMPLEMENTATIONS:
        raise ValueError("Model is not a supported dynamic candidate")
    parameters = validate_parameters(kind, {
        "na": {"fir": 0, "arx": 1, "oe": 2}[kind],
        "nb": dict.fromkeys(inputs, 1),
        "delays": dict.fromkeys(inputs, 0),
        "estimator": "ridge",
        "ridge_alpha": 0.001,
        **overrides,
        "dataset_id": version.dataset_id,
        "version_id": version.id,
        "input_columns": list(inputs),
        "output_column": target,
    })
    try:
        structure = _structure(parameters, list(inputs))
        split = _split(version.row_count, parameters, structure.max_history)
    except (ModelingDomainError, IdentifiabilityError) as error:
        raise ValueError(error.message) from error
    contract_fields = {
        "parameters": dynamic_parameters(parameters),
        "lag_compensation_version_id": await _lag_version(session, version, inputs),
    }
    contract = ArxExperimentContract(**contract_fields)
    if kind == "oe":
        from app.services.oe_platform_adapter import oe_training_evidence

        if series is None:
            raise ValueError("OE requires the version-bound training series")
        evidence, evidence_digest = oe_training_evidence(parameters, series, structure, split)
        contract = OeExperimentContract(
            **contract_fields, simulation_intervals=evidence, training_data_sha256=evidence_digest,
        )
    return ExperimentSpec(
        task_type="dynamic_system_identification",
        dataset_id=version.dataset_id,
        dataset_version_id=version.id,
        dataset_version_sha256=version.sha256,
        row_count=version.row_count,
        input_columns=inputs,
        target_column=target,
        time_axis=axis,
        continuous_runs=runs,
        feature_spec=_feature(structure, parameters),
        split=split,
        **{f"{kind}_contract": contract},
    )


async def build_arx_spec(session, **kwargs) -> ExperimentSpec:
    return await build_dynamic_spec(session, kind="arx", **kwargs)


def validate_dynamic_source(
    spec: ExperimentSpec, series: VersionSeries, submitted: dict[str, object] | None = None,
) -> tuple[ArxFitRequest, RowSet]:
    kind = "oe" if spec.oe_contract else "fir" if spec.fir_contract else "arx"
    contract = spec.oe_contract or spec.fir_contract or spec.arx_contract
    if (
        spec.task_type != "dynamic_system_identification"
        or contract is None
        or spec.continuous_runs != (RowRange(start=0, stop=spec.row_count),)
        or spec.time_axis.sampling_status != "uniform"
        or spec.training_selection.mode != "full_train"
        or spec.evaluation.scopes != ("validation",)
        or set(spec.evaluation.prediction_modes) != {"one_step", "free_run"}
        or spec.evaluation.sample_indices
    ):
        raise ValueError("ARX requires a single continuous full-Train contract with fixed Validation")
    params = validate_parameters(kind, contract.parameters)
    if dynamic_parameters(params) != contract.parameters:
        raise ValueError("ARX contract parameters are not canonical")
    if submitted is not None and validate_parameters(
        kind, {**contract.parameters, **submitted}
    ) != params:
        raise ValueError("ARX parameters differ from the candidate Experiment Spec")
    if (
        (params.dataset_id, params.version_id) != (spec.dataset_id, spec.dataset_version_id)
        or tuple(params.input_columns) != spec.input_columns
        or params.output_column != spec.target_column
        or (kind != "oe" and (params.training_sample_indices or params.sample_weights)) or params.evaluate_test
    ):
        raise ValueError("ARX parameters do not bind to this full-Train data contract")
    try:
        structure = _structure(params, params.input_columns)
        if contract.lag_compensation_version_id is not None and any(structure.nk.values()):
            raise ValueError("Use zero relative delay on an already Lag-compensated version")
        if _feature(structure, params) != spec.feature_spec or _split(
            spec.row_count, params, structure.max_history
        ) != spec.split:
            raise ValueError("ARX lags or split differ from the candidate Experiment Spec")
        stop = spec.split.train[0].stop - spec.split.history_guard
        val_start = spec.split.validation[0].start + spec.split.history_guard
        val_stop = spec.split.validation[0].stop - spec.split.history_guard
        if stop <= structure.max_history or val_start >= val_stop:
            raise ValueError("ARX history guard leaves insufficient Train or Validation records")
        if spec.oe_contract:
            from app.services.oe_platform_adapter import oe_training_evidence

            intervals, digest = oe_training_evidence(params, series, structure, spec.split)
            if (
                intervals != spec.oe_contract.simulation_intervals
                or digest != spec.oe_contract.training_data_sha256
            ):
                raise ValueError("OE training intervals or data SHA256 changed")
            return params, RowSet(ranges=tuple(RowRange(start=r.start, stop=r.stop) for r in intervals))
        reg = build_regressor(
            inputs={name: series.values[name][:stop] for name in params.input_columns},
            output=series.values[params.output_column][:stop], structure=structure,
        )
    except (ModelingDomainError, IdentifiabilityError) as error:
        raise ValueError(error.message) from error
    regularized = params.resolved_estimator() != "ols" and (params.ridge_alpha or 0) > 0
    needed = 8 if regularized else 2 * reg.n_parameters + 1
    if reg.n_rows < needed:
        raise ValueError(f"ARX needs at least {needed} effective Train records")
    if params.resolved_estimator() == "ols":
        design = reg.features
        if params.fit_intercept:
            design = design - np.mean(design, axis=0)
        scale = np.std(design, axis=0)
        design = design / np.where(scale > 0, scale, 1.0)
        if params.fit_intercept:
            design = np.column_stack((design, np.ones(reg.n_rows)))
        if np.linalg.matrix_rank(design) < design.shape[1]:
            raise ValueError("ARX OLS design is rank deficient on Train")
    return params, compact_rows(int(row) for row in reg.time_indices)


@dataclass(frozen=True)
class ArxTrainingOutcome:
    model_id: UUID
    training_run_id: UUID
    manifest_status: str = "published"
    error_code: str | None = None


def validate_arx_source(spec, series, submitted=None) -> tuple[ArxFitRequest, RowSet]:
    if spec.arx_contract is None:
        raise ValueError("ARX requires its own contract")
    return validate_dynamic_source(spec, series, submitted)


async def fit_arx_with_manifest(factory, *, spec, parameters, artifact_root: Path) -> ArxTrainingOutcome:
    return await fit_dynamic_with_manifest(
        factory, spec=spec, parameters=parameters, artifact_root=artifact_root, kind="arx",
    )


async def fit_dynamic_with_manifest(factory, *, spec, parameters, artifact_root: Path, kind) -> ArxTrainingOutcome:
    from app.services.model_artifact_service import publish_verified_manifest

    async with factory() as session:
        spec = await bind_experiment_spec(session, spec=spec, artifact_root=artifact_root)
        await validate_lag_reference(session, spec)
        series = await load_version_series(
            session, dataset_id=spec.dataset_id, version_id=spec.dataset_version_id,
            artifact_root=artifact_root,
        )
        if getattr(spec, f"{kind}_contract") is None:
            raise ValueError("Dynamic training requires the selected model contract")
        params, rows = validate_dynamic_source(spec, series, dynamic_parameters(parameters))
        series = await attach_model_input_context(session, series, artifact_root=artifact_root)
    model_id, run_id = uuid4(), uuid4()
    spec_payload = spec.model_dump(mode="json")
    digest = spec_hash(spec)
    identity = {"model_id": str(model_id), "model_type_id": kind}
    async with factory() as session:
        session.add(ProcessingRun(
            id=run_id, dataset_id=spec.dataset_id, source_version_id=spec.dataset_version_id,
            run_type=f"modeling.{kind}", status="running",
            parameters={
                "experiment_spec": spec_payload, "experiment_spec_hash": digest,
                f"{kind}_parameters": dynamic_parameters(params),
            },
            result=identity,
        ))
        await session.commit()
    try:
        inputs = model_input_arrays(series, params.input_columns)
        # Keep the original boundaries while withholding Test values from the fitting core.
        val_end = spec.split.validation[0].stop
        masked = {name: np.concatenate((values[:val_end], np.full(spec.row_count - val_end, np.nan)))
                  for name, values in inputs.items()}
        values = series.values[params.output_column]
        output = np.concatenate((values[:val_end], np.full(spec.row_count - val_end, np.nan)))
        result = await asyncio.to_thread(
            fit_arx_core, inputs=masked, output=output, payload=params, input_columns=params.input_columns,
        )
        if result.prior_violations or (params.require_stable and not result.validation.stable):
            raise ValueError("ARX training violates an engineering prior or stability constraint")
        if spec.oe_contract:
            expected_lineage = [
                {"name": f"selected_interval_{i}", **interval.model_dump()}
                for i, interval in enumerate(spec.oe_contract.simulation_intervals)
            ]
            if (
                result.preprocessing.get("lineage") != expected_lineage
                or result.preprocessing.get("training_rows") != rows.count
            ):
                raise ValueError("OE solver used rows different from the locked simulation intervals")
            result = replace(result, training_rows=rows.count)
        if result.training_rows != rows.count:
            raise ValueError("ARX actual Train evidence differs from preflight")
        result.preprocessing["input_support_sources"] = {
            name: series.input_context_versions.get(name, str(series.version_id))
            for name in result.preprocessing["training_input_support"]
        }
        uri = _persist_artifact(
            artifact_root, model_id=model_id, series=series, payload=params, result=result, native=True,
            staged=kind == "oe",
        )
        manifest = ModelArtifactManifest(
            model_type_id=kind, model_id=model_id, training_run_id=run_id,
            implementation_id=get_model(kind).implementation_id, implementation_version=DYNAMIC_IMPLEMENTATIONS[kind],
            experiment_spec=spec, experiment_spec_hash=digest, effective_training_rows=rows,
            payload_uri=uri, payload_sha256=sha256_file(artifact_root / uri),
        )
        if spec.oe_contract:
            from app.services.oe_platform_adapter import finish_oe_publication

            async with factory() as session:
                run = await session.get(ProcessingRun, run_id)
                if run is None or run.status != "running" or run.result != identity:
                    raise ValueError("OE training record disappeared or changed")
                run.result = {
                    **identity, "effective_training_rows": rows.model_dump(mode="json"),
                    "payload_sha256": manifest.payload_sha256,
                    "validation": to_validation_data(result.validation).model_dump(mode="json"),
                }
                await session.commit()
                if not await finish_oe_publication(session, run, artifact_root):
                    raise ValueError("OE publication is owned by another worker")
            return ArxTrainingOutcome(model_id, run_id)
        publish_verified_manifest(artifact_root, manifest)
        async with factory() as session:
            run = await session.get(ProcessingRun, run_id)
            if run is None or run.status != "running" or run.result != identity:
                raise ValueError("ARX training record disappeared or changed")
            run.result = {
                **identity, "effective_training_rows": rows.model_dump(mode="json"),
                "payload_sha256": manifest.payload_sha256,
                "validation": to_validation_data(result.validation).model_dump(mode="json"),
            }
            run.status, run.finished_at = "succeeded", datetime.now(UTC)
            await session.commit()
    except Exception as error:
        async with factory() as session:
            run = await session.get(ProcessingRun, run_id)
            if run is not None and run.status == "running" and run.result == identity:
                run.status, run.finished_at = "failed", datetime.now(UTC)
                if kind == "oe":
                    from rq.timeouts import JobTimeoutException

                    run.result = {**identity, "failure_code": (
                        "OE_OPTIMIZER_TIMEOUT" if isinstance(error, JobTimeoutException)
                        else getattr(error, "code", "OE_TRAINING_FAILED")
                    )}
                await session.commit()
        raise
    return ArxTrainingOutcome(model_id, run_id)
