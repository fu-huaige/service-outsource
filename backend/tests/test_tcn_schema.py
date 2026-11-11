import pytest
from app.schemas.tcn import TCNParameters, receptive_field
from pydantic import ValidationError


def test_defaults_and_minimum_window():
    assert TCNParameters().model_dump() == {
        "window_length": 32,
        "hidden_channels": 32,
        "learning_rate": 0.001,
        "epochs": 30,
        "batch_size": 32,
    }
    assert receptive_field() == 29
    assert TCNParameters(window_length=receptive_field()).window_length == 29


@pytest.mark.parametrize(
    "changes",
    [
        {"window_length": 28},
        {"window_length": 257},
        {"window_length": True},
        {"hidden_channels": 0},
        {"hidden_channels": 129},
        {"hidden_channels": "32"},
        {"learning_rate": 0},
        {"learning_rate": -0.1},
        {"learning_rate": True},
        {"learning_rate": "0.001"},
        {"learning_rate": float("nan")},
        {"learning_rate": float("inf")},
        {"learning_rate": 1.01},
        {"epochs": 501},
        {"epochs": 1.0},
        {"epochs": True},
        {"epochs": -1},
        {"batch_size": 129},
        {"batch_size": False},
        {"batch_size": "32"},
        {"device": "cuda"},
        {"random_seed": 3},
        {"dropout": 0.5},
    ],
)
def test_invalid_parameters(changes):
    with pytest.raises(ValidationError):
        TCNParameters(**changes)
