import pytest
from app.schemas.timexer import Seed, TimeXerParameters
from pydantic import TypeAdapter, ValidationError


def test_defaults():
    parameters = TimeXerParameters()
    assert parameters.model_dump() == {
        "target_window_length": 64,
        "exogenous_window_length": 64,
        "patch_length": 8,
        "prediction_length": 1,
        "embedding_dim": 32,
        "num_heads": 4,
        "encoder_layers": 2,
        "dropout": 0.0,
        "learning_rate": 0.001,
        "epochs": 30,
        "batch_size": 32,
    }
    assert parameters.patch_count == 8


@pytest.mark.parametrize(
    "changes",
    [
        {"target_window_length": 7},
        {"target_window_length": 257},
        {"exogenous_window_length": 7},
        {"exogenous_window_length": 257},
        {"target_window_length": 65},
        {"target_window_length": 8, "patch_length": 8},
        {"target_window_length": 136, "patch_length": 4},
        {"patch_length": 3},
        {"patch_length": 33},
        {"patch_length": True},
        {"patch_length": "8"},
        {"prediction_length": 0},
        {"prediction_length": 33},
        {"prediction_length": 1.0},
        {"embedding_dim": 15},
        {"embedding_dim": 17, "num_heads": 1},
        {"embedding_dim": 130},
        {"num_heads": 0},
        {"num_heads": 3},
        {"num_heads": 9},
        {"encoder_layers": 1},
        {"encoder_layers": 5},
        {"dropout": -0.01},
        {"dropout": 0.31},
        {"dropout": float("inf")},
        {"dropout": float("nan")},
        {"dropout": True},
        {"learning_rate": False},
        {"learning_rate": "0.001"},
        {"learning_rate": 0.0},
        {"learning_rate": 0.101},
        {"learning_rate": float("nan")},
        {"epochs": True},
        {"epochs": 101},
        {"batch_size": 0},
        {"batch_size": 65},
        {"device": "cuda"},
        {"normalization_mode": "standard"},
    ],
)
def test_invalid_parameters(changes):
    with pytest.raises(ValidationError):
        TimeXerParameters(**changes)


def test_patch_count_and_horizon_boundaries():
    lower = TimeXerParameters(target_window_length=8, patch_length=4)
    upper = TimeXerParameters(
        target_window_length=256, patch_length=8, prediction_length=32, dropout=0.3
    )
    assert (lower.patch_count, lower.prediction_length) == (2, 1)
    assert (upper.patch_count, upper.prediction_length) == (32, 32)


@pytest.mark.parametrize("seed", [False, "0", 1.0, -1, 2**32, float("inf")])
def test_invalid_seed(seed):
    with pytest.raises(ValidationError):
        TypeAdapter(Seed).validate_python(seed)


@pytest.mark.parametrize("seed", [0, 2**32 - 1])
def test_seed_boundaries(seed):
    assert TypeAdapter(Seed).validate_python(seed) == seed
