"""Strict request parameters and complete, independently recorded native configuration."""

import json

import pytest
from app.schemas.xgboost import XGBoostParameters
from pydantic import ValidationError


def test_defaults_and_native_parameters_are_separate():
    parameters = XGBoostParameters()
    assert parameters.model_dump() == {
        "max_depth": 4,
        "learning_rate": 0.05,
        "num_boost_round": 200,
    }
    native = parameters.booster_parameters(random_seed=7)
    assert native == {
        "max_depth": 4,
        "learning_rate": 0.05,
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
        "seed": 7,
    }
    assert "num_boost_round" not in native
    native["device"] = "cuda"
    assert parameters.booster_parameters()["device"] == "cpu"
    assert XGBoostParameters.model_validate(json.loads(parameters.model_dump_json())) == parameters


@pytest.mark.parametrize(
    "changes",
    [
        {"max_depth": 1},
        {"max_depth": 8},
        {"learning_rate": 1},
        {"learning_rate": 1e-6},
        {"num_boost_round": 1},
        {"num_boost_round": 1000},
    ],
)
def test_valid_boundaries(changes):
    XGBoostParameters(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"max_depth": 0},
        {"max_depth": 9},
        {"max_depth": True},
        {"max_depth": 4.0},
        {"max_depth": "4"},
        {"learning_rate": 0},
        {"learning_rate": -0.1},
        {"learning_rate": 1.01},
        {"learning_rate": float("inf")},
        {"learning_rate": float("-inf")},
        {"learning_rate": float("nan")},
        {"learning_rate": True},
        {"learning_rate": "0.1"},
        {"num_boost_round": 0},
        {"num_boost_round": 1001},
        {"num_boost_round": 20.0},
        {"num_boost_round": True},
        {"n_estimators": 20},
        {"eta": 0.1},
        {"seed": 1},
        {"device": "cuda"},
        {"objective": "custom"},
        {"early_stopping_rounds": 2},
        {"subsample": 0.5},
        {"callbacks": []},
    ],
)
def test_invalid_or_unexposed_parameters(changes):
    with pytest.raises(ValidationError):
        XGBoostParameters(**changes)


@pytest.mark.parametrize("seed", [True, "1", 1.0, -1, 2**31])
def test_seed_is_a_separate_strict_call_argument(seed):
    with pytest.raises(ValueError):
        XGBoostParameters().booster_parameters(random_seed=seed)
