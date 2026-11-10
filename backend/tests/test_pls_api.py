"""PLS HTTP lifecycle through real services and isolated SQLite."""

import json
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from app.core.config import Settings
from app.core.db import get_session, get_session_factory
from app.main import create_app
from app.models.dataset import ProcessingRun
from app.services import model_artifact_service, pls_training_service
from fastapi.testclient import TestClient
from sqlalchemy import select

from test_model_artifact_manifest import saved as saved
from test_pls_training_service import data as data

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def api(data, monkeypatch):
    from app.api import routes

    monkeypatch.setattr(routes, "get_settings", lambda: Settings(artifact_root=data["root"]))
    app = create_app()

    async def session():
        async with data["factory"]() as value:
            yield value

    app.dependency_overrides[get_session] = session
    app.dependency_overrides[get_session_factory] = lambda: data["factory"]
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def body(data, scopes=("validation", "test")):
    spec = data["spec"].model_dump(mode="json")
    spec["evaluation"]["scopes"] = list(scopes)
    return {"experiment_spec": spec, "parameters": {"n_components": 2, "scale": True}}


def trained(api, data, scopes=("validation", "test")):
    response = api.post("/api/v1/modeling/pls/fit", json=body(data, scopes))
    assert response.status_code == 200, response.text
    result = response.json()["data"]
    assert result["training_status"] == "succeeded" and result["manifest_status"] == "published"
    return result


def error(response, status):
    assert response.status_code == status, response.text
    result = response.json()
    assert result["success"] is False and result["data"] is None
    assert result["error"]["code"] and result["request_id"]
    assert "Traceback" not in response.text
    return result["error"]


async def test_five_routes_and_old_arx_contract(api):
    paths = api.get("/openapi.json").json()["paths"]
    for path, method in [
        ("/api/v1/modeling/pls/fit", "post"),
        ("/api/v1/models/{model_id}", "get"),
        ("/api/v1/modeling/pls/predict", "post"),
        ("/api/v1/modeling/pls/evaluate", "post"),
        ("/api/v1/modeling/pls/evaluations", "get"),
    ]:
        assert method in paths[path]
    assert paths["/api/v1/modeling/arx/fit"]["post"]["requestBody"]["content"]["application/json"][
        "schema"
    ]["$ref"].endswith("/ArxFitRequest")
    from app.api.routes import router

    matches = [
        r
        for r in router.routes
        if getattr(r, "path", None) == "/models/{model_id}" and "GET" in r.methods
    ]
    assert len(matches) == 1
    error(api.get("/api/v1/does-not-exist"), 404)


