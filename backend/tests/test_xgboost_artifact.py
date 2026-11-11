"""Independent UBJSON publication, identity binding, and fail-closed restoration."""

import errno
import hashlib
import json
from uuid import uuid4

import numpy as np
import pytest
import xgboost as xgb
from app.schemas.xgboost import XGBoostParameters
from app.services import xgboost_artifact_service as artifacts
from app.services.xgboost_modeling_service import fit_xgboost_core, predict_xgboost

NAMES = ("温度[℃]", "flow < limit")


@pytest.fixture(scope="module")
def model():
    rng = np.random.default_rng(52)
    x = rng.normal(size=(80, 2))
    y = np.sin(x[:, 0]) + x[:, 1] ** 2
    fitted = fit_xgboost_core(
        x,
        y,
        feature_names=NAMES,
        target_name="quality",
        parameters=XGBoostParameters(num_boost_round=25),
    )
    return fitted, x


@pytest.fixture
def saved(tmp_path, model):
    fitted, x = model
    metadata = artifacts.save_xgboost_artifact(fitted, artifact_root=tmp_path)
    directory = tmp_path / "models" / "xgboost"
    return tmp_path, fitted, metadata, directory, x


def document(saved):
    return json.loads((saved[3] / f"{saved[2].model_id}.json").read_text(encoding="utf-8"))


def write_document(saved, value):
    (saved[3] / f"{saved[2].model_id}.json").write_text(json.dumps(value), encoding="utf-8")


def load(saved):
    return artifacts.load_xgboost_artifact(model_id=saved[2].model_id, artifact_root=saved[0])


def test_roundtrip_is_read_only_and_has_no_implicit_fit(saved, monkeypatch):
    root, fitted, metadata, directory, x = saved
    expected = predict_xgboost(fitted, x, feature_names=NAMES)
    before = {p.name: p.read_bytes() for p in directory.iterdir()}

    def forbidden(*args, **kwargs):
        raise AssertionError("Restoration and prediction must never train or update")

    monkeypatch.setattr(xgb, "train", forbidden)
    monkeypatch.setattr(xgb.Booster, "update", forbidden)
    restored = load(saved)
    assert isinstance(restored.booster, xgb.Booster)
    assert restored.metadata == metadata
    np.testing.assert_array_equal(restored.predict(x, feature_names=NAMES), expected)
    assert before == {p.name: p.read_bytes() for p in directory.iterdir()}
    assert metadata.training_run_id is None
    assert metadata.provenance_status == "unbound"
    assert not list(root.glob("models/*.manifest.json"))


def test_supplied_run_is_unverified_and_bound_into_native_payload(tmp_path, model):
    fitted, x = model
    run_id = uuid4()
    metadata = artifacts.save_xgboost_artifact(
        fitted,
        artifact_root=tmp_path,
        training_run_id=run_id,
    )
    restored = artifacts.load_xgboost_artifact(model_id=metadata.model_id, artifact_root=tmp_path)
    assert restored.metadata.training_run_id == run_id
    assert restored.metadata.provenance_status == "provided_unverified"
    np.testing.assert_array_equal(
        restored.predict(x, feature_names=NAMES), predict_xgboost(fitted, x, feature_names=NAMES)
    )


@pytest.mark.parametrize(
    "change",
    [
        "json",
        "duplicate_key",
        "version",
        "payload_format",
        "implementation",
        "missing_version",
        "missing_policy",
        "xgboost_version",
        "model_id",
        "run_id",
        "verified",
        "feature_mapping",
        "feature_order",
        "native_parameters",
        "sha",
        "size",
        "traversal",
        "absolute",
        "missing_json",
        "missing_ubj",
        "corrupt_ubj_with_matching_hash",
    ],
)
def test_invalid_artifacts_fail_closed(saved, change):
    value = document(saved)
    json_path = saved[3] / f"{saved[2].model_id}.json"
    if change == "json":
        json_path.write_text("{", encoding="utf-8")
    elif change == "duplicate_key":
        json_path.write_text(
            '{"artifact_version":1,' + json_path.read_text(encoding="utf-8")[1:], encoding="utf-8"
        )
    elif change == "version":
        value["artifact_version"] = 999
    elif change == "missing_version":
        value.pop("artifact_version")
    elif change == "missing_policy":
        value.pop("missing_policy")
    elif change == "payload_format":
        value["payload_format"] = "pickle"
    elif change == "implementation":
        value["implementation_version"] = "unknown"
    elif change == "xgboost_version":
        value["xgboost_version"] = "0.90"
    elif change == "model_id":
        value["model_id"] = str(uuid4())
    elif change == "run_id":
        value["training_run_id"] = str(uuid4())
        value["provenance_status"] = "provided_unverified"
    elif change == "verified":
        value["provenance_status"] = "verified"
    elif change == "feature_mapping":
        value["internal_feature_names"].reverse()
    elif change == "feature_order":
        value["feature_names"].reverse()
    elif change == "native_parameters":
        value["effective_parameters"]["max_depth"] = 8
    elif change == "sha":
        value["ubj_sha256"] = "0" * 64
    elif change == "size":
        value["ubj_size_bytes"] += 1
    elif change == "traversal":
        value["ubj_filename"] = "../outside.ubj"
    elif change == "absolute":
        value["ubj_filename"] = str(saved[3] / value["ubj_filename"])
    elif change == "missing_json":
        json_path.unlink()
    elif change == "missing_ubj":
        (saved[3] / value["ubj_filename"]).unlink()
    elif change == "corrupt_ubj_with_matching_hash":
        raw = b"not an xgboost model"
        (saved[3] / value["ubj_filename"]).write_bytes(raw)
        value["ubj_sha256"] = hashlib.sha256(raw).hexdigest()
        value["ubj_size_bytes"] = len(raw)
    if change not in {"json", "duplicate_key", "missing_json", "missing_ubj"}:
        write_document(saved, value)
    with pytest.raises(ValueError):
        load(saved)


