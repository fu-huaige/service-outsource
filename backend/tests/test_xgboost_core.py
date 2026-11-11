"""Native training boundary, nonlinear behavior, and fixed prediction contracts."""

import json
import subprocess
import sys

import numpy as np
import pytest
import xgboost as xgb
from app.schemas.xgboost import XGBoostParameters
from app.services.xgboost_modeling_service import (
    fit_xgboost_core,
    predict_xgboost,
    training_metadata,
)

NAMES = ("反应温度(℃)", "进料流量(m³/h)", "压力[kPa]")


def data():
    rng = np.random.default_rng(31)
    x = rng.uniform(-2, 2, (360, 3))
    y = 2 * np.sin(x[:, 0]) + 0.5 * x[:, 1] ** 2 + x[:, 0] * x[:, 1]
    y += rng.normal(0, 0.025, len(x))
    return x, y


@pytest.fixture(scope="module")
def trained():
    x, y = data()
    model = fit_xgboost_core(
        x[:280],
        y[:280],
        feature_names=NAMES,
        target_name="质量",
        parameters=XGBoostParameters(num_boost_round=160),
        random_seed=19,
    )
    return model, x, y


def test_native_booster_and_nonlinear_predictions(trained):
    model, x, y = trained
    assert isinstance(model, xgb.Booster)
    prediction = predict_xgboost(model, x[280:], feature_names=NAMES)
    assert prediction.shape == (80,)
    assert np.isfinite(prediction).all()
    error = np.mean((prediction - y[280:]) ** 2)
    baseline = np.mean((y[:280].mean() - y[280:]) ** 2)
    assert error < 0.5 * baseline
    metadata = training_metadata(model)
    assert metadata.training_rows == 280
    assert metadata.random_seed == 19
    assert metadata.boosting_rounds == 160
    assert metadata.internal_feature_names == ("f0", "f1", "f2")
    assert metadata.effective_parameters["nthread"] == 1
    assert metadata.effective_parameters["device"] == "cpu"


def test_train_is_called_once_with_exact_train_data_and_no_evaluation(monkeypatch):
    x, y = data()
    before_x, before_y = x.copy(), y.copy()
    original = xgb.train
    calls = []

    def counted(params, dtrain, num_boost_round, **kwargs):
        calls.append((params.copy(), dtrain.num_row(), dtrain.get_label(), num_boost_round, kwargs))
        return original(params, dtrain, num_boost_round=num_boost_round, **kwargs)

    monkeypatch.setattr(xgb, "train", counted)
    first = fit_xgboost_core(
        x[:80],
        y[:80],
        feature_names=NAMES,
        target_name="质量",
        parameters=XGBoostParameters(num_boost_round=15),
        random_seed=11,
    )
    assert len(calls) == 1
    params, count, labels, rounds, options = calls[0]
    assert count == 80 and rounds == 15
    np.testing.assert_array_equal(labels, y[:80].astype(np.float32))
    assert not options.get("evals")
    assert not options.get("early_stopping_rounds")
    assert not options.get("xgb_model")
    assert not options.get("callbacks")
    assert params == training_metadata(first).effective_parameters
    assert "num_boost_round" not in params
    second = fit_xgboost_core(
        x[:80],
        y[:80],
        feature_names=NAMES,
        target_name="质量",
        parameters=XGBoostParameters(num_boost_round=15),
        random_seed=11,
    )
    np.testing.assert_array_equal(
        predict_xgboost(first, x[80:100], feature_names=NAMES),
        predict_xgboost(second, x[80:100], feature_names=NAMES),
    )
    np.testing.assert_array_equal(x, before_x)
    np.testing.assert_array_equal(y, before_y)


