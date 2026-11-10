"""PLS persistence parity, bounded numerical loading and publication failure cases."""

import hashlib
import io
import json
import zipfile
from uuid import uuid4

import numpy as np
import pytest
from app.schemas.pls import PLSParameters
from app.services import pls_artifact_service as artifacts
from app.services.pls_modeling_service import fit_pls_core
from sklearn.cross_decomposition import PLSRegression


@pytest.fixture
def artifact(tmp_path):
    rng = np.random.default_rng(39)
    x = rng.normal(size=(60, 3)) * [1, 10, 0.1] + [8, 20, -4]
    y = x @ [3, -2, 4] + 7 + rng.normal(0, 0.1, 60)
    model = fit_pls_core(x[:40], y[:40], feature_names=("a", "b", "c"), target_name="quality")
    metadata = artifacts.save_pls_artifact(model, artifact_root=tmp_path)
    directory = tmp_path / "models" / "pls"
    return tmp_path, model, metadata, directory, x[40:], x[:40], y[:40]


def read_document(artifact):
    _, _, metadata, directory, *_ = artifact
    return json.loads((directory / f"{metadata.model_id}.json").read_text())


def write_document(artifact, document):
    _, _, metadata, directory, *_ = artifact
    (directory / f"{metadata.model_id}.json").write_text(json.dumps(document), encoding="utf-8")


def replace_npz(artifact, raw):
    _, _, metadata, directory, *_ = artifact
    (directory / metadata.npz_filename).write_bytes(raw)
    document = read_document(artifact)
    document["npz_size_bytes"] = len(raw)
    document["npz_sha256"] = hashlib.sha256(raw).hexdigest()
    write_document(artifact, document)


def load(artifact):
    root, _, metadata, *_ = artifact
    return artifacts.load_pls_artifact(model_id=metadata.model_id, artifact_root=root)


@pytest.mark.parametrize("scale", [True, False])
def test_artifact_round_trip_matches_sklearn_without_fitting(tmp_path, monkeypatch, scale):
    rng = np.random.default_rng(41)
    x = rng.normal(size=(70, 4)) * [1, 4, 10, 0.1] + [7, -9, 30, 2]
    y = x @ [2, -3, 0.1, 5] + 13 + rng.normal(0, 0.02, 70)
    reference = PLSRegression(n_components=3, scale=scale).fit(x[:50], y[:50])
    model = fit_pls_core(
        x[:50],
        y[:50],
        feature_names=("a", "b", "c", "d"),
        target_name="quality",
        parameters=PLSParameters(n_components=3, scale=scale),
    )
    metadata = artifacts.save_pls_artifact(model, artifact_root=tmp_path)
    original_files = {
        path.name: path.read_bytes() for path in (tmp_path / "models" / "pls").iterdir()
    }

    def forbidden(*args, **kwargs):
        raise AssertionError("Loading, prediction and transform must never fit")

    monkeypatch.setattr(PLSRegression, "fit", forbidden)
    loaded = artifacts.load_pls_artifact(model_id=metadata.model_id, artifact_root=tmp_path)
    np.testing.assert_allclose(
        loaded.predict(x[50:]), reference.predict(x[50:]), rtol=1e-9, atol=1e-12
    )
    np.testing.assert_allclose(
        loaded.transform(x[50:]), reference.transform(x[50:]), rtol=1e-9, atol=1e-12
    )
    assert loaded.metadata.model_id == metadata.model_id
    assert loaded.metadata.training_rows == 50
    assert "training_run_id" not in metadata.model_dump()
    assert not (tmp_path / "models" / f"{metadata.model_id}.json").exists()
    assert not list(tmp_path.rglob("*.manifest.json"))
    assert original_files == {
        path.name: path.read_bytes() for path in (tmp_path / "models" / "pls").iterdir()
    }


