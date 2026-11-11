"""Version-bound TCN training, provenance verification, and publication."""

from __future__ import annotations

import asyncio
import hashlib
import math
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import numpy as np
from pydantic import TypeAdapter
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dataset import DatasetVersion, ProcessingRun
from app.schemas.experiment_spec import ExperimentSpec
from app.schemas.model_catalog import TCNModelArtifactManifest
from app.schemas.tcn import Seed, TCNArtifactMetadata, TCNParameters
from app.schemas.tcn_platform import (
    MAX_FEATURE_NAME_LENGTH,
    TCNFitResponse,
    TCNPublicationData,
)
from app.services.dataset_version_io import artifact_matches_sha256
from app.services.experiment_spec_service import bind_experiment_spec, spec_hash
from app.services.model_artifact_service import ModelArtifactError, publish_verified_manifest
from app.services.model_data_adapter import BoundSource
from app.services.model_registry import get_model
from app.services.sequence_data_adapter import SequenceSampleEvidence, TCNSamples, build_tcn_samples
from app.services.tcn_artifact_service import read_tcn_artifact, save_tcn_artifact
from app.services.tcn_modeling_service import TCNModel, fit_tcn_core
from app.services.version_data import VersionDataError, load_version_series

SessionFactory = Callable[[], AsyncSession]
RUN_TYPE = "modeling.tcn"
_SEED = TypeAdapter(Seed)


class TCNTrainingError(ValueError):
    def __init__(self, model_id: UUID, training_run_id: UUID, stage: str, outcome: str):
        super().__init__("TCN training did not complete normally")
        self.model_id = model_id
        self.training_run_id = training_run_id
        self.stage = stage
        self.outcome = outcome


def _seed(spec: ExperimentSpec) -> int:
    return 0 if spec.random_seed is None else spec.random_seed


async def _prepare(
    session: AsyncSession, spec: ExperimentSpec, root: Path, params: TCNParameters
) -> tuple[ExperimentSpec, TCNSamples]:
    if spec.training_selection.mode != "full_train":
        raise ValueError("TCN platform training requires full Train")
    time_axis = spec.time_axis
    period = time_axis.sample_period_seconds
    if (
        time_axis.column is None
        or not time_axis.column.strip()
        or time_axis.sampling_status != "uniform"
        or period is None
        or not math.isfinite(period)
        or period <= 0
    ):
        raise ValueError("TCN requires a named time column and a verified uniform sample period")
    bound = await bind_experiment_spec(session, spec=spec, artifact_root=root)
    series = await load_version_series(
        session,
        version_id=bound.dataset_version_id,
        dataset_id=bound.dataset_id,
        artifact_root=root,
    )
    version = await session.get(DatasetVersion, bound.dataset_version_id, populate_existing=True)
    if (
        version is None
        or version.dataset_id != bound.dataset_id
        or version.sha256 != bound.dataset_version_sha256
        or not artifact_matches_sha256(
            artifact_root=root,
            relative_path=version.artifact_path,
            expected_sha256=bound.dataset_version_sha256,
        )
    ):
        raise ValueError("DatasetVersion SHA256 or ownership changed while reading")
    source = BoundSource(
        bound.dataset_id, bound.dataset_version_id, bound.dataset_version_sha256, spec_hash(bound)
    )
    batch = build_tcn_samples(
        series, spec=bound, source=source, partition="train", parameters=params
    )
    return bound, batch


def _evidence(evidence: SequenceSampleEvidence) -> dict:
    return {
        "source": {
            "dataset_id": str(evidence.source.dataset_id),
            "dataset_version_id": str(evidence.source.dataset_version_id),
            "dataset_sha256": evidence.source.dataset_sha256,
            "experiment_spec_hash": evidence.source.experiment_spec_hash,
        },
        "partition": evidence.partition,
        "target_name": evidence.target_name,
        "feature_names": list(evidence.feature_names),
        "anchor_rows": evidence.anchor_rows.model_dump(mode="json"),
        "sample_count": evidence.sample_count,
        "history_lengths": [list(item) for item in evidence.history_lengths],
        "history_offsets": [-evidence.history_lengths[0][1], 0],
        "prediction_horizon": evidence.prediction_horizon,
        "target_offsets": list(evidence.target_offsets),
        "continuous_runs": [run.model_dump(mode="json") for run in evidence.continuous_runs],
        "record_positions_used": evidence.record_positions_used,
        "sampling_status": evidence.sampling_status,
        "rule_version": evidence.rule_version,
    }


