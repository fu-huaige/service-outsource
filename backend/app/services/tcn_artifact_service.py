"""Standalone TCN weights as a bounded, numeric-only NPZ and JSON descriptor."""

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

from app.schemas.tcn import (
    TCNArtifactMetadata,
    TCNParameters,
    TCNTensorDescription,
    TCNTrainingMetadata,
)
from app.services.tcn_modeling_service import TCNModel, build_tcn, cpu_execution, torch_runtime

MAX_JSON_BYTES = 1_048_576
MAX_NPZ_BYTES = 8_388_608
MAX_UNCOMPRESSED_BYTES = 8_388_608


def _regular(info: os.stat_result, *, directory: bool = False) -> None:
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(info.st_mode) or (
        getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    ):
        raise ValueError(
            "Expected a regular artifact path without symbolic links or reparse points"
        )


def _directory(root: Path, *, create: bool = False) -> Path:
    root = Path(root)
    if create:
        root.mkdir(parents=True, exist_ok=True)
    _regular(root.lstat(), directory=True)
    root = root.resolve(strict=True)
    directory = root
    for part in ("models", "tcn"):
        directory = directory / part
        if create:
            directory.mkdir(exist_ok=True)
        _regular(directory.lstat(), directory=True)
        if not directory.resolve(strict=True).is_relative_to(root):
            raise ValueError("Artifact directory escapes its root")
    return directory


def _read(path: Path, limit: int) -> bytes:
    info = path.lstat()
    _regular(info)
    if not 0 < info.st_size <= limit:
        raise ValueError("Artifact size exceeds limit or is empty")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        _regular(opened)
        if not os.path.samestat(info, opened) or info.st_size != opened.st_size:
            raise ValueError("Artifact changed while opening")
        raw = stream.read(limit + 1)
    if len(raw) != info.st_size:
        raise ValueError("Artifact size changed while reading")
    return raw


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("Duplicate JSON metadata key")
        result[name] = value
    return result


def _layout(state) -> tuple[TCNTensorDescription, ...]:
    return tuple(
        TCNTensorDescription(
            parameter_name=name,
            array_name=f"tensor_{i:03d}",
            shape=tuple(tensor.shape),
        )
        for i, (name, tensor) in enumerate(state.items())
    )


def _validate_archive(raw: bytes, arrays: tuple[TCNTensorDescription, ...]) -> None:
    expected = {f"{item.array_name}.npy": item.shape for item in arrays}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = archive.infolist()
        if len(members) != len(expected) or {m.filename for m in members} != set(expected):
            raise ValueError("Unexpected, missing or duplicate NPZ members")
        if sum(m.file_size for m in members) > MAX_UNCOMPRESSED_BYTES:
            raise ValueError("NPZ uncompressed size exceeds limit")
        for member in members:
            if member.flag_bits & 1 or member.compress_type not in (
                zipfile.ZIP_STORED,
                zipfile.ZIP_DEFLATED,
            ):
                raise ValueError("Unsupported NPZ member encoding")
            with archive.open(member) as stream:
                if np.lib.format.read_magic(stream) != (1, 0):
                    raise ValueError("Unsupported NPY header version")
                shape, fortran, dtype = np.lib.format.read_array_header_1_0(stream)
                if dtype != np.dtype("<f4") or fortran or shape != expected[member.filename]:
                    raise ValueError("Unexpected NPY shape, dtype or storage order")
                if stream.tell() + math.prod(shape) * dtype.itemsize != member.file_size:
                    raise ValueError("NPY payload size does not match its header")


def _temporary(directory: Path, raw: bytes, owned: list[Path]) -> Path:
    with tempfile.NamedTemporaryFile(dir=directory, suffix=".tmp", delete=False) as stream:
        path = Path(stream.name)
        owned.append(path)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return path


def _rebuild(metadata: TCNTrainingMetadata):
    torch = torch_runtime()
    if torch.__version__ != metadata.torch_version:
        raise ValueError("TCN artifact requires the original PyTorch build")
    with cpu_execution(0), torch.inference_mode(False):
        return build_tcn(len(metadata.feature_names), metadata.parameters)


