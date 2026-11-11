"""Service-layer contracts for fixed, version-bound model evaluation."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, StrictFloat, StrictInt, model_validator

from app.schemas.common import Schema
from app.schemas.experiment_spec import Digest, RowSet

EvaluationPartition = Literal["validation", "test"]
EvaluationModelType = Literal["pls", "xgboost"]
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