def _parameters(spec: ExperimentSpec, batch: TCNSamples, params: TCNParameters) -> dict:
    return {
        "experiment_spec": spec.model_dump(mode="json"),
        "experiment_spec_hash": batch.evidence.source.experiment_spec_hash,
        "dataset_sha256": batch.evidence.source.dataset_sha256,
        "tcn_parameters": params.model_dump(mode="json"),
        "random_seed": _seed(spec),
        "planned_training_rows": batch.evidence.anchor_rows.model_dump(mode="json"),
    }


def _identity(model_id: UUID, run_id: UUID) -> dict:
    return {"model_id": str(model_id), "model_type_id": "tcn", "training_run_id": str(run_id)}


def _result(
    metadata: TCNArtifactMetadata, batch: TCNSamples, json_sha256: str, run_id: UUID
) -> dict:
    return {
        **_identity(metadata.model_id, run_id),
        "effective_training_rows": batch.evidence.anchor_rows.model_dump(mode="json"),
        "training_samples": metadata.training_samples,
        "implementation_id": get_model("tcn").implementation_id,
        "window_length": metadata.window_length,
        "training_loss": metadata.training_loss,
        "torch_version": metadata.torch_version,
        "numpy_version": metadata.numpy_version,
        "sequence_evidence": _evidence(batch.evidence),
        "implementation_version": metadata.implementation_version,
        "artifact": {
            "json_uri": f"models/tcn/{metadata.model_id}.json",
            "json_sha256": json_sha256,
            "npz_uri": f"models/tcn/{metadata.npz_filename}",
            "npz_size_bytes": metadata.npz_size_bytes,
            "npz_sha256": metadata.npz_sha256,
        },
    }


def _check_metadata(
    metadata: TCNArtifactMetadata,
    model_id: UUID,
    spec: ExperimentSpec,
    batch: TCNSamples,
    params: TCNParameters,
) -> None:
    definition = get_model("tcn")
    if (
        metadata.model_id != model_id
        or metadata.window_length != params.window_length
        or metadata.source_status != "unbound"
        or metadata.training_samples != batch.evidence.anchor_rows.count
        or metadata.feature_names != batch.feature_names
        or metadata.target_name != batch.target_name
        or metadata.parameters != params
        or metadata.random_seed != _seed(spec)
        or metadata.implementation_version != definition.implementation_version
    ):
        raise ValueError("TCN payload differs from the verified training inputs")


def _fit_and_save(
    spec: ExperimentSpec,
    batch: TCNSamples,
    params: TCNParameters,
    model_id: UUID,
    root: Path,
) -> tuple[TCNArtifactMetadata, str]:
    names = batch.feature_names
    fitted = fit_tcn_core(
        batch.x,
        batch.y,
        feature_names=names,
        target_name=batch.target_name,
        parameters=params,
        random_seed=_seed(spec),
    )
    # Assign the platform identity to the fitted model before publishing its payload.
    fitted = replace(fitted, metadata=fitted.metadata.model_copy(update={"model_id": model_id}))
    metadata = save_tcn_artifact(fitted, artifact_root=root)
    digest = hashlib.sha256(metadata.model_dump_json(indent=2).encode("utf-8")).hexdigest()
    saved, restored, digest = read_tcn_artifact(
        model_id=model_id,
        artifact_root=root,
        expected_json_sha256=digest,
        expected_npz=(metadata.npz_size_bytes, metadata.npz_sha256),
    )
    _check_metadata(restored, model_id, spec, batch, params)
    sample = batch.x[:32]
    if restored != metadata or not np.array_equal(
        fitted.predict(sample, feature_names=names),
        saved.predict(sample, feature_names=names),
    ):
        raise ValueError("Restored TCN model differs from the fitted model")
    return restored, digest


