"""Static, single-target PLS core and standalone artifact contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, ClassVar, Literal, Self
from uuid import UUID

from pydantic import ConfigDict, Field, StrictBool, StrictFloat, StrictInt, model_validator

from app.schemas.common import Schema
from app.schemas.experiment_spec import ExperimentSpec, RowSet
from app.schemas.timexer import TimeXerParameters

PositiveInt = Annotated[StrictInt, Field(gt=0)]
ArrayName = Literal[
    "coefficients",
    "intercept",
    "x_mean",
    "x_std",
    "y_mean",
    "y_std",
    "x_rotations",
    "x_loadings",
    "y_loadings",
]


class PLSParameters(Schema):
    model_config = ConfigDict(extra="forbid", frozen=True)

    n_components: PositiveInt = 2
    scale: StrictBool = True
    max_iter: ClassVar[int] = 500
    tol: ClassVar[float] = 1e-6
    copy: ClassVar[bool] = True


class PLSTrainingMetadata(Schema):
    """Training rows refer only to the arrays passed to the core, not a dataset."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    implementation_id: Literal["app.services.pls_modeling_service.fit_pls_core"] = (
        "app.services.pls_modeling_service.fit_pls_core"
    )
    implementation_version: Literal["pls-core-1"] = "pls-core-1"
    sklearn_version: Literal["1.7.2"]
    numpy_version: str = Field(min_length=1)
    scipy_version: str = Field(min_length=1)
    python_version: str = Field(min_length=1)
    feature_names: tuple[str, ...] = Field(min_length=1)
    target_name: str = Field(min_length=1)
    n_features: PositiveInt
    requested_n_components: PositiveInt
    effective_n_components: PositiveInt
    scale: StrictBool
    training_rows: Annotated[StrictInt, Field(ge=2)]
    parameters: PLSParameters
    n_iter: tuple[Annotated[StrictInt, Field(ge=1, le=500)], ...]
    training_warnings: tuple[str, ...] = ()
    sample_semantics: Literal["X[r] -> y[r]; zero-based CSV record; [start, stop)"] = (
        "X[r] -> y[r]; zero-based CSV record; [start, stop)"
    )
    prediction_horizon: Literal[1] = 1
    history_window: Literal[0] = 0
    history_guard: Literal[0] = 0

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if (
            self.n_features != len(self.feature_names)
            or len(set(self.feature_names)) != self.n_features
            or any(not name.strip() for name in self.feature_names)
            or not self.target_name.strip()
            or self.target_name in self.feature_names
        ):
            raise ValueError("Feature names and target must be separate, unique and ordered")
        if (
            self.requested_n_components != self.parameters.n_components
            or self.scale != self.parameters.scale
            or self.requested_n_components > min(self.training_rows, self.n_features)
            or self.effective_n_components > self.requested_n_components
            or len(self.n_iter) != self.effective_n_components
        ):
            raise ValueError("Inconsistent training dimensions or parameters")
        return self


class PLSArrayDescription(Schema):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: ArrayName
    shape: tuple[PositiveInt, ...] = Field(min_length=1, max_length=2)
    dtype: Literal["float64"] = "float64"


class PLSArtifactMetadata(PLSTrainingMetadata):
    artifact_format: Literal["indusopt_pls_json_npz_v1"] = "indusopt_pls_json_npz_v1"
    artifact_version: Annotated[StrictInt, Field(ge=1, le=1)] = 1
    model_type_id: Literal["pls"] = "pls"
    model_id: UUID
    npz_filename: str
    npz_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    npz_size_bytes: PositiveInt
    arrays: tuple[PLSArrayDescription, ...] = Field(min_length=9, max_length=9)

    @model_validator(mode="after")
    def valid_arrays(self) -> Self:
        if self.npz_filename != f"{self.model_id}.npz":
            raise ValueError("NPZ filename must match model_id")
        p, k = self.n_features, self.effective_n_components
        expected = {
            "coefficients": (1, p),
            "intercept": (1,),
            "x_mean": (p,),
            "x_std": (p,),
            "y_mean": (1,),
            "y_std": (1,),
            "x_rotations": (p, k),
            "x_loadings": (p, k),
            "y_loadings": (1, k),
        }
        if (
            len({a.name for a in self.arrays}) != 9
            or {a.name: a.shape for a in self.arrays} != expected
        ):
            raise ValueError("Array descriptors do not match model dimensions")
        return self


