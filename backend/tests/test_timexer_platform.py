"""TimeXer platform tests on synthetic CSVs and isolated SQLite."""

import asyncio
import hashlib
import json

import numpy as np
import pytest
import torch
from app.models.dataset import ProcessingRun
from app.schemas.experiment_spec import RowRange, RowSet
from app.schemas.timexer import TimeXerParameters
from app.schemas.timexer_platform import TimeXerForecastSpec
from app.services import model_artifact_service as artifacts
from app.services import timexer_platform_adapter as platform
from app.services.experiment_spec_service import spec_hash
from app.services.model_data_adapter import BoundSource, ResolvedRows
from app.services.sequence_data_adapter import build_timexer_samples
from app.services.version_data import load_version_series
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from test_pls_training_service import runs
from test_tcn_platform import data as data

pytestmark = pytest.mark.asyncio


def params(horizon=3):
    return TimeXerParameters(
        target_window_length=8,
        exogenous_window_length=11,
        patch_length=4,
        prediction_length=horizon,
        embedding_dim=16,
        num_heads=2,
        epochs=1,
        batch_size=64,
    )


def forecast(horizon=3):
    return TimeXerForecastSpec(
        target_window_length=8, exogenous_window_length=11, prediction_length=horizon
    )


async def fit(data, *, horizon=3, spec=None):
    return await platform.fit_timexer_on_version(
        data["factory"],
        spec=spec or data["spec"],
        parameters=params(horizon),
        forecast_spec=forecast(horizon),
        artifact_root=data["root"],
    )


async def load(data, model_id):
    async with data["factory"]() as session:
        return await artifacts.load_model_instance(
            session, model_id=model_id, artifact_root=data["root"]
        )


