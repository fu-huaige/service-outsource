"""No-estimator tests of new manifests and unchanged legacy model JSON."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.models.dataset import Dataset, DatasetColumn, DatasetVersion, ProcessingRun
from app.schemas.experiment_spec import ExperimentSpec, RowSet
from app.schemas.model_catalog import ModelArtifactManifest
from app.schemas.modeling import ArxFitRequest
from app.services import modeling_service
from app.services.experiment_spec_service import spec_hash
from app.services.model_artifact_service import build_model_manifest, load_model_instance


@pytest.fixture
def saved(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Read-only model loading must not fit")

    for name in ("fit_arx_core", "fit_arx_on_version", "estimate_parameters", "fit_multihorizon"):
        monkeypatch.setattr(modeling_service, name, forbidden)
    dataset_id, version_id, model_id, run_id = (uuid4() for _ in range(4))
    raw = (
        "timestamp,u,y\n"
        + "".join(
            f"{(datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=i)).isoformat()},{i},{2 * i + 1}\n"
            for i in range(30)
        )
    ).encode()
    (tmp_path / "source.csv").write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    request = ArxFitRequest(
        version_id=version_id,
        dataset_id=dataset_id,
        input_columns=["u"],
        output_column="y",
        na=1,
        nb={"u": 1},
        delays={"u": 0},
    )
    artifact = {
        "model_id": str(model_id),
        "dataset_id": str(dataset_id),
        "version_id": str(version_id),
        "configuration": request.model_dump(mode="json"),
        "coefficients": {"a1": -0.5, "b_u_0": 0.4},
        "intercept": 0.0,
        "preprocessing": {},
        "training_rows": 16,
    }
    (tmp_path / "models").mkdir()
    payload_path = tmp_path / "models" / f"{model_id}.json"
    payload_path.write_text(json.dumps(artifact), encoding="utf-8")
    run = ProcessingRun(
        id=run_id,
        dataset_id=dataset_id,
        source_version_id=version_id,
        run_type="modeling.arx",
        status="succeeded",
        parameters=request.model_dump(mode="json"),
        result={
            "model_id": str(model_id),
            **json.loads(
                json.dumps(
                    {
                        k: artifact[k]
                        for k in ("coefficients", "intercept", "preprocessing", "training_rows")
                    }
                )
            ),
        },
    )
    objects = {
        (Dataset, dataset_id): Dataset(id=dataset_id, name="test", encoding="utf-8", delimiter=","),
        (DatasetVersion, version_id): DatasetVersion(
            id=version_id,
            dataset_id=dataset_id,
            row_count=30,
            sha256=digest,
            artifact_path="source.csv",
            parameters={},
        ),
    }
    runs = [run]
    columns = [DatasetColumn(name="u", role="input"), DatasetColumn(name="y", role="output")]

    class Session:
        async def get(self, cls, key):
            if cls is ProcessingRun:
                return next((r for r in runs if r.id == key), None)
            return objects.get((cls, key))

        async def scalars(self, statement):
            table = statement.column_descriptions[0]["entity"]
            return SimpleNamespace(all=lambda: runs if table is ProcessingRun else columns)

    spec = ExperimentSpec.model_validate(
        {
            "task_type": "dynamic_system_identification",
            "dataset_id": dataset_id,
            "dataset_version_id": version_id,
            "dataset_version_sha256": digest,
            "row_count": 30,
            "input_columns": ["u"],
            "target_column": "y",
            "time_axis": {
                "column": "timestamp",
                "sample_period_seconds": 1,
                "sampling_status": "uniform",
            },
            "continuous_runs": [{"start": 0, "stop": 30}],
            "feature_spec": {
                "kind": "dynamic_lags",
                "input_lags": {"u": [0]},
                "target_lags": [1],
                "history_window": 1,
            },
            "split": {
                "train": [{"start": 0, "stop": 18}],
                "validation": [{"start": 18, "stop": 24}],
                "test": [{"start": 24, "stop": 30}],
                "history_guard": 1,
            },
        }
    )
    return SimpleNamespace(
        root=tmp_path,
        session=Session(),
        model_id=model_id,
        run=run,
        runs=runs,
        spec=spec,
        artifact=artifact,
        payload_path=payload_path,
    )


def load(saved):
    return asyncio.run(
        load_model_instance(saved.session, model_id=saved.model_id, artifact_root=saved.root)
    )


def manifest(saved):
    return asyncio.run(
        build_model_manifest(
            saved.session,
            model_id=saved.model_id,
            spec=saved.spec,
            artifact_root=saved.root,
            effective_training_rows=RowSet.model_validate({"ranges": [{"start": 1, "stop": 17}]}),
        )
    )


def sidecar(saved, data):
    path = saved.root / "models" / f"{saved.model_id}.manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")


def test_legacy_loading_does_not_write_or_fit(saved):
    before = saved.payload_path.read_bytes()
    result = load(saved)
    assert result.origin == "legacy" and result.manifest is None
    assert result.model_id != result.training_run_id == saved.run.id
    assert saved.payload_path.read_bytes() == before
    assert not (saved.root / "models" / f"{saved.model_id}.manifest.json").exists()


def test_build_and_read_manifest_without_changing_payload(saved):
    before = saved.payload_path.read_bytes()
    result = manifest(saved)
    assert result.implementation_version == "legacy-unknown"
    assert result.experiment_spec.leakage.status == "unknown"
    assert result.experiment_spec_hash == spec_hash(result.experiment_spec)
    sidecar(saved, result.model_dump(mode="json"))
    loaded = load(saved)
    assert loaded.origin == "native_manifest"
    assert loaded.payload.model_id == saved.model_id
    assert saved.payload_path.read_bytes() == before


@pytest.mark.parametrize(
    "change", ["broken_json", "model_id", "training_run_id", "digest", "leakage", "implementation"]
)
def test_corrupt_manifest_never_falls_back(saved, change):
    data = manifest(saved).model_dump(mode="json")
    if change == "broken_json":
        path = saved.root / "models" / f"{saved.model_id}.manifest.json"
        path.write_text("{", encoding="utf-8")
    else:
        if change in ("model_id", "training_run_id"):
            data[change] = str(uuid4())
        elif change == "digest":
            data["payload_sha256"] = "0" * 64
        elif change == "leakage":
            data["experiment_spec"]["leakage"]["status"] = "verified_train_only"
            data["experiment_spec_hash"] = spec_hash(
                ExperimentSpec.model_validate(data["experiment_spec"])
            )
        else:
            data["implementation_id"] = "arbitrary.module"
        sidecar(saved, data)
    with pytest.raises(ValueError):
        load(saved)


def test_missing_and_ambiguous_runs_are_not_guessed(saved):
    saved.runs.clear()
    assert load(saved).training_run_id is None
    with pytest.raises(ValueError, match="exact training run"):
        manifest(saved)
    saved.runs.extend([saved.run, saved.run])
    with pytest.raises(ValueError, match="Ambiguous"):
        load(saved)


def test_exact_run_parameters_and_effective_rows_are_checked(saved):
    saved.run.parameters = {**saved.run.parameters, "na": 2}
    with pytest.raises(ValueError):
        load(saved)
    saved.run.parameters = saved.artifact["configuration"]
    with pytest.raises(ValueError, match="Effective"):
        asyncio.run(
            build_model_manifest(
                saved.session,
                model_id=saved.model_id,
                spec=saved.spec,
                artifact_root=saved.root,
                effective_training_rows=RowSet.model_validate(
                    {"ranges": [{"start": 2, "stop": 17}]}
                ),
            )
        )


@pytest.mark.parametrize("family", ["ARX", "FIR", "OE"])
def test_all_existing_payload_families_dispatch_through_old_loader(saved, family):
    config = dict(saved.artifact["configuration"])
    config["model_type"] = family
    coefficients = dict(saved.artifact["coefficients"])
    if family == "FIR":
        config["na"] = 0
        coefficients.pop("a1")
    if family == "OE":
        config["estimator"] = "ridge"
        config["ridge_alpha"] = 0.001
    saved.artifact.update(configuration=config, coefficients=coefficients)
    saved.payload_path.write_text(json.dumps(saved.artifact), encoding="utf-8")
    saved.run.parameters = config
    saved.run.result = {**saved.run.result, "coefficients": coefficients}
    assert load(saved).model_type_id == family.lower()


def test_old_missing_defaults_remain_supported(saved):
    for field in ("model_type", "fit_intercept", "standardize"):
        saved.artifact["configuration"].pop(field)
    saved.run.parameters = dict(saved.artifact["configuration"])
    saved.payload_path.write_text(json.dumps(saved.artifact), encoding="utf-8")
    assert load(saved).payload.intercept == 0.0


def test_manifest_schema_rejects_extra_fields(saved):
    with pytest.raises(ValueError):
        ModelArtifactManifest.model_validate(manifest(saved).model_dump() | {"router": "forbidden"})


def test_multirange_contract_is_not_claimed_as_executed_by_legacy_arx(saved):
    data = saved.spec.model_dump()
    data["split"]["train"] = [{"start": 0, "stop": 8}, {"start": 10, "stop": 18}]
    saved.spec = ExperimentSpec.model_validate(data)
    with pytest.raises(ValueError, match="single chronological split"):
        manifest(saved)


def test_payload_training_count_is_verified(saved):
    saved.artifact["training_rows"] = 999
    saved.payload_path.write_text(json.dumps(saved.artifact), encoding="utf-8")
    with pytest.raises(ValueError, match="row count"):
        manifest(saved)


def _qa_symlink(link, target):
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"Symbolic links unavailable: {error}")


@pytest.mark.parametrize("entry", ["load", "build"])
def test_qa_external_payload_is_rejected_before_legacy_reader(saved, monkeypatch, entry):
    from app.services import model_artifact_service

    outside = saved.root.parent / f"{uuid4()}.json"
    outside.write_bytes(saved.payload_path.read_bytes())
    saved.payload_path.unlink()
    _qa_symlink(saved.payload_path, outside)

    def forbidden_reader(**kwargs):
        pytest.fail("Legacy reader must not see an unchecked path")

    monkeypatch.setattr(model_artifact_service, "load_saved_arx_model", forbidden_reader)
    with pytest.raises(ValueError):
        load(saved) if entry == "load" else manifest(saved)


@pytest.mark.parametrize("kind", ["external", "dangling"])
def test_qa_invalid_manifest_link_never_falls_back(saved, monkeypatch, kind):
    from app.services import model_artifact_service

    link = saved.root / "models" / f"{saved.model_id}.manifest.json"
    target = (
        saved.root.parent / f"{uuid4()}.json"
        if kind == "external"
        else saved.root / "models" / "missing.json"
    )
    if kind == "external":
        target.write_text("{}", encoding="utf-8")
    _qa_symlink(link, target)

    def forbidden_reader(**kwargs):
        pytest.fail("Invalid manifest must not enter legacy loading")

    monkeypatch.setattr(model_artifact_service, "load_saved_arx_model", forbidden_reader)
    with pytest.raises(ValueError):
        load(saved)


@pytest.mark.parametrize(
    "uri",
    ["../outside.json", "/tmp/outside.json", "file:///outside.json", "models/../outside.json"],
)
def test_qa_payload_uri_is_rejected(saved, uri):
    data = manifest(saved).model_dump(mode="json")
    data["payload_uri"] = uri
    sidecar(saved, data)
    with pytest.raises(ValueError):
        load(saved)


@pytest.mark.parametrize("kind", ["directory", "missing", "dangling"])
def test_qa_payload_must_be_an_existing_regular_file(saved, kind):
    saved.payload_path.unlink()
    if kind == "directory":
        saved.payload_path.mkdir()
    elif kind == "dangling":
        _qa_symlink(saved.payload_path, saved.root / "models" / "absent.json")
    with pytest.raises(ValueError):
        load(saved)


@pytest.mark.parametrize(
    "field,bad",
    [
        ("coefficients", {"a1": 9.2, "b_u_0": 8.3}),
        ("coefficients", {"a1": [-0.5], "b_u_0": 0.4}),
        ("intercept", 0.5),
        ("preprocessing", {"output_center": [1.0, 2.0]}),
        ("training_rows", 99),
    ],
)
def test_qa_training_result_mismatch_rejects_manifest(saved, field, bad):
    saved.run.result = {**saved.run.result, field: bad}
    with pytest.raises(ValueError, match="mismatch"):
        manifest(saved)


def test_qa_training_result_numeric_tolerance_and_nested_shapes(saved):
    saved.run.result["coefficients"]["a1"] += 1e-12
    assert manifest(saved).training_run_id == saved.run.id
    saved.run.result["preprocessing"] = {"scale": [1.0, 2.0]}
    saved.artifact["preprocessing"] = {"scale": [[1.0, 2.0]]}
    saved.payload_path.write_text(json.dumps(saved.artifact), encoding="utf-8")
    with pytest.raises(ValueError, match="mismatch"):
        manifest(saved)


@pytest.mark.parametrize("field", ["coefficients", "intercept", "preprocessing", "training_rows"])
def test_qa_missing_historical_run_evidence_stays_incomplete(saved, field):
    saved.run.result.pop(field)
    loaded = load(saved)
    assert f"training_result.{field}" in loaded.missing_provenance
    with pytest.raises(ValueError, match="incomplete"):
        manifest(saved)


def test_qa_missing_payload_evidence_stays_incomplete(saved):
    saved.artifact.pop("preprocessing")
    saved.payload_path.write_text(json.dumps(saved.artifact), encoding="utf-8")
    assert "payload.preprocessing" in load(saved).missing_provenance
    with pytest.raises(ValueError, match="incomplete"):
        manifest(saved)


def test_qa_wrong_model_id_is_not_guessed(saved):
    saved.run.result["model_id"] = str(uuid4())
    assert load(saved).training_run_id is None
    with pytest.raises(ValueError, match="exact training run"):
        manifest(saved)


def test_qa_real_sqlite_filters_training_identity(saved):
    from app.models import Base
    from app.services.model_artifact_service import _training_run
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    async def exercise():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            factory = async_sessionmaker(engine, expire_on_commit=False)
            async with factory() as session:
                common = dict(
                    dataset_id=saved.spec.dataset_id,
                    source_version_id=saved.spec.dataset_version_id,
                    run_type="modeling.arx",
                    status="succeeded",
                    parameters=saved.run.parameters,
                    result=saved.run.result,
                )
                valid = ProcessingRun(id=saved.run.id, **common)
                session.add(valid)
                for patch in (
                    {"dataset_id": uuid4()},
                    {"source_version_id": uuid4()},
                    {"run_type": "modeling.arx_evaluation"},
                    {"result": {"model_id": str(uuid4())}},
                ):
                    session.add(ProcessingRun(id=uuid4(), **(common | patch)))
                await session.commit()
                payload = modeling_service.load_saved_arx_model(
                    model_id=saved.model_id, artifact_root=saved.root
                )
                assert (await _training_run(session, payload)).id == valid.id
                session.add(ProcessingRun(id=uuid4(), **common))
                await session.commit()
                with pytest.raises(ValueError, match="Ambiguous"):
                    await _training_run(session, payload)
        finally:
            await engine.dispose()

    asyncio.run(exercise())