@pytest.mark.parametrize(
    "change",
    [
        "sha",
        "size",
        "json",
        "missing",
        "version",
        "id",
        "traversal",
        "descriptors",
        "duplicate_json",
    ],
)
def test_corrupt_metadata_or_missing_payload_rejected(artifact, change):
    _, _, metadata, directory, *_ = artifact
    document = read_document(artifact)
    if change == "sha":
        document["npz_sha256"] = "0" * 64
    elif change == "size":
        document["npz_size_bytes"] += 1
    elif change == "version":
        document["artifact_version"] = 2
    elif change == "id":
        document["model_id"] = str(uuid4())
    elif change == "traversal":
        document["npz_filename"] = "../outside.npz"
    elif change == "descriptors":
        document["arrays"][0]["shape"] = [1, 99]
    elif change == "missing":
        (directory / metadata.npz_filename).unlink()
    if change == "json":
        (directory / f"{metadata.model_id}.json").write_text("{")
    elif change == "duplicate_json":
        (directory / f"{metadata.model_id}.json").write_text('{"model_id": 1, "model_id": 2}')
    else:
        write_document(artifact, document)
    with pytest.raises(ValueError):
        load(artifact)


@pytest.mark.parametrize(
    "kind",
    [
        "shape",
        "float32",
        "integer",
        "string",
        "complex",
        "nan",
        "inf",
        "unknown",
        "missing",
        "coefficient",
        "scale",
        "target_mean",
    ],
)
def test_invalid_arrays_rejected_even_with_updated_digest(artifact, kind):
    _, model, *_ = artifact
    arrays = {name: value.copy() for name, value in model.arrays().items()}
    if kind == "shape":
        arrays["coefficients"] = np.zeros((3, 1))
    elif kind == "float32":
        arrays["x_mean"] = arrays["x_mean"].astype(np.float32)
    elif kind == "integer":
        arrays["x_mean"] = arrays["x_mean"].astype(np.int64)
    elif kind == "string":
        arrays["x_mean"] = arrays["x_mean"].astype(str)
    elif kind == "complex":
        arrays["x_mean"] = arrays["x_mean"].astype(complex)
    elif kind == "nan":
        arrays["x_mean"][0] = np.nan
    elif kind == "inf":
        arrays["x_mean"][0] = np.inf
    elif kind == "unknown":
        arrays["unexpected"] = np.ones(1)
    elif kind == "missing":
        arrays.pop("x_mean")
    elif kind == "coefficient":
        arrays["coefficients"][0, 0] += 10
    elif kind == "scale":
        arrays["x_std"][0] = 0
    elif kind == "target_mean":
        arrays["y_mean"][0] += 10
    buffer = io.BytesIO()
    np.savez(buffer, **arrays)
    replace_npz(artifact, buffer.getvalue())
    with pytest.raises(ValueError):
        load(artifact)


@pytest.mark.parametrize("kind", ["duplicate", "object", "huge_shape", "truncated"])
def test_zip_and_npy_inspected_before_numpy_loading(artifact, monkeypatch, kind):
    _, _, metadata, directory, *_ = artifact
    source = zipfile.ZipFile(directory / metadata.npz_filename)
    buffer = io.BytesIO()
    with source, zipfile.ZipFile(buffer, "w") as target:
        for item in source.infolist():
            raw = source.read(item)
            if item.filename == "coefficients.npy" and kind in ("object", "huge_shape"):
                header = io.BytesIO()
                np.lib.format.write_array_header_1_0(
                    header,
                    {
                        "descr": "|O" if kind == "object" else "<f8",
                        "fortran_order": False,
                        "shape": (1, 3) if kind == "object" else (1, 10**12),
                    },
                )
                raw = header.getvalue()
            if item.filename == "coefficients.npy" and kind == "truncated":
                raw = raw[:-1]
            target.writestr(item.filename, raw)
        if kind == "duplicate":
            with pytest.warns(UserWarning, match="Duplicate"):
                target.writestr("coefficients.npy", b"duplicate")
    replace_npz(artifact, buffer.getvalue())

    def forbidden(*args, **kwargs):
        raise AssertionError("Unsafe headers must be rejected before np.load")

    monkeypatch.setattr(np, "load", forbidden)
    with pytest.raises(ValueError):
        load(artifact)


