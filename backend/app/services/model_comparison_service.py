"""Read-only comparison of persisted evaluation metrics and target evidence."""

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dataset import ProcessingRun
from app.schemas.experiment_spec import ExperimentSpec, RowRange, RowSet
from app.schemas.model_comparison import (
    HorizonRanking,
    ModelComparisonCandidate,
    ModelComparisonRequest,
    ModelComparisonResult,
    ModelComparisonScope,
    RankedHorizon,
    RankingEntry,
)
from app.schemas.model_evaluation import (
    MetricName,
    ModelEvaluationResult,
    RegressionMetrics,
    TCNModelEvaluationResult,
    TimeXerModelEvaluationResult,
)
from app.services.experiment_spec_service import effective_ranges, iter_rows, spec_hash
from app.services.model_evaluation_service import RUN_TYPE
from app.services.model_registry import get_model


class _TCNComparisonResult(TCNModelEvaluationResult):
    # The comparison contract depends on the evaluation format, not the model core version.
    model_implementation_version: str


METRICS: tuple[MetricName, ...] = ("r2", "rmse", "mae", "nrmse")
RESULT_TYPES = {
    "pls": ModelEvaluationResult,
    "xgboost": ModelEvaluationResult,
    "tcn": _TCNComparisonResult,
    "timexer": TimeXerModelEvaluationResult,
}
SCOPE_FIELDS = (
    "dataset_id",
    "dataset_version_id",
    "dataset_sha256",
    "partition",
    "target_column",
    "prediction_length",
)
Coverage = tuple[tuple[int, int, RowRange], ...]
Rankings = dict[MetricName, tuple[RankingEntry, ...]]


class ModelComparisonError(ValueError):
    def __init__(self, code: str, run_id: UUID, field: str, *, status_code: int = 409):
        super().__init__(field)
        self.code = code
        self.run_id = run_id
        self.field = field
        self.status_code = status_code


def _invalid(run_id: UUID, field: str) -> ModelComparisonError:
    return ModelComparisonError("MODEL_COMPARISON_EVIDENCE_INVALID", run_id, field)


def _read_result(run: ProcessingRun) -> ModelEvaluationResult:
    if not isinstance(run.result, dict) or not isinstance(run.parameters, dict):
        raise _invalid(run.id, "evaluation")
    raw = run.result.get("evaluation")
    if not isinstance(raw, dict):
        raise _invalid(run.id, "evaluation")
    kind = raw.get("model_type_id")
    if not isinstance(kind, str) or kind not in RESULT_TYPES:
        raise _invalid(run.id, "model_type_id")
    try:
        result_type = RESULT_TYPES[kind]
        result = result_type.model_validate(raw)
    except ValidationError as error:
        location = error.errors()[0]["loc"]
        field = (
            str(location[0])
            if location and location[0] in result_type.model_fields
            else "evaluation"
        )
        raise _invalid(run.id, field) from error
    if result.evaluation_run_id != run.id or run.result.get("evaluation_run_id") != str(run.id):
        raise _invalid(run.id, "evaluation_run_id")
    if run.result.get("model_id") != str(result.model_id):
        raise _invalid(run.id, "model_id")
    if (run.dataset_id, run.source_version_id) != (result.dataset_id, result.dataset_version_id):
        raise _invalid(run.id, "dataset_version_id")
    for key in (
        "model_id",
        "model_type_id",
        "training_run_id",
        "dataset_id",
        "dataset_version_id",
        "dataset_sha256",
        "partition",
        "actual_rows",
        "experiment_spec_hash",
        "forecast_spec",
        "sequence_evidence",
    ):
        if run.parameters.get(key) != raw.get(key):
            raise _invalid(run.id, key)
    return result


