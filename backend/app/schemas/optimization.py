from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.common import Schema, TaskResource
from app.schemas.modeling import ModelValidationData, PredictionMetrics


class OptimizationStartRequest(Schema):
    version_id: UUID
    input_columns: list[str] = Field(min_length=1)
    output_column: str = Field(min_length=1)
    max_trials: int = Field(default=50, ge=1, le=10_000)
    timeout_seconds: int | None = Field(default=None, ge=1, le=86_400)
    search_space: dict[str, Any] = Field(default_factory=dict)
    random_seed: int = Field(default=42, ge=0, le=2_147_483_647)
    train_ratio: float = Field(default=0.6, gt=0, lt=1)
    validation_ratio: float = Field(default=0.2, gt=0, lt=1)

    @model_validator(mode="after")
    def validate_time_split(self) -> "OptimizationStartRequest":
        if self.train_ratio + self.validation_ratio >= 1:
            raise ValueError("train_ratio 与 validation_ratio 之和必须小于 1。")
        return self


class OptimizationStartData(Schema):
    study_id: UUID
    task: TaskResource


class OptimizationObjectiveSemantics(Schema):
    """Authoritative meaning of the score stored in ``value``/``best_value``."""

    name: Literal["composite_identification_score"] = "composite_identification_score"
    version: Literal["v1"] = "v1"
    direction: Literal["maximize"] = "maximize"


class OptimizationObjectiveComponents(Schema):
    """Raw inputs and weighted terms from the existing composite objective."""

    validation_free_run_fit: float | None = None
    validation_free_run_fit_component: float | None = None
    normalized_error: float | None = None
    normalized_error_component: float | None = None
    residual_whiteness_ratio: float | None = None
    residual_whiteness_component: float | None = None
    parameter_count: int | None = Field(default=None, ge=1)
    complexity: float | None = None
    complexity_component: float | None = None
    stability_gate: bool
    final_score: float | None = None


class OptimizationSelectionProvenance(Schema):
    """Compact, replayable evidence for the rows selected by one trial."""

    candidate_count: int = Field(ge=0)
    gated_count: int = Field(ge=0)
    selected_segment_count: int = Field(ge=0)
    selected_sample_count: int = Field(ge=0)
    selected_indices_hash: str = Field(min_length=64, max_length=64)
    coverage_ratio: float | None = None
    gating_rejection_counts: dict[str, int] = Field(default_factory=dict)
    excitation_satisfied: bool | None = None
    persistent_excitation_order: dict[str, int] = Field(default_factory=dict)
    required_excitation_order: dict[str, int] = Field(default_factory=dict)
    condition_number: float | None = None


class OptimizationValidationFeedback(Schema):
    """Validation-only evidence already computed while evaluating one candidate."""

    partition: Literal["validation"] = "validation"
    one_step: PredictionMetrics
    free_run: PredictionMetrics
    summary: ModelValidationData


class OptimizationTrial(Schema):
    trial_id: int = Field(ge=0)
    state: Literal["queued", "running", "complete", "pruned", "failed"]
    value: float | None = None
    params: dict[str, Any]
    metrics: dict[str, Any] = Field(default_factory=dict)
    selection_provenance: OptimizationSelectionProvenance | None = None
    validation_feedback: OptimizationValidationFeedback | None = None
    objective_semantics: OptimizationObjectiveSemantics | None = None
    objective_components: OptimizationObjectiveComponents | None = None
    created_at: datetime
    finished_at: datetime | None = None
    error_code: str | None = None


class BaselineEvaluation(Schema):
    status: Literal["succeeded", "failed"]
    parameters: dict[str, Any] = Field(default_factory=dict)
    validation_free_run_fit: float | None = None
    test_free_run_fit: float | None = None
    test_mae: float | None = None
    test_rmse: float | None = None
    test_r2: float | None = None
    # Deprecated aliases above are one-step diagnostics. Use explicit fields below.
    test_one_step_fit: float | None = None
    test_one_step_mae: float | None = None
    test_one_step_rmse: float | None = None
    test_one_step_r2: float | None = None
    test_free_run_mae: float | None = None
    test_free_run_rmse: float | None = None
    test_free_run_r2: float | None = None
    generalization_gap: float | None = None
    duration_ms: float | None = None
    processing_run_id: UUID | None = None
    error_code: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class FinalTestEvaluation(Schema):
    status: Literal["succeeded", "failed"]
    best_trial_number: int | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    validation_free_run_fit: float | None = None
    test_free_run_fit: float | None = None
    test_mae: float | None = None
    test_rmse: float | None = None
    test_r2: float | None = None
    # Deprecated aliases above are one-step diagnostics. Use explicit fields below.
    test_one_step_fit: float | None = None
    test_one_step_mae: float | None = None
    test_one_step_rmse: float | None = None
    test_one_step_r2: float | None = None
    test_free_run_mae: float | None = None
    test_free_run_rmse: float | None = None
    test_free_run_r2: float | None = None
    generalization_gap: float | None = None
    duration_ms: float | None = None
    processing_run_id: UUID | None = None
    error_code: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class OptimizationStatusData(Schema):
    study_id: UUID
    task: TaskResource
    trials: list[OptimizationTrial]
    best_trial_id: int | None = None
    best_value: float | None = None
    best_curve: list[float | None]
    param_importances: dict[str, float]
    # Cache-hit rate, trial counts and timings — the phase-8 acceptance evidence.
    statistics: dict[str, Any] = Field(default_factory=dict)
    best_params: dict[str, Any] = Field(default_factory=dict)
    baseline_model_id: UUID | None = None
    optimized_model_id: UUID | None = None
    # Set when this study reused parameters learned from a different dataset.
    warm_started_from: UUID | None = None
    baseline: BaselineEvaluation | None = None
    final_test_evaluation: FinalTestEvaluation | None = None
    objective_semantics: OptimizationObjectiveSemantics | None = None
    best_validation_feedback: OptimizationValidationFeedback | None = None
    best_selection_summary: OptimizationSelectionProvenance | None = None
    best_objective_components: OptimizationObjectiveComponents | None = None