async def test_full_http_lifecycle_uses_fixed_model(api, data, monkeypatch):
    result = trained(api, data)
    identity = result["model_id"]
    detail = api.get(f"/api/v1/models/{identity}")
    assert detail.status_code == 200, detail.text
    metadata = detail.json()["data"]
    assert metadata["model_type"] == "pls" and metadata["feature_names"] == ["b", "a"]
    assert metadata["training_run_id"] == result["training_run_id"]
    assert metadata["source"]["dataset_version_id"] == str(data["spec"].dataset_version_id)
    assert metadata["execution_scope"] == "api"
    assert metadata["manifest_version"] == 1 and metadata["artifact_version"] == 2
    assert str(data["root"]) not in detail.text
    assert "coefficients" not in metadata and "npz_filename" not in metadata
    before = {str(p): p.read_bytes() for p in (data["root"] / "models").rglob("*") if p.is_file()}
    async with data["factory"]() as session:
        run = await session.get(ProcessingRun, UUID(result["training_run_id"]))
        original_result = json.loads(json.dumps(run.result))
    from app.services import pls_modeling_service
    from sklearn.cross_decomposition import PLSRegression

    def forbidden(*args, **kwargs):
        raise AssertionError("HTTP prediction/evaluation must not fit")

    monkeypatch.setattr(PLSRegression, "fit", forbidden)
    monkeypatch.setattr(pls_modeling_service, "fit_pls_core", forbidden)
    for name in ("fit_pls_core", "fit_pls_on_version", "fit_pls_with_manifest"):
        monkeypatch.setattr(pls_training_service, name, forbidden)
    x = data["x"][24:32, ::-1].tolist()
    predicted = api.post(
        "/api/v1/modeling/pls/predict",
        json={"model_id": identity, "feature_names": ["b", "a"], "X": x},
    )
    assert predicted.status_code == 200, predicted.text
    assert predicted.json()["data"]["sample_count"] == 8
    outcomes = []
    for partition in ("validation", "test", "validation"):
        response = api.post(
            "/api/v1/modeling/pls/evaluate", json={"model_id": identity, "partition": partition}
        )
        assert response.status_code == 200, response.text
        evaluation = response.json()["data"]
        assert (
            evaluation["model_id"] == identity
            and evaluation["training_run_id"] == result["training_run_id"]
        )
        assert evaluation["sample_count"] == 8
        assert set(evaluation["metrics"]) == {"r2", "rmse", "mae", "nrmse"}
        outcomes.append(evaluation["evaluation_run_id"])
    assert len(set(outcomes)) == 3
    history = api.get("/api/v1/modeling/pls/evaluations", params={"model_id": identity, "limit": 1})
    assert history.status_code == 200, history.text
    assert history.json()["data"]["total"] == 3 and len(history.json()["data"]["items"]) == 1
    assert history.json()["data"]["items"][0]["status"] == "succeeded"
    filtered = api.get(
        "/api/v1/modeling/pls/evaluations",
        params={"model_id": identity, "partition": "test", "status": "succeeded"},
    )
    assert filtered.json()["data"]["total"] == 1
    assert (
        api.get("/api/v1/modeling/pls/evaluations", params={"model_id": str(uuid4())}).json()[
            "data"
        ]["total"]
        == 0
    )
    async with data["factory"]() as session:
        run = await session.get(ProcessingRun, UUID(result["training_run_id"]))
        assert run.result == original_result
        training_runs = (
            await session.scalars(
                select(ProcessingRun).where(ProcessingRun.run_type == "modeling.pls")
            )
        ).all()
        assert len(training_runs) == 1
    assert before == {
        str(p): p.read_bytes() for p in (data["root"] / "models").rglob("*") if p.is_file()
    }


async def test_manifest_failure_retains_successful_training_identity(api, data, monkeypatch):
    original = pls_training_service.fit_pls_core
    count = []

    def fit(*args, **kwargs):
        count.append(1)
        return original(*args, **kwargs)

    async def fail(*args, **kwargs):
        raise OSError("private filesystem detail must not reach client")

    monkeypatch.setattr(pls_training_service, "fit_pls_core", fit)
    monkeypatch.setattr(model_artifact_service, "publish_pls_manifest", fail)
    response = api.post("/api/v1/modeling/pls/fit", json=body(data))
    assert response.status_code == 200, response.text
    result = response.json()["data"]
    assert result["training_status"] == "succeeded" and result["manifest_status"] == "failed"
    assert result["manifest_retryable"] is True and result["retry_model_id"] == result["model_id"]
    assert result["error_code"] and len(count) == 1
    assert "private filesystem" not in response.text
    async with data["factory"]() as session:
        assert (
            await session.get(ProcessingRun, UUID(result["training_run_id"]))
        ).status == "succeeded"


@pytest.mark.parametrize("change", ["order", "columns", "ragged", "target", "rows", "cells"])
async def test_prediction_input_errors(api, data, change):
    result = trained(api, data)
    request = {"model_id": result["model_id"], "feature_names": ["b", "a"], "X": [[1, 2]]}
    if change == "order":
        request["feature_names"] = ["a", "b"]
    elif change == "columns":
        request["X"] = [[1]]
    elif change == "ragged":
        request["X"] = [[1, 2], [3]]
    elif change == "target":
        request["feature_names"] = ["b", "quality"]
    elif change == "rows":
        request["X"] = [[1, 2]] * 1001
    elif change == "cells":
        request["feature_names"] = [f"c{i}" for i in range(256)]
        request["X"] = [[1] * 256] * 400
    response = api.post("/api/v1/modeling/pls/predict", json=request)
    error(response, 400 if change in ("order", "target") else 422)


