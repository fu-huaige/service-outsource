"""Manifest construction/publication and static model loading. Never fits."""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
import tempfile
from dataclasses import dataclass
from itertools import zip_longest
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dataset import ProcessingRun
from app.schemas.experiment_spec import ExperimentSpec, RowRange, RowSet
from app.schemas.model_catalog import (
    ModelArtifactManifest,
    PLSModelArtifactManifest,
    TCNModelArtifactManifest,
    TimeXerModelArtifactManifest,
    XGBoostModelArtifactManifest,
)
from app.schemas.pls import PLSBoundArtifactMetadata
from app.services.experiment_spec_service import (
    bind_experiment_spec,
    contained_path,
    iter_rows,
    spec_hash,
)
from app.services.model_registry import get_model
from app.services.modeling_service import SavedArxModel, load_saved_arx_model
from app.services.pls_modeling_service import SavedPLSModel
from app.services.tcn_modeling_service import TCNModel
from app.services.timexer_modeling_service import TimeXerModel
from app.services.xgboost_artifact_service import SavedXGBoostModel


@dataclass(frozen=True)
class LoadedModelInstance:
    model_id: UUID
    model_type_id: str
    training_run_id: UUID | None
    origin: str
    manifest: ModelArtifactManifest | None
    payload: SavedArxModel | SavedPLSModel | SavedXGBoostModel | TCNModel | TimeXerModel
    missing_provenance: tuple[str, ...] = ()


def _checked_model_file(root: Path, uri: str, *, optional: bool = False) -> Path | None:
    """Resolve and inspect before any legacy reader can follow a file link."""
    try:
        resolved = contained_path(root, uri)
        models = contained_path(root, "models")
        if not resolved.is_relative_to(models):
            raise ValueError("Model file escapes artifact_root/models")
        original = root / uri
        try:
            original.lstat()
        except FileNotFoundError:
            if optional:
                return None
            raise ValueError("Model payload is missing") from None
        try:
            mode = resolved.stat().st_mode
        except FileNotFoundError:
            raise ValueError("Dangling model or manifest symbolic link") from None
        if not stat.S_ISREG(mode):
            raise ValueError("Model or manifest must be a regular file")
        return resolved
    except (OSError, RuntimeError) as error:
        raise ValueError("Model path cannot be safely resolved") from error


def _read_payload(root: Path, model_id: UUID) -> tuple[dict[str, object], str]:
    path = _checked_model_file(root, f"models/{model_id}.json")
    raw = path.read_bytes()
    document = json.loads(raw)
    if not isinstance(document, dict):
        raise ValueError("Model payload must be a JSON object")
    return document, hashlib.sha256(raw).hexdigest()


def _same_result(left: object, right: object) -> bool:
    """Compare JSON structure and finite numbers (rtol=1e-9, atol=1e-12)."""
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_same_result(left[k], right[k]) for k in left)
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        return len(left) == len(right) and all(
            _same_result(a, b) for a, b in zip(left, right, strict=True)
        )
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return (
            math.isfinite(left)
            and math.isfinite(right)
            and math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-12)
        )
    return type(left) is type(right) and left == right


def _training_result_gaps(
    run: ProcessingRun | None,
    document: dict[str, object],
) -> tuple[str, ...]:
    missing = []
    for field in ("coefficients", "intercept", "preprocessing", "training_rows"):
        if run is None or field not in run.result:
            missing.append(f"training_result.{field}")
        if field not in document:
            missing.append(f"payload.{field}")
        if run is None or field not in run.result or field not in document:
            continue
        left, right = run.result[field], document[field]
        if field == "training_rows":
            equal = type(left) is int and type(right) is int and left >= 0 and left == right
        else:
            equal = _same_result(left, right)
        if not equal:
            label = "training row count" if field == "training_rows" else field
            raise ValueError(f"Training result {label} mismatch")
    return tuple(missing)


