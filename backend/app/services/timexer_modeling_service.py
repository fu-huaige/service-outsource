"""Standalone CPU TimeXer for prebuilt endogenous and exogenous windows."""

from __future__ import annotations

import math
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

import numpy as np
from numpy.typing import ArrayLike, NDArray
from pydantic import TypeAdapter

from app.schemas.timexer import (
    Seed,
    TimeXerParameters,
    TimeXerTrainingMetadata,
    validate_feature_names,
)

if TYPE_CHECKING:
    from torch import nn

_SEED = TypeAdapter(Seed)


def torch_runtime():
    import torch

    if torch.__version__.split("+", 1)[0] != "2.9.1":
        raise ValueError("Unsupported TimeXer PyTorch version; expected 2.9.1")
    return torch


@contextmanager
def seeded_cpu(seed: int, *, deterministic: bool = False) -> Iterator[None]:
    """Restore Torch settings on exit. Call only during serial PyTorch execution."""
    torch = torch_runtime()
    previous = torch.are_deterministic_algorithms_enabled()
    warn_only = torch.is_deterministic_algorithms_warn_only_enabled()
    try:
        if deterministic:
            torch.use_deterministic_algorithms(True)
        with torch.random.fork_rng(devices=[]), torch.autocast(device_type="cpu", enabled=False):
            torch.random.default_generator.manual_seed(seed)
            yield
    finally:
        if deterministic:
            torch.use_deterministic_algorithms(previous, warn_only=warn_only)


def _float32_window(value: ArrayLike, shape: tuple[int, ...], name: str) -> NDArray[np.float32]:
    array = np.asarray(value)
    if array.ndim != len(shape) + 1 or not array.shape[0] or array.shape[1:] != shape:
        raise ValueError(f"{name} must have shape (N, {', '.join(map(str, shape))}) with N > 0")
    if array.dtype.kind not in "iuf" or not np.isfinite(array).all():
        raise ValueError(f"{name} must contain finite real numbers")
    with np.errstate(over="ignore"):
        result = np.array(array, dtype=np.float32, order="C", copy=True)
    if not np.isfinite(result).all():
        raise ValueError(f"{name} overflows float32")
    return result


def _windows(X_target, X_exogenous, p: TimeXerParameters, count: int):
    target = _float32_window(X_target, (p.target_window_length, 1), "X_target")
    exogenous = _float32_window(X_exogenous, (p.exogenous_window_length, count), "X_exogenous")
    if len(target) != len(exogenous):
        raise ValueError("Target and exogenous windows must have the same sample count")
    return target, exogenous


def build_timexer(p: TimeXerParameters, *, device: str = "cpu") -> nn.Module:
    torch = torch_runtime()
    nn = torch.nn
    dim = p.embedding_dim
    options = {"device": device, "dtype": torch.float32}

    class EncoderLayer(nn.Module):
        def __init__(self):
            super().__init__()
            self.self_attention = nn.MultiheadAttention(
                dim, p.num_heads, dropout=p.dropout, batch_first=True, **options
            )
            self.cross_attention = nn.MultiheadAttention(
                dim, p.num_heads, dropout=p.dropout, batch_first=True, **options
            )
            self.self_norm = nn.LayerNorm(dim, **options)
            self.cross_norm = nn.LayerNorm(dim, **options)
            self.ff_norm = nn.LayerNorm(dim, **options)
            self.dropout = nn.Dropout(p.dropout)
            self.feed_forward = nn.Sequential(
                nn.Linear(dim, 2 * dim, **options),
                nn.GELU(),
                nn.Dropout(p.dropout),
                nn.Linear(2 * dim, dim, **options),
            )

        def forward(self, tokens, variates):
            attention, _ = self.self_attention(tokens, tokens, tokens, need_weights=False)
            tokens = self.self_norm(tokens + self.dropout(attention))
            global_token = tokens[:, -1:, :]
            attention, _ = self.cross_attention(
                global_token, variates, variates, need_weights=False
            )
            global_token = self.cross_norm(global_token + self.dropout(attention))
            tokens = torch.cat((tokens[:, :-1, :], global_token), dim=1)
            return self.ff_norm(tokens + self.dropout(self.feed_forward(tokens)))

    class TimeXerNetwork(nn.Module):
        def __init__(self):
            super().__init__()
            self.patch_embedding = nn.Linear(p.patch_length, dim, bias=False, **options)
            self.variate_embedding = nn.Linear(p.exogenous_window_length, dim, **options)
            self.global_token = nn.Parameter(torch.empty(1, 1, dim, **options))
            nn.init.normal_(self.global_token, mean=0.0, std=0.02)
            positions = torch.arange(p.patch_count, **options).unsqueeze(1)
            scale = torch.exp(torch.arange(0, dim, 2, **options) * (-math.log(10000) / dim))
            angles = positions * scale
            encoding = torch.stack((angles.sin(), angles.cos()), dim=-1).flatten(1).unsqueeze(0)
            self.register_buffer("position_encoding", encoding)
            self.embedding_dropout = nn.Dropout(p.dropout)
            self.encoder = nn.ModuleList(EncoderLayer() for _ in range(p.encoder_layers))
            self.encoder_norm = nn.LayerNorm(dim, **options)
            self.head = nn.Linear((p.patch_count + 1) * dim, p.prediction_length, **options)

        def forward(self, target, exogenous):
            patches = target.squeeze(-1).unfold(-1, p.patch_length, p.patch_length)
            patches = self.patch_embedding(patches) + self.position_encoding
            tokens = torch.cat((patches, self.global_token.expand(len(target), -1, -1)), dim=1)
            tokens = self.embedding_dropout(tokens)
            variates = self.embedding_dropout(self.variate_embedding(exogenous.transpose(1, 2)))
            for layer in self.encoder:
                tokens = layer(tokens, variates)
            return self.head(self.encoder_norm(tokens).flatten(1))

    return TimeXerNetwork()


