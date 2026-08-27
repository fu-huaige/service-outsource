"""Closed-loop preprocessing and structure search (phase 8).

The loop the brief asks for: pick preprocessing parameters, run the real pipeline, identify
a model, feed the identification metric back, and repeat until the best strategy is found.

Three things make it practical rather than merely correct:

* **The objective is validation free-run FIT**, not one-step prediction. Measured on the S6
  benchmark, one-step FIT spans 0.46 points across strategies where free-run spans 12.83,
  so optimising one-step is close to optimising noise.
* **Lineage-as-cache.** Consecutive trials usually change only model orders while the
  gating and selection parameters stay put; those stages are memoised by content-addressed
  key, so the expensive part runs once per distinct head configuration.
* **Strategy memory.** A finished study is stored against a profile fingerprint, and a new
  study on similar data enqueues those parameters as its first trials.

Test data never enters the objective. The best configuration is frozen first and persisted as
a formal model without opening the held-out Test split.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import numpy as np
import optuna
from algorithms.pipeline.cache import LineageCache, stage_key
from algorithms.pipeline.fingerprint import (
    ProfileFingerprint,
    build_fingerprint,
    fingerprint_distance,
)
from optuna.samplers import TPESampler
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dataset import ProcessingRun
from app.models.operation_log import OperationLog
from app.models.optimization import OptimizationStudy, OptimizationTrialRecord, StrategyMemory
from app.schemas.modeling import ArxFitData, ArxFitRequest
from app.schemas.optimization import (
    BaselineEvaluation,
    FinalTestEvaluation,
    OptimizationStartData,
    OptimizationStartRequest,
    OptimizationStatusData,
    OptimizationTrial,
)
from app.schemas.preprocessing import SegmentRequest
from app.services.contract_stubs import completed_task, queued_task
from app.services.evaluation_policy import DEFAULT_BASELINE_CONFIG
from app.services.job_queue import submit_optimization
from app.services.modeling_service import (
    ArxCoreResult,
    ModelingDomainError,
    fit_arx_core,
    fit_arx_on_version,
)
from app.services.segment_service import SegmentDomainError, run_segment_selection
from app.services.version_data import VersionDataError, VersionSeries, load_version_series

TOOL_VERSION = "1.0.0"
# A study is only warm-started from memory entries at least this similar. Beyond it the
# stored parameters describe a different kind of process and would waste trials.
WARM_START_MAX_DISTANCE = 0.35
WARM_START_LIMIT = 3
# Quantisation of the gating thresholds in the search space. See _suggest() for why.
THRESHOLD_STEP = 0.02
# The formal baseline remains OLS when the selected design is identifiable.  Sparse,
# heterogeneous excitation can make that exact selected matrix rank deficient even though
# the closed-loop search still has viable Ridge candidates.  Use the same conservative
# Ridge value already present in the structure grid, and record the fallback in provenance.
BASELINE_RIDGE_FALLBACK_ALPHA = 0.1
# Bounds the gating ranges so that low/high are both multiples of THRESHOLD_STEP.
_GATING_BOUNDS = {
    "max_anomaly_ratio": (0.02, 0.30),
    "max_missing_ratio": (0.02, 0.40),
    "min_input_activity_ratio": (0.02, 0.30),
}

optuna.logging.set_verbosity(optuna.logging.WARNING)


class OptimizationDomainError(Exception):
    """A client-safe optimisation failure for the standard error envelope."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


@dataclass
class TrialOutcome:
    """One evaluated configuration and everything worth persisting about it."""

    number: int
    state: str
    value: float | None
    params: dict[str, Any]
    metrics: dict[str, Any]
    cache_hit: bool
    duration_ms: float
    error_code: str | None = None


@dataclass
class StudyOutcome:
    """The finished search: trials, winner, and how much work the cache saved."""

    study_id: UUID
    trials: list[TrialOutcome]
    best_number: int | None
    best_value: float | None
    best_params: dict[str, Any]
    best_metrics: dict[str, Any]
    fingerprint: ProfileFingerprint
    statistics: dict[str, Any]
    warm_started_from: UUID | None = None
    warm_start_params: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class EvaluationOutcome:
    """One persisted non-Optuna evaluation run."""

    status: str
    parameters: dict[str, Any]
    validation_free_run_fit: float | None
    test_free_run_fit: float | None
    test_mae: float | None
    test_rmse: float | None
    test_r2: float | None
    test_one_step_fit: float | None
    test_free_run_mae: float | None
    test_free_run_rmse: float | None
    test_free_run_r2: float | None
    generalization_gap: float | None
    duration_ms: float
    started_at: datetime
    finished_at: datetime
    error_code: str | None = None
    best_trial_number: int | None = None


@dataclass(frozen=True)
class OptimizationStudyExecution:
    """One completed formal study, including the runs needed by an Agent step."""

    study_id: UUID
    source_version_id: UUID
    statistics: dict[str, Any]
    best_params: dict[str, Any]
    best_value: float | None
    baseline_processing_run_id: UUID
    optimized_model_id: UUID | None
    optimized_model_processing_run_id: UUID | None


@dataclass(frozen=True)
class AgentOptimizationStudyResult:
    """The compact, provenance-complete result of the Agent-only inline entry."""

    study_id: UUID
    status: str
    source_version_id: UUID
    baseline_model_id: UUID
    optimized_model_id: UUID
    best_params: dict[str, Any]
    best_value: float | None
    processing_run_ids: list[str]
    error_code: str | None = None
    error_message: str | None = None