class PLSArtifactProvenance(Schema):
    """A source claim; database evidence is verified by the training service."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    training_run_id: UUID
    experiment_spec: ExperimentSpec
    experiment_spec_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    effective_training_rows: RowSet


class PLSBoundArtifactMetadata(PLSArtifactMetadata):
    """Standalone PLS v2, separate from the unified model manifest."""

    artifact_format: Literal["indusopt_pls_json_npz_v2"] = "indusopt_pls_json_npz_v2"
    artifact_version: Annotated[StrictInt, Field(ge=2, le=2)] = 2
    provenance: PLSArtifactProvenance

    @model_validator(mode="after")
    def consistent_source(self) -> Self:
        source = self.provenance
        spec = source.experiment_spec
        if self.model_id == source.training_run_id:
            raise ValueError("model_id and training_run_id must be different")
        if (
            self.feature_names != spec.input_columns
            or self.target_name != spec.target_column
            or self.training_rows != source.effective_training_rows.count
            or spec.feature_spec.history_window != self.history_window
            or spec.feature_spec.prediction_horizon != self.prediction_horizon
            or spec.split.history_guard != self.history_guard
        ):
            raise ValueError("PLS artifact and experiment source mismatch")
        return self


EvaluationPartition = Literal["validation", "test"]
EvaluationStatus = Literal["running", "succeeded", "failed"]
FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]


class PLSEvaluationRequest(Schema):
    model_id: UUID
    partition: EvaluationPartition
    training_run_id: UUID | None = None
    dataset_id: UUID | None = None
    dataset_version_id: UUID | None = None
    dataset_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None = None


class PLSRegressionMetrics(Schema):
    r2: FiniteFloat | None
    rmse: FiniteFloat | None
    mae: FiniteFloat | None
    nrmse: FiniteFloat | None


class PLSPredictionSummary(Schema):
    sample_count: PositiveInt
    prediction_min: FiniteFloat
    prediction_max: FiniteFloat
    prediction_mean: FiniteFloat
    residual_min: FiniteFloat
    residual_max: FiniteFloat
    residual_mean: FiniteFloat


class PLSEvaluationResult(Schema):
    evaluation_run_id: UUID
    model_id: UUID
    training_run_id: UUID
    dataset_id: UUID
    dataset_version_id: UUID
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    experiment_spec_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    partition: EvaluationPartition
    evaluation_rows: RowSet
    sample_count: PositiveInt
    metrics: PLSRegressionMetrics
    prediction_summary: PLSPredictionSummary
    evaluation_status: Literal["succeeded"] = "succeeded"
    implementation_version: Literal["pls-evaluation-1"] = "pls-evaluation-1"

    @model_validator(mode="after")
    def consistent_counts(self) -> Self:
        if self.sample_count != self.evaluation_rows.count or (
            self.sample_count != self.prediction_summary.sample_count
        ):
            raise ValueError("Evaluation row counts do not agree")
        if self.evaluation_run_id in (self.model_id, self.training_run_id):
            raise ValueError("Evaluation requires its own run identity")
        return self


class PLSEvaluationHistoryQuery(Schema):
    model_id: UUID
    partition: EvaluationPartition | None = None
    status: EvaluationStatus | None = None
    offset: Annotated[StrictInt, Field(ge=0)] = 0
    limit: Annotated[StrictInt, Field(ge=1, le=100)] = 20


class PLSEvaluationHistoryEntry(Schema):
    evaluation_run_id: UUID
    model_id: UUID
    training_run_id: UUID | None = None
    partition: EvaluationPartition
    evaluation_status: EvaluationStatus
    created_at: datetime
    finished_at: datetime | None = None
    evaluation_rows: RowSet | None = None
    sample_count: Annotated[StrictInt, Field(ge=0)] = 0
    metrics: PLSRegressionMetrics | None = None
    prediction_summary: PLSPredictionSummary | None = None
    failure_stage: str | None = None
    error_message: str | None = None


class PLSEvaluationHistory(Schema):
    items: tuple[PLSEvaluationHistoryEntry, ...]
    total: Annotated[StrictInt, Field(ge=0)]
    offset: Annotated[StrictInt, Field(ge=0)]
    limit: Annotated[StrictInt, Field(ge=1, le=100)]


class PLSFitRequest(Schema):
    experiment_spec: ExperimentSpec
    parameters: PLSParameters = Field(default_factory=PLSParameters)


class PLSModelBasics(Schema):
    model_type: Literal["pls"] = "pls"
    dataset_id: UUID
    dataset_version_id: UUID
    feature_names: tuple[str, ...]
    target_name: str
    parameters: PLSParameters


class PLSFitResponse(Schema):
    model_id: UUID
    training_run_id: UUID
    training_status: Literal["succeeded"]
    manifest_status: Literal["published", "failed"]
    model_info: PLSModelBasics
    manifest_retryable: bool = False
    retry_model_id: UUID | None = None
    retry_action: Literal["publish_existing_model_manifest"] | None = None
    error_code: str | None = None
    error_message: str | None = None


class ModelSourceSummary(Schema):
    dataset_id: UUID | None
    dataset_version_id: UUID
    dataset_sha256: str | None
    experiment_spec_hash: str | None


class ModelDetailsData(Schema):
    model_id: UUID
    model_type: Literal["arx", "fir", "oe", "pls", "xgboost", "tcn", "timexer"]
    training_run_id: UUID | None
    source: ModelSourceSummary
    feature_names: tuple[str, ...]
    target_name: str
    implementation_id: str | None
    implementation_version: str | None
    execution_scope: Literal["legacy_api", "core_only", "api"]
    manifest_version: int | None = None
    artifact_version: int | None = None
    status: Literal["loaded"] = "loaded"
    training_status: Literal["succeeded", "unknown"]
    provenance_status: Literal["verified", "incomplete"]
    missing_provenance: tuple[str, ...] = ()
    parameters: PLSParameters | TimeXerParameters | None = None
    requested_n_components: int | None = None
    effective_n_components: int | None = None
    training_rows: int | None = None


PredictionNumber = Annotated[StrictFloat, Field(allow_inf_nan=False)]


class PLSPredictRequest(Schema):
    model_id: UUID
    feature_names: tuple[Annotated[str, Field(min_length=1, max_length=255)], ...] = Field(
        min_length=1, max_length=256
    )
    X: tuple[Annotated[tuple[PredictionNumber, ...], Field(min_length=1, max_length=256)], ...] = (
        Field(min_length=1, max_length=1000)
    )

    @model_validator(mode="after")
    def validate_batch(self) -> Self:
        if (
            len(set(self.feature_names)) != len(self.feature_names)
            or any(not name.strip() for name in self.feature_names)
            or any(len(row) != len(self.feature_names) for row in self.X)
            or len(self.X) * len(self.feature_names) > 100_000
        ):
            raise ValueError("Expected aligned unique features and at most 100000 numeric cells")
        return self


class PLSPredictResponse(Schema):
    model_id: UUID
    predictions: tuple[FiniteFloat, ...] = Field(min_length=1, max_length=1000)
    sample_count: PositiveInt


class PLSEvaluationAPIHistoryEntry(PLSEvaluationHistoryEntry):
    evaluation_status: EvaluationStatus = Field(serialization_alias="status")


class PLSEvaluationAPIHistory(PLSEvaluationHistory):
    items: tuple[PLSEvaluationAPIHistoryEntry, ...]