async def _training_run(session: AsyncSession, saved: SavedArxModel) -> ProcessingRun | None:
    # Scope first, then exact model identity. Never choose the latest run.
    statement = select(ProcessingRun).where(
        ProcessingRun.run_type == "modeling.arx",
        ProcessingRun.dataset_id == saved.dataset_id,
        ProcessingRun.source_version_id == saved.source_version_id,
    )
    candidates = [
        r
        for r in (await session.scalars(statement)).all()
        if r.result.get("model_id") == str(saved.model_id)
    ]
    if len(candidates) > 1:
        raise ValueError("Ambiguous training_run_id")
    if not candidates:
        return None
    run = candidates[0]
    if run.status != "succeeded" or run.parameters != saved.payload.model_dump(mode="json"):
        # Legacy configurations can omit fields that the existing loader supplies.
        from app.schemas.modeling import ArxFitRequest

        params = dict(run.parameters)
        params.setdefault("fit_intercept", False)
        params.setdefault("standardize", False)
        if run.status != "succeeded" or ArxFitRequest.model_validate(params) != saved.payload:
            raise ValueError("Training run parameters mismatch")
    return run


def _validate_payload_spec(saved: SavedArxModel, spec: ExperimentSpec, root: Path) -> None:
    p = saved.payload
    if (
        spec.task_type != "dynamic_system_identification"
        or spec.dataset_id != saved.dataset_id
        or spec.dataset_version_id != saved.source_version_id
        or list(spec.input_columns) != p.input_columns
        or spec.target_column != p.output_column
    ):
        raise ValueError("Model and experiment source/task/variables mismatch")
    n = spec.row_count
    train_end, val_end = int(n * p.train_ratio), int(n * (p.train_ratio + p.validation_ratio))
    expected = (
        (RowRange(start=0, stop=train_end),),
        (RowRange(start=train_end, stop=val_end),),
        (RowRange(start=val_end, stop=n),),
    )
    if (spec.split.train, spec.split.validation, spec.split.test) != expected:
        raise ValueError("Existing dynamic payload only executes a single chronological split")
    s, f = saved.structure, spec.feature_spec
    expected_lags = {c: tuple(range(s.nk[c], s.nk[c] + s.nb[c])) for c in s.input_columns}
    if (
        f.kind != "dynamic_lags"
        or f.input_lags != expected_lags
        or f.target_lags != tuple(range(1, s.na + 1))
        or f.history_window != s.max_history
        or f.prediction_horizon != 1
        or f.initialization_policy != p.initialization_policy
        or spec.split.history_guard != max(s.max_history, p.history_guard or 0)
    ):
        raise ValueError("Experiment feature/guard semantics do not match saved payload")
    selection = spec.training_selection
    if p.training_sample_indices:
        if selection.mode != "selected_rows":
            raise ValueError("Saved model requires selected rows")
        pairs = zip_longest(
            iter(p.training_sample_indices), iter_rows(selection.requested_indices, root)
        )
        if any(a != b for a, b in pairs):
            raise ValueError("Saved training selection mismatch")
    elif selection.mode != "full_train":
        raise ValueError("Empty legacy selection means full Train")


async def build_model_manifest(
    session: AsyncSession,
    *,
    model_id: UUID,
    spec: ExperimentSpec,
    artifact_root: Path,
    effective_training_rows: RowSet,
) -> ModelArtifactManifest:
    """Build only; effective rows must be cross-checked by the read-only validator."""
    document, payload_digest = _read_payload(artifact_root, model_id)
    saved = load_saved_arx_model(model_id=model_id, artifact_root=artifact_root)
    definition = get_model(saved.payload.model_type.lower())
    bound = await bind_experiment_spec(session, spec=spec, artifact_root=artifact_root)
    _validate_payload_spec(saved, bound, artifact_root)
    run = await _training_run(session, saved)
    if run is None:
        raise ValueError("A manifest requires an exact training run")
    missing = _training_result_gaps(run, document)
    if missing:
        raise ValueError("Training result provenance incomplete: " + ", ".join(missing))
    await _validate_effective_rows(session, saved, bound, effective_training_rows, artifact_root)
    return ModelArtifactManifest(
        model_type_id=definition.model_type_id,
        model_id=model_id,
        training_run_id=run.id,
        implementation_id=definition.implementation_id,
        # Retrospective metadata must not invent the training implementation version.
        implementation_version="legacy-unknown",
        experiment_spec=bound,
        experiment_spec_hash=spec_hash(bound),
        effective_training_rows=effective_training_rows,
        payload_uri=saved.artifact_uri,
        payload_sha256=payload_digest,
    )


