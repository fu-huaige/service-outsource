"""Static model descriptions and read-only artifact contracts."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field

from app.schemas.common import Schema
from app.schemas.experiment_spec import ExperimentSpec, RowSet

ModelTypeId = Literal["arx", "fir", "oe", "pls"]


class ModelCapabilities(Schema):
    model_config = ConfigDict(extra="forbid", frozen=True)
    single_target: bool = True
    prediction: bool = True
    supervised_regression: bool = False
    latent_transform: bool = False
    multi_input: bool = True
    multi_output: bool = False
    selected_rows: bool = True
    soft_weights: bool = True
    free_run: bool = True
    one_step_equation: bool = True
    continuous_selected_intervals_required: bool = False
    independent_run_api: bool = False


class ModelTypeDefinition(Schema):
    model_config = ConfigDict(extra="forbid", frozen=True)
    model_type_id: ModelTypeId
    display_name: str
    family: Literal["linear_dynamic", "linear_latent_regression"] = "linear_dynamic"
    supported_tasks: tuple[str, ...] = ("dynamic_system_identification",)
    availability: Literal["available", "planned"] = "available"
    maturity: Literal["established", "experimental"] = "established"
    execution_scope: Literal["legacy_api", "core_only", "api"] = "legacy_api"
    implementation_id: str
    implementation_version: str = "stage1a-contract-1"
    parameter_schema_id: str = "app.schemas.modeling.ArxFitRequest"
    capabilities: ModelCapabilities = Field(default_factory=ModelCapabilities)
    constraints: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ("numpy>=1.26,<3", "scipy>=1.13,<2")
    device: Literal["cpu"] = "cpu"
    budget_enforcement: Literal["not_implemented"] = "not_implemented"


class ModelArtifactManifest(Schema):
    """A sidecar contract; this module never writes or changes model payloads."""

    manifest_version: Literal[1] = 1
    model_type_id: Literal["arx", "fir", "oe"]
    model_id: UUID
    training_run_id: UUID
    implementation_id: str
    implementation_version: str
    experiment_spec: ExperimentSpec
    experiment_spec_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    effective_training_rows: RowSet
    payload_format: Literal["legacy_dynamic_json"] = "legacy_dynamic_json"
    payload_uri: str
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PLSModelArtifactManifest(ModelArtifactManifest):
    """Same manifest structure v1; the standalone PLS payload has its own v2."""

    model_type_id: Literal["pls"] = "pls"
    payload_format: Literal["indusopt_pls_json_npz_v2"] = "indusopt_pls_json_npz_v2"