def test_swapped_valid_native_model_is_rejected_even_with_updated_sha(saved, model):
    fitted, _ = model
    other = artifacts.save_xgboost_artifact(fitted, artifact_root=saved[0])
    raw = (saved[3] / other.ubj_filename).read_bytes()
    value = document(saved)
    (saved[3] / value["ubj_filename"]).write_bytes(raw)
    value["ubj_sha256"], value["ubj_size_bytes"] = hashlib.sha256(raw).hexdigest(), len(raw)
    write_document(saved, value)
    with pytest.raises(ValueError, match="identity"):
        load(saved)


def test_duplicate_identity_never_overwrites(saved):
    before = {p.name: p.read_bytes() for p in saved[3].iterdir()}
    with pytest.raises(ValueError):
        artifacts.save_xgboost_artifact(
            saved[1],
            model_id=saved[2].model_id,
            artifact_root=saved[0],
        )
    assert before == {p.name: p.read_bytes() for p in saved[3].iterdir()}


@pytest.mark.parametrize("suffix", [".ubj", ".json"])
def test_partial_publication_is_not_a_complete_model(tmp_path, model, suffix):
    identity = uuid4()
    directory = tmp_path / "models" / "xgboost"
    directory.mkdir(parents=True)
    target = directory / f"{identity}{suffix}"
    target.write_bytes(b"retained")
    with pytest.raises(ValueError):
        artifacts.save_xgboost_artifact(model[0], model_id=identity, artifact_root=tmp_path)
    assert target.read_bytes() == b"retained"
    with pytest.raises(ValueError):
        artifacts.load_xgboost_artifact(model_id=identity, artifact_root=tmp_path)


def test_json_publication_failure_leaves_unusable_ubj_and_cleans_temporaries(
    tmp_path,
    model,
    monkeypatch,
):
    identity = uuid4()
    original = artifacts.os.link

    def fail_json(source, target):
        if str(target).endswith(".json"):
            raise OSError("simulated publication failure")
        return original(source, target)

    monkeypatch.setattr(artifacts.os, "link", fail_json)
    with pytest.raises(OSError):
        artifacts.save_xgboost_artifact(model[0], model_id=identity, artifact_root=tmp_path)
    directory = tmp_path / "models" / "xgboost"
    assert sorted(p.suffix for p in directory.iterdir()) == [".ubj"]
    with pytest.raises(ValueError):
        artifacts.load_xgboost_artifact(model_id=identity, artifact_root=tmp_path)


def make_link(link, target, *, directory=False):
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError as error:
        if (
            error.errno in (errno.EPERM, errno.EACCES, errno.ENOTSUP)
            or getattr(error, "winerror", None) == 1314
        ):
            pytest.skip("Windows account/filesystem does not allow symbolic links")
        raise


@pytest.mark.parametrize("kind", ["json", "ubj", "directory"])
def test_symbolic_links_are_rejected(tmp_path, model, kind):
    if kind == "directory":
        outside = tmp_path / "outside"
        outside.mkdir()
        (tmp_path / "models").mkdir()
        make_link(tmp_path / "models" / "xgboost", outside, directory=True)
        with pytest.raises(ValueError):
            artifacts.save_xgboost_artifact(model[0], artifact_root=tmp_path)
        assert not list(outside.iterdir())
        return
    metadata = artifacts.save_xgboost_artifact(model[0], artifact_root=tmp_path)
    directory = tmp_path / "models" / "xgboost"
    path = directory / (f"{metadata.model_id}.json" if kind == "json" else metadata.ubj_filename)
    outside = tmp_path / f"outside.{kind}"
    path.replace(outside)
    make_link(path, outside)
    with pytest.raises(ValueError):
        artifacts.load_xgboost_artifact(model_id=metadata.model_id, artifact_root=tmp_path)


