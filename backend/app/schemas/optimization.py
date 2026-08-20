from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.common import Schema, TaskResource


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


class OptimizationTrial(Schema):
    trial_id: int = Field(ge=0)
    state: Literal["queued", "running", "complete", "pruned", "failed"]
    value: float | None = None
    params: dict[str, Any]
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
    # Set when this study reused parameters learned from a different dataset.
    warm_started_from: UUID | None = None
    baseline: BaselineEvaluation | None = None
    final_test_evaluation: FinalTestEvaluation | None = None
