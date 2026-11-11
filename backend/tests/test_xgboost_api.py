"""XGBoost HTTP training, saved prediction and publication retry."""

from uuid import uuid4

import pytest
from app.services import xgboost_platform_adapter as platform

from test_pls_api import api as api
from test_pls_api import data as data
from test_xgboost_platform import no_training

pytestmark = pytest.mark.asyncio
BASE = "/api/v1/modeling/xgboost"


def fit(api, data):
    response = api.post(
        f"{BASE}/fit",
        json={
            "experiment_spec": data["spec"].model_dump(mode="json"),
            "parameters": {"num_boost_round": 6},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def error(response, status, code):
    assert response.status_code == status, response.text
    envelope = response.json()
    assert envelope["success"] is False and envelope["error"]["code"] == code
    assert envelope["request_id"] and "Traceback" not in response.text


async def test_http_fit_details_and_fixed_prediction(api, data, monkeypatch):
    trained = fit(api, data)
    assert trained["manifest_status"] == "published"
    model_id = trained["model_id"]
    monkeypatch.setattr(platform, "fit_xgboost_core", no_training)
    detail = api.get(f"/api/v1/models/{model_id}")
    assert detail.status_code == 200, detail.text
    model = detail.json()["data"]
    assert model["model_type"] == "xgboost" and model["feature_names"] == ["b", "a"]
    assert model["provenance_status"] == "verified" and model["training_rows"] == 24
    assert model["training_run_id"] == trained["training_run_id"]
    assert model["source"]["dataset_version_id"] == str(data["spec"].dataset_version_id)
    assert str(data["root"]) not in detail.text

    body = {"model_id": model_id, "feature_names": ["b", "a"], "X": [[1, 2], [2, 3]]}
    prediction = api.post(f"{BASE}/predict", json=body)
    assert prediction.status_code == 200, prediction.text
    result = prediction.json()["data"]
    assert (
        result["model_id"] == model_id and result["sample_count"] == len(result["predictions"]) == 2
    )
    error(
        api.post(f"{BASE}/predict", json={**body, "feature_names": ["a", "b"]}),
        422,
        "XGBOOST_INPUT_INVALID",
    )
    error(
        api.post(f"{BASE}/predict", json={**body, "X": [["1", 2]]}),
        422,
        "REQUEST_VALIDATION_FAILED",
    )
    error(
        api.post(f"{BASE}/predict", json={**body, "model_id": str(uuid4())}),
        404,
        "TRAINING_RUN_MISSING",
    )


async def test_http_manifest_failure_retry_and_wrong_run(api, data, monkeypatch):
    publish = platform.publish_verified_manifest

    def unavailable(*args):
        raise OSError("internal path must not be returned")

    monkeypatch.setattr(platform, "publish_verified_manifest", unavailable)
    trained = fit(api, data)
    assert trained["training_status"] == "succeeded" and trained["manifest_status"] == "failed"
    assert trained["manifest_retryable"]
    model_id = trained["model_id"]
    error(api.get(f"/api/v1/models/{model_id}"), 409, "MANIFEST_NOT_PUBLISHED")
    monkeypatch.setattr(platform, "fit_xgboost_core", no_training)
    route = f"{BASE}/{model_id}/manifest/retry"
    error(api.post(route, json={"training_run_id": str(uuid4())}), 409, "TRAINING_RUN_ID_MISMATCH")
    response = api.post(route, json={"training_run_id": trained["training_run_id"]})
    error(response, 503, "XGBOOST_SERVICE_UNAVAILABLE")
    assert "internal path" not in response.text
    monkeypatch.setattr(platform, "publish_verified_manifest", publish)
    response = api.post(route, json={"training_run_id": trained["training_run_id"]})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["manifest_status"] == "published"
    assert api.get(f"/api/v1/models/{model_id}").status_code == 200
