"""TimeXer platform requests and an explicit forecast contract alongside the data Spec."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    ConfigDict,
    Field,
    FiniteFloat,
    PositiveInt,
    StrictFloat,
    StrictInt,
    model_validator,
)

from app.schemas.common import Schema
from app.schemas.experiment_spec import ExperimentSpec
from app.schemas.timexer import MAX_EXOGENOUS_FEATURES, TimeXerParameters, validate_feature_names

MAX_PREDICT_BYTES = 4 * 1024 * 1024
MAX_PREDICT_SAMPLES = 256
MAX_PREDICT_VALUES = 100_000
MAX_FEATURE_NAME_LENGTH = 255
MAX_HORIZON = 32


class TimeXerForecastSpec(Schema):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target_window_length: Annotated[StrictInt, Field(ge=8, le=256)]
    exogenous_window_length: Annotated[StrictInt, Field(ge=8, le=256)]
    prediction_length: Annotated[StrictInt, Field(ge=1, le=MAX_HORIZON)]

    def validate_parameters(self, parameters: TimeXerParameters) -> None:
        if (
            self.target_window_length != parameters.target_window_length
            or self.exogenous_window_length != parameters.exogenous_window_length
            or self.prediction_length != parameters.prediction_length
        ):
            raise ValueError("forecast_spec must match the TimeXer window lengths and horizon")


class TimeXerFitRequest(Schema):
    experiment_spec: ExperimentSpec
    forecast_spec: TimeXerForecastSpec
    parameters: TimeXerParameters

    @model_validator(mode="after")
    def check_forecast(self) -> Self:
        self.forecast_spec.validate_parameters(self.parameters)
        return self


class TimeXerManifestRetryRequest(Schema):
    training_run_id: UUID


class TimeXerPublicationData(Schema):
    model_id: UUID
    training_run_id: UUID
    training_status: Literal["succeeded"] = "succeeded"
    manifest_status: Literal["published", "failed"]
    manifest_retryable: bool = False
    error_code: str | None = None


class TimeXerFitResponse(TimeXerPublicationData):
    dataset_version_id: UUID
    target_name: str
    exogenous_names: tuple[str, ...]
    parameters: TimeXerParameters
    forecast_spec: TimeXerForecastSpec
    training_samples: PositiveInt
    training_loss: FiniteFloat


FeatureName = Annotated[str, Field(min_length=1, max_length=MAX_FEATURE_NAME_LENGTH)]
Number = Annotated[StrictFloat, Field(allow_inf_nan=False)]
TargetRow = Annotated[tuple[Number, ...], Field(min_length=1, max_length=1)]
ExogenousRow = Annotated[tuple[Number, ...], Field(min_length=1, max_length=MAX_EXOGENOUS_FEATURES)]
TargetWindow = Annotated[tuple[TargetRow, ...], Field(min_length=8, max_length=256)]
ExogenousWindow = Annotated[tuple[ExogenousRow, ...], Field(min_length=8, max_length=256)]


class TimeXerPredictRequest(Schema):
    model_id: UUID
    target_name: FeatureName
    exogenous_names: tuple[FeatureName, ...] = Field(
        min_length=1, max_length=MAX_EXOGENOUS_FEATURES
    )
    X_target: tuple[TargetWindow, ...] = Field(min_length=1, max_length=MAX_PREDICT_SAMPLES)
    X_exogenous: tuple[ExogenousWindow, ...] = Field(min_length=1, max_length=MAX_PREDICT_SAMPLES)

    @model_validator(mode="after")
    def check_windows(self) -> Self:
        validate_feature_names(self.target_name, self.exogenous_names)
        n = len(self.X_target)
        target_length = len(self.X_target[0])
        exogenous_length = len(self.X_exogenous[0])
        width = len(self.exogenous_names)
        if (
            len(self.X_exogenous) != n
            or n * (target_length + exogenous_length * width) > MAX_PREDICT_VALUES
            or any(len(window) != target_length for window in self.X_target)
            or any(len(window) != exogenous_length for window in self.X_exogenous)
            or any(len(row) != width for window in self.X_exogenous for row in window)
        ):
            raise ValueError("Expected aligned TimeXer histories and at most 100000 numeric values")
        return self


Prediction = Annotated[tuple[FiniteFloat, ...], Field(min_length=1, max_length=MAX_HORIZON)]


class TimeXerPredictResponse(Schema):
    model_id: UUID
    predictions: tuple[Prediction, ...]
    sample_count: PositiveInt