async def _validate_effective_rows(
    session: AsyncSession,
    saved: SavedArxModel,
    spec: ExperimentSpec,
    rows: RowSet,
    root: Path,
) -> None:
    from algorithms.identifiability.regressor import build_regressor

    from app.services.version_data import load_version_series

    series = await load_version_series(
        session, version_id=saved.source_version_id, dataset_id=saved.dataset_id, artifact_root=root
    )
    reg = build_regressor(
        inputs={c: series.values[c] for c in saved.structure.input_columns},
        output=series.values[saved.payload.output_column],
        structure=saved.structure,
    )
    end = int(series.n_samples * saved.payload.train_ratio) - max(
        saved.structure.max_history, saved.payload.history_guard or 0
    )
    allowed = (
        set(saved.payload.training_sample_indices)
        if saved.payload.training_sample_indices
        else None
    )
    actual = (
        int(i) for i in reg.time_indices if i < end and (allowed is None or int(i) in allowed)
    )
    # Compare in streaming order; this does not allocate a full JSON index list.
    from app.services.experiment_spec_service import _validate_rows

    _validate_rows(spec, rows, "train", root)
    if any(a != b for a, b in zip_longest(actual, iter_rows(rows, root))):
        raise ValueError("Effective training rows do not match the saved model")
    document = json.loads(contained_path(root, saved.artifact_uri).read_text(encoding="utf-8"))
    if document.get("training_rows") != rows.count:
        raise ValueError("Payload training row count mismatch")


