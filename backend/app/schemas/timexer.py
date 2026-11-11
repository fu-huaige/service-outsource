"""Strict parameters and metadata for the standalone TimeXer core."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import ConfigDict, Field, StrictFloat, StrictInt, StrictStr, model_validator

from app.schemas.common import Schema

MAX_EXOGENOUS_FEATURES = 64
Seed = Annotated[StrictInt, Field(ge=0, lt=2**32)]
TrainingLoss = Annotated[StrictFloat, Field(ge=0, allow_inf_nan=False)]


def validate_feature_names(target_name: str, exogenous_feature_names: tuple[str, ...]) -> None:
    if not isinstance(target_name, str) or not target_name.strip():
        raise ValueError("Expected a nonempty target name")
    if not isinstance(exogenous_feature_names, (tuple, list)) or not (
        1 <= len(exogenous_feature_names) <= MAX_EXOGENOUS_FEATURES
    ):
        raise ValueError("Expected 1 to 64 ordered exogenous feature names")
    if (
        any(not isinstance(name, str) or not name.strip() for name in exogenous_feature_names)
        or len(set(exogenous_feature_names)) != len(exogenous_feature_names)
        or target_name in exogenous_feature_names
    ):
        raise ValueError("Expected unique exogenous names and a separate target")


class TimeXerParameters(Schema):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target_window_length: Annotated[StrictInt, Field(ge=8, le=256)] = 64
    exogenous_window_length: Annotated[StrictInt, Field(ge=8, le=256)] = 64
    patch_length: Annotated[StrictInt, Field(ge=4, le=32)] = 8
    prediction_length: Annotated[StrictInt, Field(ge=1, le=32)] = 1
    embedding_dim: Annotated[StrictInt, Field(ge=16, le=128)] = 32
    num_heads: Annotated[StrictInt, Field(ge=1, le=8)] = 4
    encoder_layers: Annotated[StrictInt, Field(ge=2, le=4)] = 2
    dropout: Annotated[StrictFloat, Field(ge=0, le=0.3, allow_inf_nan=False)] = 0.0
    learning_rate: Annotated[StrictFloat, Field(gt=0, le=0.1, allow_inf_nan=False)] = 0.001
    epochs: Annotated[StrictInt, Field(ge=1, le=100)] = 30
    batch_size: Annotated[StrictInt, Field(ge=1, le=64)] = 32

    @property
    def patch_count(self) -> int:
        return self.target_window_length // self.patch_length

    @model_validator(mode="after")
    def validate_architecture(self) -> Self:
        if self.target_window_length % self.patch_length or not 2 <= self.patch_count <= 32:
            raise ValueError("Target window must contain 2 to 32 complete patches")
        if self.embedding_dim % 2 or self.embedding_dim % self.num_heads:
            raise ValueError("Embedding dimension must be even and divisible by num_heads")
        return self


class TimeXerTrainingMetadata(Schema):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: UUID
    implementation_version: Literal["timexer-core-1"] = "timexer-core-1"
    source_status: Literal["unbound"] = "unbound"
    parameters: TimeXerParameters
    target_name: StrictStr
    exogenous_feature_names: tuple[StrictStr, ...] = Field(
        min_length=1, max_length=MAX_EXOGENOUS_FEATURES
    )
    target_window_length: StrictInt
    exogenous_window_length: StrictInt
    exogenous_feature_count: StrictInt
    prediction_length: StrictInt
    patch_count: StrictInt
    ff_dim: StrictInt
    ff_activation: Literal["gelu"] = "gelu"
    positional_encoding: Literal["sinusoidal"] = "sinusoidal"
    global_token_initialization: Literal["normal_0_0.02"] = "normal_0_0.02"
    attention_layout: Literal["endogenous_self_global_cross"] = "endogenous_self_global_cross"
    head: Literal["token_major_flatten_linear"] = "token_major_flatten_linear"
    normalization_mode: Literal["none"] = "none"
    device: Literal["cpu"] = "cpu"
    dtype: Literal["float32"] = "float32"
    optimizer: Literal["Adam"] = "Adam"
    loss: Literal["MSE"] = "MSE"
    epoch_loss_semantics: Literal["sample_weighted_batch_mse"] = "sample_weighted_batch_mse"
    batch_order: Literal["input_order"] = "input_order"
    early_stopping: Literal[False] = False
    deterministic_algorithms: Literal[True] = True
    execution_policy: Literal["serial_pytorch"] = "serial_pytorch"
    training_threads: Annotated[StrictInt, Field(ge=1)]
    random_seed: Seed
    training_samples: Annotated[StrictInt, Field(ge=1)]
    training_epochs: StrictInt
    epoch_losses: tuple[TrainingLoss, ...] = Field(min_length=1, max_length=100)
    training_loss: TrainingLoss
    torch_version: StrictStr = Field(pattern=r"^2\.9\.1(?:\+[a-zA-Z0-9.]+)?$")
    numpy_version: StrictStr = Field(min_length=1)

    @model_validator(mode="after")
    def validate_training(self) -> Self:
        validate_feature_names(self.target_name, self.exogenous_feature_names)
        p = self.parameters
        if (
            self.target_window_length != p.target_window_length
            or self.exogenous_window_length != p.exogenous_window_length
            or self.exogenous_feature_count != len(self.exogenous_feature_names)
            or self.prediction_length != p.prediction_length
            or self.patch_count != p.patch_count
            or self.ff_dim != 2 * p.embedding_dim
            or self.training_epochs != p.epochs
            or len(self.epoch_losses) != self.training_epochs
            or self.training_loss != self.epoch_losses[-1]
        ):
            raise ValueError("TimeXer metadata differs from its training configuration")
        return self


class TimeXerTensorDescription(Schema):
    model_config = ConfigDict(extra="forbid", frozen=True)

    parameter_name: StrictStr = Field(min_length=1)
    array_name: StrictStr = Field(pattern=r"^tensor_[0-9]{3}$")
    shape: tuple[Annotated[StrictInt, Field(gt=0)], ...] = Field(min_length=1, max_length=3)
    dtype: Literal["float32"] = "float32"


class TimeXerArtifactMetadata(TimeXerTrainingMetadata):
    schema_version: Annotated[StrictInt, Field(ge=1, le=1)] = 1
    payload_format: Literal["indusopt_timexer_json_npz_v1"] = "indusopt_timexer_json_npz_v1"
    model_type_id: Literal["timexer"] = "timexer"
    npz_filename: StrictStr
    npz_size_bytes: Annotated[StrictInt, Field(gt=0)]
    npz_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    arrays: tuple[TimeXerTensorDescription, ...] = Field(min_length=1, max_length=96)

    @model_validator(mode="after")
    def validate_payload(self) -> Self:
        if self.npz_filename != f"{self.model_id}.npz":
            raise ValueError("NPZ filename does not match model_id")
        if len({item.parameter_name for item in self.arrays}) != len(self.arrays) or any(
            item.array_name != f"tensor_{index:03d}" for index, item in enumerate(self.arrays)
        ):
            raise ValueError("Invalid TimeXer tensor mapping")
        return self