def _training_spec(result: ModelEvaluationResult, run: ProcessingRun | None) -> ExperimentSpec:
    run_id = result.evaluation_run_id
    if (
        run is None
        or run.run_type != f"modeling.{result.model_type_id}"
        or run.status != "succeeded"
        or not isinstance(run.result, dict)
        or not isinstance(run.parameters, dict)
        or (run.dataset_id, run.source_version_id) != (result.dataset_id, result.dataset_version_id)
        or run.result.get("model_id") != str(result.model_id)
        or run.result.get("model_type_id") != result.model_type_id
    ):
        raise _invalid(run_id, "training_run_id")
    try:
        spec = ExperimentSpec.model_validate(run.parameters.get("experiment_spec"))
    except ValidationError as error:
        raise _invalid(run_id, "experiment_spec") from error
    if (
        spec_hash(spec) != result.experiment_spec_hash
        or run.parameters.get("experiment_spec_hash") != result.experiment_spec_hash
        or (spec.dataset_id, spec.dataset_version_id, spec.dataset_version_sha256)
        != (result.dataset_id, result.dataset_version_id, result.dataset_sha256)
        or result.partition not in spec.evaluation.scopes
    ):
        raise _invalid(run_id, "experiment_spec")
    if isinstance(result, TimeXerModelEvaluationResult):
        forecast = result.forecast_spec.model_dump(mode="json")
        if (
            run.parameters.get("forecast_spec") != forecast
            or run.result.get("forecast_spec") != forecast
        ):
            raise _invalid(run_id, "forecast_spec")
    return spec


def _coverage(
    spans: Iterable[tuple[int, int]],
    runs: tuple[RowRange, ...],
    *,
    allowed: tuple[RowRange, ...] | None = None,
    horizon: int = 1,
) -> Coverage:
    run_iter = iter(runs)
    partition_iter = iter(allowed or ())
    run, interval = next(run_iter, None), next(partition_iter, None)
    normalized: list[tuple[int, int, RowRange]] = []
    for start, stop in spans:
        last_stop = stop + horizon - 1
        while run is not None and run.stop <= start:
            run = next(run_iter, None)
        if run is None or not run.start <= start < stop <= last_stop <= run.stop:
            raise ValueError("Target rows must stay within their continuous run")
        if allowed is not None:
            while interval is not None and interval.stop <= start:
                interval = next(partition_iter, None)
            if interval is None or not interval.start <= start < last_stop <= interval.stop:
                raise ValueError("Target rows must stay within the evaluation partition")
        if normalized and normalized[-1][2] == run and start <= normalized[-1][1]:
            prior_start, prior_stop, _ = normalized[-1]
            normalized[-1] = (prior_start, max(stop, prior_stop), run)
        else:
            normalized.append((start, stop, run))
    return tuple(normalized)


def _anchor_spans(rows: RowSet, root: Path) -> Iterable[tuple[int, int]]:
    if rows.index_file is not None:
        return ((row, row + 1) for row in iter_rows(rows, root))
    return ((span.start, span.stop) for span in rows.ranges)


def _used_runs(coverage: Coverage) -> tuple[tuple[int, int], ...]:
    return tuple(dict.fromkeys((run.start, run.stop) for _, _, run in coverage))


