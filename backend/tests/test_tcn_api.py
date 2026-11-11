"""TCN HTTP training, bounded fixed prediction and publication retry."""

from uuid import uuid4

import pytest
import torch
from app.schemas.tcn_platform import MAX_PREDICT_BYTES, MAX_PREDICT_SAMPLES
from app.services import tcn_platform_adapter as platform

from test_pls_api import api as api
from test_pls_training_service import runs
from test_tcn_platform import PARAMS, no_training
from test_tcn_platform import data as data

pytestmark = pytest.mark.asyncio
BASE = "/api/v1/modeling/tcn"


def fit(api, data):
    response = api.post(
        f"{BASE}/fit",
        json={
            "experiment_spec": data["spec"].model_dump(mode="json"),
            "parameters": PARAMS.model_dump(mode="json"),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def error(response, status, code):
    assert response.status_code == status, response.text
    envelope = response.json()
    assert envelope["success"] is False and envelope["error"]["code"] == code
    assert envelope["request_id"] and "Traceback" not in response.text


async def test_http_fit_details_and_fixed_prediction_are_read_only(api, data, monkeypatch):
    trained = fit(api, data)
    assert trained["manifest_status"] == "published" and trained["training_samples"] == 9
    model_id = trained["model_id"]
    root = data["root"]
    paths = [
        root / "models" / f"{model_id}.manifest.json",
        root / "models" / "tcn" / f"{model_id}.json",
        root / "models" / "tcn" / f"{model_id}.npz",
    ]
    original = [path.read_bytes() for path in paths]
    (before,) = await runs(data)
    monkeypatch.setattr(platform, "fit_tcn_core", no_training)
    monkeypatch.setattr(torch.optim.Adam, "step", no_training)
    detail = api.get(f"/api/v1/models/{model_id}")
    assert detail.status_code == 200, detail.text
    model = detail.json()["data"]
    assert model["model_type"] == "tcn" and model["feature_names"] == ["b", "a"]
    assert model["provenance_status"] == "verified" and model["training_rows"] == 9
    assert model["training_run_id"] == trained["training_run_id"]
    assert model["source"]["dataset_version_id"] == str(data["spec"].dataset_version_id)
    assert str(root) not in detail.text

    window = data["x"][:29, ::-1].tolist()
    body = {"model_id": model_id, "feature_names": ["b", "a"], "X": [window, window]}
    prediction = api.post(f"{BASE}/predict", json=body)
    assert prediction.status_code == 200, prediction.text
    result = prediction.json()["data"]
    assert result["model_id"] == model_id
    assert result["sample_count"] == len(result["predictions"]) == 2
    error(
        api.post(f"{BASE}/predict", json={**body, "feature_names": ["a", "b"]}),
        422,
        "TCN_INPUT_INVALID",
    )
    error(
        api.post(f"{BASE}/predict", json={**body, "X": [window + [[0, 0]]]}),
        422,
        "TCN_INPUT_INVALID",
    )
    error(
        api.post(f"{BASE}/predict", json={**body, "X": [window] * (MAX_PREDICT_SAMPLES + 1)}),
        422,
        "REQUEST_VALIDATION_FAILED",
    )
    (after,) = await runs(data)
    assert after.id == before.id and after.result == before.result and after.status == before.status
    assert [path.read_bytes() for path in paths] == original


async def test_prediction_body_limit_rejects_before_json_or_load(api, monkeypatch):
    from app.api import routes

    monkeypatch.setattr(routes, "_api_load_model", no_training)
    response = api.post(
        f"{BASE}/predict",
        content=b" " * (MAX_PREDICT_BYTES + 1),
        headers={"Content-Type": "application/json"},
    )
    error(response, 413, "TCN_PREDICT_BODY_TOO_LARGE")


async def test_http_manifest_failure_and_retry_with_same_ids(api, data, monkeypatch):
    publish = platform.publish_verified_manifest

    def unavailable(*args):
        raise OSError("internal path must not be returned")

    monkeypatch.setattr(platform, "publish_verified_manifest", unavailable)
    trained = fit(api, data)
    assert trained["training_status"] == "succeeded" and trained["manifest_status"] == "failed"
    assert trained["manifest_retryable"]
    model_id = trained["model_id"]
    error(api.get(f"/api/v1/models/{model_id}"), 409, "MANIFEST_NOT_PUBLISHED")
    monkeypatch.setattr(platform, "fit_tcn_core", no_training)
    retry = f"{BASE}/{model_id}/manifest/retry"
    error(api.post(retry, json={"training_run_id": str(uuid4())}), 409, "TRAINING_RUN_ID_MISMATCH")
    body = {"training_run_id": trained["training_run_id"]}
    response = api.post(retry, json=body)
    error(response, 503, "TCN_SERVICE_UNAVAILABLE")
    assert "internal path" not in response.text
    monkeypatch.setattr(platform, "publish_verified_manifest", publish)
    response = api.post(retry, json=body)
    assert response.status_code == 200 and response.json()["data"]["manifest_status"] == "published"