def test_size_limits_apply_before_native_loading(saved, monkeypatch):
    monkeypatch.setattr(artifacts, "MAX_UBJ_BYTES", 1)
    with pytest.raises(ValueError, match="size"):
        load(saved)


def test_unsupported_runtime_does_not_load(saved, monkeypatch):
    monkeypatch.setattr(xgb, "__version__", "9.0.0")
    with pytest.raises(ValueError, match="version"):
        load(saved)


@pytest.mark.parametrize("field", ["json", "ubj_size", "ubj_sha"])
def test_platform_digest_is_checked_before_native_parser(saved, monkeypatch, field):
    root, _, metadata, directory, _ = saved
    json_sha = hashlib.sha256((directory / f"{metadata.model_id}.json").read_bytes()).hexdigest()
    expected = {
        "expected_json_sha256": "0" * 64 if field == "json" else json_sha,
        "expected_ubj": (
            metadata.ubj_size_bytes + (field == "ubj_size"),
            "0" * 64 if field == "ubj_sha" else metadata.ubj_sha256,
        ),
    }

    def unexpected():
        pytest.fail("Trusted platform evidence must be checked before native restoration")

    monkeypatch.setattr(artifacts, "xgboost_runtime", unexpected)
    with pytest.raises(ValueError, match="platform evidence"):
        artifacts.read_xgboost_artifact(model_id=metadata.model_id, artifact_root=root, **expected)


def test_ubjson_digest_is_checked_before_native_parser(saved, monkeypatch):
    path = saved[3] / saved[2].ubj_filename
    raw = path.read_bytes()
    path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])

    def forbidden(*args, **kwargs):
        raise AssertionError("Unverified bytes must not reach the native constructor")

    monkeypatch.setattr(xgb.Booster, "__init__", forbidden)
    with pytest.raises(ValueError, match="SHA256"):
        load(saved)


def test_native_loader_uses_verified_bytes_instead_of_reopening_path(saved, monkeypatch):
    original = xgb.Booster.__init__
    seen = []

    def checked(self, *args, **kwargs):
        raw = kwargs["model_file"]
        assert isinstance(raw, bytearray)
        seen.append(hashlib.sha256(raw).hexdigest())
        (saved[3] / saved[2].ubj_filename).write_bytes(b"changed after verification")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(xgb.Booster, "__init__", checked)
    restored = load(saved)
    assert seen == [saved[2].ubj_sha256]
    assert np.isfinite(restored.predict(saved[4], feature_names=NAMES)).all()


def test_metadata_size_limit_is_checked_before_parsing(saved, monkeypatch):
    monkeypatch.setattr(artifacts, "MAX_JSON_BYTES", 1)
    with pytest.raises(ValueError, match="size"):
        load(saved)


def test_opened_file_identity_must_match_the_inspected_file(saved, monkeypatch):
    source = saved[3] / f"{saved[2].model_id}.json"
    other = saved[0] / "replacement.json"
    other.write_bytes(source.read_bytes())
    original = type(source).open

    def replaced(self, *args, **kwargs):
        return original(other if self == source else self, *args, **kwargs)

    monkeypatch.setattr(type(source), "open", replaced)
    with pytest.raises(ValueError, match="changed while opening"):
        load(saved)


def test_publication_syncs_both_files_and_does_not_mutate_original(tmp_path, model, monkeypatch):
    original = artifacts.os.fsync
    calls = []
    before = bytes(model[0].save_raw(raw_format="ubj"))

    def synced(fd):
        calls.append(fd)
        return original(fd)

    monkeypatch.setattr(artifacts.os, "fsync", synced)
    artifacts.save_xgboost_artifact(model[0], artifact_root=tmp_path)
    assert len(calls) == 2
    assert bytes(model[0].save_raw(raw_format="ubj")) == before


def test_sync_failure_does_not_publish_or_leave_temporary_files(tmp_path, model, monkeypatch):
    def failed(fd):
        raise OSError("simulated sync failure")

    monkeypatch.setattr(artifacts.os, "fsync", failed)
    with pytest.raises(OSError):
        artifacts.save_xgboost_artifact(model[0], artifact_root=tmp_path)
    assert not list((tmp_path / "models" / "xgboost").iterdir())


def test_invalid_identity_cannot_be_used_as_a_path(tmp_path):
    with pytest.raises(ValueError):
        artifacts.load_xgboost_artifact(model_id="../outside", artifact_root=tmp_path)