def _target_coverage(
    result: ModelEvaluationResult, spec: ExperimentSpec, root: Path
) -> tuple[Coverage, ...]:
    run_id = result.evaluation_run_id
    horizon = (
        result.forecast_spec.prediction_length
        if isinstance(result, TimeXerModelEvaluationResult)
        else 1
    )
    runs = spec.continuous_runs
    try:
        anchors = _coverage(
            _anchor_spans(result.actual_rows, root),
            runs,
            allowed=effective_ranges(spec, result.partition),
            horizon=horizon,
        )
    except (ValueError, OSError, RuntimeError) as error:
        raise _invalid(run_id, "actual_rows") from error

    if isinstance(result, (TCNModelEvaluationResult, TimeXerModelEvaluationResult)):
        expected = {
            "source": {
                "dataset_id": str(result.dataset_id),
                "dataset_version_id": str(result.dataset_version_id),
                "dataset_sha256": result.dataset_sha256,
                "experiment_spec_hash": result.experiment_spec_hash,
            },
            "partition": result.partition,
            "target_name": spec.target_column,
            "feature_names": list(spec.input_columns),
            "anchor_rows": result.actual_rows.model_dump(mode="json"),
            "sample_count": result.sample_count,
            "prediction_horizon": horizon,
            "target_offsets": list(range(horizon)),
            "continuous_runs": [
                {"start": start, "stop": stop} for start, stop in _used_runs(anchors)
            ],
        }
        for key, value in expected.items():
            if result.sequence_evidence.get(key) != value:
                raise _invalid(run_id, f"sequence_evidence.{key}")

    if not isinstance(result, TimeXerModelEvaluationResult):
        return (anchors,)

    try:
        steps = tuple(
            _coverage(((span.start, span.stop) for span in rows.ranges), runs)
            for rows in result.target_rows_by_horizon
        )
        expected_steps = tuple(
            tuple((start + offset, stop + offset, run) for start, stop, run in anchors)
            for offset in range(horizon)
        )
        if steps != expected_steps:
            raise ValueError("Persisted target rows must match each horizon offset")
    except ValueError as error:
        raise _invalid(run_id, "target_rows_by_horizon") from error

    try:
        union = _coverage(((span.start, span.stop) for span in result.target_rows.ranges), runs)
        expected_union = _coverage(
            ((start, stop + horizon - 1) for start, stop, _ in anchors), runs
        )
        if union != expected_union:
            raise ValueError("Persisted target rows must match the union of horizons")
    except ValueError as error:
        raise _invalid(run_id, "target_rows") from error
    return steps


@dataclass(frozen=True)
class _Candidate:
    result: ModelEvaluationResult
    spec: ExperimentSpec
    targets: tuple[Coverage, ...]

    @property
    def scope(self) -> ModelComparisonScope:
        return ModelComparisonScope(
            dataset_id=self.result.dataset_id,
            dataset_version_id=self.result.dataset_version_id,
            dataset_sha256=self.result.dataset_sha256,
            partition=self.result.partition,
            target_column=self.spec.target_column,
            prediction_length=len(self.targets),
            sample_counts_by_horizon=tuple(
                sum(stop - start for start, stop, _ in step) for step in self.targets
            ),
            evaluation_count=1,
        )


def _check_compatible(reference: _Candidate, candidate: _Candidate) -> None:
    code = "MODEL_COMPARISON_INCOMPATIBLE"
    run_id = candidate.result.evaluation_run_id
    left, right = reference.scope, candidate.scope
    for field in SCOPE_FIELDS:
        if getattr(left, field) != getattr(right, field):
            raise ModelComparisonError(code, run_id, field)
    if tuple(map(_used_runs, reference.targets)) != tuple(map(_used_runs, candidate.targets)):
        raise ModelComparisonError(code, run_id, "continuous_runs")
    if candidate.targets != reference.targets:
        raise ModelComparisonError(code, run_id, "target_rows_by_horizon")


def _rank(results: list[tuple[ModelEvaluationResult, RegressionMetrics]]) -> Rankings:
    rankings = {}
    for metric in METRICS:
        values = []
        for result, scores in results:
            value = getattr(scores, metric)
            if value is not None:
                values.append((value, result))
        values.sort(
            key=lambda item: (-item[0] if metric == "r2" else item[0], str(item[1].model_id))
        )
        entries = []
        previous = None
        rank = 0
        for position, (value, result) in enumerate(values, start=1):
            if value != previous:
                rank = position
            entries.append(
                RankingEntry(
                    evaluation_run_id=result.evaluation_run_id,
                    model_id=result.model_id,
                    value=value,
                    rank=rank,
                )
            )
            previous = value
        rankings[metric] = tuple(entries)
    return rankings