def test_uncompressed_size_limit_checked_before_loading(artifact, monkeypatch):
    monkeypatch.setattr(artifacts, "MAX_UNCOMPRESSED_BYTES", 1)
    with pytest.raises(ValueError, match="uncompressed"):
        load(artifact)


def test_numpy_loading_explicitly_disables_pickle(artifact, monkeypatch):
    original = np.load
    calls = []

    def checked(*args, **kwargs):
        calls.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(np, "load", checked)
    load(artifact)
    assert calls == [{"allow_pickle": False}]


@pytest.mark.parametrize("model_id", ["../outside", "/tmp/x", "bad", True, 12])
def test_invalid_model_id_rejected(artifact, model_id):
    root, model, *_ = artifact
    with pytest.raises(ValueError, match="UUID"):
        artifacts.load_pls_artifact(model_id=model_id, artifact_root=root)
    with pytest.raises(ValueError, match="UUID"):
        artifacts.save_pls_artifact(model, model_id=model_id, artifact_root=root)


def symlink(link, target, *, directory=False):
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"Symbolic links unavailable: {error}")


@pytest.mark.parametrize("suffix", [".json", ".npz"])
@pytest.mark.parametrize("dangling", [False, True])
def test_external_and_dangling_symlinks_rejected(artifact, suffix, dangling):
    root, _, metadata, directory, *_ = artifact
    path = directory / f"{metadata.model_id}{suffix}"
    outside = root / f"outside{suffix}"
    if not dangling:
        outside.write_bytes(path.read_bytes())
    path.unlink()
    symlink(path, outside)
    with pytest.raises(ValueError, match="symbolic link"):
        load(artifact)


def test_directory_payload_rejected(artifact):
    _, _, metadata, directory, *_ = artifact
    path = directory / metadata.npz_filename
    path.unlink()
    path.mkdir()
    with pytest.raises(ValueError, match="regular file"):
        load(artifact)


def test_artifact_directory_symlink_rejected(tmp_path):
    (tmp_path / "models").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    symlink(tmp_path / "models" / "pls", outside, directory=True)
    with pytest.raises(ValueError, match="symbolic link"):
        artifacts.load_pls_artifact(model_id=uuid4(), artifact_root=tmp_path)


def test_existing_model_never_overwritten(artifact):
    root, model, metadata, directory, *_ = artifact
    original = {path.name: path.read_bytes() for path in directory.iterdir()}
    with pytest.raises(ValueError, match="exists"):
        artifacts.save_pls_artifact(model, model_id=metadata.model_id, artifact_root=root)
    assert original == {path.name: path.read_bytes() for path in directory.iterdir()}


def test_failed_json_publication_has_no_complete_model_or_temporary_files(artifact, monkeypatch):
    root, model, _, directory, *_ = artifact
    identity = uuid4()
    original_link = artifacts.os.link

    def fail_json(source, target):
        if str(target).endswith(".json"):
            raise OSError("Injected publication failure")
        return original_link(source, target)

    monkeypatch.setattr(artifacts.os, "link", fail_json)
    with pytest.raises(OSError, match="Injected"):
        artifacts.save_pls_artifact(model, model_id=identity, artifact_root=root)
    assert not (directory / f"{identity}.json").exists()
    assert not list(directory.glob("*.tmp"))
    with pytest.raises(ValueError):
        artifacts.load_pls_artifact(model_id=identity, artifact_root=root)


def test_declared_effective_components_cannot_have_zero_latent_state(artifact):
    _, model, *_ = artifact
    arrays = {name: value.copy() for name, value in model.arrays().items()}
    for name in ("coefficients", "x_rotations", "x_loadings", "y_loadings"):
        arrays[name][:] = 0
    buffer = io.BytesIO()
    np.savez(buffer, **arrays)
    replace_npz(artifact, buffer.getvalue())
    with pytest.raises(ValueError, match="component"):
        load(artifact)
