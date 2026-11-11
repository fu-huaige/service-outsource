import subprocess
import sys

import numpy as np
import pytest
import torch
from app.schemas.timexer import TimeXerParameters
from app.services import timexer_modeling_service as modeling

NAMES = ("flow", "pressure")
TARGET = "temperature"


def sample(h=3, *, n=7, t=8, tex=12):
    rng = np.random.default_rng(31)
    target = rng.normal(size=(n, t, 1)).astype(np.float32)
    exogenous = rng.normal(size=(n, tex, len(NAMES))).astype(np.float32)
    y = target[:, -1, :] + exogenous[:, -1, 0, None] + np.arange(h, dtype=np.float32)
    return target, exogenous, y


def small_parameters(h=3, **changes):
    values = {
        "target_window_length": 8,
        "exogenous_window_length": 12,
        "patch_length": 4,
        "embedding_dim": 16,
        "prediction_length": h,
        "epochs": 2,
        "batch_size": 4,
    }
    return TimeXerParameters(**(values | changes))


def fit(data, parameters=None, *, seed=13):
    return modeling.fit_timexer_core(
        *data,
        target_name=TARGET,
        exogenous_feature_names=NAMES,
        parameters=parameters or small_parameters(),
        random_seed=seed,
    )


def predict(model, data, *, names=NAMES, target=TARGET):
    return modeling.predict_timexer(
        model, *data[:2], target_name=target, exogenous_feature_names=names
    )


@pytest.fixture(scope="module")
def trained():
    return fit(sample())


@pytest.mark.parametrize("h", [1, 3])
def test_unequal_histories_and_direct_forecast(h):
    data = sample(h)
    fitted = fit(data, small_parameters(h))
    metadata = fitted.metadata
    assert metadata.target_name == TARGET
    assert metadata.exogenous_feature_names == NAMES
    assert (metadata.target_window_length, metadata.exogenous_window_length) == (8, 12)
    assert metadata.exogenous_feature_count == 2
    assert metadata.prediction_length == h
    assert metadata.training_samples == 7
    assert metadata.training_epochs == len(metadata.epoch_losses) == 2
    assert np.isfinite(metadata.epoch_losses).all()
    assert metadata.epoch_losses[-1] == metadata.training_loss
    assert metadata.normalization_mode == "none"
    assert not fitted.model.training
    output = predict(fitted, data)
    assert output.shape == (7, h)
    assert output.dtype == np.float32
    assert np.isfinite(output).all()


def test_patch_boundaries_and_cross_attention_sources():
    p = small_parameters()
    model = modeling.build_timexer(p).eval()
    target = torch.arange(16, dtype=torch.float32).reshape(2, 8, 1)
    exogenous = torch.arange(48, dtype=torch.float32).reshape(2, 12, 2)
    layer = model.encoder[0]
    seen = {}

    def capture_input(name):
        def hook(_module, args):
            seen[name] = args

        return hook

    def capture_output(name):
        def hook(_module, _args, result):
            seen[name] = result

        return hook

    handles = [
        model.patch_embedding.register_forward_pre_hook(capture_input("patches")),
        layer.self_attention.register_forward_pre_hook(capture_input("self")),
        layer.self_norm.register_forward_hook(capture_output("self_norm")),
        layer.cross_attention.register_forward_pre_hook(capture_input("cross")),
        model.variate_embedding.register_forward_hook(capture_output("variates")),
        layer.cross_norm.register_forward_hook(capture_output("cross_norm")),
        layer.feed_forward.register_forward_pre_hook(capture_input("feed_forward")),
    ]
    try:
        with torch.inference_mode():
            model(target, exogenous)
    finally:
        for handle in handles:
            handle.remove()

    torch.testing.assert_close(seen["patches"][0], target.reshape(2, 2, 4))
    query, key, value = seen["self"]
    assert query is key is value
    assert query.shape == (2, 3, p.embedding_dim)
    assert model.global_token.requires_grad
    torch.testing.assert_close(query[:, -1:, :], model.global_token.expand(2, -1, -1))
    query, key, value = seen["cross"]
    assert query.shape == (2, 1, p.embedding_dim)
    assert key is value is seen["variates"]
    torch.testing.assert_close(query, seen["self_norm"][:, -1:, :])
    ff_tokens = seen["feed_forward"][0]
    torch.testing.assert_close(ff_tokens[:, -1:, :], seen["cross_norm"])
    torch.testing.assert_close(ff_tokens[:, :-1, :], seen["self_norm"][:, :-1, :])
    with torch.inference_mode():
        assert not torch.equal(model(target, exogenous), model(target, exogenous + 20))


def _torch_settings():
    return (
        torch.get_rng_state().clone(),
        torch.get_num_threads(),
        torch.get_num_interop_threads(),
        torch.are_deterministic_algorithms_enabled(),
        torch.is_deterministic_algorithms_warn_only_enabled(),
    )


