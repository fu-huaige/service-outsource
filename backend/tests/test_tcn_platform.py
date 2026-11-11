"""Persisted TCN training on synthetic time series and isolated SQLite."""

import asyncio
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
from app.schemas.tcn import TCNParameters
from app.services import model_artifact_service as artifacts
from app.services import tcn_platform_adapter as platform
from app.services.tcn_artifact_service import load_tcn_artifact
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from test_pls_training_service import runs

pytestmark = pytest.mark.asyncio
PARAMS = TCNParameters(window_length=29, hidden_channels=4, epochs=1, batch_size=8)


@pytest_asyncio.fixture
async def data(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'runs.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    dataset_id, version_id, latest_id = uuid4(), uuid4(), uuid4()
    size = 102
    start = datetime(2026, 1, 1, tzinfo=UTC)
    values = np.arange(size, dtype=np.float32)
    x = np.column_stack((values / 8, values / 16 + 1))
    y = values / 32 + 2
    times = [start + timedelta(seconds=i if i < 36 else i - 36) for i in range(size)]

    def make_csv(offset):
        lines = ["timestamp,a,b,quality"]
        for i, time in enumerate(times):
            lines.append(
                f"{time.isoformat()},{x[i, 0] + offset},{x[i, 1] + offset},{y[i] + offset}"
            )
        return ("\n".join(lines) + "\n").encode()

    raw = make_csv(0)
    digest = hashlib.sha256(raw).hexdigest()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        session.add(
            Dataset(
                id=dataset_id,
                name="TCN synthetic",
                raw_sha256=digest,
                raw_path="source.csv",
                byte_size=len(raw),
                encoding="utf-8",
                delimiter=",",
                active_version_id=latest_id,
            )
        )
        for identity, filename, content in (
            (version_id, "source.csv", raw),
            (latest_id, "latest.csv", make_csv(500)),
        ):
            (tmp_path / filename).write_bytes(content)
            session.add(
                DatasetVersion(
                    id=identity,
                    dataset_id=dataset_id,
                    name=filename,
                    artifact_path=filename,
                    sha256=hashlib.sha256(content).hexdigest(),
                    row_count=size,
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
            "row_count": size,
            "input_columns": ["b", "a"],
            "target_column": "quality",
            "time_axis": {
                "column": "timestamp",
                "sampling_status": "uniform",
                "sample_period_seconds": 1,
            },
            "continuous_runs": [{"start": 0, "stop": 36}, {"start": 36, "stop": size}],
            "feature_spec": {"kind": "tabular"},
            "split": {
                "train": [{"start": 0, "stop": 33}, {"start": 36, "stop": 70}],
                "validation": [{"start": 70, "stop": 86}],
                "test": [{"start": 86, "stop": size}],
            },
            "evaluation": {"prediction_modes": ["prediction"]},
        }
    )
    yield {"factory": factory, "root": tmp_path, "spec": spec, "x": x, "y": y, "latest": latest_id}
    await engine.dispose()


async def fit(data, spec=None):
    return await platform.fit_tcn_on_version(
        data["factory"], spec=spec or data["spec"], parameters=PARAMS, artifact_root=data["root"]
    )


def no_training(*args, **kwargs):
    pytest.fail("TCN restoration, prediction and publication must not train")


async def load(data, model_id):
    async with data["factory"]() as session:
        return await artifacts.load_model_instance(
            session, model_id=model_id, artifact_root=data["root"]
        )


async def test_train_persists_verified_windows_and_restores_original_model(data, monkeypatch):
    real_fit = platform.fit_tcn_core
    loop = asyncio.get_running_loop()
    calls = []

    def record(x, y, **kwargs):
        calls.append((x.copy(), y.copy(), kwargs))
        (running,) = asyncio.run_coroutine_threadsafe(runs(data), loop).result(timeout=10)
        assert running.status == "running" and running.run_type == "modeling.tcn"
        assert running.source_version_id == data["spec"].dataset_version_id != data["latest"]
        return real_fit(x, y, **kwargs)

    monkeypatch.setattr(platform, "fit_tcn_core", record)
    result = await fit(data)
    assert result.training_samples == 9 and result.manifest_status == "published"
    (call,) = calls
    x, y, kwargs = call
    anchors = [*range(29, 33), *range(65, 70)]
    assert x.shape == (9, 29, 2) and x.dtype == y.dtype == np.float32
    np.testing.assert_array_equal(x, [data["x"][r - 29 : r, ::-1] for r in anchors])
    np.testing.assert_array_equal(y, data["y"][anchors])
    assert kwargs["feature_names"] == ("b", "a")
    (run,) = await runs(data)
    assert run.id == result.training_run_id != result.model_id and run.status == "succeeded"
    assert run.result["training_loss"] == result.training_loss
    evidence = run.result["sequence_evidence"]
    assert evidence["anchor_rows"]["ranges"] == [
        {"start": 29, "stop": 33},
        {"start": 65, "stop": 70},
    ]
    assert evidence["sample_count"] == 9 and evidence["history_offsets"] == [-29, 0]
    assert evidence["target_offsets"] == [0] and evidence["sampling_status"] == "uniform"
    root, identity = data["root"], result.model_id
    manifest = json.loads((root / "models" / f"{identity}.manifest.json").read_bytes())
    payload = json.loads((root / "models" / "tcn" / f"{identity}.json").read_bytes())
    assert manifest["payload_uri"] == f"models/tcn/{identity}.json"
    assert manifest["training_samples"] == 9 and payload["source_status"] == "unbound"
    assert (root / "models" / "tcn" / f"{identity}.npz").is_file()
    monkeypatch.setattr(platform, "fit_tcn_core", no_training)
    instance = await load(data, identity)
    assert instance.model_type_id == "tcn" and instance.training_run_id == run.id
    standalone = load_tcn_artifact(model_id=identity, artifact_root=root)
    np.testing.assert_array_equal(
        instance.payload.predict(x[:2], feature_names=("b", "a")),
        standalone.predict(x[:2], feature_names=("b", "a")),
    )


@pytest.mark.parametrize("status", ["unknown", "irregular", "missing_column", "missing_period"])
async def test_training_rejects_sampling_without_verified_uniform_metadata(
    data, monkeypatch, status
):
    monkeypatch.setattr(platform, "fit_tcn_core", no_training)
    spec = data["spec"]
    changes = {
        "missing_column": {"column": None},
        "missing_period": {"sample_period_seconds": None},
    }.get(status, {"sampling_status": status})
    axis = spec.time_axis.model_copy(update=changes)
    with pytest.raises(ValueError, match="verified uniform"):
        await fit(data, spec.model_copy(update={"time_axis": axis}))
    assert await runs(data) == []


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("dataset_version_id", "ownership"),
        ("dataset_version_sha256", "SHA256"),
    ],
)
async def test_version_identity_and_sha_are_required(data, monkeypatch, field, message):
    monkeypatch.setattr(platform, "fit_tcn_core", no_training)
    spec = data["spec"]
    value = uuid4() if field == "dataset_version_id" else "0" * 64
    with pytest.raises(ValueError, match=message):
        await fit(data, spec.model_copy(update={field: value}))
    assert await runs(data) == []