async def load_model_instance(
    session: AsyncSession,
    *,
    model_id: UUID,
    artifact_root: Path,
    expected_model_type: str | None = None,
) -> LoadedModelInstance:
    path = _checked_model_file(artifact_root, f"models/{model_id}.manifest.json", optional=True)
    from app.services.tcn_platform_adapter import find_tcn_run, verify_tcn_model
    from app.services.timexer_platform_adapter import find_timexer_run, verify_timexer_model
    from app.services.xgboost_platform_adapter import find_xgboost_run, verify_xgboost_model

    manifest = _read_manifest(path) if path is not None else None
    if manifest is not None and manifest.model_id != model_id:
        raise ModelArtifactError("MODEL_ID_MISMATCH", "Manifest model_id mismatch")
    if manifest is not None and expected_model_type not in (None, manifest.model_type_id):
        raise ModelArtifactError("MODEL_TYPE_MISMATCH", "Unexpected model type")
    if isinstance(manifest, TimeXerModelArtifactManifest):
        _, saved_timexer = await verify_timexer_model(
            session,
            model_id=model_id,
            training_run_id=manifest.training_run_id,
            artifact_root=artifact_root,
            manifest=manifest,
        )
        return LoadedModelInstance(
            model_id=model_id,
            model_type_id="timexer",
            training_run_id=manifest.training_run_id,
            origin="native_manifest",
            manifest=manifest,
            payload=saved_timexer,
        )
    if isinstance(manifest, TCNModelArtifactManifest):
        _, saved_tcn = await verify_tcn_model(
            session,
            model_id=model_id,
            training_run_id=manifest.training_run_id,
            artifact_root=artifact_root,
            manifest=manifest,
        )
        return LoadedModelInstance(
            model_id=model_id,
            model_type_id="tcn",
            training_run_id=manifest.training_run_id,
            origin="native_manifest",
            manifest=manifest,
            payload=saved_tcn,
        )
    if isinstance(manifest, XGBoostModelArtifactManifest):
        _, saved_xgboost = await verify_xgboost_model(
            session,
            model_id=model_id,
            training_run_id=manifest.training_run_id,
            artifact_root=artifact_root,
            manifest=manifest,
        )
        return LoadedModelInstance(
            model_id=model_id,
            model_type_id="xgboost",
            training_run_id=manifest.training_run_id,
            origin="native_manifest",
            manifest=manifest,
            payload=saved_xgboost,
        )
    timexer_run = await find_timexer_run(session, model_id)
    if timexer_run is not None:
        if manifest is not None or expected_model_type not in (None, "timexer"):
            raise ModelArtifactError("MODEL_TYPE_MISMATCH", "Unexpected TimeXer training identity")
        if timexer_run.status != "succeeded":
            raise ModelArtifactError(
                "TRAINING_RUN_NOT_SUCCEEDED", "TimeXer training did not succeed"
            )
        raise ModelArtifactError(
            "MANIFEST_NOT_PUBLISHED", "TimeXer Manifest has not been published"
        )
    tcn_run = await find_tcn_run(session, model_id)
    if tcn_run is not None:
        if manifest is not None or expected_model_type not in (None, "tcn"):
            raise ModelArtifactError("MODEL_TYPE_MISMATCH", "Unexpected TCN training identity")
        if tcn_run.status != "succeeded":
            raise ModelArtifactError("TRAINING_RUN_NOT_SUCCEEDED", "TCN training did not succeed")
        raise ModelArtifactError("MANIFEST_NOT_PUBLISHED", "TCN Manifest has not been published")

    xgboost_run = await find_xgboost_run(session, model_id)
    if xgboost_run is not None:
        if manifest is not None or expected_model_type in ("tcn", "timexer"):
            raise ModelArtifactError(
                "MODEL_TYPE_MISMATCH", "Manifest conflicts with the training model type"
            )
        if xgboost_run.status != "succeeded":
            raise ModelArtifactError(
                "TRAINING_RUN_NOT_SUCCEEDED", "XGBoost training did not succeed"
            )
        raise ModelArtifactError(
            "MANIFEST_NOT_PUBLISHED", "XGBoost Manifest has not been published"
        )

    if manifest is None and expected_model_type == "timexer":
        raise ModelArtifactError("TRAINING_RUN_MISSING", "TimeXer training record is missing")
    if manifest is None and expected_model_type == "tcn":
        raise ModelArtifactError("TRAINING_RUN_MISSING", "TCN training record is missing")
    if manifest is None and expected_model_type == "xgboost":
        raise ModelArtifactError("TRAINING_RUN_MISSING", "XGBoost training record is missing")
    if manifest is not None:
        if manifest.model_type_id == "pls":
            return await _load_pls_instance(
                session,
                model_id=model_id,
                manifest=manifest,
                root=artifact_root,
            )
        if manifest.payload_uri != f"models/{model_id}.json":
            raise ValueError("Manifest identity or payload URI mismatch")
        get_model(manifest.model_type_id)
    else:
        pls = _checked_model_file(artifact_root, f"models/pls/{model_id}.json", optional=True)
        if pls is not None:
            raise ModelArtifactError(
                "MANIFEST_NOT_PUBLISHED",
                "PLS Manifest has not been published; v1 is supported by its independent loader only",
            )
    document, payload_digest = _read_payload(artifact_root, model_id)
    if manifest is not None:
        if payload_digest != manifest.payload_sha256:
            raise ValueError("Model payload SHA256 mismatch")
        if spec_hash(manifest.experiment_spec) != manifest.experiment_spec_hash:
            raise ValueError("Experiment contract SHA256 mismatch")
        if manifest.experiment_spec.leakage.status != "unknown":
            raise ValueError("Stage 1A cannot certify preprocessing leakage claims")
    # Retain the legacy reader, with all file checks completed before it is called.
    saved = load_saved_arx_model(model_id=model_id, artifact_root=artifact_root)
    definition = get_model(saved.payload.model_type.lower())
    run = await _training_run(session, saved)
    missing = list(_training_result_gaps(run, document))
    if manifest is not None:
        if (
            manifest.model_type_id != definition.model_type_id
            or manifest.implementation_id != definition.implementation_id
        ):
            raise ValueError("Manifest model implementation mismatch")
        if run is None or manifest.training_run_id != run.id:
            raise ValueError("Manifest training_run_id mismatch")
        bound = await bind_experiment_spec(
            session, spec=manifest.experiment_spec, artifact_root=artifact_root
        )
        _validate_payload_spec(saved, bound, artifact_root)
        await _validate_effective_rows(
            session, saved, bound, manifest.effective_training_rows, artifact_root
        )
        if manifest.implementation_version == "legacy-unknown":
            missing.append("training_implementation_version")
    else:
        missing.extend(
            ("training_implementation_version", "training_dataset_sha256", "experiment_spec")
        )
        if run is None:
            missing.append("training_run_id")
    return LoadedModelInstance(
        model_id=model_id,
        model_type_id=definition.model_type_id,
        training_run_id=run.id if run else None,
        origin="native_manifest" if manifest else "legacy",
        manifest=manifest,
        payload=saved,
        missing_provenance=tuple(missing),
    )