@pytest.mark.parametrize(
    "case",
    [
        "column_y",
        "multi_y",
        "one_row",
        "no_features",
        "row_mismatch",
        "nan_x",
        "inf_x",
        "negative_inf_y",
        "nan_y",
        "overflow_x",
        "overflow_y",
        "string",
        "boolean",
        "complex",
        "duplicate",
        "name_count",
        "target",
        "blank_name",
        "invalid_seed",
    ],
)
def test_bad_training_inputs_are_rejected_before_train(monkeypatch, case):
    x, y = data()
    names = NAMES
    seed = 0
    if case == "column_y":
        y = y[:, None]
    elif case == "multi_y":
        y = np.column_stack((y, y))
    elif case == "one_row":
        x, y = x[:1], y[:1]
    elif case == "no_features":
        x, names = x[:, :0], ()
    elif case == "row_mismatch":
        y = y[:-1]
    elif case == "nan_x":
        x[0, 0] = np.nan
    elif case == "inf_x":
        x[0, 0] = np.inf
    elif case == "negative_inf_y":
        y[0] = -np.inf
    elif case == "nan_y":
        y[0] = np.nan
    elif case == "overflow_x":
        x[0, 0] = 1e300
    elif case == "overflow_y":
        y[0] = 1e300
    elif case == "string":
        x = x.astype(str)
    elif case == "boolean":
        x = x > 0
    elif case == "complex":
        x = x.astype(complex)
    elif case == "duplicate":
        names = (NAMES[0], NAMES[0], NAMES[2])
    elif case == "name_count":
        names = NAMES[:2]
    elif case == "target":
        names = (NAMES[0], NAMES[1], "质量")
    elif case == "blank_name":
        names = (NAMES[0], NAMES[1], " ")
    elif case == "invalid_seed":
        seed = True

    def forbidden(*args, **kwargs):
        raise AssertionError("Rejected inputs must not train")

    monkeypatch.setattr(xgb, "train", forbidden)
    with pytest.raises(ValueError):
        fit_xgboost_core(x, y, feature_names=names, target_name="质量", random_seed=seed)


def test_fixed_prediction_never_trains_or_updates(trained, monkeypatch):
    model, x, _ = trained

    def forbidden(*args, **kwargs):
        raise AssertionError("Prediction must not train or update")

    monkeypatch.setattr(xgb, "train", forbidden)
    monkeypatch.setattr(xgb.Booster, "update", forbidden)
    predict_xgboost(model, x[:5], feature_names=NAMES)


@pytest.mark.parametrize("case", ["order", "width", "nan", "overflow", "empty", "string"])
def test_invalid_prediction_inputs(trained, case):
    model, x, _ = trained
    x, names = x[:5].copy(), NAMES
    if case == "order":
        names = NAMES[::-1]
    elif case == "width":
        x = x[:, :2]
    elif case == "nan":
        x[0, 0] = np.nan
    elif case == "overflow":
        x[0, 0] = 1e300
    elif case == "empty":
        x = x[:0]
    elif case == "string":
        x = x.astype(str)
    with pytest.raises(ValueError):
        predict_xgboost(model, x, feature_names=names)


@pytest.mark.parametrize("case", ["nan", "shape"])
def test_invalid_native_prediction_is_rejected(trained, monkeypatch, case):
    model, x, _ = trained
    monkeypatch.setattr(
        xgb.Booster,
        "predict",
        lambda *args, **kwargs: np.full((5, 1), np.nan) if case == "nan" else np.zeros(5),
    )
    with pytest.raises(ValueError):
        predict_xgboost(model, x[:5], feature_names=NAMES)


def test_modules_import_without_loading_xgboost():
    script = """
import builtins
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name == 'xgboost' or name.startswith('xgboost.'):
        raise AssertionError('XGBoost must be imported lazily')
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
import app.schemas.xgboost
import app.services.xgboost_modeling_service
import app.services.xgboost_artifact_service
"""
    result = subprocess.run([sys.executable, "-B", "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_core_records_all_effective_parameters(trained):
    model, _, _ = trained
    metadata = training_metadata(model)
    assert json.loads(metadata.model_dump_json())["effective_parameters"]["seed"] == 19
