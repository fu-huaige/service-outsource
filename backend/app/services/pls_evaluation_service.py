"""Fixed PLS evaluation and independent history. No fitting or artifact writes."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dataset import DatasetVersion, ProcessingRun
from app.schemas.experiment_spec import ExperimentSpec, RowSet
from app.schemas.pls import (
    PLSBoundArtifactMetadata,
    PLSEvaluationHistory,
    PLSEvaluationHistoryEntry,
    PLSEvaluationHistoryQuery,
    PLSEvaluationRequest,
    PLSEvaluationResult,
    PLSPredictionSummary,
    PLSRegressionMetrics,
)
from app.services.dataset_version_io import artifact_matches_sha256
from app.services.experiment_spec_service import (
    _validate_rows,
    bind_experiment_spec,
    effective_ranges,
    iter_rows,
    spec_hash,
    validate_partition_coverage,
    within,
)
from app.services.model_artifact_service import load_model_instance
from app.services.modeling_service import _scores
from app.services.pls_modeling_service import SavedPLSModel
from app.services.version_data import load_version_series

SessionFactory = Callable[[], AsyncSession]


class PLSEvaluationError(ValueError):
    def __init__(self, *, evaluation_run_id: UUID, model_id: UUID, stage: str, outcome: str):
        super().__init__(f"PLS evaluation failed at {stage}; database outcome: {outcome}")
        self.evaluation_run_id = evaluation_run_id
        self.model_id = model_id
        self.stage = stage
        self.outcome = outcome


def _evaluation_rows(
    spec: ExperimentSpec, training_rows: RowSet, partition: str, root: Path
) -> RowSet:
    spec = ExperimentSpec.model_validate(spec.model_dump())
    if partition not in ("validation", "test") or partition not in spec.evaluation.scopes:
        raise ValueError("Evaluation partition was not declared in the training Spec")
    validate_partition_coverage(spec)
    rows = spec.evaluation.sample_indices.get(partition)
    if rows is None:
        rows = RowSet(ranges=effective_ranges(spec, partition))
    _validate_rows(spec, rows, partition, root)
    if not rows.count or training_rows.index_file is not None:
        raise ValueError("Empty evaluation or unsupported Train evidence")
    if rows.ranges:
        # Both lists are sorted. Preserve run boundaries; never compact adjacent rows.
        i = j = 0
        while i < len(rows.ranges) and j < len(training_rows.ranges):
            left, right = rows.ranges[i], training_rows.ranges[j]
            if max(left.start, right.start) < min(left.stop, right.stop):
                raise ValueError("Evaluation overlaps actual Train rows")
            if left.stop <= right.stop:
                i += 1
            else:
                j += 1
    elif any(within(row, training_rows.ranges) for row in iter_rows(rows, root)):
        raise ValueError("Evaluation overlaps actual Train rows")
    return rows


async def _load_context(session: AsyncSession, request: PLSEvaluationRequest, root: Path):
    instance = await load_model_instance(session, model_id=request.model_id, artifact_root=root)
    if (
        instance.model_id != request.model_id
        or instance.model_type_id != "pls"
        or instance.manifest is None
        or not isinstance(instance.payload, SavedPLSModel)
        or not isinstance(instance.payload.metadata, PLSBoundArtifactMetadata)
    ):
        raise ValueError("Evaluation requires the original manifested PLS model")
    model = instance.payload
    metadata = model.metadata
    source = metadata.provenance
    run = await session.get(ProcessingRun, instance.training_run_id)
    if run is None or run.status != "succeeded" or run.run_type != "modeling.pls":
        raise ValueError("The original training record must be succeeded")
    spec = ExperimentSpec.model_validate(run.parameters["experiment_spec"])
    if (
        instance.training_run_id != source.training_run_id
        or instance.manifest.training_run_id != source.training_run_id
        or metadata.model_id != request.model_id
        or spec != source.experiment_spec
        or instance.manifest.experiment_spec != spec
        or spec_hash(spec) != source.experiment_spec_hash
        or instance.manifest.experiment_spec_hash != source.experiment_spec_hash
        or model.metadata.feature_names != spec.input_columns
        or model.metadata.target_name != spec.target_column
        or model.metadata.n_features != len(spec.input_columns)
        or model.metadata.parameters.model_dump(mode="json") != run.parameters["pls_parameters"]
        or (run.dataset_id, run.source_version_id) != (spec.dataset_id, spec.dataset_version_id)
    ):
        raise ValueError("Saved PLS model and training source are inconsistent")
    actual = {
        "training_run_id": source.training_run_id,
        "dataset_id": spec.dataset_id,
        "dataset_version_id": spec.dataset_version_id,
        "dataset_sha256": spec.dataset_version_sha256,
    }
    for key, value in actual.items():
        asserted = getattr(request, key)
        if asserted is not None and asserted != value:
            raise ValueError(f"Evaluation source assertion mismatch: {key}")
    bound = await bind_experiment_spec(session, spec=spec, artifact_root=root)
    if spec_hash(bound) != source.experiment_spec_hash:
        raise ValueError("Evaluation Experiment Spec SHA256 mismatch")
    return (
        model,
        bound,
        {
            "model_id": str(request.model_id),
            "training_run_id": str(source.training_run_id),
            "dataset_id": str(spec.dataset_id),
            "source_version_id": str(spec.dataset_version_id),
            "dataset_sha256": spec.dataset_version_sha256,
            "experiment_spec_hash": source.experiment_spec_hash,
            "partition": request.partition,
        },
    )


async def _check_version_digest(session: AsyncSession, spec: ExperimentSpec, root: Path) -> None:
    version = await session.get(DatasetVersion, spec.dataset_version_id, populate_existing=True)
    if (
        version is None
        or version.dataset_id != spec.dataset_id
        or version.sha256 != spec.dataset_version_sha256
        or not artifact_matches_sha256(
            artifact_root=root,
            relative_path=version.artifact_path,
            expected_sha256=spec.dataset_version_sha256,
        )
    ):
        raise ValueError("Evaluation DatasetVersion SHA256 mismatch")


async def _read_data(
    session: AsyncSession, model: SavedPLSModel, spec: ExperimentSpec, rows: RowSet, root: Path
):
    await _check_version_digest(session, spec, root)
    series = await load_version_series(
        session, dataset_id=spec.dataset_id, version_id=spec.dataset_version_id, artifact_root=root
    )
    names, target = series.resolve_columns(
        input_columns=list(model.metadata.feature_names), output_column=model.metadata.target_name
    )
    if (
        (series.dataset_id, series.version_id) != (spec.dataset_id, spec.dataset_version_id)
        or tuple(names) != model.metadata.feature_names
        or target != model.metadata.target_name
        or target in names
        or series.n_samples != spec.row_count
        or any(series.values[c].shape != (spec.row_count,) for c in (*names, target))
    ):
        raise ValueError("Evaluation version, feature order or target mismatch")
    if rows.index_file is None:

        def take(name):
            return np.concatenate([series.values[name][r.start : r.stop] for r in rows.ranges])
    else:
        # Consume to EOF: count-limited fromiter would skip the final SHA check.
        indices = np.fromiter(iter_rows(rows, root), dtype=np.int64)
        if indices.size != rows.count:
            raise ValueError("Evaluation index count mismatch")

        def take(name):
            return series.values[name][indices]

    x = np.column_stack([take(name) for name in model.metadata.feature_names])
    y = take(target)
    if (
        x.shape != (rows.count, model.metadata.n_features)
        or y.shape != (rows.count,)
        or not np.isfinite(x).all()
        or not np.isfinite(y).all()
    ):
        raise ValueError(
            "Evaluation dimensions or nonfinite values are invalid; no rows were dropped"
        )
    await _check_version_digest(session, spec, root)
    return x, y


def _metrics_and_summary(actual, predicted):
    if (
        actual.ndim != 1
        or predicted.shape != actual.shape
        or not actual.size
        or (not np.isfinite(actual).all() or not np.isfinite(predicted).all())
    ):
        raise ValueError("Metrics require aligned finite predictions and observations")
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        scores = _scores(actual, predicted)
        metrics = PLSRegressionMetrics(
            **{key: scores[key] for key in ("r2", "rmse", "mae", "nrmse")}
        )
        residual = actual - predicted
        summary = PLSPredictionSummary(
            sample_count=int(actual.size),
            prediction_min=float(predicted.min()),
            prediction_max=float(predicted.max()),
            prediction_mean=float(predicted.mean()),
            residual_min=float(residual.min()),
            residual_max=float(residual.max()),
            residual_mean=float(residual.mean()),
        )
    return metrics, summary


def _identity_parameters(request: PLSEvaluationRequest) -> dict:
    return {
        "model_id": str(request.model_id),
        "partition": request.partition,
        "requested_range": {"from_training_spec": True, "partition": request.partition},
        "assertions": request.model_dump(
            mode="json", exclude_none=True, exclude={"model_id", "partition"}
        ),
    }


async def _record_failure(
    factory: SessionFactory,
    request: PLSEvaluationRequest,
    run_id: UUID,
    stage: str,
    error: Exception,
    identity: dict,
    expected: dict | None,
) -> str:
    try:
        async with factory() as session:
            run = await session.get(ProcessingRun, run_id)
            if (
                run is None
                or run.run_type != "modeling.pls_evaluation"
                or (run.result.get("model_id") != str(request.model_id))
            ):
                return "unconfirmed"
            if run.status == "succeeded":
                if (
                    stage == "final_commit"
                    and expected is not None
                    and (
                        json.dumps(run.result, sort_keys=True, allow_nan=False)
                        == json.dumps(expected, sort_keys=True, allow_nan=False)
                    )
                ):
                    return "succeeded_confirmed"
                return "unconfirmed"
            if run.status == "failed":
                return "failed"
            if run.status != "running":
                return "unconfirmed"
            run.status = "failed"
            run.finished_at = datetime.now(UTC)
            run.parameters = {**run.parameters, **identity}
            if identity:
                run.dataset_id = UUID(identity["dataset_id"])
                run.source_version_id = UUID(identity["source_version_id"])
            message = str(error) if isinstance(error, ValueError) else type(error).__name__
            run.result = {
                "model_id": str(request.model_id),
                "evaluation_run_id": str(run_id),
                "training_run_id": identity.get("training_run_id"),
                "partition": request.partition,
                "evaluation_status": "failed",
                "failure_stage": stage,
                "error_type": type(error).__name__,
                "error_message": message,
                "implementation_version": "pls-evaluation-1",
            }
            await session.commit()
            return "failed"
    except Exception:
        return "unconfirmed"


async def evaluate_saved_pls_model(
    session_factory: SessionFactory,
    *,
    request: PLSEvaluationRequest,
    artifact_root: Path,
) -> PLSEvaluationResult:
    request = PLSEvaluationRequest.model_validate(request.model_dump())
    run_id = uuid4()
    if run_id in (request.model_id, request.training_run_id):
        raise ValueError("Evaluation requires an independent UUID")
    stage, identity, expected = "create_run", {}, None
    try:
        async with session_factory() as session:
            session.add(
                ProcessingRun(
                    id=run_id,
                    run_type="modeling.pls_evaluation",
                    status="running",
                    parameters=_identity_parameters(request),
                    result={"model_id": str(request.model_id), "evaluation_run_id": str(run_id)},
                )
            )
            await session.commit()
        stage = "load_model"
        async with session_factory() as session:
            model, spec, identity = await _load_context(session, request, artifact_root)
            if run_id == model.metadata.provenance.training_run_id:
                raise ValueError("Evaluation UUID collides with training UUID")
            stage = "resolve_rows"
            rows = _evaluation_rows(
                spec,
                model.metadata.provenance.effective_training_rows,
                request.partition,
                artifact_root,
            )
            identity = {**identity, "requested_range": rows.model_dump(mode="json")}
            stage = "read_data"
            x, actual = await _read_data(session, model, spec, rows, artifact_root)
        stage = "predict"
        predicted = await asyncio.to_thread(
            model.predict, x, feature_names=model.metadata.feature_names
        )
        if predicted.shape != actual.shape or not np.isfinite(predicted).all():
            raise ValueError("Prediction shape or finiteness mismatch")
        stage = "metrics"
        metrics, summary = _metrics_and_summary(actual, predicted)
        result = PLSEvaluationResult(
            evaluation_run_id=run_id,
            model_id=request.model_id,
            training_run_id=model.metadata.provenance.training_run_id,
            dataset_id=spec.dataset_id,
            dataset_version_id=spec.dataset_version_id,
            dataset_sha256=spec.dataset_version_sha256,
            experiment_spec_hash=model.metadata.provenance.experiment_spec_hash,
            partition=request.partition,
            evaluation_rows=rows,
            sample_count=rows.count,
            metrics=metrics,
            prediction_summary=summary,
        )
        expected = result.model_dump(mode="json")
        stage = "save_result"
        async with session_factory() as session:
            run = await session.get(ProcessingRun, run_id)
            if run is None or run.status != "running":
                raise ValueError("Evaluation running record is missing or changed")
            run.dataset_id, run.source_version_id = spec.dataset_id, spec.dataset_version_id
            run.parameters = {
                **run.parameters,
                **identity,
                "requested_range": rows.model_dump(mode="json"),
            }
            run.result = expected
            run.status, run.finished_at = "succeeded", datetime.now(UTC)
            stage = "final_commit"
            await session.commit()
        return result
    except Exception as error:
        outcome = await _record_failure(
            session_factory, request, run_id, stage, error, identity, expected
        )
        raise PLSEvaluationError(
            evaluation_run_id=run_id, model_id=request.model_id, stage=stage, outcome=outcome
        ) from error


async def list_pls_evaluations(
    session: AsyncSession,
    *,
    model_id: UUID,
    partition: str | None = None,
    status: str | None = None,
    offset: int = 0,
    limit: int = 20,
) -> PLSEvaluationHistory:
    query = PLSEvaluationHistoryQuery(
        model_id=model_id, partition=partition, status=status, offset=offset, limit=limit
    )
    conditions = [
        ProcessingRun.run_type == "modeling.pls_evaluation",
        ProcessingRun.result["model_id"].as_string() == str(query.model_id),
    ]
    if query.partition is not None:
        conditions.append(ProcessingRun.parameters["partition"].as_string() == query.partition)
    if query.status is not None:
        conditions.append(ProcessingRun.status == query.status)
    with session.no_autoflush:
        total = await session.scalar(
            select(func.count()).select_from(ProcessingRun).where(*conditions)
        )
        runs = (
            await session.scalars(
                select(ProcessingRun)
                .where(*conditions)
                .order_by(ProcessingRun.created_at.desc(), ProcessingRun.id.desc())
                .offset(query.offset)
                .limit(query.limit)
            )
        ).all()
    entries = []
    for run in runs:
        detail = (
            PLSEvaluationResult.model_validate(run.result) if run.status == "succeeded" else None
        )
        entries.append(
            PLSEvaluationHistoryEntry(
                evaluation_run_id=run.id,
                model_id=query.model_id,
                training_run_id=detail.training_run_id
                if detail
                else run.result.get("training_run_id"),
                partition=run.parameters["partition"],
                evaluation_status=run.status,
                created_at=run.created_at,
                finished_at=run.finished_at,
                evaluation_rows=detail.evaluation_rows if detail else None,
                sample_count=detail.sample_count if detail else 0,
                metrics=detail.metrics if detail else None,
                prediction_summary=detail.prediction_summary if detail else None,
                failure_stage=run.result.get("failure_stage"),
                error_message=run.result.get("error_message"),
            )
        )
    return PLSEvaluationHistory(
        items=tuple(entries), total=total or 0, offset=query.offset, limit=query.limit
    )
