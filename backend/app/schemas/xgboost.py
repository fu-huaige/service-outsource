"""Standalone, single-target XGBoost contracts; no registry or database dependency."""

from __future__ import annotations

import json
from types import MappingProxyType
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import ConfigDict, Field, StrictFloat, StrictInt, StrictStr, model_validator

from app.schemas.common import Schema

NativeParameter = str | int | float | bool
PositiveInt = Annotated[StrictInt, Field(gt=0)]
Seed = Annotated[StrictInt, Field(ge=0, lt=2**31)]
FIXED_PARAMETERS = MappingProxyType(
    {
        "booster": "gbtree",
        "tree_method": "hist",
        "device": "cpu",
        "objective": "reg:squarederror",
        "eval_metric": "rmse",
        "max_bin": 256,
        "num_parallel_tree": 1,
        "nthread": 1,
        "validate_parameters": True,
        "subsample": 1.0,
        "colsample_bytree": 1.0,
        "min_child_weight": 1.0,
        "reg_alpha": 0.0,
        "reg_lambda": 1.0,
        "gamma": 0.0,
    }
)


class XGBoostParameters(Schema):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_depth: Annotated[StrictInt, Field(ge=1, le=8)] = 4
    learning_rate: Annotated[StrictFloat, Field(gt=0, le=1, allow_inf_nan=False)] = 0.05
    num_boost_round: Annotated[StrictInt, Field(ge=1, le=1000)] = 200

    def booster_parameters(self, *, random_seed: int = 0) -> dict[str, NativeParameter]:
        if type(random_seed) is not int or not 0 <= random_seed < 2**31:
            raise ValueError("random_seed must be an integer in [0, 2**31)")
        return {
            **FIXED_PARAMETERS,
            "max_depth": self.max_depth,
            "learning_rate": self.learning_rate,
            "seed": random_seed,
        }


class XGBoostTrainingMetadata(Schema):
    model_config = ConfigDict(extra="forbid", frozen=True)

    implementation_id: Literal["app.services.xgboost_modeling_service.fit_xgboost_core"] = (
        "app.services.xgboost_modeling_service.fit_xgboost_core"
    )
    implementation_version: Literal["xgboost-core-1"] = "xgboost-core-1"
    xgboost_version: Literal["3.1.3"]
    python_version: StrictStr
    numpy_version: StrictStr
    scipy_version: StrictStr
    parameters: XGBoostParameters
    effective_parameters: dict[str, NativeParameter]
    random_seed: Seed
    boosting_rounds: Annotated[StrictInt, Field(ge=1, le=1000)]
    feature_names: tuple[StrictStr, ...] = Field(min_length=1)
    internal_feature_names: tuple[StrictStr, ...] = Field(min_length=1)
    n_features: PositiveInt
    target_name: StrictStr = Field(min_length=1)
    training_rows: Annotated[StrictInt, Field(ge=2)]
    numeric_dtype: Literal["float32"] = "float32"
    missing_policy: Literal["reject"] = "reject"
    preprocessing: Literal["none"] = "none"

    @model_validator(mode="after")
    def consistent_training(self) -> Self:
        if (
            len(self.feature_names) != self.n_features
            or len(set(self.feature_names)) != self.n_features
            or any(not name.strip() for name in self.feature_names)
            or not self.target_name.strip()
            or self.target_name in self.feature_names
            or self.internal_feature_names != tuple(f"f{i}" for i in range(self.n_features))
            or self.boosting_rounds != self.parameters.num_boost_round
        ):
            raise ValueError("Inconsistent features, target or boosting rounds")
        expected = self.parameters.booster_parameters(random_seed=self.random_seed)
        # Compare strict JSON types, including bool versus int and finite floats.
        if json.dumps(self.effective_parameters, sort_keys=True, allow_nan=False) != json.dumps(
            expected,
            sort_keys=True,
            allow_nan=False,
        ):
            raise ValueError("Effective parameters differ from the authorized configuration")
        return self


class XGBoostArtifactMetadata(XGBoostTrainingMetadata):
    """Standalone evidence only: a supplied run UUID has not been verified in a database."""

    artifact_version: Annotated[StrictInt, Field(ge=1, le=1)] = 1
    payload_format: Literal["indusopt_xgboost_json_ubj_v1"] = "indusopt_xgboost_json_ubj_v1"
    model_type_id: Literal["xgboost"] = "xgboost"
    model_id: UUID
    training_run_id: UUID | None = None
    provenance_status: Literal["unbound", "provided_unverified"] = "unbound"
    ubj_filename: StrictStr
    ubj_size_bytes: PositiveInt
    ubj_sha256: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]

    @model_validator(mode="after")
    def consistent_identity(self) -> Self:
        expected = "unbound" if self.training_run_id is None else "provided_unverified"
        if (
            self.provenance_status != expected
            or self.training_run_id == self.model_id
            or self.ubj_filename != f"{self.model_id}.ubj"
        ):
            raise ValueError("Artifact identity, filename or unverified provenance mismatch")
        return self
