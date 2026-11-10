"""Standalone PLS JSON/NPZ artifacts. No database, manifests or pickle."""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import stat
import tempfile
import zipfile
from pathlib import Path
from uuid import UUID, uuid4

import numpy as np

from app.schemas.pls import PLSArrayDescription, PLSArtifactMetadata
from app.services.pls_modeling_service import ARRAY_NAMES, SavedPLSModel

MAX_JSON_BYTES = 1_048_576
MAX_NPZ_BYTES = 67_108_864
MAX_UNCOMPRESSED_BYTES = 134_217_728


def _model_id(value: UUID | str) -> UUID:
    if not isinstance(value, (UUID, str)):
        raise ValueError("model_id must be a UUID")
    try:
        return UUID(str(value))
    except ValueError as error:
        raise ValueError("model_id must be a UUID") from error


def _directory(root: Path, *, create: bool = False) -> Path:
    root = Path(root).resolve()
    if create:
        root.mkdir(parents=True, exist_ok=True)
    directory = root
    for part in ("models", "pls"):
        directory = directory / part
        if directory.is_symlink():
            raise ValueError("PLS artifact directory cannot be a symbolic link")
        if create:
            directory.mkdir(exist_ok=True)
        if not directory.is_dir():
            raise ValueError("PLS artifact directory is missing or invalid")
    if not directory.resolve().is_relative_to(root):
        raise ValueError("PLS artifact directory escapes its root")
    return directory


def _read_file(directory: Path, filename: str, limit: int) -> bytes:
    if Path(filename).name != filename or any(c in filename for c in ("/", "\\", ":")):
        raise ValueError("Artifact filename must not contain a path")
    path = directory / filename
    try:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise ValueError("Artifact must be a regular file, not a symbolic link")
        if info.st_size > limit:
            raise ValueError("Artifact exceeds size limit")
        with path.open("rb") as stream:
            raw = stream.read(limit + 1)
    except OSError as error:
        raise ValueError("Artifact is missing or unreadable") from error
    if len(raw) > limit:
        raise ValueError("Artifact exceeds size limit")
    return raw


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _validate_zip(raw: bytes, metadata: PLSArtifactMetadata) -> None:
    expected = {f"{a.name}.npy": a.shape for a in metadata.arrays}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = archive.infolist()
        names = [item.filename for item in members]
        if (
            len(names) != len(expected)
            or len(set(names)) != len(names)
            or set(names) != set(expected)
        ):
            raise ValueError("Unexpected, missing or duplicate NPZ members")
        if sum(item.file_size for item in members) > MAX_UNCOMPRESSED_BYTES:
            raise ValueError("NPZ uncompressed size exceeds limit")
        for member in members:
            if member.flag_bits & 1 or member.compress_type not in (
                zipfile.ZIP_STORED,
                zipfile.ZIP_DEFLATED,
            ):
                raise ValueError("Unsupported NPZ member encoding")
            # Inspect the actual bounded NPY header before np.load can allocate.
            with archive.open(member) as stream:
                version = np.lib.format.read_magic(stream)
                if version == (1, 0):
                    shape, _, dtype = np.lib.format.read_array_header_1_0(stream)
                elif version == (2, 0):
                    shape, _, dtype = np.lib.format.read_array_header_2_0(stream)
                else:
                    raise ValueError("Unsupported NPY version")
                if dtype != np.dtype("float64") or dtype.hasobject:
                    raise ValueError("NPZ arrays must have float64 dtype")
                if shape != expected[member.filename]:
                    raise ValueError("NPZ array shape mismatch")
                if stream.tell() + math.prod(shape) * dtype.itemsize != member.file_size:
                    raise ValueError("NPY byte size does not match its shape")


def save_pls_artifact(
    model: SavedPLSModel,
    *,
    artifact_root: Path,
    model_id: UUID | str | None = None,
) -> PLSArtifactMetadata:
    """Publish JSON last, exclusively; never overwrite another model's files."""
    identity = uuid4() if model_id is None else _model_id(model_id)
    # Revalidate exposed arrays before serialization, without running fit.
    model = SavedPLSModel(metadata=model.metadata, **model.arrays())
    directory = _directory(artifact_root, create=True)
    final_npz, final_json = directory / f"{identity}.npz", directory / f"{identity}.json"
    if any(path.exists() or path.is_symlink() for path in (final_npz, final_json)):
        raise ValueError("Model artifact already exists")
    temporary: list[Path] = []
    try:
        with tempfile.NamedTemporaryFile(dir=directory, suffix=".tmp", delete=False) as stream:
            npz_temp = Path(stream.name)
            temporary.append(npz_temp)
            np.savez(stream, **model.arrays())
        raw = npz_temp.read_bytes()
        if len(raw) > MAX_NPZ_BYTES:
            raise ValueError("NPZ exceeds size limit")
        metadata = PLSArtifactMetadata.model_validate(
            {
                **model.metadata.model_dump(),
                "model_id": identity,
                "npz_filename": final_npz.name,
                "npz_sha256": hashlib.sha256(raw).hexdigest(),
                "npz_size_bytes": len(raw),
                "arrays": tuple(
                    PLSArrayDescription(name=name, shape=array.shape)
                    for name, array in model.arrays().items()
                ),
            }
        )
        _validate_zip(raw, metadata)
        document = metadata.model_dump_json(indent=2).encode("utf-8")
        if len(document) > MAX_JSON_BYTES:
            raise ValueError("JSON exceeds size limit")
        with tempfile.NamedTemporaryFile(dir=directory, suffix=".tmp", delete=False) as stream:
            json_temp = Path(stream.name)
            temporary.append(json_temp)
            stream.write(document)
        # Hard-link publication is atomic and fails if a destination already exists.
        os.link(npz_temp, final_npz)
        os.link(json_temp, final_json)
        return metadata
    except FileExistsError as error:
        raise ValueError("Model artifact already exists") from error
    finally:
        for path in temporary:
            path.unlink(missing_ok=True)


def load_pls_artifact(*, model_id: UUID | str, artifact_root: Path) -> SavedPLSModel:
    identity = _model_id(model_id)
    directory = _directory(artifact_root)
    raw_json = _read_file(directory, f"{identity}.json", MAX_JSON_BYTES)
    try:
        document = json.loads(raw_json, object_pairs_hook=_reject_duplicate_keys)
        metadata = PLSArtifactMetadata.model_validate(document)
        if metadata.model_id != identity:
            raise ValueError("Artifact model_id mismatch")
        raw_npz = _read_file(directory, metadata.npz_filename, MAX_NPZ_BYTES)
        if len(raw_npz) != metadata.npz_size_bytes:
            raise ValueError("NPZ file size mismatch")
        if hashlib.sha256(raw_npz).hexdigest() != metadata.npz_sha256:
            raise ValueError("NPZ SHA256 mismatch")
        _validate_zip(raw_npz, metadata)
        with np.load(io.BytesIO(raw_npz), allow_pickle=False) as archive:
            arrays = {name: archive[name] for name in ARRAY_NAMES}
        return SavedPLSModel(metadata=metadata, **arrays)
    except (ValueError, TypeError, KeyError, EOFError, zipfile.BadZipFile, UnicodeError) as error:
        raise ValueError(f"Invalid PLS artifact: {error}") from error