def objective_value(result: ArxCoreResult) -> tuple[float, dict[str, Any]]:
    """Score a candidate model the way an APC engineer would rank it.

    Weights follow ALG-0.2 §7.1. Every term is bounded so a single pathological trial
    cannot dominate the search, and an unstable model is rejected outright rather than
    ranked, because no amount of fit makes an unstable model deployable.
    """

    free_run = result.metrics.val_free_run_fit
    if free_run is None or not np.isfinite(free_run):
        return float("-inf"), {"reason": "free_run_undefined"}
    if not result.validation.stable:
        return float("-inf"), {"reason": "unstable"}

    nrmse = result.metrics.val_rmse or 0.0
    spread = abs(result.metrics.val_fit or 0.0)
    normalised_error = nrmse / spread if spread > 0 else nrmse
    whiteness = result.validation.residual_whiteness_ratio
    whiteness = 1.0 if whiteness is None or not np.isfinite(whiteness) else whiteness
    complexity = result.structure.parameter_count / 40.0

    value = (
        0.45 * float(np.clip(free_run / 100.0, -1.0, 1.0))
        - 0.20 * float(np.clip(normalised_error, 0.0, 3.0))
        - 0.10 * (1.0 - float(np.clip(whiteness, 0.0, 1.0)))
        - 0.10 * float(np.clip(complexity, 0.0, 1.0))
    )
    breakdown = {
        "val_free_run_fit": float(free_run),
        "val_one_step_fit": result.metrics.val_fit,
        "residual_whiteness_ratio": whiteness,
        "complexity": complexity,
        "stable": result.validation.stable,
        "max_pole_modulus": result.validation.max_pole_modulus,
        "training_rows": result.training_rows,
    }
    return float(value), breakdown


def run_baseline(
    series: VersionSeries,
    payload: OptimizationStartRequest,
    *,
    input_columns: list[str],
    output_column: str,
) -> EvaluationOutcome:
    """Run the deterministic pre-Optuna baseline through the formal pipeline."""

    started_at = datetime.now(UTC)
    started = time.perf_counter()
    parameters = DEFAULT_BASELINE_CONFIG.to_payload(
        input_columns=input_columns,
        train_ratio=payload.train_ratio,
        validation_ratio=payload.validation_ratio,
    )
    try:
        selection = run_segment_selection(
            series,
            SegmentRequest(
                version_id=series.version_id,
                input_columns=input_columns,
                output_column=output_column,
                window_size=DEFAULT_BASELINE_CONFIG.window_size,
                max_segments=DEFAULT_BASELINE_CONFIG.max_segments,
                min_segment_length=DEFAULT_BASELINE_CONFIG.min_segment_length,
                max_missing_ratio=DEFAULT_BASELINE_CONFIG.max_missing_ratio,
                max_anomaly_ratio=DEFAULT_BASELINE_CONFIG.max_anomaly_ratio,
                min_input_activity_ratio=DEFAULT_BASELINE_CONFIG.min_input_activity_ratio,
                na=DEFAULT_BASELINE_CONFIG.selection_na,
                nb=DEFAULT_BASELINE_CONFIG.selection_nb,
                nk=DEFAULT_BASELINE_CONFIG.selection_nk,
                train_ratio=payload.train_ratio,
            ),
        )
        def fit(*, estimator: str, ridge_alpha: float | None) -> ArxCoreResult:
            return fit_arx_core(
                inputs={column: series.values[column] for column in input_columns},
                output=series.values[output_column],
                payload=ArxFitRequest(
                    version_id=series.version_id,
                    input_columns=input_columns,
                    output_column=output_column,
                    na=DEFAULT_BASELINE_CONFIG.na,
                    nb={column: DEFAULT_BASELINE_CONFIG.nb for column in input_columns},
                    delays={column: DEFAULT_BASELINE_CONFIG.nk for column in input_columns},
                    estimator=estimator,
                    ridge_alpha=ridge_alpha,
                    train_ratio=payload.train_ratio,
                    validation_ratio=payload.validation_ratio,
                    training_sample_indices=selection.selected_sample_indices,
                    evaluate_test=False,
                ),
                input_columns=input_columns,
            )

        try:
            result = fit(
                estimator=DEFAULT_BASELINE_CONFIG.estimator,
                ridge_alpha=DEFAULT_BASELINE_CONFIG.ridge_alpha,
            )
        except ModelingDomainError as error:
            if (
                error.code != "DESIGN_MATRIX_RANK_DEFICIENT"
                or DEFAULT_BASELINE_CONFIG.estimator != "ols"
            ):
                raise
            parameters.update(
                {
                    "estimator": "ridge",
                    "ridge_alpha": BASELINE_RIDGE_FALLBACK_ALPHA,
                    "fallback_reason": error.code,
                }
            )
            result = fit(estimator="ridge", ridge_alpha=BASELINE_RIDGE_FALLBACK_ALPHA)
        evaluation = _evaluation_from_result(
            result,
            parameters=parameters,
            started_at=started_at,
            started=started,
            require_test=False,
        )
        validation_objective, _ = objective_value(result)
        if not np.isfinite(validation_objective):
            evaluation.status = "failed"
            evaluation.error_code = "BASELINE_VALIDATION_REJECTED"
        return evaluation
    except (SegmentDomainError, ModelingDomainError) as error:
        return _failed_evaluation(
            parameters=parameters,
            started_at=started_at,
            started=started,
            error_code=error.code,
        )



