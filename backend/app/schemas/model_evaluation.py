"""Service-layer contracts for fixed, version-bound model evaluation."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, StrictFloat, StrictInt, model_validator

from app.schemas.common import Schema
from app.schemas.experiment_spec import Digest, RowRange, RowSet, validate_ranges
from app.schemas.timexer_platform import TimeXerForecastSpec

EvaluationPartition = Literal["validation", "test"]
EvaluationModelType = Literal["pls", "xgboost", "tcn", "timexer"]
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
    prediction_mode: Literal["prediction"] = "prediction"
    sample_count: Annotated[StrictInt, Field(gt=0)]
    evaluation_status: Literal["succeeded"] = "succeeded"
    actual_rows: RowSet
    metrics: RegressionMetrics
    implementation_version: Literal["model-evaluation-1"] = "model-evaluation-1"

    @model_validator(mode="after")
    def check_result(self) -> Self:
        if self.sample_count != self.actual_rows.count:
            raise ValueError("Evaluation sample count must match its actual rows")
        if self.evaluation_run_id in (self.model_id, self.training_run_id):
            raise ValueError("Evaluation requires an independent run identity")
        return self


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
