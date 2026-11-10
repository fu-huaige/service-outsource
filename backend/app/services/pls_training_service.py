"""Version-bound PLS training with owned transactions and exact run provenance."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import numpy as np
from numpy.typing import NDArray
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dataset import DatasetVersion, ProcessingRun
from app.schemas.experiment_spec import ExperimentSpec, RowSet
from app.schemas.pls import PLSArtifactProvenance, PLSBoundArtifactMetadata, PLSParameters
from app.services.dataset_version_io import DatasetVersionArtifactError, artifact_matches_sha256
from app.services.experiment_spec_service import (
    bind_experiment_spec,
    effective_ranges,
    spec_hash,
    validate_partition_coverage,
)
from app.services.pls_artifact_service import read_pls_artifact, save_pls_artifact
from app.services.pls_modeling_service import SavedPLSModel, fit_pls_core
from app.services.version_data import VersionDataError, load_version_series

SessionFactory = Callable[[], AsyncSession]


class PLSTrainingError(ValueError):
    def __init__(self, *, model_id: UUID, training_run_id: UUID, stage: str, outcome: str):
        super().__init__(f"PLS training failed at {stage}; database outcome: {outcome}")
        self.model_id = model_id
        self.training_run_id = training_run_id
        self.stage = stage
        self.outcome = outcome


@dataclass(frozen=True)
class _TrainingData:
    spec: ExperimentSpec
    rows: RowSet
    x: NDArray[np.float64]
    y: NDArray[np.float64]


def validate_pls_experiment_spec(spec: ExperimentSpec) -> ExperimentSpec:
    spec = ExperimentSpec.model_validate(spec.model_dump())
    feature = spec.feature_spec
    if (
        spec.task_type != "supervised_regression"
        or spec.application not in ("regression", "soft_sensor")
        or feature.kind != "tabular"
        or any(lags != (0,) for lags in feature.input_lags.values())
        or feature.target_lags
        or feature.history_window != 0
        or feature.prediction_horizon != 1
        or spec.split.history_guard != 0
        or feature.initialization_policy != "fixed"
        or spec.training_selection.mode != "full_train"
        or spec.evaluation.prediction_modes != ("prediction",)
    ):
        raise ValueError(
            "Unsupported PLS experiment: static, aligned, full-Train regression required"
        )
    validate_partition_coverage(spec)
    return spec


async def _prepare_training(
    session: AsyncSession,
    spec: ExperimentSpec,
    root: Path,
    parameters: PLSParameters,
) -> _TrainingData:
    spec = validate_pls_experiment_spec(spec)
    bound = await bind_experiment_spec(session, spec=spec, artifact_root=root)
    series = await load_version_series(
        session,
        version_id=bound.dataset_version_id,
        dataset_id=bound.dataset_id,
        artifact_root=root,
    )
    names, target = series.resolve_columns(
        input_columns=list(bound.input_columns),
        output_column=bound.target_column,
    )
    if (
        series.dataset_id != bound.dataset_id
        or series.version_id != bound.dataset_version_id
        or tuple(names) != bound.input_columns
        or target != bound.target_column
        or series.n_samples != bound.row_count
    ):
        raise ValueError("Loaded version identity, variables or row count mismatch")
    version = await session.get(DatasetVersion, bound.dataset_version_id, populate_existing=True)
    if (
        version is None
        or version.dataset_id != bound.dataset_id
        or (
            version.sha256 != bound.dataset_version_sha256
            or not artifact_matches_sha256(
                artifact_root=root,
                relative_path=version.artifact_path,
                expected_sha256=bound.dataset_version_sha256,
            )
        )
    ):
        raise ValueError("DatasetVersion SHA256 changed while reading")
    # Preserve every interval, including adjacent intervals belonging to different runs.
    rows = RowSet(ranges=effective_ranges(bound, "train"))
    columns = (*bound.input_columns, target)
    if any(series.values[name].shape != (bound.row_count,) for name in columns):
        raise ValueError("Version arrays do not preserve physical CSV row positions")

    def take(name: str) -> NDArray[np.float64]:
        return np.concatenate([series.values[name][r.start : r.stop] for r in rows.ranges])

    x = np.column_stack([take(name) for name in bound.input_columns])
    y = take(target)
    if (
        x.shape != (rows.count, len(bound.input_columns))
        or y.shape != (rows.count,)
        or rows.count < 2
        or parameters.n_components > min(x.shape)
        or not np.isfinite(x).all()
        or not np.isfinite(y).all()
    ):
        raise ValueError("Invalid PLS Train dimensions, n_components or nonfinite values")
    return _TrainingData(bound, rows, x, y)


def _parameters(spec: ExperimentSpec, rows: RowSet, parameters: PLSParameters) -> dict:
    return {
        "pls_parameters": parameters.model_dump(mode="json"),
        "experiment_spec": spec.model_dump(mode="json"),
        "experiment_spec_hash": spec_hash(spec),
        "declared_training_ranges": [r.model_dump(mode="json") for r in spec.split.train],
        "planned_training_rows": rows.model_dump(mode="json"),
    }


def _result(metadata: PLSBoundArtifactMetadata, json_digest: str) -> dict:
    source = metadata.provenance
    return {
        "model_id": str(metadata.model_id),
        "model_type_id": "pls",
        "effective_training_rows": source.effective_training_rows.model_dump(mode="json"),
        "training_rows": metadata.training_rows,
        "implementation_id": metadata.implementation_id,
        "implementation_version": metadata.implementation_version,
        "dependency_versions": {
            name: getattr(metadata, name)
            for name in (
                "sklearn_version",
                "numpy_version",
                "scipy_version",
                "python_version",
            )
        },
        "effective_n_components": metadata.effective_n_components,
        "warnings": list(metadata.training_warnings),
        "artifact": {
            "json_uri": f"models/pls/{metadata.model_id}.json",
            "json_sha256": json_digest,
            "npz_uri": f"models/pls/{metadata.npz_filename}",
            "npz_sha256": metadata.npz_sha256,
            "npz_size_bytes": metadata.npz_size_bytes,
        },
        "candidate_rows": {
            part: RowSet(ranges=effective_ranges(source.experiment_spec, part)).model_dump(
                mode="json"
            )
            for part in ("train", "validation", "test")
        },
        "preprocessing": {
            "method": "PLSRegression.internal",
            "scale": metadata.scale,
            "fit_partition": "train",
            "fit_rows": source.effective_training_rows.model_dump(mode="json"),
            "state_npz_sha256": metadata.npz_sha256,
        },
        "evaluation_status": "not_evaluated",
    }


def _same_json(left: object, right: object) -> bool:
    # Preserve strict JSON types: True is not a row count of 1.
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(
        right,
        sort_keys=True,
        allow_nan=False,
    )


async def _validate_run(
    session: AsyncSession,
    run: ProcessingRun | None,
    metadata: PLSBoundArtifactMetadata,
    json_digest: str,
    *,
    root: Path,
    status: str,
) -> None:
    source = metadata.provenance
    spec = validate_pls_experiment_spec(source.experiment_spec)
    if (
        run is None
        or run.id != source.training_run_id
        or run.run_type != "modeling.pls"
        or run.status != status
        or run.dataset_id != spec.dataset_id
        or run.source_version_id != spec.dataset_version_id
    ):
        raise ValueError("PLS training record identity or status mismatch")
    bound = await bind_experiment_spec(session, spec=spec, artifact_root=root)
    if spec_hash(bound) != source.experiment_spec_hash:
        raise ValueError("PLS bound Experiment Spec SHA256 mismatch")
    if source.effective_training_rows != RowSet(ranges=effective_ranges(bound, "train")):
        raise ValueError("Actual Train rows do not match full Train")
    if not _same_json(
        run.parameters, _parameters(bound, source.effective_training_rows, metadata.parameters)
    ):
        raise ValueError("PLS training parameters or Experiment Spec mismatch")
    if not _same_json(run.result, _result(metadata, json_digest)):
        raise ValueError("PLS training result or artifact digest mismatch")
    matches = list(
        (
            await session.scalars(
                select(ProcessingRun.id).where(
                    ProcessingRun.run_type == "modeling.pls",
                    ProcessingRun.status == "succeeded",
                    ProcessingRun.result["model_id"].as_string() == str(metadata.model_id),
                )
            )
        ).all()
    )
    expected = [source.training_run_id] if status == "succeeded" else []
    if matches != expected:
        raise ValueError("Ambiguous successful PLS training records")


async def load_persisted_pls_model(
    session: AsyncSession,
    *,
    model_id: UUID,
    artifact_root: Path,
) -> SavedPLSModel:
    """Read only; v1 remains loadable independently, but has no database proof."""
    with session.no_autoflush:
        saved, digest = read_pls_artifact(model_id=model_id, artifact_root=artifact_root)
        if not isinstance(saved.metadata, PLSBoundArtifactMetadata):
            raise ValueError("Persisted PLS requires v2 training provenance")
        run = await session.get(
            ProcessingRun,
            saved.metadata.provenance.training_run_id,
            populate_existing=True,
        )
        await _validate_run(
            session,
            run,
            saved.metadata,
            digest,
            root=artifact_root,
            status="succeeded",
        )
        return saved


async def _recover_failure(
    factory: SessionFactory,
    *,
    model_id: UUID,
    run_id: UUID,
    stage: str,
    error: Exception,
    root: Path,
) -> str:
    """A fresh session is mandatory after a failed/uncertain commit."""
    try:
        async with factory() as session:
            run = await session.get(ProcessingRun, run_id)
            if (
                run is None
                or run.run_type != "modeling.pls"
                or not isinstance(run.result, dict)
                or run.result.get("model_id") != str(model_id)
            ):
                return "unconfirmed"
            if run.status == "succeeded":
                if stage != "final_commit":
                    return "unconfirmed"
                await load_persisted_pls_model(session, model_id=model_id, artifact_root=root)
                return "succeeded_confirmed"
            if run.status == "failed":
                return "failed"
            if run.status != "running":
                return "unconfirmed"
            run.status = "failed"
            run.finished_at = datetime.now(UTC)
            run.result = {
                **run.result,
                "failure_stage": stage,
                "error_type": type(error).__name__,
            }
            await session.commit()
            return "failed"
    except Exception:
        # No success assertion, file deletion or invented failure record when DB is unavailable.
        return "unconfirmed"


async def fit_pls_on_version(
    session_factory: SessionFactory,
    *,
    spec: ExperimentSpec,
    artifact_root: Path,
    parameters: PLSParameters | None = None,
) -> SavedPLSModel:
    """Own all sessions; never commit a caller's unrelated pending database work."""
    parameters = (
        PLSParameters()
        if parameters is None
        else PLSParameters.model_validate(
            parameters.model_dump() if isinstance(parameters, PLSParameters) else parameters
        )
    )
    try:
        async with session_factory() as session:
            data = await _prepare_training(session, spec, artifact_root, parameters)
    except (VersionDataError, DatasetVersionArtifactError) as error:
        raise ValueError(f"PLS source data rejected: {error.code}") from error
    model_id, run_id = uuid4(), uuid4()
    if model_id == run_id:
        raise ValueError("Model and training run UUIDs must be different")
    stage = "create_run"
    try:
        async with session_factory() as session:
            session.add(
                ProcessingRun(
                    id=run_id,
                    dataset_id=data.spec.dataset_id,
                    source_version_id=data.spec.dataset_version_id,
                    run_type="modeling.pls",
                    status="running",
                    parameters=_parameters(data.spec, data.rows, parameters),
                    result={"model_id": str(model_id), "model_type_id": "pls"},
                )
            )
            await session.commit()
        stage = "fit"
        model = await asyncio.to_thread(
            fit_pls_core,
            data.x,
            data.y,
            feature_names=data.spec.input_columns,
            target_name=data.spec.target_column,
            parameters=parameters,
        )
        if (
            model.metadata.training_rows != data.rows.count
            or model.metadata.feature_names != data.spec.input_columns
            or model.metadata.target_name != data.spec.target_column
            or model.metadata.parameters != parameters
        ):
            raise ValueError("Fitted model does not match actual Train input")
        source = PLSArtifactProvenance(
            training_run_id=run_id,
            experiment_spec=data.spec,
            experiment_spec_hash=spec_hash(data.spec),
            effective_training_rows=data.rows,
        )
        stage = "save_artifact"
        save_pls_artifact(
            model,
            artifact_root=artifact_root,
            model_id=model_id,
            provenance=source,
        )
        stage = "read_artifact"
        saved, digest = read_pls_artifact(model_id=model_id, artifact_root=artifact_root)
        if not isinstance(saved.metadata, PLSBoundArtifactMetadata):
            raise ValueError("Version training must produce a PLS v2 artifact")
        saved_arrays = saved.arrays()
        if (
            saved.metadata.model_id != model_id
            or saved.metadata.provenance != source
            or any(
                not np.array_equal(saved_arrays[name], array)
                for name, array in model.arrays().items()
            )
            or any(
                getattr(saved.metadata, name) != getattr(model.metadata, name)
                for name in type(model.metadata).model_fields
            )
        ):
            raise ValueError("Read-back artifact differs from this fitted model")
        stage = "verify"
        async with session_factory() as session:
            run = await session.get(ProcessingRun, run_id)
            if run is None:
                raise ValueError("PLS running record disappeared")
            run.result = _result(saved.metadata, digest)
            await _validate_run(
                session,
                run,
                saved.metadata,
                digest,
                root=artifact_root,
                status="running",
            )
            run.status = "succeeded"
            run.finished_at = datetime.now(UTC)
            stage = "final_commit"
            await session.commit()
        return saved
    except Exception as error:
        outcome = await _recover_failure(
            session_factory,
            model_id=model_id,
            run_id=run_id,
            stage=stage,
            error=error,
            root=artifact_root,
        )
        raise PLSTrainingError(
            model_id=model_id,
            training_run_id=run_id,
            stage=stage,
            outcome=outcome,
        ) from error
