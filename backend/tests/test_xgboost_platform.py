"""XGBoost platform provenance and transaction behavior on isolated SQLite."""

import asyncio
import hashlib
import json
from uuid import uuid4

import numpy as np
import pytest
from app.models.dataset import ProcessingRun
from app.schemas.xgboost import XGBoostParameters
from app.services import model_artifact_service as artifacts
from app.services import xgboost_platform_adapter as platform
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from test_pls_training_service import data as data
from test_pls_training_service import runs

pytestmark = pytest.mark.asyncio


async def fit(data):
    return await platform.fit_xgboost_on_version(
        data["factory"],
        spec=data["spec"],
        parameters=XGBoostParameters(num_boost_round=6),
        artifact_root=data["root"],
    )


def no_training(*args, **kwargs):
    pytest.fail("Loading, inference and publication must never fit a model")


async def load(data, model_id):
    async with data["factory"]() as session:
        return await artifacts.load_model_instance(
            session, model_id=model_id, artifact_root=data["root"]
        )


async def test_training_persists_exact_rows_and_three_distinct_files(data, monkeypatch):
    real_fit = platform.fit_xgboost_core
    loop = asyncio.get_running_loop()
    calls = []

    def record(x, y, **kwargs):
        calls.append((x.copy(), y.copy(), kwargs))
        (running,) = asyncio.run_coroutine_threadsafe(runs(data), loop).result(timeout=10)
        assert running.status == "running" and running.run_type == platform.RUN_TYPE
        assert running.source_version_id != data["latest"]
        return real_fit(x, y, **kwargs)

    monkeypatch.setattr(platform, "fit_xgboost_core", record)
    outcome = await fit(data)
    assert outcome.manifest_status == "published" and outcome.training_rows == 24
    (call,) = calls
    x, y, kwargs = call
    np.testing.assert_array_equal(x, data["x"][:24, ::-1])
    np.testing.assert_array_equal(y, data["y"][:24])
    assert kwargs["feature_names"] == ("b", "a") and kwargs["target_name"] == "quality"
    (run,) = await runs(data)
    assert run.id == outcome.training_run_id != outcome.model_id
    assert run.status == "succeeded" and run.finished_at is not None
    assert run.result["effective_training_rows"] == {
        "ranges": [{"start": 0, "stop": 12}, {"start": 12, "stop": 24}],
        "index_file": None,
    }
    model_id = outcome.model_id
    root = data["root"]
    manifest = json.loads((root / "models" / f"{model_id}.manifest.json").read_bytes())
    metadata = json.loads((root / "models" / "xgboost" / f"{model_id}.json").read_bytes())
    binary = (root / "models" / "xgboost" / f"{model_id}.ubj").read_bytes()
    assert manifest["payload_uri"] == f"models/xgboost/{model_id}.json"
    assert metadata["provenance_status"] == "provided_unverified"
    assert metadata["training_run_id"] == str(run.id)
    assert hashlib.sha256(binary).hexdigest() == run.result["artifact"]["ubj_sha256"]
    monkeypatch.setattr(platform, "fit_xgboost_core", no_training)
    instance = await load(data, model_id)
    assert instance.model_type_id == "xgboost" and instance.training_run_id == run.id
    assert instance.payload.predict(x[:3], feature_names=("b", "a")).shape == (3,)


async def test_failed_manifest_can_only_retry_original_successful_run(data, monkeypatch):
    publish = platform.publish_verified_manifest

    def unavailable(*args):
        raise OSError("temporary write failure")

    monkeypatch.setattr(platform, "publish_verified_manifest", unavailable)
    outcome = await fit(data)
    assert outcome.manifest_status == "failed" and outcome.manifest_retryable
    (run,) = await runs(data)
    assert run.status == "succeeded"
    monkeypatch.setattr(platform, "fit_xgboost_core", no_training)
    monkeypatch.setattr(platform, "publish_verified_manifest", publish)
    with pytest.raises(artifacts.ModelArtifactError, match="not been published") as missing:
        await load(data, outcome.model_id)
    assert missing.value.code == "MANIFEST_NOT_PUBLISHED"

    async def retry(run_id):
        return await platform.retry_xgboost_manifest(
            data["factory"],
            model_id=outcome.model_id,
            training_run_id=run_id,
            artifact_root=data["root"],
        )

    with pytest.raises(artifacts.ModelArtifactError, match="Unexpected"):
        await retry(uuid4())
    assert (await retry(outcome.training_run_id)).manifest_status == "published"
    assert (await retry(outcome.training_run_id)).manifest_status == "published"
    (after,) = await runs(data)
    assert after.id == run.id and after.result == run.result and after.status == "succeeded"
    path = data["root"] / "models" / f"{outcome.model_id}.manifest.json"
    conflict = json.loads(path.read_bytes())
    conflict["payload_sha256"] = "0" * 64
    original = json.dumps(conflict).encode("utf-8")
    path.write_bytes(original)
    with pytest.raises(artifacts.ModelArtifactError) as failure:
        await retry(outcome.training_run_id)
    assert failure.value.code == "MANIFEST_CONFLICT" and path.read_bytes() == original


