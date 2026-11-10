"""Version-bound PLS training and durable run identity in isolated SQLite."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import numpy as np
import pytest
import pytest_asyncio
from app.models import Base
from app.models.dataset import Dataset, DatasetColumn, DatasetVersion, ProcessingRun
from app.schemas.experiment_spec import ExperimentSpec
from app.schemas.pls import PLSParameters
from app.services import pls_training_service as training
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def data(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'runs.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    dataset_id, version_id, latest_id = uuid4(), uuid4(), uuid4()
    rng = np.random.default_rng(93)
    x = rng.normal(size=(40, 2)) * [2, 10] + [5, -8]
    y = x @ [3, -0.7] + 2 + rng.normal(0, 0.05, 40)
    start = datetime(2026, 1, 1, tzinfo=UTC)

    def csv(offset=0):
        lines = ["timestamp,a,b,quality"]
        for i in range(40):
            time = start + timedelta(seconds=i if i < 12 else i - 12)
            lines.append(
                f"{time.isoformat()},{x[i, 0] + offset},{x[i, 1] + offset},{y[i] + offset}"
            )
        return ("\n".join(lines) + "\n").encode()

    raw, latest = csv(), csv(500)
    (tmp_path / "source.csv").write_bytes(raw)
    (tmp_path / "latest.csv").write_bytes(latest)
    digest = hashlib.sha256(raw).hexdigest()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        session.add(
            Dataset(
                id=dataset_id,
                name="PLS test",
                raw_sha256=digest,
                raw_path="source.csv",
                byte_size=len(raw),
                encoding="utf-8",
                delimiter=",",
                active_version_id=latest_id,
            )
        )
        for identity, name, content in (
            (version_id, "source.csv", raw),
            (latest_id, "latest.csv", latest),
        ):
            session.add(
                DatasetVersion(
                    id=identity,
                    dataset_id=dataset_id,
                    name=name,
                    artifact_path=name,
                    sha256=hashlib.sha256(content).hexdigest(),
                    row_count=40,
                    column_count=4,
                    parameters={},
                )
            )
            for pos, (column, role) in enumerate(
                (("timestamp", "time"), ("a", "input"), ("b", "input"), ("quality", "output"))
            ):
                session.add(
                    DatasetColumn(
                        dataset_id=dataset_id,
                        version_id=identity,
                        position=pos,
                        name=column,
                        inferred_type="datetime" if pos == 0 else "float",
                        role=role,
                    )
                )
        await session.commit()
    spec = ExperimentSpec.model_validate(
        {
            "task_type": "supervised_regression",
            "application": "soft_sensor",
            "dataset_id": dataset_id,
            "dataset_version_id": version_id,
            "dataset_version_sha256": digest,
            "row_count": 40,
            "input_columns": ["b", "a"],
            "target_column": "quality",
            "time_axis": {
                "column": "timestamp",
                "sampling_status": "uniform",
                "sample_period_seconds": 1,
            },
            "continuous_runs": [{"start": 0, "stop": 12}, {"start": 12, "stop": 40}],
            "feature_spec": {"kind": "tabular"},
            "split": {
                "train": [{"start": 0, "stop": 12}, {"start": 12, "stop": 24}],
                "validation": [{"start": 24, "stop": 32}],
                "test": [{"start": 32, "stop": 40}],
            },
            "evaluation": {"prediction_modes": ["prediction"]},
        }
    )
    yield {"factory": factory, "root": tmp_path, "spec": spec, "x": x, "y": y, "latest": latest_id}
    await engine.dispose()


async def fit(data, spec=None):
    return await training.fit_pls_on_version(
        data["factory"],
        spec=spec or data["spec"],
        artifact_root=data["root"],
        parameters=PLSParameters(),
    )


async def runs(data):
    async with data["factory"]() as session:
        return list((await session.scalars(select(ProcessingRun))).all())


def modified(data, mutate):
    document = data["spec"].model_dump(mode="json")
    mutate(document)
    return ExperimentSpec.model_validate(document)


async def test_real_training_uses_exact_version_order_and_train_rows(data, monkeypatch):
    original = training.fit_pls_core
    calls = []

    def observed(x, y, **kwargs):
        calls.append((x.copy(), y.copy(), kwargs))
        return original(x, y, **kwargs)

    monkeypatch.setattr(training, "fit_pls_core", observed)
    model = await fit(data)
    metadata = model.metadata
    assert metadata.artifact_version == 2
    assert metadata.model_id != metadata.provenance.training_run_id
    assert len(calls) == 1
    np.testing.assert_array_equal(calls[0][0], data["x"][:24, ::-1])
    np.testing.assert_array_equal(calls[0][1], data["y"][:24])
    assert calls[0][2]["feature_names"] == ("b", "a")
    assert [(r.start, r.stop) for r in metadata.provenance.effective_training_rows.ranges] == [
        (0, 12),
        (12, 24),
    ]
    records = await runs(data)
    assert len(records) == 1
    run = records[0]
    assert run.id == metadata.provenance.training_run_id
    assert run.status == "succeeded" and run.run_type == "modeling.pls"
    assert run.source_version_id == data["spec"].dataset_version_id
    assert run.result["training_rows"] == 24
    assert run.result["evaluation_status"] == "not_evaluated"
    assert "evaluated_rows" not in run.result
    assert "coefficients" not in run.result
    assert run.parameters["experiment_spec"]["leakage"]["status"] == "unknown"

    def forbidden(*args, **kwargs):
        raise AssertionError("Persisted loading must not train")

    monkeypatch.setattr(training, "fit_pls_core", forbidden)
    async with data["factory"]() as session:
        loaded = await training.load_persisted_pls_model(
            session, model_id=metadata.model_id, artifact_root=data["root"]
        )
    np.testing.assert_array_equal(
        loaded.predict(data["x"][:, ::-1]), model.predict(data["x"][:, ::-1])
    )


@pytest.mark.parametrize(
    "field",
    ["dataset_id", "dataset_version_id", "dataset_version_sha256", "target_column", "row_count"],
)
async def test_invalid_identity_rejected_before_fit(data, monkeypatch, field):
    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid source must fail before fit")

    monkeypatch.setattr(training, "fit_pls_core", forbidden)
    value = (
        uuid4()
        if field.endswith("_id")
        else {
            "dataset_version_sha256": "0" * 64,
            "target_column": "b",
            "row_count": 41,
        }.get(field)
    )
    with pytest.raises(ValueError):
        await fit(data, modified(data, lambda d: d.update({field: value})))
    assert await runs(data) == []


@pytest.mark.parametrize(
    "change", ["history", "lag", "initialization", "mode", "application", "kind"]
)
async def test_pls_specific_contract_is_rejected(data, change):
    def mutate(d):
        if change == "history":
            d["feature_spec"]["history_window"] = 1
        elif change == "lag":
            d["feature_spec"].update(input_lags={"a": [1]}, history_window=1)
        elif change == "initialization":
            d["feature_spec"]["initialization_policy"] = "past_residual"
        elif change == "mode":
            d["evaluation"]["prediction_modes"] = ["free_run"]
        elif change == "application":
            d["application"] = None
        elif change == "kind":
            d["feature_spec"]["kind"] = "dynamic_lags"

    with pytest.raises(ValueError):
        await fit(data, modified(data, mutate))
    assert await runs(data) == []


async def test_noncontiguous_train_rows_keep_physical_positions(data, monkeypatch):
    spec = modified(
        data,
        lambda d: d["split"].update(train=[{"start": 1, "stop": 8}, {"start": 14, "stop": 24}]),
    )
    original = training.fit_pls_core
    received = []

    def observed(x, y, **kwargs):
        received.append((x.copy(), y.copy()))
        return original(x, y, **kwargs)

    monkeypatch.setattr(training, "fit_pls_core", observed)
    model = await fit(data, spec)
    indices = list(range(1, 8)) + list(range(14, 24))
    np.testing.assert_array_equal(received[0][0], data["x"][indices, ::-1])
    np.testing.assert_array_equal(received[0][1], data["y"][indices])
    assert (
        model.metadata.training_rows
        == model.metadata.provenance.effective_training_rows.count
        == 17
    )


async def test_partition_cannot_cross_restart(data):
    spec = modified(data, lambda d: d["split"].update(train=[{"start": 0, "stop": 24}]))
    with pytest.raises(ValueError, match="continuous run"):
        await fit(data, spec)


@pytest.mark.parametrize("kind", ["blank", "nan", "inf"])
async def test_records_are_not_dropped_to_make_training_succeed(data, kind):
    path = data["root"] / "source.csv"
    text = path.read_text()
    lines = text.splitlines()
    if kind == "blank":
        lines.insert(4, "")
    else:
        values = lines[4].split(",")
        values[1] = "nan" if kind == "nan" else "inf"
        lines[4] = ",".join(values)
    raw = ("\n".join(lines) + "\n").encode()
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    async with data["factory"]() as session:
        version = await session.get(DatasetVersion, data["spec"].dataset_version_id)
        version.sha256 = digest
        await session.commit()
    spec = modified(data, lambda d: d.update(dataset_version_sha256=digest))
    with pytest.raises(ValueError):
        await fit(data, spec)
    assert await runs(data) == []


async def test_source_digest_is_rechecked_after_reading(data, monkeypatch):
    original = training.load_version_series

    async def changed(*args, **kwargs):
        series = await original(*args, **kwargs)
        path = data["root"] / "source.csv"
        path.write_bytes(path.read_bytes() + b"\n")
        return series

    monkeypatch.setattr(training, "load_version_series", changed)
    with pytest.raises(ValueError, match="SHA256"):
        await fit(data)
    assert await runs(data) == []


@pytest.mark.parametrize("stage", ["fit", "save_artifact", "read_artifact"])
async def test_failure_stage_is_durable(data, monkeypatch, stage):
    def fail(*args, **kwargs):
        raise OSError("Injected failure")

    symbol = {
        "fit": "fit_pls_core",
        "save_artifact": "save_pls_artifact",
        "read_artifact": "read_pls_artifact",
    }[stage]
    monkeypatch.setattr(training, symbol, fail)
    with pytest.raises(training.PLSTrainingError) as caught:
        await fit(data)
    records = await runs(data)
    assert len(records) == 1
    assert records[0].id == caught.value.training_run_id
    assert records[0].status == "failed"
    assert records[0].result["failure_stage"] == stage


async def test_initial_run_creation_failure_does_not_fit_or_publish(data, monkeypatch):
    original = AsyncSession.commit

    async def fail_running(self):
        if any(isinstance(item, ProcessingRun) for item in self.new):
            raise OSError("Injected insert commit failure")
        return await original(self)

    monkeypatch.setattr(AsyncSession, "commit", fail_running)
    with pytest.raises(training.PLSTrainingError) as caught:
        await fit(data)
    assert caught.value.stage == "create_run"
    assert await runs(data) == []
    assert not list(data["root"].rglob("*.npz"))


@pytest.mark.parametrize("committed", [False, True])
async def test_uncertain_final_commit_is_reconciled_in_an_independent_session(
    data, monkeypatch, committed
):
    original = AsyncSession.commit
    failed_sessions = []

    async def fail_final(self):
        if any(
            isinstance(item, ProcessingRun) and item.status == "succeeded" for item in self.dirty
        ):
            failed_sessions.append(self)
            if committed:
                await original(self)
            raise OSError("Injected final acknowledgement failure")
        return await original(self)

    monkeypatch.setattr(AsyncSession, "commit", fail_final)
    with pytest.raises(training.PLSTrainingError) as caught:
        await fit(data)
    assert caught.value.stage == "final_commit"
    run = (await runs(data))[0]
    assert run.status == ("succeeded" if committed else "failed")
    assert caught.value.outcome == ("succeeded_confirmed" if committed else "failed")
    assert len(failed_sessions) == 1
    assert (data["root"] / "models" / "pls" / f"{caught.value.model_id}.json").is_file()


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "status",
        "model",
        "version",
        "dataset",
        "parameters",
        "rows",
        "count",
        "json_sha",
        "npz_sha",
        "spec_hash",
    ],
)
async def test_persisted_source_mismatch_is_rejected(data, change):
    model = await fit(data)
    async with data["factory"]() as session:
        run = await session.get(ProcessingRun, model.metadata.provenance.training_run_id)
        if change == "missing":
            await session.delete(run)
        elif change == "status":
            run.status = "running"
        elif change == "version":
            run.source_version_id = data["latest"]
        elif change == "dataset":
            run.dataset_id = uuid4()
        elif change in ("parameters", "spec_hash"):
            params = dict(run.parameters)
            if change == "parameters":
                params["pls_parameters"] = {"n_components": 1, "scale": False}
            else:
                params["experiment_spec_hash"] = "0" * 64
            run.parameters = params
        else:
            result = json.loads(json.dumps(run.result))
            if change == "model":
                result["model_id"] = str(uuid4())
            elif change == "rows":
                result["effective_training_rows"]["ranges"][0]["start"] = 1
            elif change == "count":
                result["training_rows"] += 1
            elif change == "json_sha":
                result["artifact"]["json_sha256"] = "0" * 64
            elif change == "npz_sha":
                result["artifact"]["npz_sha256"] = "0" * 64
            run.result = result
        await session.commit()
    async with data["factory"]() as session:
        with pytest.raises(ValueError):
            await training.load_persisted_pls_model(
                session, model_id=model.metadata.model_id, artifact_root=data["root"]
            )


async def test_duplicate_successful_training_records_are_not_guessed(data):
    model = await fit(data)
    async with data["factory"]() as session:
        run = await session.get(ProcessingRun, model.metadata.provenance.training_run_id)
        session.add(
            ProcessingRun(
                id=uuid4(),
                dataset_id=run.dataset_id,
                source_version_id=run.source_version_id,
                run_type=run.run_type,
                status=run.status,
                parameters=run.parameters,
                result=run.result,
            )
        )
        await session.commit()
    async with data["factory"]() as session:
        with pytest.raises(ValueError, match="Ambiguous"):
            await training.load_persisted_pls_model(
                session, model_id=model.metadata.model_id, artifact_root=data["root"]
            )


async def test_readback_cannot_substitute_another_fitted_model(data, monkeypatch):
    original_save = training.save_pls_artifact
    original_fit = training.fit_pls_core

    def substitute(model, **kwargs):
        wrong = original_fit(
            data["x"][:24, ::-1],
            data["y"][:24] + 100,
            feature_names=("b", "a"),
            target_name="quality",
            parameters=PLSParameters(),
        )
        return original_save(wrong, **kwargs)

    monkeypatch.setattr(training, "save_pls_artifact", substitute)
    with pytest.raises(training.PLSTrainingError):
        await fit(data)
    assert (await runs(data))[0].status == "failed"


async def test_initial_commit_acknowledgement_loss_is_recorded_without_fitting(data, monkeypatch):
    original = AsyncSession.commit

    async def lost_ack(self):
        initial = any(isinstance(item, ProcessingRun) for item in self.new)
        await original(self)
        if initial:
            raise OSError("Initial acknowledgement lost")

    monkeypatch.setattr(AsyncSession, "commit", lost_ack)

    def forbidden(*args, **kwargs):
        raise AssertionError("Must not fit after an uncertain initial commit")

    monkeypatch.setattr(training, "fit_pls_core", forbidden)
    with pytest.raises(training.PLSTrainingError) as caught:
        await fit(data)
    run = (await runs(data))[0]
    assert run.id == caught.value.training_run_id
    assert run.status == "failed" and run.result["failure_stage"] == "create_run"
    assert not list(data["root"].rglob("*.npz"))


async def test_database_unavailable_during_reconciliation_keeps_unconfirmed_run_and_files(
    data, monkeypatch
):
    original = AsyncSession.commit

    async def failed_commit(self):
        if any(
            isinstance(item, ProcessingRun) and item.status == "succeeded" for item in self.dirty
        ):
            raise OSError("Final commit failed")
        return await original(self)

    monkeypatch.setattr(AsyncSession, "commit", failed_commit)
    opened = []

    def factory():
        opened.append(len(opened) + 1)
        if len(opened) == 4:
            raise OSError("Reconciliation database unavailable")
        return data["factory"]()

    with pytest.raises(training.PLSTrainingError) as caught:
        await training.fit_pls_on_version(
            factory, spec=data["spec"], artifact_root=data["root"], parameters=PLSParameters()
        )
    assert caught.value.outcome == "unconfirmed"
    assert len(opened) == 4
    run = (await runs(data))[0]
    assert run.status == "running" and run.id == caught.value.training_run_id
    assert (data["root"] / "models" / "pls" / f"{caught.value.model_id}.json").exists()


async def test_actual_running_record_is_committed_before_fit(data, monkeypatch):
    import sqlite3

    original = training.fit_pls_core
    seen = []

    def checked(*args, **kwargs):
        connection = sqlite3.connect(data["root"] / "runs.db")
        try:
            seen.extend(
                connection.execute("SELECT status, run_type FROM processing_runs").fetchall()
            )
        finally:
            connection.close()
        return original(*args, **kwargs)

    monkeypatch.setattr(training, "fit_pls_core", checked)
    await fit(data)
    assert seen == [("running", "modeling.pls")]


async def test_wrong_existing_training_run_cannot_be_reused(data):
    first, second = await fit(data), await fit(data)
    path = data["root"] / "models" / "pls" / f"{first.metadata.model_id}.json"
    document = json.loads(path.read_text())
    document["provenance"]["training_run_id"] = str(second.metadata.provenance.training_run_id)
    path.write_text(json.dumps(document), encoding="utf-8")
    async with data["factory"]() as session:
        with pytest.raises(ValueError):
            await training.load_persisted_pls_model(
                session, model_id=first.metadata.model_id, artifact_root=data["root"]
            )


@pytest.mark.parametrize("kind", ["database_sha", "file_sha"])
async def test_persisted_loading_rechecks_dataset_identity(data, kind):
    model = await fit(data)
    if kind == "database_sha":
        async with data["factory"]() as session:
            version = await session.get(DatasetVersion, data["spec"].dataset_version_id)
            version.sha256 = "0" * 64
            await session.commit()
    else:
        path = data["root"] / "source.csv"
        path.write_bytes(path.read_bytes() + b"\n")
    async with data["factory"]() as session:
        with pytest.raises(ValueError, match="SHA256"):
            await training.load_persisted_pls_model(
                session, model_id=model.metadata.model_id, artifact_root=data["root"]
            )


async def test_json_publication_failure_leaves_only_unusable_npz_and_failed_run(data, monkeypatch):
    from app.services import pls_artifact_service as artifacts

    original = artifacts.os.link

    def fail_json(source, target):
        if str(target).endswith(".json"):
            raise OSError("Injected JSON publication failure")
        return original(source, target)

    monkeypatch.setattr(artifacts.os, "link", fail_json)
    with pytest.raises(training.PLSTrainingError) as caught:
        await fit(data)
    run = (await runs(data))[0]
    assert run.status == "failed" and run.result["failure_stage"] == "save_artifact"
    directory = data["root"] / "models" / "pls"
    assert len(list(directory.glob("*.npz"))) == 1
    assert not list(directory.glob("*.json"))
    assert not list(directory.glob("*.tmp"))
    async with data["factory"]() as session:
        with pytest.raises(ValueError):
            await training.load_persisted_pls_model(
                session, model_id=caught.value.model_id, artifact_root=data["root"]
            )


async def test_v1_cannot_be_mistaken_for_a_persisted_training_record(data):
    model = training.fit_pls_core(
        data["x"][:24],
        data["y"][:24],
        feature_names=("a", "b"),
        target_name="quality",
        parameters=PLSParameters(),
    )
    metadata = training.save_pls_artifact(model, artifact_root=data["root"])
    async with data["factory"]() as session:
        with pytest.raises(ValueError, match="v2"):
            await training.load_persisted_pls_model(
                session, model_id=metadata.model_id, artifact_root=data["root"]
            )


async def test_optional_spec_time_column_does_not_disable_csv_time_requirements(data):
    spec = modified(data, lambda d: d["time_axis"].update(column=None))
    model = await fit(data, spec)
    assert model.metadata.training_rows == 24


async def test_csv_without_time_column_is_rejected_by_existing_reader(data):
    path = data["root"] / "source.csv"
    raw = path.read_bytes().replace(b"timestamp,", b"record_id,", 1)
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    async with data["factory"]() as session:
        version = await session.get(DatasetVersion, data["spec"].dataset_version_id)
        version.sha256 = digest
        await session.commit()

    def mutate(d):
        d["dataset_version_sha256"] = digest
        d["time_axis"]["column"] = None

    with pytest.raises(ValueError):
        await fit(data, modified(data, mutate))
    assert await runs(data) == []


@pytest.mark.parametrize("change", ["target_lags", "horizon", "guard", "selected_rows"])
async def test_additional_unsupported_contracts_are_rejected(data, change):
    def mutate(d):
        if change == "target_lags":
            d["feature_spec"].update(target_lags=[1], history_window=1)
        elif change == "horizon":
            d["feature_spec"]["prediction_horizon"] = 2
        elif change == "guard":
            d["split"]["history_guard"] = 1
        else:
            d["training_selection"] = {
                "mode": "selected_rows",
                "source_run_id": str(uuid4()),
                "source_version_id": str(data["spec"].dataset_version_id),
                "requested_indices": {"ranges": [{"start": 1, "stop": 12}]},
            }

    with pytest.raises(ValueError):
        await fit(data, modified(data, mutate))
    assert await runs(data) == []


async def test_missing_held_out_targets_are_not_dropped_or_used_for_fit(data):
    path = data["root"] / "source.csv"
    lines = path.read_text().splitlines()
    for row in (25, 35):
        cells = lines[row + 1].split(",")
        cells[-1] = ""
        lines[row + 1] = ",".join(cells)
    raw = ("\n".join(lines) + "\n").encode()
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    async with data["factory"]() as session:
        version = await session.get(DatasetVersion, data["spec"].dataset_version_id)
        version.sha256 = digest
        await session.commit()
    spec = modified(data, lambda d: d.update(dataset_version_sha256=digest))
    model = await fit(data, spec)
    assert model.metadata.training_rows == 24
    result = (await runs(data))[0].result
    assert result["candidate_rows"]["validation"]["ranges"] == [{"start": 24, "stop": 32}]
    assert result["candidate_rows"]["test"]["ranges"] == [{"start": 32, "stop": 40}]
    assert "evaluated_rows" not in result