def _ranks(rankings: Rankings, model_id: UUID) -> dict[MetricName, int | None]:
    return {
        name: next((entry.rank for entry in entries if entry.model_id == model_id), None)
        for name, entries in rankings.items()
    }


def _ranked_candidate(
    candidate: _Candidate, rankings: Rankings, horizons: tuple[HorizonRanking, ...]
) -> ModelComparisonCandidate:
    result = candidate.result
    ranked_steps = ()
    aggregation = None
    if horizons and isinstance(result, TimeXerModelEvaluationResult):
        aggregation = result.metric_aggregation
        ranked_steps = tuple(
            RankedHorizon(
                horizon_step=step.horizon_step,
                metrics=RegressionMetrics.model_validate(step.model_dump(exclude={"horizon_step"})),
                ranks=_ranks(ranking.rankings, result.model_id),
            )
            for step, ranking in zip(result.horizon_metrics, horizons, strict=True)
        )
    return ModelComparisonCandidate(
        evaluation_run_id=result.evaluation_run_id,
        model_id=result.model_id,
        model_type=result.model_type_id,
        model_name=get_model(result.model_type_id).display_name,
        feature_names=candidate.spec.input_columns,
        sample_count=result.sample_count,
        metrics=result.metrics,
        ranks=_ranks(rankings, result.model_id),
        horizons=ranked_steps,
        metric_aggregation=aggregation,
    )


async def compare_model_evaluations(
    session: AsyncSession, *, request: ModelComparisonRequest, artifact_root: Path
) -> ModelComparisonResult:
    request = ModelComparisonRequest.model_validate(request.model_dump())
    with session.no_autoflush:
        evaluations = {
            run.id: run
            for run in await session.scalars(
                select(ProcessingRun).where(ProcessingRun.id.in_(request.evaluation_run_ids))
            )
        }
        results = []
        seen_models = set()
        for run_id in request.evaluation_run_ids:
            run = evaluations.get(run_id)
            if run is None or run.run_type != RUN_TYPE:
                raise ModelComparisonError(
                    "MODEL_COMPARISON_EVALUATION_NOT_FOUND",
                    run_id,
                    "evaluation_run_id",
                    status_code=404,
                )
            if run.status != "succeeded":
                raise ModelComparisonError("MODEL_COMPARISON_NOT_SUCCEEDED", run_id, "status")
            result = _read_result(run)
            if result.model_id in seen_models:
                raise ModelComparisonError("MODEL_COMPARISON_DUPLICATE_MODEL", run_id, "model_id")
            seen_models.add(result.model_id)
            results.append(result)

        training = {
            run.id: run
            for run in await session.scalars(
                select(ProcessingRun).where(
                    ProcessingRun.id.in_([r.training_run_id for r in results])
                )
            )
        }
    candidates = []
    for result in results:
        spec = _training_spec(result, training.get(result.training_run_id))
        targets = await asyncio.to_thread(_target_coverage, result, spec, artifact_root)
        candidates.append(_Candidate(result, spec, targets))
    reference = candidates[0]
    for candidate in candidates[1:]:
        _check_compatible(reference, candidate)

    scope = reference.scope.model_copy(update={"evaluation_count": len(candidates)})
    rankings = _rank([(result, result.metrics) for result in results])
    horizons = ()
    if scope.prediction_length > 1:
        timexer = [result for result in results if isinstance(result, TimeXerModelEvaluationResult)]
        horizons = tuple(
            HorizonRanking(
                horizon_step=step + 1,
                rankings=_rank([(result, result.horizon_metrics[step]) for result in timexer]),
            )
            for step in range(scope.prediction_length)
        )
    return ModelComparisonResult(
        scope=scope,
        candidates=tuple(
            _ranked_candidate(candidate, rankings, horizons) for candidate in candidates
        ),
        rankings=rankings,
        horizon_rankings=horizons,
        aggregation_method="macro_average" if horizons else None,
        compatibility=(*SCOPE_FIELDS, "target_rows_by_horizon", "continuous_runs"),
    )