@dataclass(frozen=True)
class TimeXerModel:
    model: nn.Module
    metadata: TimeXerTrainingMetadata


def fit_timexer_core(
    X_target: ArrayLike,
    X_exogenous: ArrayLike,
    y: ArrayLike,
    *,
    target_name: str,
    exogenous_feature_names: tuple[str, ...],
    parameters: TimeXerParameters | None = None,
    random_seed: int = 0,
) -> TimeXerModel:
    """Fit once on caller-aligned training windows in their original order."""
    p = TimeXerParameters() if parameters is None else parameters
    seed = _SEED.validate_python(random_seed)
    validate_feature_names(target_name, exogenous_feature_names)
    names = tuple(exogenous_feature_names)
    target, exogenous = _windows(X_target, X_exogenous, p, len(names))
    labels = _float32_window(y, (p.prediction_length,), "y")
    if len(labels) != len(target):
        raise ValueError("Labels and input windows must have the same sample count")

    torch = torch_runtime()
    with seeded_cpu(seed, deterministic=True), torch.inference_mode(False), torch.enable_grad():
        target_tensor = torch.from_numpy(target)
        exogenous_tensor = torch.from_numpy(exogenous)
        label_tensor = torch.from_numpy(labels)
        model = build_timexer(p)
        optimizer = torch.optim.Adam(model.parameters(), lr=p.learning_rate)
        criterion = torch.nn.MSELoss()
        threads = torch.get_num_threads()
        epoch_losses = []
        for _ in range(p.epochs):
            loss_sum = 0.0
            for start in range(0, len(target), p.batch_size):
                batch = slice(start, start + p.batch_size)
                optimizer.zero_grad(set_to_none=True)
                predicted = model(target_tensor[batch], exogenous_tensor[batch])
                loss = criterion(predicted, label_tensor[batch])
                batch_loss = loss.item()
                if not math.isfinite(batch_loss):
                    raise ValueError("Nonfinite TimeXer training loss")
                loss.backward()
                optimizer.step()
                loss_sum += batch_loss * len(label_tensor[batch])
            epoch_losses.append(loss_sum / len(target))
        if any(not tensor.isfinite().all().item() for tensor in model.state_dict().values()):
            raise ValueError("Nonfinite TimeXer model state")
        model.eval()

    metadata = TimeXerTrainingMetadata(
        model_id=uuid4(),
        parameters=p,
        target_name=target_name,
        exogenous_feature_names=names,
        target_window_length=p.target_window_length,
        exogenous_window_length=p.exogenous_window_length,
        exogenous_feature_count=len(names),
        prediction_length=p.prediction_length,
        patch_count=p.patch_count,
        ff_dim=2 * p.embedding_dim,
        training_threads=threads,
        random_seed=seed,
        training_samples=len(target),
        training_epochs=len(epoch_losses),
        epoch_losses=tuple(epoch_losses),
        training_loss=epoch_losses[-1],
        torch_version=str(torch.__version__),
        numpy_version=np.__version__,
    )
    return TimeXerModel(model=model, metadata=metadata)


def predict_timexer(
    fitted: TimeXerModel,
    X_target: ArrayLike,
    X_exogenous: ArrayLike,
    *,
    target_name: str,
    exogenous_feature_names: tuple[str, ...],
) -> NDArray[np.float32]:
    metadata = fitted.metadata
    validate_feature_names(target_name, exogenous_feature_names)
    if (
        target_name != metadata.target_name
        or tuple(exogenous_feature_names) != metadata.exogenous_feature_names
    ):
        raise ValueError("Target and ordered exogenous feature names must match the model")
    target, exogenous = _windows(
        X_target, X_exogenous, metadata.parameters, metadata.exogenous_feature_count
    )
    torch = torch_runtime()
    with torch.inference_mode(), torch.autocast(device_type="cpu", enabled=False):
        fitted.model.eval()
        predicted = fitted.model(torch.from_numpy(target), torch.from_numpy(exogenous))
        if (
            predicted.shape != (len(target), metadata.prediction_length)
            or predicted.device.type != "cpu"
            or predicted.dtype != torch.float32
            or not predicted.isfinite().all().item()
        ):
            raise ValueError("TimeXer prediction must contain finite CPU float32 values in (N, H)")
        return predicted.numpy()