async def _persist_optimized_model(
    session: AsyncSession,
    *,
    series: VersionSeries,
    payload: OptimizationStartRequest,
    outcome: StudyOutcome,
    input_columns: list[str],
    output_column: str,
    artifact_root: Path,
) -> ArxFitData:
    """Persist the validation-selected winner without evaluating the held-out Test split."""

    if outcome.best_number is None or not outcome.best_params:
        raise OptimizationDomainError(
            "BEST_TRIAL_UNAVAILABLE", "寻优未产生可持久化的 Best Trial。", status_code=409
        )

    parameters = dict(outcome.best_params)
    try:
        selection_params = _selection_params(
            parameters,
            input_columns,
            output_column,
            train_ratio=payload.train_ratio,
        )
        selection = run_segment_selection(
            series,
            SegmentRequest(version_id=series.version_id, **selection_params),
        )
        formal_payload = ArxFitRequest(
            version_id=series.version_id,
            input_columns=input_columns,
            output_column=output_column,
            na=int(parameters["na"]),
            nb={column: int(parameters["nb"]) for column in input_columns},
            delays={column: int(parameters["nk"]) for column in input_columns},
            estimator=parameters["estimator"],
            ridge_alpha=parameters.get("ridge_alpha"),
            train_ratio=payload.train_ratio,
            validation_ratio=payload.validation_ratio,
            training_sample_indices=selection.selected_sample_indices,
            evaluate_test=False,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise OptimizationDomainError(
            "BEST_TRIAL_PERSISTENCE_FAILED", "Best Trial 参数无法重放为正式 ARX 模型。"
        ) from error
    except SegmentDomainError as error:
        raise OptimizationDomainError(
            error.code, error.message, status_code=error.status_code, details=error.details
        ) from error

    return await fit_arx_on_version(session, payload=formal_payload, artifact_root=artifact_root)

def evaluate_best_trial(
    series: VersionSeries,
    payload: OptimizationStartRequest,
    outcome: StudyOutcome,
    *,
    input_columns: list[str],
    output_column: str,
) -> EvaluationOutcome:
    """Evaluate the validation-selected winner once on the held-out test tail."""

    started_at = datetime.now(UTC)
    started = time.perf_counter()
    parameters = dict(outcome.best_params)
    try:
        selection_params = _selection_params(
            parameters,
            input_columns,
            output_column,
            train_ratio=payload.train_ratio,
        )
        selection = run_segment_selection(
            series,
            SegmentRequest(version_id=series.version_id, **selection_params),
        )
        result = fit_arx_core(
            inputs={column: series.values[column] for column in input_columns},
            output=series.values[output_column],
            payload=ArxFitRequest(
                version_id=series.version_id,
                input_columns=input_columns,
                output_column=output_column,
                na=int(parameters["na"]),
                nb={column: int(parameters["nb"]) for column in input_columns},
                delays={column: int(parameters["nk"]) for column in input_columns},
                estimator=parameters["estimator"],
                ridge_alpha=parameters.get("ridge_alpha"),
                train_ratio=payload.train_ratio,
                validation_ratio=payload.validation_ratio,
                training_sample_indices=selection.selected_sample_indices,
                evaluate_test=True,
            ),
            input_columns=input_columns,
        )
        evaluation = _evaluation_from_result(
            result,
            parameters=parameters,
            started_at=started_at,
            started=started,
            best_trial_number=outcome.best_number,
        )
        validation_fit = outcome.best_metrics.get("val_free_run_fit")
        if isinstance(validation_fit, (int, float)) and evaluation.test_free_run_fit is not None:
            evaluation.validation_free_run_fit = float(validation_fit)
            evaluation.generalization_gap = float(validation_fit) - evaluation.test_free_run_fit
        return evaluation
    except (KeyError, SegmentDomainError, ModelingDomainError) as error:
        return _failed_evaluation(
            parameters=parameters,
            started_at=started_at,
            started=started,
            error_code=error.code if isinstance(error, (SegmentDomainError, ModelingDomainError)) else "BEST_TRIAL_REPLAY_FAILED",
            best_trial_number=outcome.best_number,
        )


def _evaluation_from_result(
    result: ArxCoreResult,
    *,
    parameters: dict[str, Any],
    started_at: datetime,
    started: float,
    best_trial_number: int | None = None,
    require_test: bool = True,
) -> EvaluationOutcome:
    one_step = result.metrics.one_step.get("test") if require_test else None
    free_run = result.metrics.free_run.get("test") if require_test else None
    test_fit = free_run.fit if free_run is not None else None
    validation_fit = result.metrics.val_free_run_fit
    error_code = None
    if validation_fit is None or (require_test and test_fit is None):
        error_code = "EVALUATION_METRIC_UNAVAILABLE"
    finished_at = datetime.now(UTC)
    return EvaluationOutcome(
        status="failed" if error_code else "succeeded",
        parameters=parameters,
        validation_free_run_fit=validation_fit,
        test_free_run_fit=test_fit,
        test_mae=one_step.mae if one_step is not None else None,
        test_rmse=one_step.rmse if one_step is not None else None,
        test_r2=one_step.r2 if one_step is not None else None,
        test_one_step_fit=one_step.fit if one_step is not None else None,
        test_free_run_mae=free_run.mae if free_run is not None else None,
        test_free_run_rmse=free_run.rmse if free_run is not None else None,
        test_free_run_r2=free_run.r2 if free_run is not None else None,
        generalization_gap=(validation_fit - test_fit)
        if validation_fit is not None and test_fit is not None
        else None,
        duration_ms=(time.perf_counter() - started) * 1000.0,
        started_at=started_at,
        finished_at=finished_at,
        error_code=error_code,
        best_trial_number=best_trial_number,
    )


def _failed_evaluation(
    *,
    parameters: dict[str, Any],
    started_at: datetime,
    started: float,
    error_code: str,
    best_trial_number: int | None = None,
) -> EvaluationOutcome:
    return EvaluationOutcome(
        status="failed",
        parameters=parameters,
        validation_free_run_fit=None,
        test_free_run_fit=None,
        test_mae=None,
        test_rmse=None,
        test_r2=None,
        test_one_step_fit=None,
        test_free_run_mae=None,
        test_free_run_rmse=None,
        test_free_run_r2=None,
        generalization_gap=None,
        duration_ms=(time.perf_counter() - started) * 1000.0,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        error_code=error_code,
        best_trial_number=best_trial_number,
    )


def run_study(
    series: VersionSeries,
    payload: OptimizationStartRequest,
    *,
    input_columns: list[str],
    output_column: str,
    warm_start: list[dict[str, Any]] | None = None,
    warm_start_source: UUID | None = None,
    study_id: UUID | None = None,
) -> StudyOutcome:
    """Execute the closed loop synchronously and return everything it learned.

    ``study_id`` is supplied when the caller already reserved a row for this study, which
    both the API and the worker do so that ``/status`` answers before the search finishes.
    Left unset it allocates its own, which is what the offline experiment scripts want.
    """

    inputs = {column: series.values[column] for column in input_columns}
    output = series.values[output_column]
    fingerprint = build_fingerprint(inputs=inputs, output=output)
    cache = LineageCache()
    trials: list[TrialOutcome] = []
    base_key = stage_key(
        parent_key=str(series.version_id),
        tool_name="load_version",
        tool_version=TOOL_VERSION,
        parameters={"inputs": sorted(input_columns), "output": output_column},
    )

    structure_evaluations = 0

    def evaluate(trial: optuna.Trial) -> float:
        nonlocal structure_evaluations
        started = time.perf_counter()
        sampled_params = _suggest(trial, payload.search_space)
        params = dict(sampled_params)
        cache_hit = False
        try:
            selection_params = _selection_params(
                sampled_params,
                input_columns,
                output_column,
                train_ratio=payload.train_ratio,
            )
            key = stage_key(
                parent_key=base_key,
                tool_name="segment_selection",
                tool_version=TOOL_VERSION,
                parameters=selection_params,
            )

            def compute_selection() -> list[int]:
                request = SegmentRequest(version_id=series.version_id, **selection_params)
                outcome = run_segment_selection(series, request)
                return outcome.selected_sample_indices

            selected, cache_hit = cache.get_or_compute(key, compute_selection)

            # Staged search. Gating and selection are the expensive head of the pipeline;
            # fitting a model on already-chosen rows is cheap. So the sampler explores the
            # head and every trial sweeps the whole structure grid against the one
            # selection it just computed, instead of spending a separate selection on each
            # structure. This is where the real saving is: a flat search recomputes the
            # head for every structure it tries, and the recomputation is pure waste
            # because the head does not depend on na, nb or the estimator.
            result = None
            best_structure_value = float("-inf")
            best_breakdown: dict[str, Any] = {}
            last_error: SegmentDomainError | ModelingDomainError | None = None
            for structure in _structure_grid(sampled_params):
                candidate_params = {**sampled_params, **structure}
                if candidate_params["estimator"] != "ridge":
                    candidate_params.pop("ridge_alpha", None)
                fit_request = ArxFitRequest(
                    version_id=series.version_id,
                    input_columns=input_columns,
                    output_column=output_column,
                    na=structure["na"],
                    nb={column: structure["nb"] for column in input_columns},
                    delays={column: sampled_params["nk"] for column in input_columns},
                    estimator=structure["estimator"],
                    ridge_alpha=structure.get("ridge_alpha"),
                    train_ratio=payload.train_ratio,
                    validation_ratio=payload.validation_ratio,
                    training_sample_indices=selected,
                    evaluate_test=False,
                )
                try:
                    candidate = fit_arx_core(
                        inputs=inputs,
                        output=output,
                        payload=fit_request,
                        input_columns=input_columns,
                    )
                except ModelingDomainError as error:
                    last_error = error
                    continue
                structure_evaluations += 1
                candidate_value, candidate_breakdown = objective_value(candidate)
                if candidate_value > best_structure_value:
                    best_structure_value = candidate_value
                    best_breakdown = candidate_breakdown
                    result = candidate
                    params = candidate_params
            if result is None:
                raise last_error or ModelingDomainError(
                    "NUMERICAL_INSTABILITY", "该配置下所有模型结构均求解失败。"
                )
        except (SegmentDomainError, ModelingDomainError) as error:
            duration = (time.perf_counter() - started) * 1000.0
            trials.append(
                TrialOutcome(
                    number=trial.number,
                    state="failed",
                    value=None,
                    params=params,
                    metrics={},
                    cache_hit=cache_hit,
                    duration_ms=duration,
                    error_code=error.code,
                )
            )
            # A failed configuration is a real outcome, not an exception to hide. Optuna
            # prunes it so the sampler learns to avoid that region.
            raise optuna.TrialPruned() from error

        value, breakdown = best_structure_value, best_breakdown
        duration = (time.perf_counter() - started) * 1000.0
        if not np.isfinite(value):
            trials.append(
                TrialOutcome(
                    number=trial.number,
                    state="pruned",
                    value=None,
                    params=params,
                    metrics=breakdown,
                    cache_hit=cache_hit,
                    duration_ms=duration,
                    error_code=str(breakdown.get("reason", "not_finite")),
                )
            )
            raise optuna.TrialPruned()

        trials.append(
            TrialOutcome(
                number=trial.number,
                state="complete",
                value=value,
                params=params,
                metrics=breakdown,
                cache_hit=cache_hit,
                duration_ms=duration,
            )
        )
        return value

    study = optuna.create_study(
        direction="maximize",
        sampler=TPESampler(seed=payload.random_seed),
    )
    for candidate in (warm_start or [])[:WARM_START_LIMIT]:
        enqueued = _sanitise_warm_start(candidate)
        if enqueued:
            study.enqueue_trial(enqueued)
    study.optimize(
        evaluate,
        n_trials=payload.max_trials,
        timeout=payload.timeout_seconds,
        catch=(),
    )

    completed = [trial for trial in trials if trial.state == "complete"]
    best = max(completed, key=lambda item: item.value or float("-inf"), default=None)
    selection_computations = cache.misses
    statistics = {
        **cache.statistics(),
        "total_trials": len(trials),
        "completed_trials": len(completed),
        "failed_trials": sum(1 for trial in trials if trial.state == "failed"),
        "pruned_trials": sum(1 for trial in trials if trial.state == "pruned"),
        "mean_trial_ms": float(np.mean([trial.duration_ms for trial in trials])) if trials else 0.0,
        "warm_start_trials": len(warm_start or []),
        "structure_evaluations": structure_evaluations,
        "selection_computations": selection_computations,
        # How many model fits each computed selection served. A flat search would run one
        # selection per fit, so this is the factor by which the staged design plus the
        # lineage cache reduce the expensive stage.
        "evaluations_per_selection": (
            structure_evaluations / selection_computations if selection_computations else 0.0
        ),
    }
    return StudyOutcome(
        study_id=study_id or uuid4(),
        trials=trials,
        best_number=best.number if best else None,
        best_value=best.value if best else None,
        best_params=best.params if best else {},
        best_metrics=best.metrics if best else {},
        fingerprint=fingerprint,
        statistics=statistics,
        warm_started_from=warm_start_source,
        warm_start_params=list(warm_start or []),
    )


async def start_optimization_study(
    session: AsyncSession,
    *,
    payload: OptimizationStartRequest,
    artifact_root: Path,
) -> OptimizationStartData:
    """Allocate the study, then either hand it to a worker or run it here.

    The study row is written as ``queued`` *before* anything long starts, so ``/status``
    answers immediately in both paths and the client never holds a study id that the
    database has not heard of.

    Queueing is best-effort by design (see ``job_queue``): if Redis or the worker is not
    there, the study runs inline and the returned message says which path was taken. What
    it never does is report success for work that was dropped.
    """

    # Fail fast on a bad version before allocating anything, so a typo does not leave a
    # queued study behind that no worker can ever complete.
    try:
        await load_version_series(
            session, version_id=payload.version_id, artifact_root=artifact_root
        )
    except VersionDataError as error:
        raise OptimizationDomainError(
            error.code, error.message, status_code=error.status_code, details=error.details
        ) from error

    study_id = uuid4()
    await _reserve_study(session, study_id=study_id, payload=payload)

    submission = submit_optimization(study_id, payload.model_dump(mode="json"))
    if submission.queued:
        return OptimizationStartData(
            study_id=study_id,
            task=queued_task(
                status="queued",
                stage="optimize_pipeline",
                message=f"闭环寻优已提交后台执行（作业 {submission.job_id}），请轮询研究状态。",
            ),
        )

    statistics = await execute_study(
        session, study_id=study_id, payload=payload, artifact_root=artifact_root
    )
    suffix = f"（{submission.reason}，已同步执行）" if submission.reason else ""
    return OptimizationStartData(
        study_id=study_id,
        task=completed_task(
            stage="optimize_pipeline",
            message=(
                f"闭环寻优完成：{statistics['completed_trials']} 个有效试验，"
                f"缓存命中率 {statistics['hit_rate']:.0%}。{suffix}"
            ),
        ),
    )


async def execute_agent_optimization_study(
    session: AsyncSession,
    *,
    payload: OptimizationStartRequest,
    baseline_model_id: UUID,
    artifact_root: Path,
    study_id: UUID | None = None,
) -> AgentOptimizationStudyResult:
    """Run one Agent-authorized study inline, without historical warm starts or RQ."""

    study_id = study_id or uuid4()
    try:
        await _reserve_study(
            session,
            study_id=study_id,
            payload=payload,
            baseline_model_id=baseline_model_id,
        )
        execution = await _execute_study(
            session,
            study_id=study_id,
            payload=payload,
            artifact_root=artifact_root,
            use_warm_start=False,
        )
    except OptimizationDomainError:
        raise
    except Exception as error:
        raise OptimizationDomainError(
            getattr(error, "code", "AGENT_OPTIMIZATION_STUDY_FAILED"),
            getattr(error, "message", "Agent 优化研究执行失败。"),
        ) from error

    study = await session.get(OptimizationStudy, study_id)
    if study is None:
        raise OptimizationDomainError(
            "OPTIMIZATION_STUDY_NOT_FOUND", "Agent 优化研究未能持久化。", status_code=500
        )
    if study.status != "succeeded":
        raise OptimizationDomainError(
            str(study.statistics.get("error_code", "OPTIMIZATION_STUDY_FAILED")),
            "Agent 优化研究未成功完成。",
        )
    if study.baseline_model_id != baseline_model_id:
        raise OptimizationDomainError(
            "OPTIMIZATION_BASELINE_MODEL_MISMATCH",
            "Agent 优化研究的基线模型血缘不一致。",
            status_code=500,
        )
    if (
        study.optimized_model_id is None
        or execution.optimized_model_id is None
        or execution.optimized_model_processing_run_id is None
        or study.optimized_model_id != execution.optimized_model_id
    ):
        raise OptimizationDomainError(
            "OPTIMIZED_MODEL_REQUIRED", "Agent 优化研究未产生正式优化模型。", status_code=500
        )

    return AgentOptimizationStudyResult(
        study_id=study.id,
        status=study.status,
        source_version_id=study.version_id,
        baseline_model_id=study.baseline_model_id,
        optimized_model_id=study.optimized_model_id,
        best_params=dict(study.best_params),
        best_value=study.best_value,
        processing_run_ids=[
            str(execution.baseline_processing_run_id),
            str(execution.optimized_model_processing_run_id),
        ],
    )

async def execute_study(
    session: AsyncSession,
    *,
    study_id: UUID,
    payload: OptimizationStartRequest,
    artifact_root: Path,
    use_warm_start: bool = True,
) -> dict[str, Any]:
    """Run one reserved study and keep the standalone/worker return contract stable."""

    execution = await _execute_study(
        session,
        study_id=study_id,
        payload=payload,
        artifact_root=artifact_root,
        use_warm_start=use_warm_start,
    )
    return dict(execution.statistics)


async def _execute_study(
    session: AsyncSession,
    *,
    study_id: UUID,
    payload: OptimizationStartRequest,
    artifact_root: Path,
    use_warm_start: bool,
) -> OptimizationStudyExecution:
    """Run one reserved study to completion and persist it. Shared by API and worker.

    Both callers go through this function on purpose. A worker that computed something
    subtly different from the synchronous path would be worse than having no worker.
    """

    try:
        series = await load_version_series(
            session, version_id=payload.version_id, artifact_root=artifact_root
        )
        input_columns, output_column = series.resolve_columns(
            input_columns=payload.input_columns, output_column=payload.output_column
        )
    except VersionDataError as error:
        await _mark_study_failed(session, study_id=study_id, reason=error.code)
        raise OptimizationDomainError(
            error.code, error.message, status_code=error.status_code, details=error.details
        ) from error

    await _mark_study_running(session, study_id=study_id)

    baseline = run_baseline(
        series,
        payload,
        input_columns=input_columns,
        output_column=output_column,
    )
    baseline_processing_run_id = await _persist_evaluation(
        session,
        study_id=study_id,
        series=series,
        evaluation=baseline,
        kind="baseline",
    )
    if baseline.status != "succeeded":
        await _mark_study_failed(
            session,
            study_id=study_id,
            reason=baseline.error_code or "BASELINE_EVALUATION_FAILED",
        )
        raise OptimizationDomainError(
            baseline.error_code or "BASELINE_EVALUATION_FAILED",
            "默认基线流程失败，未开始 Optuna 寻优。",
            details={"baseline": _evaluation_payload(baseline)},
        )

    fingerprint = build_fingerprint(
        inputs={column: series.values[column] for column in input_columns},
        output=series.values[output_column],
    )
    warm_start, source = (
        await _retrieve_warm_start(session, series=series, fingerprint=fingerprint)
        if use_warm_start
        else ([], None)
    )

    try:
        outcome = run_study(
            series,
            payload,
            input_columns=input_columns,
            output_column=output_column,
            warm_start=warm_start,
            warm_start_source=source,
            study_id=study_id,
        )
    except Exception:
        # A crash mid-search must not leave the row stuck at "running" forever; the client
        # polling /status has to be able to tell "still working" from "this one died".
        await _mark_study_failed(session, study_id=study_id, reason="STUDY_EXECUTION_FAILED")
        raise

    if outcome.best_number is None:
        await _persist_study(
            session,
            series=series,
            payload=payload,
            outcome=outcome,
            optimized_model_id=None,
        )
        return OptimizationStudyExecution(
            study_id=study_id,
            source_version_id=series.version_id,
            statistics=dict(outcome.statistics),
            best_params=dict(outcome.best_params),
            best_value=outcome.best_value,
            baseline_processing_run_id=baseline_processing_run_id,
            optimized_model_id=None,
            optimized_model_processing_run_id=None,
        )

    try:
        optimized = await _persist_optimized_model(
            session,
            series=series,
            payload=payload,
            outcome=outcome,
            input_columns=input_columns,
            output_column=output_column,
            artifact_root=artifact_root,
        )
    except Exception as error:
        await _persist_study(
            session,
            series=series,
            payload=payload,
            outcome=outcome,
            optimized_model_id=None,
        )
        error_code = getattr(error, "code", "OPTIMIZED_MODEL_PERSISTENCE_FAILED")
        await _mark_study_failed(session, study_id=study_id, reason=error_code)
        if isinstance(error, OptimizationDomainError):
            raise
        if isinstance(error, ModelingDomainError):
            raise OptimizationDomainError(
                error.code, error.message, status_code=error.status_code, details=error.details
            ) from error
        raise

    await _persist_study(
        session,
        series=series,
        payload=payload,
        outcome=outcome,
        optimized_model_id=optimized.model_id,
    )
    return OptimizationStudyExecution(
        study_id=study_id,
        source_version_id=series.version_id,
        statistics=dict(outcome.statistics),
        best_params=dict(outcome.best_params),
        best_value=outcome.best_value,
        baseline_processing_run_id=baseline_processing_run_id,
        optimized_model_id=optimized.model_id,
        optimized_model_processing_run_id=optimized.processing_run_id,
    )


async def get_optimization_status(
    session: AsyncSession, *, study_id: UUID
) -> OptimizationStatusData:
    """Return trials, the best value and the convergence curve for one study."""

    study = await session.get(OptimizationStudy, study_id)
    if study is None:
        raise OptimizationDomainError(
            "OPTIMIZATION_STUDY_NOT_FOUND", "寻优任务不存在。", status_code=404
        )
    records = list(
        (
            await session.scalars(
                select(OptimizationTrialRecord)
                .where(OptimizationTrialRecord.study_id == study_id)
                .order_by(OptimizationTrialRecord.trial_number)
            )
        ).all()
    )

    curve: list[float | None] = []
    best_so_far: float | None = None
    for record in records:
        if record.value is not None and (best_so_far is None or record.value > best_so_far):
            best_so_far = record.value
        curve.append(best_so_far)

    return OptimizationStatusData(
        study_id=study_id,
        task=completed_task(stage="optimize_pipeline", message=f"研究状态：{study.status}。"),
        trials=[
            OptimizationTrial(
                trial_id=record.trial_number,
                state=_trial_state(record.state),
                value=record.value,
                params=record.params,
                created_at=record.created_at,
                finished_at=record.finished_at,
                error_code=record.error_code,
            )
            for record in records
        ],
        best_trial_id=study.best_trial_number,
        best_value=study.best_value,
        best_curve=curve,
        param_importances=_param_importances(records),
        statistics=dict(study.statistics),
        best_params=dict(study.best_params),
        baseline_model_id=study.baseline_model_id,
        optimized_model_id=study.optimized_model_id,
        warm_started_from=study.warm_started_from,
        baseline=_stored_baseline(study.statistics),
        final_test_evaluation=_stored_final_evaluation(study.statistics),
    )


def _trial_state(value: str) -> str:
    return value if value in {"queued", "running", "complete", "pruned", "failed"} else "complete"


def _suggest(trial: optuna.Trial, overrides: dict[str, Any]) -> dict[str, Any]:
    """Search space with engineering bounds; every range is finite by design."""

    space = {
        "window_size": (30, 200),
        "max_segments": (3, 20),
        **_GATING_BOUNDS,
        "na": (1, 5),
        "nb": (1, 4),
        "nk": (0, 20),
        "ridge_alpha": (1e-4, 10.0),
        **overrides,
    }
    # The gating thresholds are quantised on purpose. A continuous suggestion gives every
    # trial a unique threshold like 0.2016644..., which makes the selection cache key
    # unique too — measured hit rate was exactly 0% before this, so the cache paid its
    # overhead and returned nothing. The distinction between a 20% and a 20.17% anomaly
    # limit is not one the process can act on, so quantising costs no fidelity and lets
    # trials that differ only in model structure reuse the selection they share.
    params: dict[str, Any] = {
        "window_size": trial.suggest_int(
            "window_size", *_bounds_int(space["window_size"]), step=10
        ),
        "max_segments": trial.suggest_int("max_segments", *_bounds_int(space["max_segments"])),
        "max_anomaly_ratio": trial.suggest_float(
            "max_anomaly_ratio", *_bounds_float(space["max_anomaly_ratio"]), step=THRESHOLD_STEP
        ),
        "max_missing_ratio": trial.suggest_float(
            "max_missing_ratio", *_bounds_float(space["max_missing_ratio"]), step=THRESHOLD_STEP
        ),
        "min_input_activity_ratio": trial.suggest_float(
            "min_input_activity_ratio",
            *_bounds_float(space["min_input_activity_ratio"]),
            step=THRESHOLD_STEP,
        ),
        # nk stays with the sampler: the pure delay is process-specific, its useful range
        # is wide, and it changes the regressor, so it does not belong in a fixed grid.
        "nk": trial.suggest_int("nk", *_bounds_int(space["nk"])),
    }
    return params


def _structure_grid(params: dict[str, Any]) -> list[dict[str, Any]]:
    """Model structures swept inside one trial, against a single selection.

    Small and fixed on purpose: these fits are cheap once the rows are chosen, so an
    exhaustive sweep is both faster and more thorough than asking the sampler to find the
    orders one trial at a time.
    """

    grid: list[dict[str, Any]] = []
    for na in (1, 2, 3, 4):
        for nb in (1, 2, 3):
            grid.append({"na": na, "nb": nb, "estimator": "ols"})
            grid.append({"na": na, "nb": nb, "estimator": "ridge", "ridge_alpha": 0.1})
    return grid


def _bounds_int(value: Any) -> tuple[int, int]:
    low, high = value
    return int(low), int(high)


def _bounds_float(value: Any) -> tuple[float, float]:
    low, high = value
    return float(low), float(high)


def _selection_params(
    params: dict[str, Any],
    input_columns: list[str],
    output_column: str,
    *,
    train_ratio: float,
) -> dict[str, Any]:
    """Only the parameters that actually change the selected rows enter the cache key."""

    return {
        "input_columns": list(input_columns),
        "output_column": output_column,
        "window_size": params["window_size"],
        "max_segments": params["max_segments"],
        "max_anomaly_ratio": params["max_anomaly_ratio"],
        "max_missing_ratio": params["max_missing_ratio"],
        "min_input_activity_ratio": params["min_input_activity_ratio"],
        "train_ratio": train_ratio,
    }


def _sanitise_warm_start(candidate: dict[str, Any]) -> dict[str, Any]:
    """Keep only keys the current search space defines, so enqueue cannot fail."""

    allowed = {
        "window_size",
        "max_segments",
        "max_anomaly_ratio",
        "max_missing_ratio",
        "min_input_activity_ratio",
        "na",
        "nb",
        "nk",
        "estimator",
        "ridge_alpha",
    }
    cleaned = {key: value for key, value in candidate.items() if key in allowed}
    if cleaned.get("estimator") != "ridge":
        cleaned.pop("ridge_alpha", None)
    return cleaned


async def _retrieve_warm_start(
    session: AsyncSession,
    *,
    series: VersionSeries,
    fingerprint: ProfileFingerprint,
) -> tuple[list[dict[str, Any]], UUID | None]:
    """Find the closest past studies on *other* datasets and reuse their winners.

    Excluding the current dataset is not a formality: warm-starting a dataset from its own
    previous run would recycle a configuration that already saw this data, which is exactly
    the leakage the evaluation protocol forbids.
    """

    entries = list((await session.scalars(select(StrategyMemory))).all())
    scored: list[tuple[float, StrategyMemory]] = []
    for entry in entries:
        if series.dataset_id is not None and entry.dataset_id == series.dataset_id:
            continue
        distance = fingerprint_distance(fingerprint.vector, list(entry.fingerprint_vector))
        if distance <= WARM_START_MAX_DISTANCE:
            scored.append((distance, entry))
    if not scored:
        return [], None
    scored.sort(key=lambda item: item[0])
    chosen = scored[:WARM_START_LIMIT]
    return [dict(entry.best_params) for _, entry in chosen], chosen[0][1].study_id


async def _reserve_study(
    session: AsyncSession,
    *,
    study_id: UUID,
    payload: OptimizationStartRequest,
    baseline_model_id: UUID | None = None,
) -> None:
    """Write the study row before any long work starts.

    Without this the caller gets a study id that ``/status`` answers 404 for until the
    search finishes — which, once the search runs in a worker, is the entire useful window.
    """

    session.add(
        OptimizationStudy(
            id=study_id,
            dataset_id=None,
            version_id=payload.version_id,
            status="queued",
            objective="val_free_run_fit",
            parameters=payload.model_dump(mode="json"),
            baseline_model_id=baseline_model_id,
            best_params={},
            fingerprint={},
            statistics={"target_trials": payload.max_trials},
            created_at=datetime.now(UTC),
        )
    )
    await session.commit()


async def _mark_study_running(session: AsyncSession, *, study_id: UUID) -> None:
    study = await session.get(OptimizationStudy, study_id)
    if study is not None:
        study.status = "running"
        await session.commit()


async def _mark_study_failed(session: AsyncSession, *, study_id: UUID, reason: str) -> None:
    """Never leave a row at ``running`` after a crash; polling clients cannot tell the
    difference between "still working" and "died an hour ago"."""

    study = await session.get(OptimizationStudy, study_id)
    if study is not None:
        study.status = "failed"
        study.statistics = {**dict(study.statistics), "error_code": reason}
        study.finished_at = datetime.now(UTC)
        await session.commit()


async def _persist_evaluation(
    session: AsyncSession,
    *,
    study_id: UUID,
    series: VersionSeries,
    evaluation: EvaluationOutcome,
    kind: str,
) -> UUID:
    """Persist a baseline/final evaluation without introducing a new table."""

    study = await session.get(OptimizationStudy, study_id)
    if study is None:
        raise OptimizationDomainError(
            "OPTIMIZATION_STUDY_NOT_FOUND", "优化研究不存在，无法持久化评价运行。", status_code=404
        )
    run_id = uuid4()
    payload = _evaluation_payload(evaluation, processing_run_id=run_id)
    evaluations = dict(study.statistics.get("evaluations", {}))
    evaluations[kind] = payload
    study.statistics = {**dict(study.statistics), "evaluations": evaluations}
    session.add(
        ProcessingRun(
            id=run_id,
            dataset_id=series.dataset_id,
            source_version_id=series.version_id,
            run_type=f"optimization.{kind}",
            status=evaluation.status,
            parameters=evaluation.parameters,
            result=payload,
            created_at=evaluation.started_at,
            finished_at=evaluation.finished_at,
        )
    )
    await session.commit()
    return run_id


def _evaluation_payload(
    evaluation: EvaluationOutcome,
    *,
    processing_run_id: UUID | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": evaluation.status,
        "parameters": evaluation.parameters,
        "validation_free_run_fit": evaluation.validation_free_run_fit,
        "test_free_run_fit": evaluation.test_free_run_fit,
        "test_mae": evaluation.test_mae,
        "test_rmse": evaluation.test_rmse,
        "test_r2": evaluation.test_r2,
        "test_one_step_fit": evaluation.test_one_step_fit,
        "test_one_step_mae": evaluation.test_mae,
        "test_one_step_rmse": evaluation.test_rmse,
        "test_one_step_r2": evaluation.test_r2,
        "test_free_run_mae": evaluation.test_free_run_mae,
        "test_free_run_rmse": evaluation.test_free_run_rmse,
        "test_free_run_r2": evaluation.test_free_run_r2,
        "generalization_gap": evaluation.generalization_gap,
        "duration_ms": evaluation.duration_ms,
        "processing_run_id": str(processing_run_id) if processing_run_id else None,
        "error_code": evaluation.error_code,
        "started_at": evaluation.started_at.isoformat(),
        "finished_at": evaluation.finished_at.isoformat(),
    }
    if evaluation.best_trial_number is not None:
        payload["best_trial_number"] = evaluation.best_trial_number
    return payload


def _stored_baseline(statistics: dict[str, Any]) -> BaselineEvaluation | None:
    payload = _stored_evaluation(statistics, "baseline")
    return BaselineEvaluation.model_validate(payload) if payload else None


def _stored_final_evaluation(statistics: dict[str, Any]) -> FinalTestEvaluation | None:
    payload = _stored_evaluation(statistics, "final_test")
    return FinalTestEvaluation.model_validate(payload) if payload else None


def _stored_evaluation(statistics: dict[str, Any], kind: str) -> dict[str, Any] | None:
    evaluations = statistics.get("evaluations")
    if not isinstance(evaluations, dict):
        return None
    value = evaluations.get(kind)
    return dict(value) if isinstance(value, dict) else None


async def _persist_study(
    session: AsyncSession,
    *,
    series: VersionSeries,
    payload: OptimizationStartRequest,
    outcome: StudyOutcome,
    optimized_model_id: UUID | None,
) -> None:
    now = datetime.now(UTC)
    # The row already exists when the API or the worker reserved it. Updating in place is
    # what makes a job retry idempotent: re-running the same study id cannot produce two
    # study records for one request.
    study = await session.get(OptimizationStudy, outcome.study_id)
    if study is None:
        study = OptimizationStudy(id=outcome.study_id, created_at=now)
        session.add(study)
    study.dataset_id = series.dataset_id
    study.version_id = series.version_id
    study.status = ("succeeded" if outcome.best_number is not None and optimized_model_id else "failed")
    study.objective = "val_free_run_fit"
    study.parameters = payload.model_dump(mode="json")
    study.best_trial_number = outcome.best_number
    study.best_value = outcome.best_value
    study.best_params = outcome.best_params
    study.optimized_model_id = optimized_model_id
    study.fingerprint = outcome.fingerprint.to_payload()
    # Keep what was asked for alongside what happened: a study that requested 50 trials and
    # completed 12 is a different story from one that requested 12, and the final statistics
    # alone cannot tell them apart.
    study.statistics = {
        "target_trials": payload.max_trials,
        **dict(study.statistics),
        **outcome.statistics,
    }
    study.warm_started_from = outcome.warm_started_from
    study.finished_at = now

    # Trials from an earlier attempt at the same study id would otherwise accumulate.
    await session.execute(
        delete(OptimizationTrialRecord).where(OptimizationTrialRecord.study_id == outcome.study_id)
    )
    for trial in outcome.trials:
        session.add(
            OptimizationTrialRecord(
                id=uuid4(),
                study_id=outcome.study_id,
                trial_number=trial.number,
                state=trial.state,
                value=trial.value,
                params=trial.params,
                metrics=trial.metrics,
                cache_hit=trial.cache_hit,
                duration_ms=trial.duration_ms,
                error_code=trial.error_code,
                created_at=now,
                finished_at=now,
            )
        )
    if outcome.best_number is not None and optimized_model_id is not None:
        session.add(
            StrategyMemory(
                id=uuid4(),
                dataset_id=series.dataset_id,
                version_id=series.version_id,
                study_id=outcome.study_id,
                fingerprint=outcome.fingerprint.to_payload(),
                fingerprint_vector=outcome.fingerprint.vector,
                best_params=outcome.best_params,
                achieved_metrics=outcome.best_metrics,
                objective_value=outcome.best_value,
                source="study",
                created_at=now,
            )
        )
    session.add(
        OperationLog(
            id=uuid4(),
            event_type=(
                "optimization.study.completed"
                if optimized_model_id is not None
                else "optimization.study.failed"
            ),
            subject_id=str(series.dataset_id),
            payload_json=json.dumps(
                {
                    "study_id": str(outcome.study_id),
                    "best_value": outcome.best_value,
                    "best_params": outcome.best_params,
                    "optimized_model_id": str(optimized_model_id)
                    if optimized_model_id is not None
                    else None,
                    "statistics": outcome.statistics,
                    "warm_started_from": str(outcome.warm_started_from)
                    if outcome.warm_started_from
                    else None,
                    "executed_at": now.isoformat(),
                },
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ),
            created_at=now,
        )
    )
    await session.commit()


def _param_importances(records: list[OptimizationTrialRecord]) -> dict[str, float]:
    """Correlation-based importance, which needs no extra dependency.

    Optuna's fANOVA importance requires a live Study object; the persisted trials are all
    that survive a restart, so importance is derived from them directly. It is reported as
    the absolute Spearman-style rank correlation between a parameter and the objective,
    normalised to sum to one.
    """

    completed = [record for record in records if record.value is not None]
    if len(completed) < 4:
        return {}
    values = np.asarray([record.value for record in completed], dtype=float)
    names = sorted({name for record in completed for name in record.params})
    importances: dict[str, float] = {}
    for name in names:
        column = []
        target = []
        for record, score in zip(completed, values, strict=True):
            raw = record.params.get(name)
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                continue
            column.append(float(raw))
            target.append(float(score))
        if len(column) < 4 or len(set(column)) < 2:
            continue
        ranked_x = _ranks(np.asarray(column))
        ranked_y = _ranks(np.asarray(target))
        left = ranked_x - ranked_x.mean()
        right = ranked_y - ranked_y.mean()
        denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
        if denominator <= 0:
            continue
        importances[name] = abs(float(np.dot(left, right) / denominator))
    total = sum(importances.values())
    if total <= 0:
        return {}
    return {name: value / total for name, value in sorted(importances.items())}


def _ranks(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(values.size, dtype=float)
    ranks[order] = np.arange(1, values.size + 1, dtype=float)
    return ranks