def forbid_training(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("TimeXer loading, retry and prediction must not train or update weights")

    monkeypatch.setattr(platform, "fit_timexer_core", forbidden)
    monkeypatch.setattr(torch.optim.Adam, "step", forbidden)


async def test_real_fit_uses_only_bound_train_histories_and_persists_forecast(data, monkeypatch):
    real_fit = platform.fit_timexer_core
    loop = asyncio.get_running_loop()
    calls = []

    def record(target, exogenous, y, **kwargs):
        (run,) = asyncio.run_coroutine_threadsafe(runs(data), loop).result(timeout=10)
        assert run.run_type == "modeling.timexer" and run.status == "running"
        assert run.result["forecast_spec"] == forecast().model_dump()
        assert run.source_version_id == data["spec"].dataset_version_id != data["latest"]
        calls.append((target.copy(), exogenous.copy(), y.copy(), kwargs))
        return real_fit(target, exogenous, y, **kwargs)

    monkeypatch.setattr(platform, "fit_timexer_core", record)
    outcome = await fit(data)
    ((target, exogenous, y, kwargs),) = calls
    anchors = [*range(11, 31), *range(47, 68)]
    assert target.shape == (41, 8, 1) and exogenous.shape == (41, 11, 2)
    assert y.shape == (41, 3)
    np.testing.assert_array_equal(target[:, :, 0], [data["y"][r - 8 : r] for r in anchors])
    np.testing.assert_array_equal(exogenous, [data["x"][r - 11 : r, ::-1] for r in anchors])
    np.testing.assert_array_equal(y, [data["y"][r : r + 3] for r in anchors])
    assert kwargs["target_name"] == "quality" and kwargs["exogenous_feature_names"] == ("b", "a")
    assert outcome.manifest_status == "published" and outcome.training_samples == 41
    (run,) = await runs(data)
    assert run.id == outcome.training_run_id != outcome.model_id and run.status == "succeeded"
    assert run.parameters["forecast_spec"] == run.result["forecast_spec"] == forecast().model_dump()
    assert run.parameters["experiment_spec"]["feature_spec"]["prediction_horizon"] == 1
    evidence = run.result["sequence_evidence"]
    assert evidence["target_offsets"] == [0, 1, 2] and evidence["sample_count"] == 41
    assert evidence["history_offsets"] == {"target": [-8, 0], "exogenous": [-11, 0]}
    assert evidence["anchor_rows"]["ranges"] == [
        {"start": 11, "stop": 31},
        {"start": 47, "stop": 68},
    ]
    models = data["root"] / "models"
    manifest = json.loads((models / f"{outcome.model_id}.manifest.json").read_bytes())
    payload = json.loads((models / "timexer" / f"{outcome.model_id}.json").read_bytes())
    assert manifest["forecast_spec"] == forecast().model_dump()
    assert manifest["payload_uri"] == f"models/timexer/{outcome.model_id}.json"
    assert manifest["target_name"] == "quality" and manifest["exogenous_names"] == ["b", "a"]
    assert manifest["torch_version"] == payload["torch_version"]
    assert payload["source_status"] == "unbound" and payload["prediction_length"] == 3
    forbid_training(monkeypatch)
    loaded = await load(data, outcome.model_id)
    assert loaded.model_type_id == "timexer" and loaded.training_run_id == run.id
    prediction = platform.predict_saved_timexer(
        loaded.payload, target[:2], exogenous[:2], target_name="quality", exogenous_names=("b", "a")
    )
    assert prediction.shape == (2, 3) and np.isfinite(prediction).all()


@pytest.mark.parametrize(("anchor", "first_stop"), [(68, 33), (34, 36)])
async def test_future_labels_cannot_cross_partition_or_run(data, anchor, first_stop):
    spec = data["spec"]
    train = (RowRange(start=0, stop=first_stop), spec.split.train[1])
    spec = spec.model_copy(update={"split": spec.split.model_copy(update={"train": train})})
    source = BoundSource(
        spec.dataset_id, spec.dataset_version_id, spec.dataset_version_sha256, spec_hash(spec)
    )
    async with data["factory"]() as session:
        series = await load_version_series(
            session, version_id=spec.dataset_version_id, artifact_root=data["root"]
        )
    rows = ResolvedRows(RowSet(ranges=(RowRange(start=anchor, stop=anchor + 1),)))
    with pytest.raises(ValueError, match="outside the effective partition"):
        build_timexer_samples(
            series,
            spec=spec,
            source=source,
            partition="train",
            parameters=params(),
            requested_rows=rows,
        )


async def test_wrong_csv_sha_and_unverified_time_axis_reject_before_fit(data, monkeypatch):
    forbid_training(monkeypatch)
    spec = data["spec"]
    axis = spec.time_axis.model_copy(update={"sampling_status": "unknown"})
    with pytest.raises(ValueError, match="verified uniform"):
        await fit(data, spec=spec.model_copy(update={"time_axis": axis}))
    with pytest.raises(ValueError, match="SHA256"):
        await fit(data, spec=spec.model_copy(update={"dataset_version_sha256": "0" * 64}))
    assert await runs(data) == []


@pytest.mark.parametrize("tamper", ["manifest", "artifact", "result"])
async def test_loader_rejects_forecast_inconsistency(data, monkeypatch, tamper):
    outcome = await fit(data)
    forbid_training(monkeypatch)
    models = data["root"] / "models"
    manifest_path = models / f"{outcome.model_id}.manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    if tamper == "manifest":
        manifest["forecast_spec"]["prediction_length"] = 1
    else:
        async with data["factory"]() as session:
            run = await session.get(ProcessingRun, outcome.training_run_id)
            assert run is not None
            if tamper == "result":
                run.result = {**run.result, "forecast_spec": forecast(1).model_dump()}
            else:
                payload = models / "timexer" / f"{outcome.model_id}.json"
                document = json.loads(payload.read_bytes())
                document["prediction_length"] = 1
                raw = json.dumps(document).encode("utf-8")
                payload.write_bytes(raw)
                digest = hashlib.sha256(raw).hexdigest()
                manifest["payload_sha256"] = digest
                run.result = {
                    **run.result,
                    "artifact": {**run.result["artifact"], "json_sha256": digest},
                }
            await session.commit()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(artifacts.ModelArtifactError) as error:
        await load(data, outcome.model_id)
    assert error.value.code == (
        "TIMEXER_SOURCE_MISMATCH" if tamper == "manifest" else "TIMEXER_ARTIFACT_INVALID"
    )


async def test_failed_fit_is_durable(data, monkeypatch):
    def fail(*args, **kwargs):
        raise ValueError("fit failed")

    monkeypatch.setattr(platform, "fit_timexer_core", fail)
    with pytest.raises(platform.TimeXerTrainingError) as error:
        await fit(data)
    (run,) = await runs(data)
    assert run.id == error.value.training_run_id and run.status == "failed"
    assert run.parameters["forecast_spec"] == run.result["forecast_spec"] == forecast().model_dump()
    assert not (data["root"] / "models").exists()


async def test_lost_final_commit_acknowledgement_uses_original_run(data):
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
    outcome = await fit({**data, "factory": factory})
    (run,) = await runs(data)
    assert outcome.manifest_status == "published" and run.status == "succeeded"
    assert run.id == outcome.training_run_id