class ModelArtifactError(ValueError):
    """Stable distinctions for publication and unified PLS loading failures."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _read_manifest(path: Path) -> ModelArtifactManifest:
    try:
        document = json.loads(path.read_bytes())
    except (ValueError, UnicodeError) as error:
        raise ModelArtifactError("MANIFEST_INVALID", "Manifest JSON is damaged") from error
    if not isinstance(document, dict):
        raise ModelArtifactError("MANIFEST_INVALID", "Manifest must be an object")
    version = document.get("manifest_version", 1)
    if type(version) is not int or version != 1:
        raise ModelArtifactError("MANIFEST_VERSION_UNSUPPORTED", "Unsupported Manifest version")
    kind = document.get("model_type_id")
    if kind == "xgboost":
        model: type[ModelArtifactManifest] = XGBoostModelArtifactManifest
    elif kind == "tcn":
        model = TCNModelArtifactManifest
    elif kind == "timexer":
        model = TimeXerModelArtifactManifest
    elif kind == "pls":
        model = PLSModelArtifactManifest
    elif kind in ("arx", "fir", "oe"):
        model = ModelArtifactManifest
    else:
        raise ModelArtifactError("MODEL_TYPE_UNSUPPORTED", "Unsupported Manifest model type")
    try:
        return model.model_validate(document)
    except ValueError as error:
        raise ModelArtifactError(
            "MANIFEST_INVALID", "Manifest schema or payload format is invalid"
        ) from error


async def _verified_pls(
    session: AsyncSession, model_id: UUID, root: Path
) -> tuple[SavedPLSModel, str]:
    from app.services.pls_artifact_service import read_pls_artifact
    from app.services.pls_training_service import load_persisted_pls_model

    path = _checked_model_file(root, f"models/pls/{model_id}.json", optional=True)
    if path is None:
        raise ModelArtifactError("PAYLOAD_MISSING", "PLS JSON payload is missing")
    try:
        preliminary, digest = read_pls_artifact(model_id=model_id, artifact_root=root)
    except ValueError as error:
        npz = _checked_model_file(root, f"models/pls/{model_id}.npz", optional=True)
        code = "PLS_PAYLOAD_INVALID"
        if npz is None:
            code = "PLS_NPZ_MISSING"
        elif "NPZ" in str(error) or "NPY" in str(error):
            code = "PLS_NPZ_INVALID"
        raise ModelArtifactError(code, str(error)) from error
    if not isinstance(preliminary.metadata, PLSBoundArtifactMetadata):
        raise ModelArtifactError("PLS_PROVENANCE_REQUIRED", "PLS Manifest requires a v2 payload")
    source = preliminary.metadata.provenance
    with session.no_autoflush:
        run = await session.get(ProcessingRun, source.training_run_id, populate_existing=True)
        if run is None:
            raise ModelArtifactError("TRAINING_RUN_MISSING", "PLS training record is missing")
        if run.status != "succeeded":
            raise ModelArtifactError(
                "TRAINING_RUN_NOT_SUCCEEDED", "PLS training record is not succeeded"
            )
        if run.run_type != "modeling.pls":
            raise ModelArtifactError("TRAINING_RUN_TYPE_MISMATCH", "PLS training run_type mismatch")
        if run.result.get("model_id") != str(model_id):
            raise ModelArtifactError("MODEL_ID_MISMATCH", "PLS training record model_id mismatch")
        if (run.dataset_id, run.source_version_id) != (
            source.experiment_spec.dataset_id,
            source.experiment_spec.dataset_version_id,
        ):
            raise ModelArtifactError(
                "DATASET_VERSION_MISMATCH", "PLS training dataset/version mismatch"
            )
        # The existing service owns all detailed result, Spec, SHA and duplicate-run checks.
        try:
            saved = await load_persisted_pls_model(session, model_id=model_id, artifact_root=root)
        except ValueError as error:
            raise ModelArtifactError("PLS_SOURCE_INVALID", str(error)) from error
        if (
            saved.metadata != preliminary.metadata
            or run.result.get("artifact", {}).get("json_sha256") != digest
        ):
            raise ModelArtifactError("PAYLOAD_SHA_MISMATCH", "PLS JSON changed during validation")
    return saved, digest


def _pls_manifest(saved: SavedPLSModel, digest: str) -> PLSModelArtifactManifest:
    metadata = saved.metadata
    if not isinstance(metadata, PLSBoundArtifactMetadata):
        raise ModelArtifactError("PLS_PROVENANCE_REQUIRED", "PLS v2 provenance is required")
    source = metadata.provenance
    return PLSModelArtifactManifest(
        model_id=metadata.model_id,
        training_run_id=source.training_run_id,
        implementation_id=metadata.implementation_id,
        implementation_version=metadata.implementation_version,
        experiment_spec=source.experiment_spec,
        experiment_spec_hash=source.experiment_spec_hash,
        effective_training_rows=source.effective_training_rows,
        payload_uri=f"models/pls/{metadata.model_id}.json",
        payload_sha256=digest,
    )


async def build_pls_manifest(
    session: AsyncSession,
    *,
    model_id: UUID,
    artifact_root: Path,
) -> PLSModelArtifactManifest:
    saved, digest = await _verified_pls(session, model_id, artifact_root)
    return _pls_manifest(saved, digest)


def _existing_manifest(root: Path, expected: ModelArtifactManifest) -> bool:
    path = _checked_model_file(root, f"models/{expected.model_id}.manifest.json", optional=True)
    if path is None:
        return False
    actual = _read_manifest(path)
    if actual.model_dump(mode="json") != expected.model_dump(mode="json"):
        raise ModelArtifactError(
            "MANIFEST_CONFLICT", "Manifest publication conflict; existing file retained"
        )
    return True


async def publish_pls_manifest(
    session: AsyncSession,
    *,
    model_id: UUID,
    artifact_root: Path,
) -> PLSModelArtifactManifest:
    """Publish only a verified, already succeeded model; no database writes."""
    manifest = await build_pls_manifest(session, model_id=model_id, artifact_root=artifact_root)
    publish_verified_manifest(artifact_root, manifest)
    return manifest


def publish_verified_manifest(artifact_root: Path, manifest: ModelArtifactManifest) -> None:
    """Publish a caller-verified sidecar exclusively and accept identical retries."""
    if _existing_manifest(artifact_root, manifest):
        return
    root = artifact_root.resolve()
    directory = root / "models"
    if (
        directory.is_symlink()
        or not directory.is_dir()
        or not directory.resolve().is_relative_to(root)
    ):
        raise ModelArtifactError("MANIFEST_PATH_INVALID", "Unsafe Manifest publication directory")
    target = directory / f"{manifest.model_id}.manifest.json"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=directory, suffix=".manifest.tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(manifest.model_dump_json(indent=2).encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            if not _existing_manifest(artifact_root, manifest):
                raise ModelArtifactError(
                    "MANIFEST_CONFLICT", "Manifest publication conflict"
                ) from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


async def _load_pls_instance(
    session: AsyncSession,
    *,
    model_id: UUID,
    manifest: ModelArtifactManifest,
    root: Path,
) -> LoadedModelInstance:
    get_model("pls")
    if manifest.payload_uri != f"models/pls/{model_id}.json":
        raise ModelArtifactError("PAYLOAD_URI_MISMATCH", "PLS Manifest payload URI mismatch")
    path = _checked_model_file(root, manifest.payload_uri, optional=True)
    if path is None:
        raise ModelArtifactError("PAYLOAD_MISSING", "PLS JSON payload is missing")
    if hashlib.sha256(path.read_bytes()).hexdigest() != manifest.payload_sha256:
        raise ModelArtifactError("PAYLOAD_SHA_MISMATCH", "PLS JSON SHA256 mismatch")
    if spec_hash(manifest.experiment_spec) != manifest.experiment_spec_hash:
        raise ModelArtifactError(
            "EXPERIMENT_SPEC_MISMATCH", "Manifest Experiment Spec SHA256 mismatch"
        )
    saved, digest = await _verified_pls(session, model_id, root)
    expected = _pls_manifest(saved, digest)
    for field, code in (
        ("training_run_id", "TRAINING_RUN_ID_MISMATCH"),
        ("implementation_id", "IMPLEMENTATION_MISMATCH"),
        ("implementation_version", "IMPLEMENTATION_MISMATCH"),
        ("experiment_spec", "EXPERIMENT_SPEC_MISMATCH"),
        ("experiment_spec_hash", "EXPERIMENT_SPEC_MISMATCH"),
        ("effective_training_rows", "TRAINING_ROWS_MISMATCH"),
        ("payload_sha256", "PAYLOAD_SHA_MISMATCH"),
    ):
        if getattr(manifest, field) != getattr(expected, field):
            raise ModelArtifactError(code, f"PLS Manifest {field} mismatch")
    return LoadedModelInstance(
        model_id=model_id,
        model_type_id="pls",
        training_run_id=expected.training_run_id,
        origin="native_manifest",
        manifest=manifest,
        payload=saved,
    )
