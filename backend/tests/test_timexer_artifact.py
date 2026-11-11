import errno
import gc
import hashlib
import io
import json
import weakref
import zipfile

import numpy as np
import pytest
import torch
from app.services import timexer_artifact_service as artifacts
from app.services import timexer_modeling_service as modeling

from test_timexer_core import fit, predict, sample, small_parameters
from test_timexer_core import trained as trained


@pytest.fixture
def saved(tmp_path, trained):
    metadata = artifacts.save_timexer_artifact(trained, artifact_root=tmp_path)
    directory = tmp_path / "models" / "timexer"
    return (
        tmp_path,
        metadata.model_id,
        directory / f"{metadata.model_id}.json",
        directory / metadata.npz_filename,
    )


def _load(saved):
    return artifacts.load_timexer_artifact(model_id=saved[1], artifact_root=saved[0])


def _replace_payload(saved, raw):
    _, _, json_path, npz_path = saved
    npz_path.write_bytes(raw)
    document = json.loads(json_path.read_bytes())
    document.update(npz_size_bytes=len(raw), npz_sha256=hashlib.sha256(raw).hexdigest())
    json_path.write_text(json.dumps(document), encoding="utf-8")


@pytest.mark.parametrize("horizon", [1, 3])
def test_restore_from_disk_after_releasing_model(tmp_path, monkeypatch, horizon):
    data = sample(horizon)
    fitted = fit(data, small_parameters(horizon))
    expected = predict(fitted, data)
    reference = weakref.ref(fitted.model)
    rng = torch.get_rng_state()
    metadata = artifacts.save_timexer_artifact(fitted, artifact_root=tmp_path)
    assert torch.equal(torch.get_rng_state(), rng)
    assert {item.parameter_name for item in metadata.arrays} == set(fitted.model.state_dict())
    assert "position_encoding" in fitted.model.state_dict()
    del fitted
    gc.collect()
    assert reference() is None

    def forbidden(*args, **kwargs):
        raise AssertionError("Restoring and predicting must not train or use object serialization")

    monkeypatch.setattr(modeling, "fit_timexer_core", forbidden)
    monkeypatch.setattr(torch.optim.Adam, "step", forbidden)
    monkeypatch.setattr(torch, "load", forbidden)
    monkeypatch.setattr(torch, "save", forbidden)
    restored = artifacts.load_timexer_artifact(
        model_id=str(metadata.model_id), artifact_root=tmp_path
    )
    assert torch.equal(torch.get_rng_state(), rng)
    assert restored.metadata.model_id == metadata.model_id
    assert restored.metadata.source_status == "unbound"
    assert not restored.model.training
    actual = predict(restored, data)
    assert actual.shape == (7, horizon)
    np.testing.assert_allclose(actual, expected, rtol=1e-6, atol=1e-7)


@pytest.mark.parametrize(
    "case",
    [
        "malformed_json",
        "duplicate_json_key",
        "sha",
        "corrupt_archive",
        "corrupt_weight",
        "relative_path",
        "wrong_model",
        "missing_metadata",
        "missing_parameter",
        "missing_tensor_field",
        "tensor_mapping",
        "metadata_shape",
        "bad_schema",
        "wrong_runtime",
        "npz_directory",
        "json_directory",
    ],
)
def test_reject_corrupt_or_misplaced_files(saved, case):
    _, _, json_path, npz_path = saved
    document = json.loads(json_path.read_bytes())
    if case == "malformed_json":
        json_path.write_bytes(b"{")
    elif case == "duplicate_json_key":
        json_path.write_bytes(b'{"schema_version": 1, "schema_version": 1}')
    elif case == "corrupt_archive":
        _replace_payload(saved, b"not a ZIP")
    elif case == "corrupt_weight":
        raw = bytearray(npz_path.read_bytes())
        raw[len(raw) // 2] ^= 1
        npz_path.write_bytes(raw)
    elif case in ("npz_directory", "json_directory"):
        path = npz_path if case == "npz_directory" else json_path
        path.unlink()
        path.mkdir()
    else:
        if case == "sha":
            document["npz_sha256"] = "0" * 64
        elif case == "relative_path":
            document["npz_filename"] = "../model.npz"
        elif case == "wrong_model":
            document["model_id"] = "00000000-0000-0000-0000-000000000001"
            document["npz_filename"] = f"{document['model_id']}.npz"
        elif case == "missing_metadata":
            document.pop("normalization_mode")
        elif case == "missing_parameter":
            document["parameters"].pop("epochs")
        elif case == "missing_tensor_field":
            document["arrays"][0].pop("dtype")
        elif case == "tensor_mapping":
            document["arrays"][0]["parameter_name"] = "wrong.weight"
        elif case == "metadata_shape":
            document["arrays"][0]["shape"] = [1]
        elif case == "bad_schema":
            document["schema_version"] = 2
        else:
            document["torch_version"] = "2.9.1+different"
        json_path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError):
        _load(saved)


@pytest.mark.parametrize("identity", ["../outside", "models/timexer/bad", "C:/outside"])
def test_reject_non_uuid_lookup_before_path_access(tmp_path, identity, monkeypatch):
    def forbidden(_root):
        raise AssertionError("Invalid IDs must fail before path resolution")

    monkeypatch.setattr(artifacts, "_directory", forbidden)
    with pytest.raises(ValueError):
        artifacts.load_timexer_artifact(model_id=identity, artifact_root=tmp_path)


