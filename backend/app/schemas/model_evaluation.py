"""Service-layer contracts for fixed, version-bound model evaluation."""

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import ConfigDict, Field, StrictFloat, StrictInt, model_validator

from app.schemas.common import Schema
from app.schemas.experiment_spec import Digest, RowRange, RowSet, validate_ranges
from app.schemas.modeling import (
    ArxEvaluationResidualDiagnostics,
    ArxModelHealth,
    ArxModelStructureData,
    ArxTestEvaluationData,
)
from app.schemas.timexer_platform import TimeXerForecastSpec

EvaluationPartition = Literal["validation", "test"]
EvaluationStatus = Literal["running", "succeeded", "failed"]
EvaluationModelType = Literal["arx", "fir", "oe", "pls", "xgboost", "tcn", "timexer"]
NonnegativeMetric = Annotated[StrictFloat, Field(ge=0, allow_inf_nan=False)]
R2Metric = Annotated[StrictFloat, Field(le=1, allow_inf_nan=False)]


class ModelEvaluationRequest(Schema):
    model_id: UUID
    partition: EvaluationPartition


class RegressionMetrics(Schema):
    r2: R2Metric | None
    rmse: NonnegativeMetric
    mae: NonnegativeMetric
    nrmse: NonnegativeMetric | None


class ModelEvaluationResult(Schema):
    evaluation_run_id: UUID
    model_id: UUID
    model_type_id: EvaluationModelType
    training_run_id: UUID
    dataset_id: UUID
    dataset_version_id: UUID
    dataset_sha256: Digest
    experiment_spec_hash: Digest
    partition: EvaluationPartition
    prediction_mode: Literal["prediction", "free_run"] = "prediction"
    sample_count: Annotated[StrictInt, Field(gt=0)]
    evaluation_status: Literal["succeeded"] = "succeeded"
    actual_rows: RowSet
    metrics: RegressionMetrics
    prediction_artifact_sha256: Digest | None = None
    implementation_version: Literal["model-evaluation-1"] = "model-evaluation-1"

    @model_validator(mode="after")
    def check_result(self) -> Self:
        if self.sample_count != self.actual_rows.count:
            raise ValueError("Evaluation sample count must match its actual rows")
        if self.evaluation_run_id in (self.model_id, self.training_run_id):
            raise ValueError("Evaluation requires an independent run identity")
        return self


class ArxModelEvaluationResult(ModelEvaluationResult):
    model_type_id: Literal["arx"]
    partition: Literal["validation"]
    prediction_mode: Literal["free_run"] = "free_run"
    validation: ArxTestEvaluationData
    model_structure: ArxModelStructureData
    model_health: ArxModelHealth
    residual_diagnostics: ArxEvaluationResidualDiagnostics


class TCNModelEvaluationResult(ModelEvaluationResult):
    model_type_id: Literal["tcn"]
    window_length: Annotated[StrictInt, Field(gt=0)]
    sequence_evidence: dict[str, object]
    model_implementation_version: Literal["tcn-core-1"]
    dependency_versions: dict[str, str]


MetricName = Literal["r2", "rmse", "mae", "nrmse"]
HorizonStep = Annotated[StrictInt, Field(gt=0)]


class TargetRowSet(Schema):
    """Inline coverage derived from verified anchors, including sparse index files."""

    ranges: tuple[RowRange, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def check_ranges(self) -> Self:
        validate_ranges(self.ranges)
        return self


class HorizonMetrics(RegressionMetrics):
    horizon_step: HorizonStep


class MetricAggregation(Schema):
    method: Literal["macro_average"] = "macro_average"
    valid_horizon_counts: dict[MetricName, Annotated[StrictInt, Field(ge=0)]]
    undefined_horizons: dict[MetricName, tuple[HorizonStep, ...]]


class TimeXerModelEvaluationResult(ModelEvaluationResult):
    model_type_id: Literal["timexer"]
    forecast_spec: TimeXerForecastSpec
    target_rows: TargetRowSet
    target_rows_by_horizon: tuple[TargetRowSet, ...]
    sequence_evidence: dict[str, object]
    horizon_metrics: tuple[HorizonMetrics, ...]
    metric_aggregation: MetricAggregation
    model_implementation_version: str
    dependency_versions: dict[str, str]

    @model_validator(mode="after")
    def check_horizons(self) -> Self:
        horizon = self.forecast_spec.prediction_length
        if len(self.target_rows_by_horizon) != horizon or tuple(
            item.horizon_step for item in self.horizon_metrics
        ) != tuple(range(1, horizon + 1)):
            raise ValueError("TimeXer evaluation must record each forecast horizon in order")
        return self


ModelEvaluationSuccess = (
    ArxModelEvaluationResult | TCNModelEvaluationResult | TimeXerModelEvaluationResult | ModelEvaluationResult
)
EvaluationOffset = Annotated[int, Field(ge=0, le=2**63 - 1)]
EvaluationLimit = Annotated[int, Field(ge=1, le=100)]


class ModelEvaluationHistoryQuery(Schema):
    model_id: UUID | None = None
    partition: EvaluationPartition | None = None
    status: EvaluationStatus | None = None
    offset: EvaluationOffset = 0
    limit: EvaluationLimit = 20


class ModelEvaluationSummary(Schema):
    evaluation_run_id: UUID
    model_id: UUID
    training_run_id: UUID | None
    model_type_id: EvaluationModelType | None
    partition: EvaluationPartition
    status: EvaluationStatus
    sample_count: Annotated[StrictInt, Field(gt=0)] | None
    created_at: datetime
    metrics: RegressionMetrics | None


class ModelEvaluationHistory(Schema):
    total: Annotated[int, Field(ge=0)]
    offset: EvaluationOffset
    limit: EvaluationLimit
    items: list[ModelEvaluationSummary]


class ModelEvaluationParameters(ModelEvaluationRequest):
    # Persisted metadata may gain internal fields. Keep the HTTP projection explicit.
    model_config = ConfigDict(extra="ignore")

    prediction_mode: Literal["prediction", "free_run"]
    training_run_id: UUID | None = None
    model_type_id: EvaluationModelType | None = None
    dataset_id: UUID | None = None
    dataset_version_id: UUID | None = None
    dataset_sha256: Digest | None = None
    experiment_spec_hash: Digest | None = None
    actual_rows: RowSet | None = None
    window_length: Annotated[StrictInt, Field(gt=0)] | None = None
    forecast_spec: TimeXerForecastSpec | None = None
    target_rows: TargetRowSet | None = None
    target_rows_by_horizon: tuple[TargetRowSet, ...] | None = None
    sequence_evidence: dict[str, object] | None = None
    model_implementation_version: str | None = None
    dependency_versions: dict[str, str] | None = None


class ModelEvaluationFailure(Schema):
    model_config = ConfigDict(extra="ignore")

    evaluation_status: Literal["failed"]
    failure_stage: str
    implementation_version: str


class ModelEvaluationDetail(ModelEvaluationSummary):
    finished_at: datetime | None
    parameters: ModelEvaluationParameters
    result: ModelEvaluationSuccess | ModelEvaluationFailure | None