async def test_uniform_declaration_is_checked_against_real_csv_timestamps(data, monkeypatch):
    monkeypatch.setattr(platform, "fit_tcn_core", no_training)
    path = data["root"] / "source.csv"
    raw = path.read_bytes().replace(b"00:00:14+00:00", b"00:00:14.500000+00:00", 1)
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    spec = data["spec"]
    async with data["factory"]() as session:
        version = await session.get(DatasetVersion, spec.dataset_version_id)
        assert version is not None
        version.sha256 = digest
        await session.commit()
    with pytest.raises(ValueError, match="uniform sampling"):
        await fit(data, spec.model_copy(update={"dataset_version_sha256": digest}))
    assert await runs(data) == []


async def test_publish_failure_retry_keeps_success_and_does_not_fit(data, monkeypatch):
    publish = platform.publish_verified_manifest

    def unavailable(*args):
        raise OSError("publication unavailable")

    monkeypatch.setattr(platform, "publish_verified_manifest", unavailable)
    result = await fit(data)
    assert result.manifest_status == "failed" and result.manifest_retryable
    (before,) = await runs(data)
    assert before.status == "succeeded"
    monkeypatch.setattr(platform, "fit_tcn_core", no_training)
    monkeypatch.setattr(platform, "publish_verified_manifest", publish)
    with pytest.raises(artifacts.ModelArtifactError) as missing:
        await load(data, result.model_id)
    assert missing.value.code == "MANIFEST_NOT_PUBLISHED"

    async def retry(run_id):
        return await platform.retry_tcn_manifest(
            data["factory"],
            model_id=result.model_id,
            training_run_id=run_id,
            artifact_root=data["root"],
        )

    with pytest.raises(artifacts.ModelArtifactError, match="Unexpected"):
        await retry(uuid4())
    assert (await retry(result.training_run_id)).manifest_status == "published"
    assert (await retry(result.training_run_id)).manifest_status == "published"
    (after,) = await runs(data)
    assert after.result == before.result and after.status == before.status


@pytest.mark.parametrize("change", ["manifest", "weights", "anchors"])
async def test_loader_rejects_corrupt_manifest_weights_and_training_evidence(
    data, monkeypatch, change
):
    outcome = await fit(data)
    model_id = outcome.model_id
    monkeypatch.setattr(platform, "fit_tcn_core", no_training)
    if change in ("manifest", "weights"):
        path = (
            data["root"] / "models" / f"{model_id}.manifest.json"
            if change == "manifest"
            else data["root"] / "models" / "tcn" / f"{model_id}.npz"
        )
        path.write_bytes(b"invalid")
    else:
        async with data["factory"]() as session:
            run = await session.get(ProcessingRun, outcome.training_run_id)
            assert run is not None
            run.result = {**run.result, "effective_training_rows": {"ranges": []}}
            await session.commit()
    with pytest.raises(artifacts.ModelArtifactError) as error:
        await load(data, model_id)
    assert error.value.code == (
        "MANIFEST_INVALID" if change == "manifest" else "TCN_ARTIFACT_INVALID"
    )


async def test_failed_fit_is_durable(data, monkeypatch):
    def fail(*args, **kwargs):
        raise ValueError("fit failed")

    monkeypatch.setattr(platform, "fit_tcn_core", fail)
    with pytest.raises(platform.TCNTrainingError) as error:
        await fit(data)
    (run,) = await runs(data)
    assert run.id == error.value.training_run_id
    assert run.status == error.value.outcome == "failed"
    assert run.result["failure_stage"] == "fit_and_save" and run.finished_at is not None
    assert not (data["root"] / "models").exists()


async def test_final_commit_acknowledgement_loss_is_reconciled(data):
    class LostAcknowledgement(AsyncSession):
        async def commit(self):
            finalizing = any(
                isinstance(run, ProcessingRun) and run.status == "succeeded" for run in self.dirty
            )
            await super().commit()
            if finalizing:
                raise OSError("commit acknowledgement lost")

    factory = async_sessionmaker(
        data["factory"].kw["bind"], class_=LostAcknowledgement, expire_on_commit=False
    )
    result = await fit({**data, "factory": factory})
    (run,) = await runs(data)
    assert result.manifest_status == "published" and run.status == "succeeded"
    assert run.id == result.training_run_id