@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity"])
async def test_nonfinite_request_is_a_client_error_not_an_internal_error(api, data, number):
    identity = trained(api, data)["model_id"]
    raw = '{"model_id":"' + identity + '","feature_names":["b","a"],"X":[[' + number + ",1]]}"
    error(
        api.post(
            "/api/v1/modeling/pls/predict",
            content=raw,
            headers={"content-type": "application/json"},
        ),
        422,
    )


async def test_source_scope_and_schema_rejections(api, data):
    identity = trained(api, data, ("validation",))["model_id"]
    error(
        api.post("/api/v1/modeling/pls/evaluate", json={"model_id": identity, "partition": "test"}),
        409,
    )
    error(
        api.post(
            "/api/v1/modeling/pls/evaluate",
            json={
                "model_id": identity,
                "partition": "validation",
                "dataset_version_id": str(uuid4()),
            },
        ),
        409,
    )
    error(
        api.post(
            "/api/v1/modeling/pls/evaluate", json={"model_id": identity, "partition": "train"}
        ),
        422,
    )
    error(api.get("/api/v1/modeling/pls/evaluations"), 422)
    error(
        api.get("/api/v1/modeling/pls/evaluations", params={"model_id": identity, "limit": 101}),
        422,
    )
    bad = body(data)
    bad["artifact_root"] = "outside"
    error(api.post("/api/v1/modeling/pls/fit", json=bad), 422)


async def test_missing_and_corrupt_models_have_distinct_errors(api, data):
    error(api.get("/api/v1/models/not-a-uuid"), 422)
    error(api.get(f"/api/v1/models/{uuid4()}"), 404)
    identity = trained(api, data)["model_id"]
    (data["root"] / "models" / f"{identity}.manifest.json").write_text("{")
    response = api.get(f"/api/v1/models/{identity}")
    assert error(response, 422)["code"] == "MANIFEST_INVALID"


async def test_unconfirmed_evaluation_is_not_a_success_response(api, data, monkeypatch):
    from app.api import routes
    from app.services.pls_evaluation_service import PLSEvaluationError

    async def failed(*args, **kwargs):
        raise PLSEvaluationError(
            evaluation_run_id=uuid4(),
            model_id=kwargs["request"].model_id,
            stage="final_commit",
            outcome="unconfirmed",
        )

    monkeypatch.setattr(routes, "evaluate_saved_pls_model", failed)
    response = api.post(
        "/api/v1/modeling/pls/evaluate", json={"model_id": uuid4().hex, "partition": "validation"}
    )
    detail = error(response, 503)["details"]
    assert detail["outcome"] == "unconfirmed" and detail["evaluation_run_id"]


async def test_database_error_uses_existing_error_envelope(api, monkeypatch):
    from app.api import routes
    from sqlalchemy.exc import SQLAlchemyError

    async def failed(*args, **kwargs):
        raise SQLAlchemyError("internal connection details")

    monkeypatch.setattr(routes, "list_pls_evaluations", failed)
    response = api.get("/api/v1/modeling/pls/evaluations", params={"model_id": str(uuid4())})
    error(response, 500)
    assert "internal connection details" not in response.text


@pytest.mark.parametrize("family", ["ARX", "FIR", "OE"])
async def test_dynamic_model_details_and_type_rejection(saved, monkeypatch, family):
    from app.api import routes

    config = dict(saved.artifact["configuration"])
    config["model_type"] = family
    coefficients = dict(saved.artifact["coefficients"])
    if family == "FIR":
        config["na"] = 0
        coefficients.pop("a1")
    if family == "OE":
        config.update(estimator="ridge", ridge_alpha=0.001)
    saved.artifact.update(configuration=config, coefficients=coefficients)
    saved.payload_path.write_text(json.dumps(saved.artifact), encoding="utf-8")
    saved.run.parameters = config
    saved.run.result = {**saved.run.result, "coefficients": coefficients}
    monkeypatch.setattr(routes, "get_settings", lambda: Settings(artifact_root=saved.root))
    app = create_app()

    async def session():
        yield saved.session

    app.dependency_overrides[get_session] = session
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(f"/api/v1/models/{saved.model_id}")
        assert response.status_code == 200, response.text
        detail = response.json()["data"]
        assert detail["model_type"] == family.lower()
        assert detail["source"]["dataset_sha256"] is None
        assert detail["provenance_status"] == "incomplete"
        error(
            client.post(
                "/api/v1/modeling/pls/predict",
                json={"model_id": str(saved.model_id), "feature_names": ["u"], "X": [[1]]},
            ),
            409,
        )


