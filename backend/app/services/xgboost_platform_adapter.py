"""Version-bound XGBoost training, provenance verification, and publication."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import numpy as np
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dataset import DatasetVersion, ProcessingRun
from app.schemas.experiment_spec import ExperimentSpec
from app.schemas.model_catalog import XGBoostModelArtifactManifest
from app.schemas.xgboost import XGBoostArtifactMetadata, XGBoostParameters
from app.schemas.xgboost_platform import (
    MAX_FEATURE_NAME_LENGTH,
    MAX_FEATURES,
    XGBoostFitResponse,
    XGBoostPublicationData,
)
from app.services.dataset_version_io import artifact_matches_sha256
from app.services.experiment_spec_service import bind_experiment_spec, spec_hash
from app.services.model_artifact_service import ModelArtifactError, publish_verified_manifest
from app.services.model_data_adapter import BoundSource, PreparedBatch, build_table_samples
from app.services.model_registry import get_model
from app.services.version_data import load_version_series
from app.services.xgboost_artifact_service import (
    SavedXGBoostModel,
    read_xgboost_artifact,
    save_xgboost_artifact,
)
from app.services.xgboost_modeling_service import fit_xgboost_core, predict_xgboost

SessionFactory = Callable[[], AsyncSession]
RUN_TYPE = "modeling.xgboost"


class XGBoostTrainingError(ValueError):
    def __init__(self, model_id: UUID, training_run_id: UUID, stage: str, outcome: str):
        super().__init__("XGBoost training did not complete normally")
        self.model_id = model_id
        self.training_run_id = training_run_id
        self.stage = stage
        self.outcome = outcome


def _seed(spec: ExperimentSpec) -> int:
    return 0 if spec.random_seed is None else spec.random_seed


async def _prepare(
    session: AsyncSession, spec: ExperimentSpec, root: Path
) -> tuple[ExperimentSpec, PreparedBatch]:
    if spec.training_selection.mode != "full_train":
        raise ValueError("XGBoost platform training requires full Train")
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
    batch = build_table_samples(series, spec=bound, source=source, partition="train")
    if batch.evidence.anchor_rows.count < 2:
        raise ValueError("XGBoost requires at least two Train records")
    return bound, batch


def _parameters(spec: ExperimentSpec, batch: PreparedBatch, params: XGBoostParameters) -> dict:
    return {
        "experiment_spec": spec.model_dump(mode="json"),
        "experiment_spec_hash": batch.evidence.source.experiment_spec_hash,
        "dataset_sha256": batch.evidence.source.dataset_sha256,
        "xgboost_parameters": params.model_dump(mode="json"),
        "random_seed": _seed(spec),
        "planned_training_rows": batch.evidence.anchor_rows.model_dump(mode="json"),
    }


def _identity(model_id: UUID, run_id: UUID) -> dict:
    return {"model_id": str(model_id), "model_type_id": "xgboost", "training_run_id": str(run_id)}


def _result(metadata: XGBoostArtifactMetadata, batch: PreparedBatch, json_sha256: str) -> dict:
    return {
        "model_id": str(metadata.model_id),
        "model_type_id": metadata.model_type_id,
        "training_run_id": str(metadata.training_run_id),
        "effective_training_rows": batch.evidence.anchor_rows.model_dump(mode="json"),
        "training_rows": metadata.training_rows,
        "implementation_id": metadata.implementation_id,
        "implementation_version": metadata.implementation_version,
        "artifact": {
            "json_uri": f"models/xgboost/{metadata.model_id}.json",
            "json_sha256": json_sha256,
            "ubj_uri": f"models/xgboost/{metadata.ubj_filename}",
            "ubj_size_bytes": metadata.ubj_size_bytes,
            "ubj_sha256": metadata.ubj_sha256,
        },
    }


def _check_metadata(
    metadata: XGBoostArtifactMetadata,
    model_id: UUID,
    run_id: UUID,
    spec: ExperimentSpec,
    batch: PreparedBatch,
    params: XGBoostParameters,
) -> None:
    definition = get_model("xgboost")
    if (
        metadata.model_id != model_id
        or metadata.training_run_id != run_id
        or metadata.training_rows != batch.evidence.anchor_rows.count
        or metadata.feature_names != batch.inputs.feature_names
        or metadata.target_name != batch.target_name
        or metadata.parameters != params
        or metadata.random_seed != _seed(spec)
        or metadata.implementation_id != definition.implementation_id
        or metadata.implementation_version != definition.implementation_version
    ):
        raise ValueError("XGBoost payload differs from the verified training inputs")


def _fit_and_save(
    spec: ExperimentSpec,
    batch: PreparedBatch,
    params: XGBoostParameters,
    model_id: UUID,
    run_id: UUID,
    root: Path,
) -> tuple[XGBoostArtifactMetadata, str]:
    names = batch.inputs.feature_names
    booster = fit_xgboost_core(
        batch.inputs.x,
        batch.y,
        feature_names=names,
        target_name=batch.target_name,
        parameters=params,
        random_seed=_seed(spec),
    )
    metadata = save_xgboost_artifact(
        booster, artifact_root=root, model_id=model_id, training_run_id=run_id
    )
    digest = hashlib.sha256(metadata.model_dump_json(indent=2).encode("utf-8")).hexdigest()
    saved, digest = read_xgboost_artifact(
        model_id=model_id,
        artifact_root=root,
        expected_json_sha256=digest,
        expected_ubj=(metadata.ubj_size_bytes, metadata.ubj_sha256),
    )
    _check_metadata(saved.metadata, model_id, run_id, spec, batch, params)
    sample = batch.inputs.x[:32]
    if saved.metadata != metadata or not np.array_equal(
        predict_xgboost(booster, sample, feature_names=names),
        saved.predict(sample, feature_names=names),
    ):
        raise ValueError("Restored XGBoost model differs from the fitted model")
    return saved.metadata, digest


async def find_xgboost_run(session: AsyncSession, model_id: UUID) -> ProcessingRun | None:
    """Identify platform models using Run evidence, including non-successful runs."""
    runs = (
        await session.scalars(
            select(ProcessingRun)
            .where(
                ProcessingRun.result["model_id"].as_string() == str(model_id),
                or_(
                    ProcessingRun.run_type.in_((RUN_TYPE, "modeling.pls", "modeling.arx")),
                    ProcessingRun.result["model_type_id"].as_string() == "xgboost",
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
        if run.run_type == RUN_TYPE or run.result.get("model_type_id") == "xgboost"
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
        raise ModelArtifactError(
            "TRAINING_RUN_ID_MISMATCH", "Conflicting XGBoost training identity"
        )
    return run


async def verify_xgboost_model(
    session: AsyncSession,
    *,
    model_id: UUID,
    training_run_id: UUID,
    artifact_root: Path,
    manifest: XGBoostModelArtifactManifest | None = None,
) -> tuple[XGBoostModelArtifactManifest, SavedXGBoostModel]:
    with session.no_autoflush:
        run = await find_xgboost_run(session, model_id)
        if run is None:
            raise ModelArtifactError("TRAINING_RUN_MISSING", "XGBoost training record is missing")
        if run.id != training_run_id:
            raise ModelArtifactError("TRAINING_RUN_ID_MISMATCH", "Unexpected XGBoost training run")
        if run.status != "succeeded":
            raise ModelArtifactError(
                "TRAINING_RUN_NOT_SUCCEEDED", "XGBoost training did not succeed"
            )

        try:
            spec = ExperimentSpec.model_validate(run.parameters["experiment_spec"])
            params = XGBoostParameters.model_validate(run.parameters["xgboost_parameters"])
            bound, batch = await _prepare(session, spec, artifact_root)
            evidence = run.result["artifact"]
            definition = get_model("xgboost")
            expected = XGBoostModelArtifactManifest(
                model_id=model_id,
                training_run_id=run.id,
                implementation_id=definition.implementation_id,
                implementation_version=definition.implementation_version,
                experiment_spec=bound,
                experiment_spec_hash=batch.evidence.source.experiment_spec_hash,
                effective_training_rows=batch.evidence.anchor_rows,
                payload_uri=f"models/xgboost/{model_id}.json",
                payload_sha256=evidence["json_sha256"],
            )
            if (
                (run.dataset_id, run.source_version_id)
                != (bound.dataset_id, bound.dataset_version_id)
                or bound != spec
                or run.parameters != _parameters(bound, batch, params)
                or evidence["json_uri"] != expected.payload_uri
                or evidence["ubj_uri"] != f"models/xgboost/{model_id}.ubj"
                or (manifest is not None and manifest != expected)
            ):
                raise ValueError("Manifest or Run does not match the bound training source")
        except (ValueError, KeyError, TypeError) as error:
            raise ModelArtifactError(
                "XGBOOST_SOURCE_MISMATCH", "Invalid XGBoost training evidence"
            ) from error

        try:
            saved, digest = await asyncio.to_thread(
                read_xgboost_artifact,
                model_id=model_id,
                artifact_root=artifact_root,
                expected_json_sha256=expected.payload_sha256,
                expected_ubj=(evidence["ubj_size_bytes"], evidence["ubj_sha256"]),
            )
            _check_metadata(saved.metadata, model_id, run.id, bound, batch, params)
            if run.result != _result(saved.metadata, batch, digest):
                raise ValueError("Training result differs from the restored XGBoost model")
        except (ValueError, KeyError, TypeError) as error:
            raise ModelArtifactError(
                "XGBOOST_ARTIFACT_INVALID", "Invalid XGBoost model payload"
            ) from error
        return expected, saved


async def retry_xgboost_manifest(
    session_factory: SessionFactory, *, model_id: UUID, training_run_id: UUID, artifact_root: Path
) -> XGBoostPublicationData:
    async with session_factory() as session:
        manifest, _ = await verify_xgboost_model(
            session, model_id=model_id, training_run_id=training_run_id, artifact_root=artifact_root
        )
    await asyncio.to_thread(publish_verified_manifest, artifact_root, manifest)
    return XGBoostPublicationData(
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
            run = await find_xgboost_run(session, model_id)
            if run is None or run.id != run_id:
                return "unconfirmed"
            if run.status == "succeeded" and stage == "final_commit":
                await verify_xgboost_model(
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


async def fit_xgboost_on_version(
    session_factory: SessionFactory,
    *,
    spec: ExperimentSpec,
    parameters: XGBoostParameters,
    artifact_root: Path,
) -> XGBoostFitResponse:
    params = XGBoostParameters.model_validate(parameters.model_dump())
    params.booster_parameters(random_seed=_seed(spec))
    if len(spec.input_columns) > MAX_FEATURES or any(
        len(name) > MAX_FEATURE_NAME_LENGTH for name in spec.input_columns
    ):
        raise ValueError("Training features exceed the fixed prediction API limits")
    async with session_factory() as session:
        bound, batch = await _prepare(session, spec, artifact_root)
    model_id, run_id = uuid4(), uuid4()
    if model_id == run_id:
        raise ValueError("Model and training run identities must differ")
    identity = _identity(model_id, run_id)
    run_params = _parameters(bound, batch, params)
    stage = "create_run"
    try:
        async with session_factory() as session:
            if await find_xgboost_run(session, model_id) is not None:
                raise ValueError("XGBoost model identity already exists")
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
            _fit_and_save, bound, batch, params, model_id, run_id, artifact_root
        )
        stage = "verify_run"
        async with session_factory() as session:
            run = await find_xgboost_run(session, model_id)
            if (
                run is None
                or run.id != run_id
                or run.status != "running"
                or run.result != identity
                or run.parameters != run_params
                or (run.dataset_id, run.source_version_id)
                != (bound.dataset_id, bound.dataset_version_id)
            ):
                raise ValueError("XGBoost running record changed")
            run.result = _result(metadata, batch, digest)
            run.status, run.finished_at = "succeeded", datetime.now(UTC)
            stage = "final_commit"
            await session.commit()
    except Exception as error:
        outcome = await _recover(session_factory, model_id, run_id, stage, error, artifact_root)
        if outcome != "succeeded_confirmed":
            raise XGBoostTrainingError(model_id, run_id, stage, outcome) from error

    try:
        publication = await retry_xgboost_manifest(
            session_factory, model_id=model_id, training_run_id=run_id, artifact_root=artifact_root
        )
    except Exception as error:
        publication = XGBoostPublicationData(
            model_id=model_id,
            training_run_id=run_id,
            manifest_status="failed",
            manifest_retryable=not isinstance(error, ModelArtifactError)
            or error.code == "MANIFEST_PATH_INVALID",
            error_code=error.code
            if isinstance(error, ModelArtifactError)
            else "MANIFEST_PUBLICATION_FAILED",
        )
    return XGBoostFitResponse(
        **publication.model_dump(),
        dataset_version_id=bound.dataset_version_id,
        feature_names=batch.inputs.feature_names,
        target_name=batch.target_name,
        parameters=params,
        training_rows=batch.evidence.anchor_rows.count,
    )
