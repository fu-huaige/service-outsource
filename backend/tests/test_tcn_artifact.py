import errno
import gc
import hashlib
import io
import json
import weakref

import numpy as np
import pytest
import torch
from app.services import tcn_artifact_service as artifacts
from app.services import tcn_modeling_service as modeling

from test_tcn_core import NAMES, data, fit
from test_tcn_core import trained as trained


@pytest.fixture
def saved(tmp_path, trained):
    metadata = artifacts.save_tcn_artifact(trained, artifact_root=tmp_path)
    directory = tmp_path / "models" / "tcn"
    return (
        tmp_path,
        metadata.model_id,
        directory / f"{metadata.model_id}.json",
        directory / metadata.npz_filename,
    )


def load(saved):
    return artifacts.load_tcn_artifact(model_id=saved[1], artifact_root=saved[0])


def test_roundtrip_after_releasing_original_model(tmp_path, monkeypatch):
    x, y = data()
    fitted = fit(x, y)
    expected = fitted.predict(x, feature_names=NAMES)
    reference = weakref.ref(fitted.model)
    metadata = artifacts.save_tcn_artifact(fitted, artifact_root=tmp_path)
    del fitted
    gc.collect()
    assert reference() is None

    def forbidden(*args, **kwargs):
        raise AssertionError("Load and prediction must not train or deserialize Python objects")

    monkeypatch.setattr(modeling, "fit_tcn_core", forbidden)
    monkeypatch.setattr(torch.optim.Adam, "step", forbidden)
    monkeypatch.setattr(torch, "load", forbidden)
    restored = artifacts.load_tcn_artifact(model_id=metadata.model_id, artifact_root=tmp_path)
    assert restored.metadata.model_id == metadata.model_id
    assert restored.metadata.source_status == "unbound"
    assert not restored.model.training

    def check_inference(module, args):
        assert not module.training
        assert torch.is_inference_mode_enabled()
        assert torch.get_num_threads() == 1

    hook = restored.model.register_forward_pre_hook(check_inference)
    try:
        np.testing.assert_allclose(
            restored.predict(x, feature_names=NAMES),
            expected,
            rtol=1e-6,
            atol=1e-7,
        )
    finally:
        hook.remove()


@pytest.mark.parametrize(
    "case",
    [
        "json",
        "missing_json",
        "missing_npz",
        "sha",
        "zip",
        "traversal",
        "identity",
        "version",
        "missing_field",
        "missing_parameter",
        "missing_dtype",
        "mapping",
        "runtime",
    ],
)
def test_invalid_files(saved, case):
    _, _, json_path, npz_path = saved
    document = json.loads(json_path.read_bytes())
    if case == "json":
        json_path.write_bytes(b"{")
    elif case == "missing_json":
        json_path.unlink()
    elif case == "missing_npz":
        npz_path.unlink()
    else:
        if case == "sha":
            document["npz_sha256"] = "0" * 64
        elif case == "zip":
            raw = b"invalid ZIP"
            npz_path.write_bytes(raw)
            document.update(npz_size_bytes=len(raw), npz_sha256=hashlib.sha256(raw).hexdigest())
        elif case == "traversal":
            document["npz_filename"] = "../model.npz"
        elif case == "identity":
            document["model_id"] = "00000000-0000-0000-0000-000000000001"
        elif case == "version":
            document["format_version"] = 2
        elif case == "missing_field":
            document.pop("source_status")
        elif case == "missing_parameter":
            document["parameters"].pop("epochs")
        elif case == "missing_dtype":
            document["arrays"][0].pop("dtype")
        elif case == "mapping":
            document["arrays"][0]["parameter_name"] = "wrong.weight"
        else:
            document["torch_version"] = "2.9.1+different"
        json_path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError):
        load(saved)


@pytest.mark.parametrize("case", ["shape", "dtype", "nan", "pickle", "extra"])
def test_invalid_npz_even_with_valid_digest(saved, case, monkeypatch):
    _, _, json_path, npz_path = saved
    with np.load(npz_path, allow_pickle=False) as archive:
        arrays = dict(archive)
    key = next(iter(arrays))
    value = arrays[key]
    if case == "shape":
        arrays[key] = value.reshape(-1)
    elif case == "dtype":
        arrays[key] = value.astype(np.float64)
    elif case == "nan":
        value.flat[0] = np.nan
    elif case == "pickle":
        arrays[key] = value.astype(object)
    else:
        arrays["unexpected"] = value
    buffer = io.BytesIO()
    np.savez(buffer, **arrays)
    raw = buffer.getvalue()
    npz_path.write_bytes(raw)
    document = json.loads(json_path.read_bytes())
    document.update(npz_size_bytes=len(raw), npz_sha256=hashlib.sha256(raw).hexdigest())
    json_path.write_text(json.dumps(document), encoding="utf-8")
    if case != "nan":

        def forbidden(*args, **kwargs):
            raise AssertionError("Invalid archive must fail before NumPy loads arrays")

        monkeypatch.setattr(np, "load", forbidden)
    with pytest.raises(ValueError):
        load(saved)


def test_duplicate_publication_preserves_bytes(saved, trained):
    before = tuple(p.read_bytes() for p in saved[2:])
    with pytest.raises(ValueError, match="already exists"):
        artifacts.save_tcn_artifact(trained, artifact_root=saved[0])
    assert tuple(p.read_bytes() for p in saved[2:]) == before


def test_publish_json_last_and_clean_temporary_files(tmp_path, trained, monkeypatch):
    original = artifacts.os.link
    order = []

    def fail_json(source, target):
        order.append(target.suffix)
        if target.suffix == ".json":
            raise OSError("simulated publication failure")
        return original(source, target)

    monkeypatch.setattr(artifacts.os, "link", fail_json)
    with pytest.raises(OSError, match="publication failure"):
        artifacts.save_tcn_artifact(trained, artifact_root=tmp_path)
    directory = tmp_path / "models" / "tcn"
    assert order == [".npz", ".json"]
    assert [p.suffix for p in directory.iterdir()] == [".npz"]
    with pytest.raises(ValueError):
        artifacts.load_tcn_artifact(model_id=trained.metadata.model_id, artifact_root=tmp_path)


@pytest.mark.parametrize("kind", ["json", "npz", "directory"])
def test_symlink_rejected(saved, kind):
    root, _, json_path, npz_path = saved
    path = {"json": json_path, "npz": npz_path, "directory": json_path.parent}[kind]
    destination = root / f"redirected-{kind}"
    path.replace(destination)
    try:
        path.symlink_to(destination, target_is_directory=kind == "directory")
    except OSError as error:
        if getattr(error, "winerror", None) == 1314 or error.errno in (
            errno.EPERM,
            errno.EACCES,
            errno.ENOTSUP,
        ):
            pytest.skip("Account or filesystem does not permit symbolic links")
        raise
    with pytest.raises(ValueError):
        load(saved)
