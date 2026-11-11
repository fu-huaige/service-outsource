"""Parameters and metadata for the standalone TCN."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import ConfigDict, Field, StrictFloat, StrictInt, StrictStr, model_validator

from app.schemas.common import Schema

KERNEL_SIZE = 3
DILATIONS = (1, 2, 4)
CONVOLUTIONS_PER_BLOCK = 2
MAX_FEATURES = 256
ADAM_BETAS = (0.9, 0.999)
ADAM_EPS = 1e-8
Seed = Annotated[StrictInt, Field(ge=0, lt=2**32)]


def receptive_field() -> int:
    return 1 + CONVOLUTIONS_PER_BLOCK * (KERNEL_SIZE - 1) * sum(DILATIONS)


class TCNParameters(Schema):
    model_config = ConfigDict(extra="forbid", frozen=True)

    window_length: Annotated[StrictInt, Field(ge=receptive_field(), le=256)] = 32
    hidden_channels: Annotated[StrictInt, Field(ge=1, le=128)] = 32
    learning_rate: Annotated[StrictFloat, Field(gt=0, le=1, allow_inf_nan=False)] = 0.001
    epochs: Annotated[StrictInt, Field(ge=1, le=500)] = 30
    batch_size: Annotated[StrictInt, Field(ge=1, le=128)] = 32


class TCNTrainingMetadata(Schema):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: UUID
    implementation_version: Literal["tcn-core-1"] = "tcn-core-1"
    torch_version: StrictStr = Field(pattern=r"^2\.9\.1(?:\+[a-zA-Z0-9.]+)?$")
    numpy_version: StrictStr = Field(min_length=1)
    python_version: StrictStr = Field(min_length=1)
    parameters: TCNParameters
    feature_names: tuple[StrictStr, ...] = Field(min_length=1, max_length=MAX_FEATURES)
    target_name: StrictStr
    window_length: StrictInt
    receptive_field: StrictInt
    training_samples: Annotated[StrictInt, Field(ge=2)]
    training_epochs: StrictInt
    training_loss: Annotated[StrictFloat, Field(ge=0, allow_inf_nan=False)]
    random_seed: Seed
    device: Literal["cpu"] = "cpu"
    dtype: Literal["float32"] = "float32"
    threads: Literal[1] = 1
    deterministic_algorithms: Literal[True] = True
    optimizer: Literal["Adam"] = "Adam"
    adam_betas: tuple[Literal[0.9], Literal[0.999]] = ADAM_BETAS
    adam_eps: Literal[1e-8] = ADAM_EPS
    adam_weight_decay: Literal[0] = 0
    adam_amsgrad: Literal[False] = False
    adam_foreach: Literal[False] = False
    adam_fused: Literal[False] = False
    loss: Literal["MSELoss"] = "MSELoss"
    loss_reduction: Literal["mean"] = "mean"
    kernel_size: Literal[3] = KERNEL_SIZE
    dilations: tuple[Literal[1], Literal[2], Literal[4]] = DILATIONS
    convolutions_per_block: Literal[2] = CONVOLUTIONS_PER_BLOCK
    activation: Literal["relu"] = "relu"
    dropout: Literal[0] = 0
    stride: Literal[1] = 1
    padding: Literal["left_causal_zero"] = "left_causal_zero"
    head: Literal["last_position_linear"] = "last_position_linear"
    prediction_horizon: Literal[1] = 1
    sample_semantics: Literal["X[r-L:r] -> y[r]"] = "X[r-L:r] -> y[r]"
    shuffle: Literal[False] = False
    early_stopping: Literal[False] = False
    scheduler: Literal["none"] = "none"
    preprocessing: Literal["none"] = "none"
    source_status: Literal["unbound"] = "unbound"

    @model_validator(mode="after")
    def consistent_training(self) -> Self:
        if (
            any(not name.strip() for name in self.feature_names)
            or len(set(self.feature_names)) != len(self.feature_names)
            or not self.target_name.strip()
            or self.target_name in self.feature_names
        ):
            raise ValueError("Expected ordered unique features and a separate target")
        if (
            self.window_length != self.parameters.window_length
            or self.receptive_field != receptive_field()
            or self.training_epochs != self.parameters.epochs
        ):
            raise ValueError("Training metadata differs from the model configuration")
        return self


class TCNTensorDescription(Schema):
    model_config = ConfigDict(extra="forbid", frozen=True)

    parameter_name: StrictStr = Field(min_length=1)
    array_name: StrictStr = Field(pattern=r"^tensor_[0-9]{3}$")
    shape: tuple[Annotated[StrictInt, Field(gt=0)], ...] = Field(min_length=1, max_length=3)
    dtype: Literal["float32"] = "float32"


class TCNArtifactMetadata(TCNTrainingMetadata):
    format_version: Annotated[StrictInt, Field(ge=1, le=1)] = 1
    payload_format: Literal["indusopt_tcn_json_npz_v1"] = "indusopt_tcn_json_npz_v1"
    model_type_id: Literal["tcn"] = "tcn"
    npz_filename: StrictStr
    npz_size_bytes: Annotated[StrictInt, Field(gt=0)]
    npz_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    arrays: tuple[TCNTensorDescription, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def consistent_artifact(self) -> Self:
        if self.npz_filename != f"{self.model_id}.npz":
            raise ValueError("NPZ filename does not match model_id")
        if len({item.parameter_name for item in self.arrays}) != len(self.arrays) or any(
            item.array_name != f"tensor_{i:03d}" for i, item in enumerate(self.arrays)
        ):
            raise ValueError("Invalid state_dict array mapping")
        return self
