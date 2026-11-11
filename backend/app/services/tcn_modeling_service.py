"""CPU TCN training and fixed prediction on prebuilt windows."""

from __future__ import annotations

import platform
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from threading import RLock
from typing import TYPE_CHECKING
from uuid import uuid4

import numpy as np
from numpy.typing import ArrayLike, NDArray
from pydantic import TypeAdapter

from app.schemas.tcn import (
    ADAM_BETAS,
    ADAM_EPS,
    CONVOLUTIONS_PER_BLOCK,
    DILATIONS,
    KERNEL_SIZE,
    MAX_FEATURES,
    Seed,
    TCNParameters,
    TCNTrainingMetadata,
    receptive_field,
)

if TYPE_CHECKING:
    import torch
    from torch import nn

_EXECUTION_LOCK = RLock()
_SEED = TypeAdapter(Seed)


def torch_runtime():
    import torch

    if torch.__version__.split("+", 1)[0] != "2.9.1":
        raise ValueError("Unsupported TCN PyTorch version; expected 2.9.1")
    return torch


@contextmanager
def cpu_execution(seed: int | None = None) -> Iterator[None]:
    """Serialize TCN operations while temporarily changing Torch process settings."""
    torch = torch_runtime()
    with _EXECUTION_LOCK:
        threads = torch.get_num_threads()
        deterministic = torch.are_deterministic_algorithms_enabled()
        warn_only = torch.is_deterministic_algorithms_warn_only_enabled()
        try:
            torch.set_num_threads(1)
            torch.use_deterministic_algorithms(True)
            with (
                torch.random.fork_rng(devices=[], enabled=seed is not None),
                torch.autocast(device_type="cpu", enabled=False),
            ):
                if seed is not None:
                    torch.random.default_generator.manual_seed(seed)
                yield
        finally:
            torch.use_deterministic_algorithms(deterministic, warn_only=warn_only)
            torch.set_num_threads(threads)


def _numeric_array(value: ArrayLike, *, ndim: int) -> NDArray[np.float32]:
    array = np.asarray(value)
    if array.ndim != ndim or array.dtype.kind not in "iuf":
        raise ValueError(f"Expected a {ndim}-dimensional real numeric array")
    if not np.isfinite(array).all():
        raise ValueError("Inputs must be finite")
    with np.errstate(over="ignore", invalid="ignore"):
        result = np.array(array, dtype=np.float32, order="C", copy=True)
    if not np.isfinite(result).all():
        raise ValueError("Input overflows float32")
    return result


def _feature_names(
    feature_names: tuple[str, ...],
    target_name: str,
    width: int,
) -> tuple[str, ...]:
    if (
        not isinstance(feature_names, (list, tuple))
        or not 1 <= width <= MAX_FEATURES
        or len(feature_names) != width
        or any(not isinstance(name, str) or not name.strip() for name in feature_names)
        or len(set(feature_names)) != width
        or not isinstance(target_name, str)
        or not target_name.strip()
        or target_name in feature_names
    ):
        raise ValueError("Expected ordered unique features and a separate target")
    return tuple(feature_names)


def build_tcn(n_features: int, parameters: TCNParameters) -> nn.Module:
    """Build the fixed architecture with the caller's scoped CPU RNG."""
    torch = torch_runtime()
    nn = torch.nn
    options = {"device": "cpu", "dtype": torch.float32}

    class ResidualBlock(nn.Module):
        def __init__(self, width: int, dilation: int):
            super().__init__()
            layers = []
            for _ in range(CONVOLUTIONS_PER_BLOCK):
                layers.extend(
                    (
                        nn.ConstantPad1d((dilation * (KERNEL_SIZE - 1), 0), 0),
                        nn.Conv1d(
                            width,
                            parameters.hidden_channels,
                            KERNEL_SIZE,
                            dilation=dilation,
                            **options,
                        ),
                        nn.ReLU(),
                    )
                )
                width = parameters.hidden_channels
            self.convolutions = nn.Sequential(*layers)
            input_width = self.convolutions[1].in_channels
            self.skip = (
                nn.Identity()
                if input_width == width
                else nn.Conv1d(input_width, width, 1, **options)
            )

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            return torch.relu(self.convolutions(x) + self.skip(x))

    class TCN(nn.Module):
        def __init__(self):
            super().__init__()
            width = parameters.hidden_channels
            self.blocks = nn.Sequential(
                *(
                    ResidualBlock(n_features if i == 0 else width, dilation)
                    for i, dilation in enumerate(DILATIONS)
                )
            )
            self.head = nn.Linear(width, 1, **options)

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            return self.head(self.blocks(x)[:, :, -1]).squeeze(-1)

    return TCN()


