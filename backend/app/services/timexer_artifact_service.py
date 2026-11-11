"""Standalone TimeXer metadata and bounded numeric state, with no object serialization."""

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
from uuid import UUID

import numpy as np

from app.schemas.timexer import (
    TimeXerArtifactMetadata,
    TimeXerParameters,
    TimeXerTensorDescription,
    TimeXerTrainingMetadata,
)
from app.services.timexer_modeling_service import (
    TimeXerModel,
    build_timexer,
    seeded_cpu,
    torch_runtime,
)

MAX_JSON_BYTES = 1_048_576
MAX_NPZ_BYTES = 8_388_608
MAX_UNCOMPRESSED_BYTES = 8_388_608
MAX_NPY_HEADER_BYTES = 4096
_FLOAT32 = np.dtype("<f4")


def _regular(info: os.stat_result, *, directory: bool = False) -> None:
    expected_type = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected_type(info.st_mode) or (
        getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    ):
        raise ValueError("Expected a regular TimeXer artifact path without links or reparse points")


def _directory(artifact_root: Path, *, create: bool = False) -> Path:
    root = Path(artifact_root)
    if create:
        root.mkdir(parents=True, exist_ok=True)
    _regular(root.lstat(), directory=True)
    root = root.resolve(strict=True)
    directory = root
    for name in ("models", "timexer"):
        directory = directory / name
        if create:
            directory.mkdir(exist_ok=True)
        _regular(directory.lstat(), directory=True)
        if directory.resolve(strict=True) != directory or not directory.is_relative_to(root):
            raise ValueError("TimeXer artifact directory escapes its root")
    return directory


def _read(path: Path, max_bytes: int) -> bytes:
    before = path.lstat()
    _regular(before)
    if not 0 < before.st_size <= max_bytes:
        raise ValueError("TimeXer artifact size is outside its limit")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        _regular(opened)
        if not os.path.samestat(before, opened) or before.st_size != opened.st_size:
            raise ValueError("TimeXer artifact changed while opening")
        raw = stream.read(max_bytes + 1)
    if len(raw) != before.st_size:
        raise ValueError("TimeXer artifact size changed while reading")
    return raw