async def find_tcn_run(session: AsyncSession, model_id: UUID) -> ProcessingRun | None:
    """Identify platform models using Run evidence, including non-successful runs."""
    runs = (
        await session.scalars(
            select(ProcessingRun)
            .where(
                ProcessingRun.result["model_id"].as_string() == str(model_id),
                or_(
                    ProcessingRun.run_type.in_(
                        (RUN_TYPE, "modeling.pls", "modeling.arx", "modeling.xgboost")
                    ),
                    ProcessingRun.result["model_type_id"].as_string() == "tcn",
                ),
            )
            .execution_options(autoflush=False)
        )
    ).all()
    matching = [
        run
        for run in runs
        if isinstance(run.result, dict) and run.result.get("model_id") == str(model_id)
    ]
    candidates = [
        run
        for run in matching
        if run.run_type == RUN_TYPE or run.result.get("model_type_id") == "tcn"
    ]
    if not candidates:
        return None
    run = candidates[0]
    if (
        len(matching) != 1
        or run.run_type != RUN_TYPE
        or run.id == model_id
        or any(run.result.get(key) != value for key, value in _identity(model_id, run.id).items())
    ):
        raise ModelArtifactError("TRAINING_RUN_ID_MISMATCH", "Conflicting TCN training identity")
    return run


async def verify_tcn_model(
    session: AsyncSession,
    *,
    model_id: UUID,
    training_run_id: UUID,
    artifact_root: Path,
    manifest: TCNModelArtifactManifest | None = None,
) -> tuple[TCNModelArtifactManifest, TCNModel]:
    with session.no_autoflush:
        run = await find_tcn_run(session, model_id)
        if run is None:
            raise ModelArtifactError("TRAINING_RUN_MISSING", "TCN training record is missing")
        if run.id != training_run_id:
            raise ModelArtifactError("TRAINING_RUN_ID_MISMATCH", "Unexpected TCN training run")
        if run.status != "succeeded":
            raise ModelArtifactError("TRAINING_RUN_NOT_SUCCEEDED", "TCN training did not succeed")

        try:
            spec = ExperimentSpec.model_validate(run.parameters["experiment_spec"])
            params = TCNParameters.model_validate(run.parameters["tcn_parameters"])
            bound, batch = await _prepare(session, spec, artifact_root, params)
            evidence = run.result["artifact"]
            definition = get_model("tcn")
            expected = TCNModelArtifactManifest(
                model_id=model_id,
                training_run_id=run.id,
                implementation_id=definition.implementation_id,
                implementation_version=definition.implementation_version,
                experiment_spec=bound,
                experiment_spec_hash=batch.evidence.source.experiment_spec_hash,
                effective_training_rows=batch.evidence.anchor_rows,
                training_samples=batch.evidence.sample_count,
                payload_uri=f"models/tcn/{model_id}.json",
                payload_sha256=evidence["json_sha256"],
            )
            if (
                (run.dataset_id, run.source_version_id)
                != (bound.dataset_id, bound.dataset_version_id)
                or bound != spec
                or run.parameters != _parameters(bound, batch, params)
                or evidence["json_uri"] != expected.payload_uri
                or evidence["npz_uri"] != f"models/tcn/{model_id}.npz"
                or (manifest is not None and manifest != expected)
            ):
                raise ValueError("Manifest or Run does not match the bound training source")
        except (ValueError, KeyError, TypeError, VersionDataError) as error:
            raise ModelArtifactError(
                "TCN_SOURCE_MISMATCH", "Invalid TCN training evidence"
            ) from error

        try:
            saved, metadata, digest = await asyncio.to_thread(
                read_tcn_artifact,
                model_id=model_id,
                artifact_root=artifact_root,
                expected_json_sha256=expected.payload_sha256,
                expected_npz=(evidence["npz_size_bytes"], evidence["npz_sha256"]),
            )
            _check_metadata(metadata, model_id, bound, batch, params)
            if run.result != _result(metadata, batch, digest, run.id):
                raise ValueError("Training result differs from the restored TCN model")
        except (ValueError, KeyError, TypeError) as error:
            raise ModelArtifactError("TCN_ARTIFACT_INVALID", "Invalid TCN model payload") from error
        return expected, saved


async def retry_tcn_manifest(
    session_factory: SessionFactory, *, model_id: UUID, training_run_id: UUID, artifact_root: Path
) -> TCNPublicationData:
    async with session_factory() as session:
        manifest, _ = await verify_tcn_model(
            session, model_id=model_id, training_run_id=training_run_id, artifact_root=artifact_root
        )
    await asyncio.to_thread(publish_verified_manifest, artifact_root, manifest)
    return TCNPublicationData(
        model_id=model_id, training_run_id=training_run_id, manifest_status="published"
    )


