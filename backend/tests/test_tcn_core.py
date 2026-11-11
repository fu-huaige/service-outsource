import subprocess
import sys

import numpy as np
import pytest
import torch
from app.schemas.tcn import TCNParameters, TCNTrainingMetadata, receptive_field
from app.services.tcn_modeling_service import build_tcn, cpu_execution, fit_tcn_core, predict_tcn

NAMES = ("温度", "流量")
CONFIG = TCNParameters(hidden_channels=4, epochs=5, batch_size=8)


def data():
    x = np.random.default_rng(21).normal(size=(16, 32, 2))
    return x, 0.3 * x[:, -1, 0] + x[:, -2, 1]


def fit(x, y, *, feature_names=NAMES, target_name="quality", random_seed=13):
    return fit_tcn_core(
        x,
        y,
        feature_names=feature_names,
        target_name=target_name,
        parameters=CONFIG,
        random_seed=random_seed,
    )


@pytest.fixture(scope="module")
def trained():
    return fit(*data())


def torch_settings():
    return (
        torch.get_num_threads(),
        torch.are_deterministic_algorithms_enabled(),
        torch.is_deterministic_algorithms_warn_only_enabled(),
    )


def test_repeated_training_matches_and_restores_state():
    x, y = data()
    rng = torch.get_rng_state().clone()
    settings = torch_settings()
    first = fit(x, y)
    second = fit(x, y)
    assert torch.equal(torch.get_rng_state(), rng)
    assert torch_settings() == settings
    assert first.metadata.model_id != second.metadata.model_id
    assert first.metadata.training_loss == second.metadata.training_loss
    assert first.metadata.training_epochs == CONFIG.epochs
    assert first.metadata.training_samples == len(x)
    assert first.metadata.random_seed == 13
    assert all(
        p.device.type == "cpu" and p.dtype == torch.float32 for p in first.model.parameters()
    )
    assert not first.model.training
    left = first.predict(x, feature_names=NAMES)
    right = second.predict(x, feature_names=NAMES)
    assert left.shape == (len(x),) and left.dtype == np.float32
    np.testing.assert_array_equal(left, right)
    np.testing.assert_allclose(first.metadata.training_loss, np.mean((left - y) ** 2), rtol=1e-6)
    expected_x, expected_y = data()
    np.testing.assert_array_equal(x, expected_x)
    np.testing.assert_array_equal(y, expected_y)


def test_cpu_float32_is_preserved_under_ambient_autocast():
    x, y = data()
    expected = fit(x, y).predict(x, feature_names=NAMES)
    with torch.autocast(device_type="cpu", dtype=torch.bfloat16):
        actual = fit(x, y).predict(x, feature_names=NAMES)
        assert torch.is_autocast_enabled("cpu")
    np.testing.assert_array_equal(actual, expected)


def test_training_settings_restore_on_failure(monkeypatch):
    rng = torch.get_rng_state().clone()
    settings = torch_settings()

    def fail(*args, **kwargs):
        assert torch.get_num_threads() == 1
        assert torch.are_deterministic_algorithms_enabled()
        raise RuntimeError("step failed")

    monkeypatch.setattr(torch.optim.Adam, "step", fail)
    with pytest.raises(RuntimeError, match="step failed"):
        fit(*data())
    assert torch.equal(torch.get_rng_state(), rng)
    assert torch_settings() == settings


def test_causal_prefix_and_receptive_field():
    with cpu_execution(7), torch.inference_mode():
        model = build_tcn(2, CONFIG)
        for parameter in model.parameters():
            parameter.fill_(0.1)
        x = torch.ones((2, 2, 32))
        changed = x.clone()
        changed[:, :, 16:] *= 2
        a, b = model.blocks(x), model.blocks(changed)
        assert a.shape == (2, CONFIG.hidden_channels, 32)
        torch.testing.assert_close(a[:, :, :16], b[:, :, :16], rtol=0, atol=0)
        assert not torch.equal(a[:, :, 16:], b[:, :, 16:])
        boundary = x.shape[-1] - receptive_field()
        changed = x.clone()
        changed[:, :, :boundary] *= 2
        torch.testing.assert_close(model(x), model(changed), rtol=0, atol=0)
        changed[:, :, boundary] *= 2
        assert not torch.equal(model(x), model(changed))


@pytest.mark.parametrize(
    "case",
    [
        "rank",
        "ragged",
        "window",
        "target_rank",
        "row_count",
        "one_row",
        "empty_feature",
        "bool",
        "complex",
        "object",
        "string",
        "nan",
        "inf",
        "overflow",
        "label_nan",
        "label_overflow",
        "duplicate",
        "target",
        "name_count",
        "blank",
        "bad_seed",
    ],
)
def test_invalid_training_input(case, monkeypatch):
    x, y = data()
    names, target, seed = NAMES, "quality", 0
    if case == "rank":
        x = x[:, -1]
    elif case == "ragged":
        x = [x[0], x[1, :-1]]
    elif case == "window":
        x = x[:, :-1]
    elif case == "target_rank":
        y = y[:, None]
    elif case == "row_count":
        y = y[:-1]
    elif case == "one_row":
        x, y = x[:1], y[:1]
    elif case == "empty_feature":
        x, names = x[:, :, :0], ()
    elif case in {"bool", "complex", "object", "string"}:
        x = x.astype({"bool": bool, "complex": complex, "object": object, "string": str}[case])
    elif case in {"nan", "inf", "overflow"}:
        x[0, 0, 0] = {"nan": np.nan, "inf": -np.inf, "overflow": 1e300}[case]
    elif case in {"label_nan", "label_overflow"}:
        y[0] = np.nan if case == "label_nan" else 1e300
    elif case == "duplicate":
        names = (NAMES[0], NAMES[0])
    elif case == "target":
        target = NAMES[0]
    elif case == "name_count":
        names = NAMES[:1]
    elif case == "blank":
        names = (" ", NAMES[1])
    else:
        seed = True

    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid input reached the training loop")

    monkeypatch.setattr(torch.optim.Adam, "step", forbidden)
    with pytest.raises(ValueError):
        fit(x, y, feature_names=names, target_name=target, random_seed=seed)


def test_metadata_rejects_duplicate_features(trained):
    with pytest.raises(ValueError):
        TCNTrainingMetadata.model_validate(
            {
                **trained.metadata.model_dump(),
                "feature_names": (NAMES[0], NAMES[0]),
            }
        )


@pytest.mark.parametrize("case", ["order", "length", "width", "rank", "nan", "inf"])
def test_bad_prediction_input(trained, case):
    x, _ = data()
    names = NAMES
    if case == "order":
        names = NAMES[::-1]
    elif case == "length":
        x = x[:, :-1]
    elif case == "width":
        x = x[:, :, :1]
    elif case == "rank":
        x = x[:, -1]
    else:
        x[0, 0, 0] = np.nan if case == "nan" else np.inf
    with pytest.raises(ValueError):
        predict_tcn(trained, x, feature_names=names)


def test_module_import_does_not_require_torch():
    script = """
import builtins
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name == 'torch' or name.startswith('torch.'):
        raise AssertionError('PyTorch imported eagerly')
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
import app.schemas.tcn
import app.services.tcn_modeling_service
import app.services.tcn_artifact_service
"""
    result = subprocess.run([sys.executable, "-B", "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
