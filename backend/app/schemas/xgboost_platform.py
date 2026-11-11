"""HTTP contracts for version-bound XGBoost training and fixed inference."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, FiniteFloat, PositiveInt, StrictFloat, model_validator

from app.schemas.common import Schema
from app.schemas.experiment_spec import ExperimentSpec
from app.schemas.xgboost import XGBoostParameters


class XGBoostFitRequest(Schema):
    experiment_spec: ExperimentSpec
    parameters: XGBoostParameters = Field(default_factory=XGBoostParameters)


class XGBoostManifestRetryRequest(Schema):
    training_run_id: UUID


class XGBoostPublicationData(Schema):
    model_id: UUID
    training_run_id: UUID
    training_status: Literal["succeeded"] = "succeeded"
    manifest_status: Literal["published", "failed"]
    manifest_retryable: bool = False
    error_code: str | None = None


class XGBoostFitResponse(XGBoostPublicationData):
    dataset_version_id: UUID
    feature_names: tuple[str, ...]
    target_name: str
    parameters: XGBoostParameters
    training_rows: PositiveInt


MAX_FEATURE_NAME_LENGTH = 255
MAX_FEATURES = 256
FeatureName = Annotated[str, Field(min_length=1, max_length=MAX_FEATURE_NAME_LENGTH)]
PredictionNumber = Annotated[StrictFloat, Field(allow_inf_nan=False)]
PredictionRow = Annotated[
    tuple[PredictionNumber, ...], Field(min_length=1, max_length=MAX_FEATURES)
]


class XGBoostPredictRequest(Schema):
    model_id: UUID
    feature_names: tuple[FeatureName, ...] = Field(min_length=1, max_length=MAX_FEATURES)
    X: tuple[PredictionRow, ...] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_batch(self) -> Self:
        width = len(self.feature_names)
        if (
            len(set(self.feature_names)) != width
            or any(not name.strip() for name in self.feature_names)
            or any(len(row) != width for row in self.X)
            or len(self.X) * width > 100_000
        ):
            raise ValueError("Expected aligned unique features and at most 100000 numeric cells")
        return self


class XGBoostPredictResponse(Schema):
    model_id: UUID
    predictions: tuple[FiniteFloat, ...]
    sample_count: PositiveInt
