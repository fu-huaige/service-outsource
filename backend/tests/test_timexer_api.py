"""TimeXer HTTP forecast contract, fixed inference and retry."""

from uuid import uuid4

import pytest
from app.schemas.timexer_platform import MAX_PREDICT_BYTES
from app.services import timexer_platform_adapter as platform

from test_pls_api import api as api
from test_pls_training_service import runs
from test_tcn_platform import data as data
from test_timexer_platform import forbid_training, forecast, params

pytestmark = pytest.mark.asyncio
BASE = "/api/v1/modeling/timexer"


def request_body(data, horizon=3):
    return {
        "experiment_spec": data["spec"].model_dump(mode="json"),
        "forecast_spec": forecast(horizon).model_dump(),
        "parameters": params(horizon).model_dump(),
    }


def fit(api, data, horizon=3):
    response = api.post(f"{BASE}/fit", json=request_body(data, horizon))
    assert response.status_code == 200, response.text
    return response.json()["data"]


def error(response, status, code):
    assert response.status_code == status, response.text
    envelope = response.json()
    assert envelope["success"] is False and envelope["error"]["code"] == code
    assert envelope["request_id"] and "Traceback" not in response.text


@pytest.mark.parametrize("horizon", [1, 3])
async def test_fit_details_and_fixed_dual_input_prediction(api, data, monkeypatch, horizon):
    outcome = fit(api, data, horizon)
    assert (
        outcome["manifest_status"] == "published"
        and outcome["forecast_spec"] == forecast(horizon).model_dump()
    )
    identity = outcome["model_id"]
    models = data["root"] / "models"
    paths = [
        models / f"{identity}.manifest.json",
        models / "timexer" / f"{identity}.json",
        models / "timexer" / f"{identity}.npz",
    ]
    before = [path.read_bytes() for path in paths]
    (run,) = await runs(data)
    forbid_training(monkeypatch)
    detail = api.get(f"/api/v1/models/{identity}")
    assert detail.status_code == 200, detail.text
    model = detail.json()["data"]
    assert model["model_type"] == "timexer" and model["provenance_status"] == "verified"
    assert model["parameters"] == params(horizon).model_dump()
    assert model["source"]["dataset_version_id"] == str(data["spec"].dataset_version_id)
    assert model["feature_names"] == ["b", "a"] and model["target_name"] == "quality"
    body = {
        "model_id": identity,
        "target_name": "quality",
        "exogenous_names": ["b", "a"],
        "X_target": [data["y"][3:11, None].tolist()] * 2,
        "X_exogenous": [data["x"][:11, ::-1].tolist()] * 2,
    }
    response = api.post(f"{BASE}/predict", json=body)
    assert response.status_code == 200, response.text
    predicted = response.json()["data"]
    assert (
        predicted["sample_count"] == 2
        and [len(row) for row in predicted["predictions"]] == [horizon] * 2
    )
    if horizon == 3:
        error(
            api.post(f"{BASE}/predict", json={**body, "exogenous_names": ["a", "b"]}),
            422,
            "TIMEXER_INPUT_INVALID",
        )
        error(
            api.post(f"{BASE}/predict", json={**body, "target_name": "b"}),
            422,
            "REQUEST_VALIDATION_FAILED",
        )
    (after,) = await runs(data)
    assert after.id == run.id and after.result == run.result and after.status == run.status
    assert [path.read_bytes() for path in paths] == before


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("prediction_length", 1),
        ("prediction_length", 33),
        ("target_window_length", 12),
        ("exogenous_window_length", 8),
    ],
)
async def test_invalid_forecast_is_rejected_before_training(api, data, monkeypatch, field, value):
    forbid_training(monkeypatch)
    body = request_body(data)
    body["forecast_spec"][field] = value
    error(api.post(f"{BASE}/fit", json=body), 422, "REQUEST_VALIDATION_FAILED")
    assert await runs(data) == []


async def test_base_experiment_spec_still_rejects_multistep_horizon(api, data, monkeypatch):
    forbid_training(monkeypatch)
    body = request_body(data)
    body["experiment_spec"]["feature_spec"]["prediction_horizon"] = 3
    error(api.post(f"{BASE}/fit", json=body), 422, "REQUEST_VALIDATION_FAILED")
    assert await runs(data) == []


async def test_prediction_request_byte_limit(api):
    response = api.post(
        f"{BASE}/predict",
        content=b" " * (MAX_PREDICT_BYTES + 1),
        headers={"Content-Type": "application/json"},
    )
    error(response, 413, "TIMEXER_PREDICT_BODY_TOO_LARGE")


async def test_manifest_retry_is_idempotent_and_does_not_train(api, data, monkeypatch):
    publish = platform.publish_verified_manifest

    def unavailable(*args):
        raise OSError("publication unavailable")

    monkeypatch.setattr(platform, "publish_verified_manifest", unavailable)
    outcome = fit(api, data)
    assert outcome["training_status"] == "succeeded" and outcome["manifest_status"] == "failed"
    identity = outcome["model_id"]
    (before,) = await runs(data)
    forbid_training(monkeypatch)
    error(api.get(f"/api/v1/models/{identity}"), 409, "MANIFEST_NOT_PUBLISHED")
    retry = f"{BASE}/{identity}/manifest/retry"
    error(api.post(retry, json={"training_run_id": str(uuid4())}), 409, "TRAINING_RUN_ID_MISMATCH")
    monkeypatch.setattr(platform, "publish_verified_manifest", publish)
    body = {"training_run_id": outcome["training_run_id"]}
    for _ in range(2):
        response = api.post(retry, json=body)
        assert (
            response.status_code == 200
            and response.json()["data"]["manifest_status"] == "published"
        )
    assert api.get(f"/api/v1/models/{identity}").status_code == 200
    (after,) = await runs(data)
    assert after.id == before.id and after.status == "succeeded" and after.result == before.result