async def test_pls_v1_never_gets_fabricated_details(api, data):
    from app.services.pls_artifact_service import save_pls_artifact
    from app.services.pls_modeling_service import fit_pls_core

    model = fit_pls_core(
        data["x"][:24], data["y"][:24], feature_names=("a", "b"), target_name="quality"
    )
    metadata = save_pls_artifact(model, artifact_root=data["root"])
    detail = error(api.get(f"/api/v1/models/{metadata.model_id}"), 409)
    assert detail["code"] == "MANIFEST_NOT_PUBLISHED"


async def test_training_source_validation_cannot_be_bypassed(api, data):
    request = body(data)
    request["experiment_spec"]["dataset_version_id"] = str(uuid4())
    error(api.post("/api/v1/modeling/pls/fit", json=request), 400)
    async with data["factory"]() as session:
        assert not (
            await session.scalars(
                select(ProcessingRun).where(ProcessingRun.run_type == "modeling.pls")
            )
        ).all()


async def test_training_must_be_succeeded_for_details_and_prediction(api, data):
    result = trained(api, data)
    async with data["factory"]() as session:
        run = await session.get(ProcessingRun, UUID(result["training_run_id"]))
        run.status = "running"
        await session.commit()
    response = api.get(f"/api/v1/models/{result['model_id']}")
    assert error(response, 409)["code"] == "TRAINING_RUN_NOT_SUCCEEDED"
    error(
        api.post(
            "/api/v1/modeling/pls/predict",
            json={"model_id": result["model_id"], "feature_names": ["b", "a"], "X": [[1, 2]]},
        ),
        409,
    )


async def test_failed_evaluation_is_an_error_and_has_an_independent_history_record(
    api, data, monkeypatch
):
    from app.services.pls_modeling_service import SavedPLSModel

    result = trained(api, data)

    def fail(*args, **kwargs):
        raise RuntimeError("private prediction implementation")

    monkeypatch.setattr(SavedPLSModel, "predict", fail)
    response = api.post(
        "/api/v1/modeling/pls/evaluate",
        json={"model_id": result["model_id"], "partition": "validation"},
    )
    details = error(response, 500)["details"]
    assert details["evaluation_run_id"] and details["stage"] == "predict"
    history = api.get(
        "/api/v1/modeling/pls/evaluations",
        params={"model_id": result["model_id"], "status": "failed"},
    )
    assert history.json()["data"]["total"] == 1
    assert history.json()["data"]["items"][0]["status"] == "failed"
    assert "private prediction" not in response.text
    async with data["factory"]() as session:
        assert (
            await session.get(ProcessingRun, UUID(result["training_run_id"]))
        ).status == "succeeded"


async def test_legacy_missing_target_uses_existing_loader_default(saved, monkeypatch):
    from app.api import routes

    saved.artifact["configuration"].pop("output_column", None)
    saved.payload_path.write_text(json.dumps(saved.artifact), encoding="utf-8")
    saved.run.parameters = saved.artifact["configuration"]
    monkeypatch.setattr(routes, "get_settings", lambda: Settings(artifact_root=saved.root))
    app = create_app()

    async def session():
        yield saved.session

    app.dependency_overrides[get_session] = session
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(f"/api/v1/models/{saved.model_id}")
        assert response.status_code == 200, response.text
        assert response.json()["data"]["target_name"] == "y"
        assert response.json()["data"]["provenance_status"] == "incomplete"
