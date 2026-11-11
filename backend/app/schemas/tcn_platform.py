"""HTTP contracts for version-bound TCN training and fixed inference."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, FiniteFloat, PositiveInt, StrictFloat, model_validator

from app.schemas.common import Schema
from app.schemas.experiment_spec import ExperimentSpec
from app.schemas.tcn import MAX_FEATURES, TCNParameters, receptive_field

MAX_PREDICT_BYTES = 4 * 1024 * 1024
MAX_FEATURE_NAME_LENGTH = 255
MAX_WINDOW_LENGTH = 256
MAX_PREDICT_SAMPLES = 256
MAX_PREDICT_VALUES = 100_000


class TCNFitRequest(Schema):
    experiment_spec: ExperimentSpec
    parameters: TCNParameters = Field(default_factory=TCNParameters)


class TCNManifestRetryRequest(Schema):
    training_run_id: UUID


class TCNPublicationData(Schema):
    model_id: UUID
    training_run_id: UUID
    training_status: Literal["succeeded"] = "succeeded"
    manifest_status: Literal["published", "failed"]
    manifest_retryable: bool = False
    error_code: str | None = None


class TCNFitResponse(TCNPublicationData):
    dataset_version_id: UUID
    feature_names: tuple[str, ...]
    target_name: str
    parameters: TCNParameters
    training_samples: PositiveInt
    training_loss: FiniteFloat


FeatureName = Annotated[str, Field(min_length=1, max_length=MAX_FEATURE_NAME_LENGTH)]
PredictionNumber = Annotated[StrictFloat, Field(allow_inf_nan=False)]
PredictionRow = Annotated[
    tuple[PredictionNumber, ...], Field(min_length=1, max_length=MAX_FEATURES)
]
PredictionWindow = Annotated[
    tuple[PredictionRow, ...], Field(min_length=receptive_field(), max_length=MAX_WINDOW_LENGTH)
]


class TCNPredictRequest(Schema):
    model_id: UUID
    feature_names: tuple[FeatureName, ...] = Field(min_length=1, max_length=MAX_FEATURES)
    X: tuple[PredictionWindow, ...] = Field(min_length=1, max_length=MAX_PREDICT_SAMPLES)

    @model_validator(mode="after")
    def validate_batch(self) -> Self:
        width = len(self.feature_names)
        length = len(self.X[0])
        if (
            len(set(self.feature_names)) != width
            or any(not name.strip() for name in self.feature_names)
            or len(self.X) * length * width > MAX_PREDICT_VALUES
            or any(len(window) != length for window in self.X)
            or any(len(row) != width for window in self.X for row in window)
        ):
            raise ValueError("Expected aligned TCN windows and at most 100000 numeric values")
        return self


class TCNPredictResponse(Schema):
    model_id: UUID
    predictions: tuple[FiniteFloat, ...]
    sample_count: PositiveInt
