"""Evaluate saved models on their original held-out data."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from platform import python_version
from uuid import UUID, uuid4

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dataset import DatasetVersion, ProcessingRun
from app.schemas.experiment_spec import ExperimentSpec, RowSet
from app.schemas.model_catalog import (
    PLSModelArtifactManifest,
    TCNModelArtifactManifest,
    XGBoostModelArtifactManifest,
)
from app.schemas.model_evaluation import (
    EvaluationModelType,
    ModelEvaluationRequest,
    ModelEvaluationResult,
    RegressionMetrics,
    TCNModelEvaluationResult,
)
from app.schemas.pls import PLSBoundArtifactMetadata
from app.services.dataset_version_io import artifact_matches_sha256
from app.services.experiment_spec_service import iter_rows, spec_hash
from app.services.model_artifact_service import load_model_instance
from app.services.model_data_adapter import (
    BoundSource,
    ResolvedRows,
    build_table_samples,
)
from app.services.modeling_service import _scores
from app.services.pls_modeling_service import SavedPLSModel
from app.services.sequence_data_adapter import build_tcn_samples
from app.services.tcn_modeling_service import TCNModel
from app.services.tcn_platform_adapter import _evidence as serialize_tcn_evidence
from app.services.version_data import FloatArray, load_version_series
from app.services.xgboost_artifact_service import SavedXGBoostModel

SessionFactory = Callable[[], AsyncSession]
RUN_TYPE = "modeling.model_evaluation"
IMPLEMENTATION_VERSION = "model-evaluation-1"


class ModelEvaluationError(ValueError):
    def __init__(self, *, evaluation_run_id: UUID, model_id: UUID, stage: str, outcome: str):
        super().__init__(f"Model evaluation failed at {stage}; database outcome: {outcome}")
        self.evaluation_run_id = evaluation_run_id
        self.model_id = model_id
        self.stage = stage
        self.outcome = outcome


@dataclass(frozen=True)
class _EvaluationSource:
    model: SavedPLSModel | SavedXGBoostModel | TCNModel
    model_type_id: EvaluationModelType
    training_run_id: UUID
    spec: ExperimentSpec
    source: BoundSource
    training_rows: RowSet


async def _load_source(session: AsyncSession, model_id: UUID, root: Path) -> _EvaluationSource:
    with session.no_autoflush:
        instance = await load_model_instance(session, model_id=model_id, artifact_root=root)
        model, manifest = instance.payload, instance.manifest
        if (
            instance.model_type_id == "pls"
            and isinstance(model, SavedPLSModel)
            and isinstance(model.metadata, PLSBoundArtifactMetadata)
            and isinstance(manifest, PLSModelArtifactManifest)
        ):
            model_type: EvaluationModelType = "pls"
        elif (
            instance.model_type_id == "xgboost"
            and isinstance(model, SavedXGBoostModel)
            and isinstance(manifest, XGBoostModelArtifactManifest)
        ):
            model_type = "xgboost"
        elif (
            instance.model_type_id == "tcn"
            and isinstance(model, TCNModel)
            and isinstance(manifest, TCNModelArtifactManifest)
        ):
            model_type = "tcn"
        else:
            raise ValueError("Evaluation requires a verified PLS, XGBoost or TCN Manifest")

        spec = manifest.experiment_spec
        if (
            instance.model_id != model_id
            or manifest.model_id != model_id
            or model.metadata.model_id != model_id
            or instance.training_run_id != manifest.training_run_id
            or instance.missing_provenance
            or manifest.experiment_spec_hash != spec_hash(spec)
            or model.metadata.feature_names != spec.input_columns
            or model.metadata.target_name != spec.target_column
        ):
            raise ValueError("Saved model identity, feature order or training Spec mismatch")

        run = await session.get(ProcessingRun, manifest.training_run_id, populate_existing=True)
        if (
            run is None
            or run.run_type != f"modeling.{model_type}"
            or run.status != "succeeded"
            or (run.dataset_id, run.source_version_id) != (spec.dataset_id, spec.dataset_version_id)
            or run.result.get("model_id") != str(model_id)
            or run.result.get("model_type_id") != model_type
            or run.parameters.get("experiment_spec_hash") != manifest.experiment_spec_hash
            or ExperimentSpec.model_validate(run.parameters.get("experiment_spec")) != spec
        ):
            raise ValueError("Evaluation requires the original succeeded training Run and source")
        rows = RowSet.model_validate(run.result.get("effective_training_rows"))
        training_count = (
            model.metadata.training_samples
            if isinstance(model, TCNModel)
            else model.metadata.training_rows
        )
        if rows != manifest.effective_training_rows or rows.count != training_count:
            raise ValueError("Actual training rows differ from the verified model")
    return _EvaluationSource(
        model=model,
        model_type_id=model_type,
        training_run_id=manifest.training_run_id,
        spec=spec,
        source=BoundSource(
            spec.dataset_id,
            spec.dataset_version_id,
            spec.dataset_version_sha256,
            manifest.experiment_spec_hash,
        ),
        training_rows=rows,
    )


def _resolve_requested_rows(
    spec: ExperimentSpec, partition: str, root: Path
) -> ResolvedRows | None:
    if partition not in spec.evaluation.scopes:
        raise ValueError("Evaluation partition was not declared in the training Spec")
    rows = spec.evaluation.sample_indices.get(partition)
    if rows is None:
        return None
    # Exhaust the iterator so external index count and SHA are checked.
    return ResolvedRows(rows, tuple(iter_rows(rows, root)) if rows.index_file else None)


async def _check_version_digest(session: AsyncSession, source: BoundSource, root: Path) -> None:
    version = await session.get(DatasetVersion, source.dataset_version_id, populate_existing=True)
    if (
        version is None
        or version.dataset_id != source.dataset_id
        or version.sha256 != source.dataset_sha256
        or not artifact_matches_sha256(
            artifact_root=root,
            relative_path=version.artifact_path,
            expected_sha256=source.dataset_sha256,
        )
    ):
        raise ValueError("Evaluation DatasetVersion SHA256 or ownership mismatch")


def _intervals(rows: RowSet, indices: tuple[int, ...] | None) -> Iterator[tuple[int, int]]:
    if indices is not None:
        yield from ((index, index + 1) for index in indices)
    else:
        yield from ((interval.start, interval.stop) for interval in rows.ranges)


def _assert_disjoint(
    training_rows: RowSet, actual_rows: RowSet, requested: ResolvedRows | None, root: Path
) -> None:
    training_indices = tuple(iter_rows(training_rows, root)) if training_rows.index_file else None
    actual_indices = None
    if actual_rows.index_file:
        if requested is None or requested.evidence != actual_rows or requested.indices is None:
            raise ValueError("Actual evaluation index is missing its verified selection")
        actual_indices = requested.indices
    training = _intervals(training_rows, training_indices)
    evaluation = _intervals(actual_rows, actual_indices)
    left, right = next(training, None), next(evaluation, None)
    while left is not None and right is not None:
        if max(left[0], right[0]) < min(left[1], right[1]):
            raise ValueError("Evaluation overlaps actual Train rows")
        if left[1] <= right[1]:
            left = next(training, None)
        else:
            right = next(evaluation, None)


def calculate_regression_metrics(actual: FloatArray, predicted: FloatArray) -> RegressionMetrics:
    if (
        not isinstance(actual, np.ndarray)
        or not isinstance(predicted, np.ndarray)
        or actual.ndim != 1
        or not actual.size
        or predicted.shape != actual.shape
        or actual.dtype.kind not in "iuf"
        or predicted.dtype.kind not in "iuf"
        or not np.isfinite(actual).all()
        or not np.isfinite(predicted).all()
    ):
        raise ValueError(
            "Evaluation requires aligned, nonempty, finite numeric observations and predictions"
        )
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        actual = np.asarray(actual, dtype=np.float64)
        predicted = np.asarray(predicted, dtype=np.float64)
        if not np.isfinite(actual).all() or not np.isfinite(predicted).all():
            raise ValueError("Evaluation values exceed the finite metric representation")
        scores = _scores(actual, predicted)
    return RegressionMetrics.model_validate(
        {key: scores[key] for key in ("r2", "rmse", "mae", "nrmse")}
    )


def _verified_parameters(context: _EvaluationSource) -> dict:
    return {
        "model_type_id": context.model_type_id,
        "training_run_id": str(context.training_run_id),
        "dataset_id": str(context.source.dataset_id),
        "dataset_version_id": str(context.source.dataset_version_id),
        "dataset_sha256": context.source.dataset_sha256,
        "experiment_spec_hash": context.source.experiment_spec_hash,
    }


def _is_initial_run(run: ProcessingRun, parameters: dict, result: dict) -> bool:
    return run.status == "running" and run.parameters == parameters and run.result == result


async def _recover(
    factory: SessionFactory,
    *,
    run_id: UUID,
    stage: str,
    error: Exception,
    initial_parameters: dict,
    initial_result: dict,
    evidence: dict,
    expected: ModelEvaluationResult | None,
) -> str:
    if stage == "create_run":
        return "unconfirmed"
    try:
        async with factory() as session:
            run = await session.get(ProcessingRun, run_id)
            if (
                run is None
                or run.run_type != RUN_TYPE
                or any(run.result.get(key) != value for key, value in initial_result.items())
            ):
                return "unconfirmed"
            if run.status == "succeeded":
                if (
                    stage == "final_commit"
                    and expected is not None
                    and run.parameters == {**initial_parameters, **evidence}
                    and (run.dataset_id, run.source_version_id)
                    == (expected.dataset_id, expected.dataset_version_id)
                    and json.dumps(run.result, sort_keys=True, allow_nan=False)
                    == json.dumps(
                        {**initial_result, "evaluation": expected.model_dump(mode="json")},
                        sort_keys=True,
                        allow_nan=False,
                    )
                ):
                    return "succeeded_confirmed"
                return "unconfirmed"
            if run.status == "failed":
                return "failed"
            if not _is_initial_run(run, initial_parameters, initial_result):
                return "unconfirmed"
            run.parameters = {**initial_parameters, **evidence}
            if "dataset_id" in evidence:
                run.dataset_id = UUID(evidence["dataset_id"])
                run.source_version_id = UUID(evidence["dataset_version_id"])
            run.result = {
                **initial_result,
                "evaluation": {
                    **evidence,
                    "partition": initial_parameters["partition"],
                    "evaluation_status": "failed",
                    "failure_stage": stage,
                    "error_type": type(error).__name__,
                    "implementation_version": IMPLEMENTATION_VERSION,
                },
            }
            run.status, run.finished_at = "failed", datetime.now(UTC)
            await session.commit()
            return "failed"
    except Exception:
        return "unconfirmed"


async def evaluate_saved_model(
    session_factory: SessionFactory,
    *,
    request: ModelEvaluationRequest,
    artifact_root: Path,
) -> ModelEvaluationResult:
    request = ModelEvaluationRequest.model_validate(request.model_dump())
    run_id = uuid4()
    if run_id == request.model_id:
        raise ValueError("Evaluation requires an independent run identity")
    initial_parameters = {
        "model_id": str(request.model_id),
        "partition": request.partition,
        "prediction_mode": "prediction",
    }
    initial_result = {"model_id": str(request.model_id), "evaluation_run_id": str(run_id)}
    stage = "create_run"
    evidence: dict = {}
    expected = None
    try:
        async with session_factory() as session:
            session.add(
                ProcessingRun(
                    id=run_id,
                    run_type=RUN_TYPE,
                    status="running",
                    parameters=initial_parameters,
                    result=initial_result,
                )
            )
            await session.flush()
            stage = "initial_commit"
            await session.commit()

        stage = "load_model"
        async with session_factory() as session:
            context = await _load_source(session, request.model_id, artifact_root)
            if run_id == context.training_run_id:
                raise ValueError("Evaluation run identity collides with the training Run")
            evidence = _verified_parameters(context)
            stage = "resolve_rows"
            requested = _resolve_requested_rows(context.spec, request.partition, artifact_root)
            stage = "read_data"
            await _check_version_digest(session, context.source, artifact_root)
            series = await load_version_series(
                session,
                dataset_id=context.source.dataset_id,
                version_id=context.source.dataset_version_id,
                artifact_root=artifact_root,
            )
            await _check_version_digest(session, context.source, artifact_root)

        stage = "build_samples"
        metadata = context.model.metadata
        sequence_details = {}
        result_type: type[ModelEvaluationResult] = ModelEvaluationResult
        if isinstance(context.model, TCNModel):
            tcn_metadata = context.model.metadata
            sequence = build_tcn_samples(
                series,
                spec=context.spec,
                source=context.source,
                partition=request.partition,
                requested_rows=requested,
                parameters=tcn_metadata.parameters,
            )
            x, y = sequence.x, sequence.y
            feature_names, target_name = sequence.feature_names, sequence.target_name
            actual_rows = sequence.evidence.anchor_rows
            expected_shape = (actual_rows.count, tcn_metadata.window_length, len(feature_names))
            sequence_details = {
                "window_length": tcn_metadata.window_length,
                "sequence_evidence": serialize_tcn_evidence(sequence.evidence),
                "model_implementation_version": tcn_metadata.implementation_version,
                "dependency_versions": {
                    "python": python_version(),
                    "numpy": np.__version__,
                    # Artifact restoration checks the installed PyTorch build.
                    "torch": tcn_metadata.torch_version,
                },
            }
            result_type = TCNModelEvaluationResult
        else:
            batch = build_table_samples(
                series,
                spec=context.spec,
                source=context.source,
                partition=request.partition,
                requested_rows=requested,
            )
            x, y = batch.inputs.x, batch.y
            feature_names, target_name = batch.inputs.feature_names, batch.target_name
            actual_rows = batch.evidence.anchor_rows
            expected_shape = (actual_rows.count, len(feature_names))

        _assert_disjoint(context.training_rows, actual_rows, requested, artifact_root)
        evidence = {**evidence, "actual_rows": actual_rows.model_dump(mode="json")}
        if feature_names != metadata.feature_names:
            raise ValueError("Evaluation feature order differs from the saved model")
        if (
            x.shape != expected_shape
            or y.shape != (actual_rows.count,)
            or target_name != metadata.target_name
        ):
            raise ValueError("Evaluation samples differ from their row or target evidence")
        evidence.update(sequence_details)

        stage = "predict"
        predicted = await asyncio.to_thread(context.model.predict, x, feature_names=feature_names)
        stage = "metrics"
        metrics = calculate_regression_metrics(y, predicted)
        expected = result_type(
            evaluation_run_id=run_id,
            model_id=request.model_id,
            model_type_id=context.model_type_id,
            training_run_id=context.training_run_id,
            dataset_id=context.source.dataset_id,
            dataset_version_id=context.source.dataset_version_id,
            dataset_sha256=context.source.dataset_sha256,
            experiment_spec_hash=context.source.experiment_spec_hash,
            partition=request.partition,
            actual_rows=actual_rows,
            sample_count=actual_rows.count,
            metrics=metrics,
            **sequence_details,
        )
        stage = "save_result"
        async with session_factory() as session:
            run = await session.get(ProcessingRun, run_id)
            if (
                run is None
                or run.run_type != RUN_TYPE
                or not _is_initial_run(run, initial_parameters, initial_result)
            ):
                raise ValueError("Evaluation running record is missing or changed")
            run.dataset_id, run.source_version_id = expected.dataset_id, expected.dataset_version_id
            run.parameters = {**initial_parameters, **evidence}
            # Training lookup interprets a top-level model_type_id as training identity.
            run.result = {**initial_result, "evaluation": expected.model_dump(mode="json")}
            run.status, run.finished_at = "succeeded", datetime.now(UTC)
            stage = "final_commit"
            await session.commit()
        return expected
    except Exception as error:
        outcome = await _recover(
            session_factory,
            run_id=run_id,
            stage=stage,
            error=error,
            initial_parameters=initial_parameters,
            initial_result=initial_result,
            evidence=evidence,
            expected=expected,
        )
        if outcome == "succeeded_confirmed" and expected is not None:
            return expected
        raise ModelEvaluationError(
            evaluation_run_id=run_id, model_id=request.model_id, stage=stage, outcome=outcome
        ) from error
