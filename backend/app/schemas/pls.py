"""Static, single-target PLS core and standalone artifact contracts."""

from __future__ import annotations

from typing import Annotated, ClassVar, Literal, Self
from uuid import UUID

from pydantic import ConfigDict, Field, StrictBool, StrictInt, model_validator

from app.schemas.common import Schema
from app.schemas.experiment_spec import ExperimentSpec, RowSet

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