@pytest.mark.parametrize("names", [tuple(f"x{i}" for i in range(257)), ("x" * 256,)])
async def test_training_rejects_features_the_prediction_api_cannot_accept(data, monkeypatch, names):
    monkeypatch.setattr(platform, "fit_xgboost_core", no_training)
    spec = data["spec"].model_copy(update={"input_columns": names})
    with pytest.raises(ValueError, match="prediction API limits"):
        await fit({**data, "spec": spec})
    assert await runs(data) == []


async def test_version_sha_failure_creates_no_run(data, monkeypatch):
    monkeypatch.setattr(platform, "fit_xgboost_core", no_training)
    (data["root"] / "source.csv").write_bytes(b"changed")
    with pytest.raises(ValueError, match="SHA256"):
        await fit(data)
    assert await runs(data) == []


@pytest.mark.parametrize("change", ["manifest", "payload", "rows", "duplicate"])
async def test_loader_rejects_conflicting_provenance(data, monkeypatch, change):
    outcome = await fit(data)
    model_id = outcome.model_id
    monkeypatch.setattr(platform, "fit_xgboost_core", no_training)
    if change in ("manifest", "payload"):
        path = (
            data["root"] / "models" / f"{model_id}.manifest.json"
            if change == "manifest"
            else data["root"] / "models" / "xgboost" / f"{model_id}.ubj"
        )
        path.write_bytes(b"damaged")
    else:
        async with data["factory"]() as session:
            run = await session.get(ProcessingRun, outcome.training_run_id)
            assert run is not None
            if change == "rows":
                run.result = {**run.result, "training_rows": 1}
            else:
                other = uuid4()
                session.add(
                    ProcessingRun(
                        id=other,
                        dataset_id=run.dataset_id,
                        source_version_id=run.source_version_id,
                        run_type=platform.RUN_TYPE,
                        status="succeeded",
                        parameters=run.parameters,
                        result={**run.result, "training_run_id": str(other)},
                    )
                )
            await session.commit()
    with pytest.raises(artifacts.ModelArtifactError) as failure:
        await load(data, model_id)
    assert (
        failure.value.code
        == {
            "manifest": "MANIFEST_INVALID",
            "payload": "XGBOOST_ARTIFACT_INVALID",
            "rows": "XGBOOST_ARTIFACT_INVALID",
            "duplicate": "TRAINING_RUN_ID_MISMATCH",
        }[change]
    )


@pytest.mark.parametrize("status", ["running", "failed"])
async def test_unpublished_incomplete_model_never_reaches_legacy_loader(data, monkeypatch, status):
    model_id, run_id = uuid4(), uuid4()
    async with data["factory"]() as session:
        session.add(
            ProcessingRun(
                id=run_id,
                run_type=platform.RUN_TYPE,
                status=status,
                result={
                    "model_id": str(model_id),
                    "model_type_id": "xgboost",
                    "training_run_id": str(run_id),
                },
            )
        )
        await session.commit()
    monkeypatch.setattr(artifacts, "load_saved_arx_model", no_training)
    with pytest.raises(artifacts.ModelArtifactError) as failure:
        await load(data, model_id)
    assert failure.value.code == "TRAINING_RUN_NOT_SUCCEEDED"


async def test_final_commit_acknowledgement_loss_is_reconciled(data):
    class LostAcknowledgement(AsyncSession):
        async def commit(self):
            finalizing = any(
                isinstance(run, ProcessingRun) and run.status == "succeeded" for run in self.dirty
            )
            await super().commit()
            if finalizing:
                raise OSError("lost commit acknowledgement")

    factory = async_sessionmaker(
        data["factory"].kw["bind"], class_=LostAcknowledgement, expire_on_commit=False
    )
    outcome = await fit({**data, "factory": factory})
    assert outcome.manifest_status == "published"
    (run,) = await runs(data)
    assert run.status == "succeeded" and run.id == outcome.training_run_id


async def test_failed_fit_is_durable_and_does_not_publish(data, monkeypatch):
    def fail(*args, **kwargs):
        raise ValueError("training failed")

    monkeypatch.setattr(platform, "fit_xgboost_core", fail)
    with pytest.raises(platform.XGBoostTrainingError) as failure:
        await fit(data)
    (run,) = await runs(data)
    assert run.id == failure.value.training_run_id
    assert run.status == failure.value.outcome == "failed"
    assert run.result["failure_stage"] == "fit_and_save" and run.finished_at is not None
    assert not (data["root"] / "models").exists()


async def test_initial_commit_failure_never_fits(data, monkeypatch):
    class FailedInitialCommit(AsyncSession):
        async def commit(self):
            if any(isinstance(run, ProcessingRun) for run in self.new):
                raise OSError("initial commit failed")
            await super().commit()

    factory = async_sessionmaker(
        data["factory"].kw["bind"], class_=FailedInitialCommit, expire_on_commit=False
    )
    monkeypatch.setattr(platform, "fit_xgboost_core", no_training)
    with pytest.raises(platform.XGBoostTrainingError) as failure:
        await fit({**data, "factory": factory})
    assert failure.value.stage == "create_run" and failure.value.outcome == "unconfirmed"
    assert await runs(data) == []
