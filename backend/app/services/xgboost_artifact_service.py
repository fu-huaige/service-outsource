"""Independent JSON/UBJSON files, exclusive publication and bounded native restoration."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from app.schemas.xgboost import XGBoostArtifactMetadata, XGBoostTrainingMetadata
from app.services.xgboost_modeling_service import (
    predict_xgboost,
    training_metadata,
    xgboost_runtime,
)

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import ArrayLike, NDArray
    from xgboost import Booster

MAX_JSON_BYTES = 1_048_576
MAX_UBJ_BYTES = 67_108_864
IDENTITY_ATTRIBUTE = "indusopt_artifact_identity"


def _uuid(value: UUID | str) -> UUID:
    if not isinstance(value, (UUID, str)):
        raise ValueError("Expected a UUID identity")
    try:
        return UUID(str(value))
    except ValueError as error:
        raise ValueError("Invalid UUID identity") from error


def _reject_link(info: os.stat_result) -> None:
    if stat.S_ISLNK(info.st_mode) or (
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    ):
        raise ValueError("Artifact paths cannot be symbolic links or reparse points")


def _directory(root: Path, *, create: bool = False) -> Path:
    root = Path(root)
    if root.exists() or root.is_symlink():
        _reject_link(root.lstat())
    if create:
        root.mkdir(parents=True, exist_ok=True)
    root = root.resolve()
    directory = root
    for part in ("models", "xgboost"):
        directory = directory / part
        if directory.exists() or directory.is_symlink():
            _reject_link(directory.lstat())
        if create:
            directory.mkdir(exist_ok=True)
        if not directory.is_dir() or not directory.resolve().is_relative_to(root):
            raise ValueError("Artifact directory is missing or outside its root")
    return directory


def _read_file(directory: Path, filename: str, limit: int) -> bytes:
    if Path(filename).name != filename or any(c in filename for c in ("/", "\\", ":")):
        raise ValueError("Artifact filename must not contain a path")
    path = directory / filename
    try:
        original = path.lstat()
        _reject_link(original)
        if not stat.S_ISREG(original.st_mode):
            raise ValueError("Artifact must be a regular file")
        if original.st_size > limit:
            raise ValueError("Artifact size exceeds limit")
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino) != (
                original.st_dev,
                original.st_ino,
            ) or not stat.S_ISREG(opened.st_mode):
                raise ValueError("Artifact changed while opening")
            raw = stream.read(limit + 1)
    except OSError as error:
        raise ValueError("Artifact file is missing or unreadable") from error
    if len(raw) > limit or len(raw) != opened.st_size:
        raise ValueError("Artifact size changed or exceeds limit")
    return raw


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON metadata key")
        result[key] = value
    return result


def _identity(model_id: UUID, training_run_id: UUID | None, status: str) -> str:
    return json.dumps(
        {
            "model_id": str(model_id),
            "training_run_id": str(training_run_id) if training_run_id else None,
            "provenance_status": status,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _verify_native(booster: Booster, metadata: XGBoostArtifactMetadata) -> None:
    actual = training_metadata(booster)
    expected = {name: getattr(metadata, name) for name in XGBoostTrainingMetadata.model_fields}
    if actual != XGBoostTrainingMetadata.model_validate(expected):
        raise ValueError("JSON metadata differs from native training metadata")
    if booster.attr(IDENTITY_ATTRIBUTE) != _identity(
        metadata.model_id,
        metadata.training_run_id,
        metadata.provenance_status,
    ):
        raise ValueError("Native artifact identity differs from JSON metadata")


@dataclass(frozen=True)
class SavedXGBoostModel:
    metadata: XGBoostArtifactMetadata
    booster: Booster

    def predict(
        self,
        X: ArrayLike,
        *,
        feature_names: tuple[str, ...],
    ) -> NDArray[np.float64]:
        _verify_native(self.booster, self.metadata)
        return predict_xgboost(self.booster, X, feature_names=feature_names)


def _temporary(directory: Path, raw: bytes, owned: list[Path]) -> Path:
    with tempfile.NamedTemporaryFile(dir=directory, suffix=".tmp", delete=False) as stream:
        path = Path(stream.name)
        owned.append(path)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return path


def save_xgboost_artifact(
    booster: Booster,
    *,
    artifact_root: Path,
    model_id: UUID | str | None = None,
    training_run_id: UUID | str | None = None,
) -> XGBoostArtifactMetadata:
    """Save a new identity only. UUID claims are never promoted to database verification."""
    training = training_metadata(booster)
    identity = uuid4() if model_id is None else _uuid(model_id)
    run = None if training_run_id is None else _uuid(training_run_id)
    if identity == run:
        raise ValueError("model_id and training_run_id must be different")
    status = "unbound" if run is None else "provided_unverified"
    xgb = xgboost_runtime()
    # Clone from the native buffer, without mutating the caller's existing Booster.
    clone = xgb.Booster(
        params={"device": "cpu", "nthread": 1},
        model_file=bytearray(booster.save_raw(raw_format="ubj")),
    )
    clone.set_attr(**{IDENTITY_ATTRIBUTE: _identity(identity, run, status)})
    raw = bytes(clone.save_raw(raw_format="ubj"))
    if not raw or len(raw) > MAX_UBJ_BYTES:
        raise ValueError("UBJSON size exceeds limit")
    metadata = XGBoostArtifactMetadata(
        **training.model_dump(),
        model_id=identity,
        training_run_id=run,
        provenance_status=status,
        ubj_filename=f"{identity}.ubj",
        ubj_size_bytes=len(raw),
        ubj_sha256=hashlib.sha256(raw).hexdigest(),
    )
    _verify_native(clone, metadata)
    document = metadata.model_dump_json(indent=2).encode("utf-8")
    if len(document) > MAX_JSON_BYTES:
        raise ValueError("JSON metadata size exceeds limit")
    directory = _directory(artifact_root, create=True)
    ubj_path, json_path = directory / metadata.ubj_filename, directory / f"{identity}.json"
    if any(p.exists() or p.is_symlink() for p in (ubj_path, json_path)):
        raise ValueError("Artifact already exists; files will not be overwritten")
    owned: list[Path] = []
    try:
        ubj_temp = _temporary(directory, raw, owned)
        os.link(ubj_temp, ubj_path)
        json_temp = _temporary(directory, document, owned)
        os.link(json_temp, json_path)
    except FileExistsError as error:
        raise ValueError("Artifact publication conflict; existing files retained") from error
    finally:
        for path in owned:
            path.unlink(missing_ok=True)
    return metadata


def read_xgboost_artifact(
    *,
    model_id: UUID | str,
    artifact_root: Path,
    expected_json_sha256: str | None = None,
    expected_ubj: tuple[int, str] | None = None,
) -> tuple[SavedXGBoostModel, str]:
    """Return a validated standalone claim and the digest of the exact metadata bytes."""
    identity = _uuid(model_id)
    directory = _directory(artifact_root)
    raw_json = _read_file(directory, f"{identity}.json", MAX_JSON_BYTES)
    json_sha256 = hashlib.sha256(raw_json).hexdigest()
    if expected_json_sha256 is not None and json_sha256 != expected_json_sha256:
        raise ValueError("JSON SHA256 differs from the platform evidence")
    try:
        document = json.loads(raw_json, object_pairs_hook=_unique_keys)
        if not isinstance(document, dict) or set(document) != set(
            XGBoostArtifactMetadata.model_fields
        ):
            raise ValueError("Incomplete or unexpected XGBoost artifact metadata fields")
        metadata = XGBoostArtifactMetadata.model_validate(document)
        if metadata.model_id != identity:
            raise ValueError("Artifact model identity mismatch")
        if expected_ubj is not None and expected_ubj != (
            metadata.ubj_size_bytes,
            metadata.ubj_sha256,
        ):
            raise ValueError("UBJSON size or SHA256 differs from the platform evidence")
        raw = _read_file(directory, metadata.ubj_filename, MAX_UBJ_BYTES)
        if len(raw) != metadata.ubj_size_bytes:
            raise ValueError("UBJSON size mismatch")
        if hashlib.sha256(raw).hexdigest() != metadata.ubj_sha256:
            raise ValueError("UBJSON SHA256 mismatch")
        xgb = xgboost_runtime()
        # Restore the exact bytes already verified above, never reopen the native path.
        try:
            booster = xgb.Booster(
                params={"device": "cpu", "nthread": 1},
                model_file=bytearray(raw),
            )
        except xgb.core.XGBoostError as error:
            raise ValueError("Invalid native UBJSON model") from error
        _verify_native(booster, metadata)
    except (UnicodeError, TypeError, KeyError) as error:
        raise ValueError("Invalid XGBoost artifact metadata") from error
    return SavedXGBoostModel(metadata, booster), json_sha256


def load_xgboost_artifact(*, model_id: UUID | str, artifact_root: Path) -> SavedXGBoostModel:
    return read_xgboost_artifact(model_id=model_id, artifact_root=artifact_root)[0]