def _assert_settings(before):
    after = _torch_settings()
    assert torch.equal(before[0], after[0])
    assert before[1:] == after[1:]


def test_same_seed_reproducible_and_different_seed_changes_predictions():
    data = sample()
    p = small_parameters(dropout=0.1)
    before = _torch_settings()
    first = fit(data, p)
    _assert_settings(before)
    second = fit(data, p)
    third = fit(data, p, seed=14)
    assert first.metadata.training_threads == before[1]
    assert first.metadata.epoch_losses == second.metadata.epoch_losses
    np.testing.assert_array_equal(predict(first, data), predict(second, data))
    assert not np.array_equal(predict(first, data), predict(third, data))
    _assert_settings(before)


def test_training_failure_restores_rng_and_settings(monkeypatch):
    before = _torch_settings()

    def fail(_optimizer):
        assert torch.get_num_threads() == before[1]
        torch.rand(4)
        raise RuntimeError("optimizer failed")

    monkeypatch.setattr(torch.optim.Adam, "step", fail)
    with pytest.raises(RuntimeError, match="optimizer failed"):
        fit(sample())
    _assert_settings(before)


@pytest.mark.parametrize(
    "target,names",
    [
        (" ", NAMES),
        (None, NAMES),
        (TARGET, ("flow", "flow")),
        (TARGET, ("flow", " ")),
        (TARGET, ("flow", TARGET)),
        (TARGET, ("flow", 1)),
        (TARGET, ()),
        (TARGET, tuple(str(i) for i in range(65))),
        (TARGET, "flow"),
    ],
)
def test_invalid_training_names(target, names):
    with pytest.raises(ValueError):
        modeling.fit_timexer_core(
            *sample(),
            target_name=target,
            exogenous_feature_names=names,
            parameters=small_parameters(),
        )


@pytest.mark.parametrize(
    "index,change",
    [
        (0, lambda a: a.squeeze(-1)),
        (0, lambda a: a[:, :-1]),
        (1, lambda a: a[..., :-1]),
        (1, lambda a: a[:-1]),
        (1, lambda a: a[:, 1:]),
        (2, lambda a: a[:-1]),
        (2, lambda a: a[:, :1]),
        (2, lambda a: a[:, 0]),
        (0, lambda a: a[:0]),
        (0, lambda a: np.full(a.shape, np.nan)),
        (1, lambda a: np.full(a.shape, np.inf)),
        (2, lambda a: np.full(a.shape, -np.inf)),
        (0, lambda a: np.full(a.shape, 1e100)),
        (1, lambda a: a.astype(complex)),
        (1, lambda a: a.astype(bool)),
        (2, lambda a: a.astype(object)),
        (2, lambda a: a.astype(str)),
    ],
)
def test_invalid_training_arrays(index, change, monkeypatch):
    data = list(sample())
    data[index] = change(data[index])

    def forbidden():
        raise AssertionError("Reject malformed arrays before importing PyTorch")

    monkeypatch.setattr(modeling, "torch_runtime", forbidden)
    with pytest.raises(ValueError):
        fit(data)


@pytest.mark.parametrize("names,target", [(NAMES[::-1], TARGET), (NAMES, "wrong")])
def test_prediction_rejects_name_mismatch(trained, names, target):
    with pytest.raises(ValueError, match="must match"):
        predict(trained, sample(), names=names, target=target)


@pytest.mark.parametrize("value", [np.nan, np.inf, 1e100])
def test_prediction_rejects_nonfinite_inputs(trained, value):
    target, exogenous, y = sample()
    with pytest.raises(ValueError):
        predict(trained, (target, np.full(exogenous.shape, value), y))


def test_prediction_is_fixed_float32_inference(trained, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Fixed predictions must not train")

    def check(module, _args):
        assert not module.training
        assert torch.is_inference_mode_enabled()

    monkeypatch.setattr(modeling, "fit_timexer_core", forbidden)
    monkeypatch.setattr(torch.optim.Adam, "step", forbidden)
    hook = trained.model.register_forward_pre_hook(check)
    before = _torch_settings()
    try:
        with torch.autocast(device_type="cpu", dtype=torch.bfloat16):
            assert predict(trained, sample()).dtype == np.float32
    finally:
        hook.remove()
    _assert_settings(before)


def test_nonfinite_predictions_rejected(trained, monkeypatch):
    monkeypatch.setattr(
        trained.model, "forward", lambda x, z: torch.full((len(x), 3), float("inf"))
    )
    with pytest.raises(ValueError, match="finite"):
        predict(trained, sample())


def test_modules_import_without_torch():
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            """
import builtins
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.split(".")[0] == "torch":
        raise AssertionError("Unexpected eager torch import")
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
import app.schemas.timexer
import app.services.timexer_modeling_service
import app.services.timexer_artifact_service
""",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