@pytest.mark.parametrize("case", ["shape", "dtype", "nan", "inf", "object", "extra"])
def test_reject_invalid_arrays_with_matching_digest(saved, monkeypatch, case):
    with np.load(saved[3], allow_pickle=False) as archive:
        arrays = dict(archive)
    key = next(iter(arrays))
    value = arrays[key]
    if case == "shape":
        arrays[key] = value.reshape(-1)
    elif case == "dtype":
        arrays[key] = value.astype(np.float64)
    elif case == "nan":
        value.flat[0] = np.nan
    elif case == "inf":
        value.flat[0] = np.inf
    elif case == "object":
        arrays[key] = value.astype(object)
    else:
        arrays["unexpected"] = value
    buffer = io.BytesIO()
    np.savez(buffer, **arrays)
    _replace_payload(saved, buffer.getvalue())

    def forbidden(*args, **kwargs):
        raise AssertionError("Malformed archives must fail before NumPy array allocation")

    if case not in ("nan", "inf"):
        monkeypatch.setattr(np, "load", forbidden)
    with pytest.raises(ValueError):
        _load(saved)


@pytest.mark.parametrize(
    "case,pattern",
    [
        ("duplicate", "duplicate"),
        ("decompressed", "uncompressed size"),
        ("header", "header length"),
        ("truncated_header", "NPY"),
    ],
)
def test_archive_preflight(saved, monkeypatch, case, pattern):
    with zipfile.ZipFile(saved[3]) as source:
        members = {item.filename: source.read(item) for item in source.infolist()}
    first = next(iter(members))
    if case == "decompressed":
        members[first] = b"x" * (artifacts.MAX_UNCOMPRESSED_BYTES + 1)
    elif case == "header":
        members[first] = b"\x93NUMPY\x01\x00\xff\xff"
    elif case == "truncated_header":
        members[first] = b"\x93NUMPY\x01\x00\x10\x00"

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in members.items():
            archive.writestr(name, value)
        if case == "duplicate":
            with pytest.warns(UserWarning, match="Duplicate name"):
                archive.writestr(first, members[first])
    _replace_payload(saved, buffer.getvalue())

    def forbidden(*args, **kwargs):
        raise AssertionError("Preflight must run before NumPy loads array data")

    monkeypatch.setattr(np, "load", forbidden)
    with pytest.raises(ValueError, match=pattern):
        _load(saved)


@pytest.mark.parametrize("file,limit", [(2, "MAX_JSON_BYTES"), (3, "MAX_NPZ_BYTES")])
def test_artifact_size_limit(saved, monkeypatch, file, limit):
    monkeypatch.setattr(artifacts, limit, saved[file].stat().st_size - 1)
    with pytest.raises(ValueError, match="size"):
        _load(saved)


def test_duplicate_publication_preserves_existing_files(saved, trained):
    before = tuple(path.read_bytes() for path in saved[2:])
    with pytest.raises(ValueError, match="already exists"):
        artifacts.save_timexer_artifact(trained, artifact_root=saved[0])
    assert tuple(path.read_bytes() for path in saved[2:]) == before
    assert len(list(saved[2].parent.iterdir())) == 2


def test_failed_json_publication_is_unloadable(tmp_path, trained, monkeypatch):
    link = artifacts.os.link
    order = []

    def fail_json(source, target):
        order.append(target.suffix)
        if target.suffix == ".json":
            raise OSError("simulated JSON publication failure")
        return link(source, target)

    monkeypatch.setattr(artifacts.os, "link", fail_json)
    with pytest.raises(OSError, match="publication failure"):
        artifacts.save_timexer_artifact(trained, artifact_root=tmp_path)
    assert order == [".npz", ".json"]
    assert [path.suffix for path in (tmp_path / "models" / "timexer").iterdir()] == [".npz"]
    with pytest.raises(ValueError):
        artifacts.load_timexer_artifact(model_id=trained.metadata.model_id, artifact_root=tmp_path)


@pytest.mark.parametrize("kind", ["external_file", "dangling_file", "external_directory"])
def test_reject_artifact_symlinks(saved, tmp_path_factory, kind):
    _, _, json_path, npz_path = saved
    outside = tmp_path_factory.mktemp("timexer-outside")
    if kind == "external_directory":
        path = json_path.parent
        destination = outside / "external-directory"
        path.rename(destination)
    elif kind == "external_file":
        path = npz_path
        destination = outside / "external.npz"
        path.rename(destination)
    else:
        path = json_path
        destination = outside / "absent.json"
        path.unlink()
    try:
        path.symlink_to(destination, target_is_directory=kind == "external_directory")
    except OSError as error:
        if getattr(error, "winerror", None) == 1314 or error.errno in (
            errno.EPERM,
            errno.EACCES,
            errno.ENOTSUP,
        ):
            pytest.skip(f"Symbolic link creation denied: {error.strerror}")
        raise
    with pytest.raises(ValueError, match="links or reparse"):
        _load(saved)