def save_tcn_artifact(fitted: TCNModel, *, artifact_root: Path) -> TCNArtifactMetadata:
    training = TCNTrainingMetadata.model_validate(fitted.metadata.model_dump())
    state = fitted.model.state_dict()
    expected = _layout(_rebuild(training).state_dict())
    if _layout(state) != expected:
        raise ValueError("State does not match the TCN architecture")
    torch = torch_runtime()
    arrays = {}
    for item in expected:
        tensor = state[item.parameter_name]
        if tensor.device.type != "cpu" or tensor.dtype != torch.float32:
            raise ValueError("Expected CPU float32 model weights")
        value = np.array(tensor.detach().numpy(), dtype="<f4", order="C", copy=True)
        if not np.isfinite(value).all():
            raise ValueError("Nonfinite TCN model state")
        arrays[item.array_name] = value
    stream = io.BytesIO()
    np.savez(stream, allow_pickle=False, **arrays)
    raw = stream.getvalue()
    if len(raw) > MAX_NPZ_BYTES:
        raise ValueError("NPZ size exceeds limit")
    metadata = TCNArtifactMetadata(
        **training.model_dump(),
        npz_filename=f"{training.model_id}.npz",
        npz_size_bytes=len(raw),
        npz_sha256=hashlib.sha256(raw).hexdigest(),
        arrays=expected,
    )
    document = metadata.model_dump_json(indent=2).encode("utf-8")
    if len(document) > MAX_JSON_BYTES:
        raise ValueError("JSON metadata size exceeds limit")
    directory = _directory(artifact_root, create=True)
    npz_path, json_path = directory / metadata.npz_filename, directory / f"{training.model_id}.json"
    if os.path.lexists(npz_path) or os.path.lexists(json_path):
        raise ValueError("TCN artifact already exists")
    owned: list[Path] = []
    try:
        os.link(_temporary(directory, raw, owned), npz_path)
        os.link(_temporary(directory, document, owned), json_path)
    except FileExistsError as error:
        raise ValueError("TCN artifact publication conflict") from error
    finally:
        for path in owned:
            path.unlink(missing_ok=True)
    return metadata


def load_tcn_artifact(*, model_id: UUID | str, artifact_root: Path) -> TCNModel:
    identity = UUID(str(model_id))
    try:
        directory = _directory(artifact_root)
        document = json.loads(
            _read(directory / f"{identity}.json", MAX_JSON_BYTES),
            object_pairs_hook=_unique_keys,
        )
        if not isinstance(document, dict) or set(document) != set(TCNArtifactMetadata.model_fields):
            raise ValueError("Incomplete or unexpected TCN metadata")
        parameters = document["parameters"]
        descriptors = document["arrays"]
        if (
            not isinstance(parameters, dict)
            or set(parameters) != set(TCNParameters.model_fields)
            or not isinstance(descriptors, list)
            or any(
                not isinstance(item, dict) or set(item) != set(TCNTensorDescription.model_fields)
                for item in descriptors
            )
        ):
            raise ValueError("Incomplete or unexpected TCN parameters or array descriptors")
        metadata = TCNArtifactMetadata.model_validate(document)
        if metadata.model_id != identity:
            raise ValueError("TCN artifact model_id mismatch")
        raw = _read(directory / metadata.npz_filename, MAX_NPZ_BYTES)
        if (
            len(raw) != metadata.npz_size_bytes
            or hashlib.sha256(raw).hexdigest() != metadata.npz_sha256
        ):
            raise ValueError("NPZ size or SHA256 mismatch")
        model = _rebuild(metadata)
        if _layout(model.state_dict()) != metadata.arrays:
            raise ValueError("NPZ layout differs from the TCN architecture")
        _validate_archive(raw, metadata.arrays)
        torch = torch_runtime()
        state = {}
        with np.load(io.BytesIO(raw), allow_pickle=False) as arrays:
            for item in metadata.arrays:
                value = arrays[item.array_name]
                if value.shape != item.shape or value.dtype != np.dtype("<f4"):
                    raise ValueError("NPZ tensor differs from the declared layout")
                if not np.isfinite(value).all():
                    raise ValueError("Nonfinite TCN weights")
                state[item.parameter_name] = torch.from_numpy(value)
        model.load_state_dict(state, strict=True)
        model.eval()
    except (OSError, EOFError, zipfile.BadZipFile, RuntimeError, RecursionError) as error:
        raise ValueError("TCN artifact is unreadable or invalid") from error
    training = TCNTrainingMetadata.model_validate(
        {name: getattr(metadata, name) for name in TCNTrainingMetadata.model_fields}
    )
    return TCNModel(model, training)