async def _recover(
    session_factory: SessionFactory,
    model_id: UUID,
    run_id: UUID,
    stage: str,
    error: Exception,
    root: Path,
) -> str:
    try:
        async with session_factory() as session:
            run = await find_tcn_run(session, model_id)
            if run is None or run.id != run_id:
                return "unconfirmed"
            if run.status == "succeeded" and stage == "final_commit":
                await verify_tcn_model(
                    session, model_id=model_id, training_run_id=run_id, artifact_root=root
                )
                return "succeeded_confirmed"
            if run.status == "failed":
                return "failed"
            if run.status == "running":
                run.status, run.finished_at = "failed", datetime.now(UTC)
                run.result = {
                    **run.result,
                    "failure_stage": stage,
                    "error_type": type(error).__name__,
                }
                await session.commit()
                return "failed"
    except Exception:
        return "unconfirmed"
    return "unconfirmed"


async def fit_tcn_on_version(
    session_factory: SessionFactory,
    *,
    spec: ExperimentSpec,
    parameters: TCNParameters,
    artifact_root: Path,
) -> TCNFitResponse:
    params = TCNParameters.model_validate(parameters.model_dump())
    _SEED.validate_python(_seed(spec))
    if any(len(name) > MAX_FEATURE_NAME_LENGTH for name in spec.input_columns):
        raise ValueError("Training features exceed the fixed prediction API limits")
    async with session_factory() as session:
        bound, batch = await _prepare(session, spec, artifact_root, params)
    model_id, run_id = uuid4(), uuid4()
    if model_id == run_id:
        raise ValueError("Model and training run identities must differ")
    identity = _identity(model_id, run_id)
    run_params = _parameters(bound, batch, params)
    stage = "create_run"
    try:
        async with session_factory() as session:
            if await find_tcn_run(session, model_id) is not None:
                raise ValueError("TCN model identity already exists")
            session.add(
                ProcessingRun(
                    id=run_id,
                    dataset_id=bound.dataset_id,
                    source_version_id=bound.dataset_version_id,
                    run_type=RUN_TYPE,
                    status="running",
                    parameters=run_params,
                    result=identity,
                )
            )
            await session.commit()
        stage = "fit_and_save"
        metadata, digest = await asyncio.to_thread(
            _fit_and_save, bound, batch, params, model_id, artifact_root
        )
        stage = "verify_run"
        async with session_factory() as session:
            run = await find_tcn_run(session, model_id)
            if (
                run is None
                or run.id != run_id
                or run.status != "running"
                or run.result != identity
                or run.parameters != run_params
                or (run.dataset_id, run.source_version_id)
                != (bound.dataset_id, bound.dataset_version_id)
            ):
                raise ValueError("TCN running record changed")
            run.result = _result(metadata, batch, digest, run_id)
            run.status, run.finished_at = "succeeded", datetime.now(UTC)
            stage = "final_commit"
            await session.commit()
    except Exception as error:
        outcome = await _recover(session_factory, model_id, run_id, stage, error, artifact_root)
        if outcome != "succeeded_confirmed":
            raise TCNTrainingError(model_id, run_id, stage, outcome) from error

    try:
        publication = await retry_tcn_manifest(
            session_factory, model_id=model_id, training_run_id=run_id, artifact_root=artifact_root
        )
    except Exception as error:
        publication = TCNPublicationData(
            model_id=model_id,
            training_run_id=run_id,
            manifest_status="failed",
            manifest_retryable=not isinstance(error, ModelArtifactError)
            or error.code == "MANIFEST_PATH_INVALID",
            error_code=error.code
            if isinstance(error, ModelArtifactError)
            else "MANIFEST_PUBLICATION_FAILED",
        )
    return TCNFitResponse(
        **publication.model_dump(),
        dataset_version_id=bound.dataset_version_id,
        feature_names=batch.feature_names,
        target_name=batch.target_name,
        parameters=params,
        training_samples=batch.evidence.sample_count,
        training_loss=metadata.training_loss,
    )