def _unique_keys(items: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("Duplicate TimeXer JSON key")
        result[key] = value
    return result


def _complete(document, schema) -> bool:
    return isinstance(document, dict) and set(document) == set(schema.model_fields)


def _read_metadata(raw: bytes) -> TimeXerArtifactMetadata:
    document = json.loads(raw, object_pairs_hook=_unique_keys)
    if not _complete(document, TimeXerArtifactMetadata):
        raise ValueError("Incomplete or unexpected TimeXer metadata")
    arrays = document["arrays"]
    if (
        not _complete(document["parameters"], TimeXerParameters)
        or not isinstance(arrays, list)
        or any(not _complete(item, TimeXerTensorDescription) for item in arrays)
    ):
        raise ValueError("Incomplete or unexpected TimeXer parameters or tensor descriptors")
    return TimeXerArtifactMetadata.model_validate(document)


def _layout(state) -> tuple[TimeXerTensorDescription, ...]:
    return tuple(
        TimeXerTensorDescription(
            parameter_name=name, array_name=f"tensor_{index:03d}", shape=tuple(tensor.shape)
        )
        for index, (name, tensor) in enumerate(state.items())
    )


def _validate_archive(raw: bytes, layout: tuple[TimeXerTensorDescription, ...]) -> None:
    expected = {f"{item.array_name}.npy": item.shape for item in layout}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = archive.infolist()
        if len(members) != len(expected) or {item.filename for item in members} != set(expected):
            raise ValueError("Unexpected, missing or duplicate TimeXer NPZ members")
        if sum(item.file_size for item in members) > MAX_UNCOMPRESSED_BYTES:
            raise ValueError("TimeXer NPZ uncompressed size exceeds limit")
        for item in members:
            if (
                item.orig_filename != item.filename
                or item.flag_bits & 1
                or item.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
            ):
                raise ValueError("Unsupported TimeXer NPZ member")
            with archive.open(item) as stream:
                if np.lib.format.read_magic(stream) != (1, 0):
                    raise ValueError("Unsupported TimeXer NPY version")
                length_bytes = stream.read(2)
                length = int.from_bytes(length_bytes, "little")
                if len(length_bytes) != 2 or not 0 < length <= MAX_NPY_HEADER_BYTES:
                    raise ValueError("TimeXer NPY header length is outside its limit")
                header_bytes = stream.read(length)
                if len(header_bytes) != length:
                    raise ValueError("Truncated TimeXer NPY header")
                header = io.BytesIO(length_bytes + header_bytes)
                shape, fortran, dtype = np.lib.format.read_array_header_1_0(header)
                if dtype != _FLOAT32 or fortran or shape != expected[item.filename]:
                    raise ValueError("Unexpected TimeXer NPY shape, dtype or storage order")
                if stream.tell() + math.prod(shape) * dtype.itemsize != item.file_size:
                    raise ValueError("TimeXer NPY payload size does not match its header")


def _temporary(directory: Path, raw: bytes, owned: list[Path]) -> Path:
    with tempfile.NamedTemporaryFile(dir=directory, suffix=".tmp", delete=False) as stream:
        path = Path(stream.name)
        owned.append(path)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return path


def _runtime_for(metadata: TimeXerTrainingMetadata):
    torch = torch_runtime()
    if torch.__version__ != metadata.torch_version or np.__version__ != metadata.numpy_version:
        raise ValueError("TimeXer artifact requires the recorded PyTorch build and NumPy version")
    return torch


def save_timexer_artifact(fitted: TimeXerModel, *, artifact_root: Path) -> TimeXerArtifactMetadata:
    training = TimeXerTrainingMetadata.model_validate(fitted.metadata.model_dump())
    torch = _runtime_for(training)
    state = fitted.model.state_dict()
    expected = _layout(build_timexer(training.parameters, device="meta").state_dict())
    if _layout(state) != expected:
        raise ValueError("State does not match the TimeXer architecture")
    arrays = {}
    for item in expected:
        tensor = state[item.parameter_name]
        if tensor.device.type != "cpu" or tensor.dtype != torch.float32:
            raise ValueError("Expected CPU float32 TimeXer state")
        value = np.array(tensor.detach().numpy(), dtype=_FLOAT32, order="C", copy=True)
        if not np.isfinite(value).all():
            raise ValueError("Nonfinite TimeXer model state")
        arrays[item.array_name] = value

    stream = io.BytesIO()
    np.savez(stream, allow_pickle=False, **arrays)
    raw = stream.getvalue()
    if len(raw) > MAX_NPZ_BYTES:
        raise ValueError("TimeXer NPZ size exceeds limit")
    metadata = TimeXerArtifactMetadata(
        **training.model_dump(),
        npz_filename=f"{training.model_id}.npz",
        npz_size_bytes=len(raw),
        npz_sha256=hashlib.sha256(raw).hexdigest(),
        arrays=expected,
    )
    document = metadata.model_dump_json(indent=2).encode("utf-8")
    if len(document) > MAX_JSON_BYTES:
        raise ValueError("TimeXer JSON size exceeds limit")

    directory = _directory(artifact_root, create=True)
    npz_path = directory / metadata.npz_filename
    json_path = directory / f"{training.model_id}.json"
    if os.path.lexists(npz_path) or os.path.lexists(json_path):
        raise ValueError("TimeXer artifact already exists")
    owned: list[Path] = []
    try:
        os.link(_temporary(directory, raw, owned), npz_path)
        os.link(_temporary(directory, document, owned), json_path)
    except FileExistsError as error:
        raise ValueError("TimeXer artifact publication conflict") from error
    finally:
        for path in owned:
            path.unlink(missing_ok=True)
    return metadata


def read_timexer_artifact(
    *,
    model_id: UUID | str,
    artifact_root: Path,
    expected_json_sha256: str | None = None,
    expected_npz: tuple[int, str] | None = None,
) -> tuple[TimeXerModel, TimeXerArtifactMetadata, str]:
    identity = UUID(str(model_id))
    try:
        directory = _directory(artifact_root)
        raw_json = _read(directory / f"{identity}.json", MAX_JSON_BYTES)
        json_sha256 = hashlib.sha256(raw_json).hexdigest()
        if expected_json_sha256 is not None and json_sha256 != expected_json_sha256:
            raise ValueError("TimeXer JSON SHA256 differs from the platform evidence")
        metadata = _read_metadata(raw_json)
        if metadata.model_id != identity:
            raise ValueError("TimeXer artifact model_id mismatch")
        if expected_npz is not None and expected_npz != (
            metadata.npz_size_bytes,
            metadata.npz_sha256,
        ):
            raise ValueError("TimeXer NPZ size or SHA256 differs from the platform evidence")
        raw = _read(directory / metadata.npz_filename, MAX_NPZ_BYTES)
        if (
            len(raw) != metadata.npz_size_bytes
            or hashlib.sha256(raw).hexdigest() != metadata.npz_sha256
        ):
            raise ValueError("TimeXer NPZ size or SHA256 mismatch")
        torch = _runtime_for(metadata)
        with seeded_cpu(0), torch.inference_mode(False):
            model = build_timexer(metadata.parameters)
            if _layout(model.state_dict()) != metadata.arrays:
                raise ValueError("NPZ layout differs from the TimeXer architecture")
            _validate_archive(raw, metadata.arrays)
            state = {}
            with np.load(io.BytesIO(raw), allow_pickle=False) as archive:
                for item in metadata.arrays:
                    value = archive[item.array_name]
                    if value.shape != item.shape or value.dtype != _FLOAT32:
                        raise ValueError("TimeXer NPZ array differs from the expected layout")
                    if not np.isfinite(value).all():
                        raise ValueError("Nonfinite TimeXer weights")
                    state[item.parameter_name] = torch.from_numpy(value)
            model.load_state_dict(state, strict=True)
            model.eval()
    except (OSError, EOFError, zipfile.BadZipFile, RuntimeError, RecursionError) as error:
        raise ValueError("TimeXer artifact is unreadable or invalid") from error
    training = TimeXerTrainingMetadata.model_validate(
        {name: getattr(metadata, name) for name in TimeXerTrainingMetadata.model_fields}
    )
    return TimeXerModel(model=model, metadata=training), metadata, json_sha256


def load_timexer_artifact(*, model_id: UUID | str, artifact_root: Path) -> TimeXerModel:
    return read_timexer_artifact(model_id=model_id, artifact_root=artifact_root)[0]