@dataclass(frozen=True)
class TCNModel:
    model: nn.Module
    metadata: TCNTrainingMetadata

    def predict(self, X: ArrayLike, *, feature_names: tuple[str, ...]) -> NDArray[np.float32]:
        return predict_tcn(self, X, feature_names=feature_names)


def _channels_first(torch, array: NDArray[np.float32]) -> torch.Tensor:
    return torch.from_numpy(array.transpose(0, 2, 1).copy(order="C"))


def fit_tcn_core(
    X_train: ArrayLike,
    y_train: ArrayLike,
    *,
    feature_names: tuple[str, ...],
    target_name: str,
    parameters: TCNParameters | None = None,
    random_seed: int = 0,
) -> TCNModel:
    config = TCNParameters.model_validate({} if parameters is None else parameters.model_dump())
    seed = _SEED.validate_python(random_seed)
    x = _numeric_array(X_train, ndim=3)
    y = _numeric_array(y_train, ndim=1)
    n, length, width = x.shape
    if n < 2 or y.shape != (n,) or length != config.window_length:
        raise ValueError("Expected aligned training windows of the configured length")
    names = _feature_names(feature_names, target_name, width)
    torch = torch_runtime()
    with cpu_execution(seed), torch.inference_mode(False), torch.enable_grad():
        model = build_tcn(width, config)
        inputs, labels = _channels_first(torch, x), torch.from_numpy(y)
        optimizer = torch.optim.Adam(
            model.parameters(),
            lr=config.learning_rate,
            betas=ADAM_BETAS,
            eps=ADAM_EPS,
            weight_decay=0,
            amsgrad=False,
            foreach=False,
            fused=False,
        )
        criterion = torch.nn.MSELoss(reduction="mean")
        model.train()
        for _ in range(config.epochs):
            for start in range(0, n, config.batch_size):
                stop = start + config.batch_size
                optimizer.zero_grad(set_to_none=True)
                loss = criterion(model(inputs[start:stop]), labels[start:stop])
                if not torch.isfinite(loss).item():
                    raise ValueError("Nonfinite TCN training loss")
                loss.backward()
                optimizer.step()

        model.eval()
        squared_error = 0.0
        with torch.inference_mode():
            for start in range(0, n, config.batch_size):
                stop = start + config.batch_size
                residual = model(inputs[start:stop]).double() - labels[start:stop].double()
                squared_error += residual.square().sum().item()
            if any(
                not torch.isfinite(tensor).all().item() for tensor in model.state_dict().values()
            ):
                raise ValueError("Nonfinite TCN model state")
    metadata = TCNTrainingMetadata(
        model_id=uuid4(),
        torch_version=torch.__version__,
        numpy_version=np.__version__,
        python_version=platform.python_version(),
        parameters=config,
        feature_names=names,
        target_name=target_name,
        window_length=length,
        receptive_field=receptive_field(),
        training_samples=n,
        training_epochs=config.epochs,
        training_loss=squared_error / n,
        random_seed=seed,
    )
    return TCNModel(model, metadata)


def predict_tcn(
    fitted: TCNModel,
    X: ArrayLike,
    *,
    feature_names: tuple[str, ...],
) -> NDArray[np.float32]:
    metadata = fitted.metadata
    if (
        not isinstance(feature_names, (tuple, list))
        or tuple(feature_names) != metadata.feature_names
    ):
        raise ValueError("Feature order differs from training")
    x = _numeric_array(X, ndim=3)
    if not len(x) or x.shape[1:] != (metadata.window_length, len(metadata.feature_names)):
        raise ValueError("Window dimensions differ from training")
    torch = torch_runtime()
    with cpu_execution(), torch.inference_mode():
        fitted.model.eval()
        batches = [
            fitted.model(_channels_first(torch, x[start : start + metadata.parameters.batch_size]))
            for start in range(0, len(x), metadata.parameters.batch_size)
        ]
        output = torch.cat(batches)
        if (
            output.shape != (len(x),)
            or output.device.type != "cpu"
            or output.dtype != torch.float32
            or not torch.isfinite(output).all().item()
        ):
            raise ValueError("Invalid TCN prediction shape, dtype, device or values")
        return output.numpy().copy()
