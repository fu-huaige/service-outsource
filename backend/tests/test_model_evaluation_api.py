"""Unified evaluation HTTP endpoints over synthetic, isolated SQLite runs."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.api import routes
from app.models.dataset import ProcessingRun
from app.services import model_evaluation_service as evaluation
from app.services import pls_modeling_service
from sklearn.cross_decomposition import PLSRegression
from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError

from test_model_evaluation_service import (
    forbid_tcn_training,
    forbid_timexer_training,
    snapshot_files,
    tcn_spec,
)
from test_pls_api import api as api
from test_pls_api import error, trained
from test_pls_training_service import runs
from test_tcn_platform import data as data
from test_tcn_platform import fit as fit_tcn
from test_tcn_platform import no_training
from test_timexer_platform import fit as fit_timexer
from test_xgboost_api import fit as fit_xgboost

pytestmark = pytest.mark.asyncio
BASE = "/api/v1/modeling"


def response_data(response):
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True and body["error"] is None and body["request_id"]
    return body["data"]


def post_evaluation(api, model_id, partition="validation"):
    return api.post(f"{BASE}/evaluate", json={"model_id": str(model_id), "partition": partition})


def forbid_evaluation_execution(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("History and detail must not execute evaluation, loading or prediction")

    monkeypatch.setattr(routes, "evaluate_saved_model", forbidden)
    monkeypatch.setattr(evaluation, "load_model_instance", forbidden)
    monkeypatch.setattr(evaluation, "predict_saved_timexer", forbidden)
    for model in (evaluation.SavedPLSModel, evaluation.SavedXGBoostModel, evaluation.TCNModel):
        monkeypatch.setattr(model, "predict", forbidden)


@pytest.mark.parametrize("model_type", ["pls", "xgboost", "tcn", "timexer"])
async def test_unified_evaluation_uses_the_saved_model(api, data, monkeypatch, model_type):
    spec = tcn_spec(data)
    if model_type == "pls":
        model_id = trained(api, data)["model_id"]
    elif model_type == "xgboost":
        model_id = fit_xgboost(api, {**data, "spec": spec})["model_id"]
    elif model_type == "tcn":
        model_id = str((await fit_tcn(data, spec)).model_id)
    else:
        model_id = str((await fit_timexer(data, spec=spec)).model_id)

    (training,) = await runs(data)
    artifact_bytes = snapshot_files(data["root"])
    forbid_tcn_training(monkeypatch)
    forbid_timexer_training(monkeypatch)
    monkeypatch.setattr(PLSRegression, "fit", no_training)
    monkeypatch.setattr(pls_modeling_service, "fit_pls_core", no_training)
    for name in (
        "fit_pls_with_manifest",
        "fit_xgboost_on_version",
        "fit_tcn_on_version",
        "fit_timexer_on_version",
    ):
        monkeypatch.setattr(routes, name, no_training)
    real_evaluate = evaluation.evaluate_saved_model
    calls = []

    async def record(*args, **kwargs):
        outcome = await real_evaluate(*args, **kwargs)
        calls.append(outcome.model_dump(mode="json"))
        return outcome

    monkeypatch.setattr(routes, "evaluate_saved_model", record)
    first = response_data(post_evaluation(api, model_id))
    second = response_data(post_evaluation(api, model_id, "test"))
    assert calls == [first, second]
    assert first["evaluation_run_id"] != second["evaluation_run_id"]

    forbid_evaluation_execution(monkeypatch)
    for result, partition in zip((first, second), ("validation", "test"), strict=True):
        assert result["model_type_id"] == model_type and result["model_id"] == model_id
        assert result["training_run_id"] == str(training.id)
        assert result["dataset_version_id"] == str(data["spec"].dataset_version_id)
        assert result["partition"] == partition and result["sample_count"] > 0
        assert result["evaluation_status"] == "succeeded"
        assert set(result["metrics"]) == {"r2", "rmse", "mae", "nrmse"}
        response = api.get(f"{BASE}/evaluations/{result['evaluation_run_id']}")
        details = response_data(response)
        assert details["status"] == "succeeded" and details["model_id"] == model_id
        assert details["result"] == result
        assert details["parameters"]["actual_rows"] == result["actual_rows"]
        assert details["parameters"]["dataset_version_id"] == result["dataset_version_id"]
        assert str(data["root"]) not in response.text
        if model_type == "timexer":
            assert result["forecast_spec"]["prediction_length"] == 3
            assert [step["horizon_step"] for step in result["horizon_metrics"]] == [1, 2, 3]
            assert len(result["target_rows_by_horizon"]) == 3 and result["target_rows"]["ranges"]
            assert result["metric_aggregation"]["method"] == "macro_average"
            for key, aggregate in result["metrics"].items():
                values = [step[key] for step in result["horizon_metrics"] if step[key] is not None]
                if values:
                    assert aggregate == pytest.approx(sum(values) / len(values))
                else:
                    assert aggregate is None
    persisted = {run.id: run for run in await runs(data)}
    assert len(persisted) == 3
    assert persisted[training.id].parameters == training.parameters
    assert persisted[training.id].result == training.result
    assert persisted[training.id].status == training.status
    assert persisted[training.id].finished_at == training.finished_at
    assert snapshot_files(data["root"]) == artifact_bytes


async def test_history_filters_stable_pagination_and_run_type_isolation(api, data, monkeypatch):
    first = trained(api, data)
    other = fit_xgboost(api, data)
    model_id = first["model_id"]
    complete = {
        partition: response_data(post_evaluation(api, model_id, partition))
        for partition in ("validation", "test")
    }
    other_run = response_data(post_evaluation(api, other["model_id"]))
    legacy = response_data(
        api.post(f"{BASE}/pls/evaluate", json={"model_id": model_id, "partition": "validation"})
    )
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    running_id, failed_id = uuid4(), uuid4()
    async with data["factory"]() as session:
        await session.execute(
            update(ProcessingRun)
            .where(ProcessingRun.run_type == evaluation.RUN_TYPE)
            .values(created_at=created_at)
        )
        for run_id, status in ((running_id, "running"), (failed_id, "failed")):
            result = {"model_id": model_id, "evaluation_run_id": str(run_id)}
            if status == "failed":
                result["evaluation"] = {
                    "partition": "test",
                    "evaluation_status": "failed",
                    "failure_stage": "load_model",
                    "error_type": "InternalLoaderError",
                    "implementation_version": "model-evaluation-1",
                    "internal_path": r"E:\private\artifact.json",
                }
            session.add(
                ProcessingRun(
                    id=run_id,
                    run_type=evaluation.RUN_TYPE,
                    status=status,
                    created_at=created_at,
                    parameters={
                        "model_id": model_id,
                        "partition": "test",
                        "prediction_mode": "prediction",
                    },
                    result=result,
                )
            )
        await session.commit()

    forbid_evaluation_execution(monkeypatch)
    all_rows = response_data(api.get(f"{BASE}/evaluations"))
    assert all_rows["total"] == 5 and all_rows["offset"] == 0 and all_rows["limit"] == 20
    items = all_rows["items"]
    all_ids = [row["evaluation_run_id"] for row in items]
    assert all_ids == sorted(all_ids, reverse=True)
    assert set(all_ids) == {
        str(running_id),
        str(failed_id),
        other_run["evaluation_run_id"],
        *(item["evaluation_run_id"] for item in complete.values()),
    }
    assert all("predictions" not in row and "horizon_metrics" not in row for row in items)
    assert all(row["created_at"] for row in items)
    assert (
        next(row for row in items if row["evaluation_run_id"] == str(running_id))["metrics"] is None
    )

    first_ids = [row["evaluation_run_id"] for row in items if row["model_id"] == model_id]
    pages = [
        response_data(
            api.get(
                f"{BASE}/evaluations", params={"model_id": model_id, "offset": offset, "limit": 2}
            )
        )
        for offset in (0, 2, 4)
    ]
    assert [p["total"] for p in pages] == [4, 4, 4]
    assert [p["offset"] for p in pages] == [0, 2, 4]
    assert all(p["limit"] == 2 for p in pages)
    assert [row["evaluation_run_id"] for page in pages for row in page["items"]] == first_ids
    filters = {"model_id": model_id, "partition": "test", "status": "succeeded", "limit": 1}
    filtered = response_data(api.get(f"{BASE}/evaluations", params=filters))
    assert filtered["total"] == 1
    assert filtered["items"][0]["evaluation_run_id"] == complete["test"]["evaluation_run_id"]
    assert filtered["items"][0]["metrics"] == complete["test"]["metrics"]
    for status, run_id in (("failed", failed_id), ("running", running_id)):
        result = response_data(api.get(f"{BASE}/evaluations", params={**filters, "status": status}))
        assert result["total"] == 1 and result["items"][0]["evaluation_run_id"] == str(run_id)
    other_page = response_data(
        api.get(f"{BASE}/evaluations", params={"model_id": other["model_id"]})
    )
    assert other_page["total"] == 1 and other_page["items"][0]["model_id"] == other["model_id"]

    failed_response = api.get(f"{BASE}/evaluations/{failed_id}")
    failed = response_data(failed_response)
    assert failed["status"] == "failed" and failed["result"]["failure_stage"] == "load_model"
    assert (
        "internal_path" not in failed_response.text
        and "InternalLoaderError" not in failed_response.text
    )
    running = response_data(api.get(f"{BASE}/evaluations/{running_id}"))
    assert running["status"] == "running" and running["result"] is None
    for run_id in (first["training_run_id"], legacy["evaluation_run_id"], uuid4()):
        assert (
            error(api.get(f"{BASE}/evaluations/{run_id}"), 404)["code"]
            == "MODEL_EVALUATION_NOT_FOUND"
        )


async def test_validation_not_found_and_version_errors_use_existing_envelopes(
    api, data, monkeypatch
):
    model_id = trained(api, data, scopes=("validation",))["model_id"]
    assert error(post_evaluation(api, uuid4()), 404)["code"] == "MODEL_NOT_FOUND"
    assert (
        error(post_evaluation(api, model_id, "test"), 409)["code"]
        == "MODEL_EVALUATION_SCOPE_NOT_ALLOWED"
    )
    for payload in (
        {"model_id": model_id, "partition": "validation", "model_type": "timexer"},
        {"model_id": model_id, "partition": "train"},
        {"model_id": "invalid", "partition": "validation"},
    ):
        assert (
            error(api.post(f"{BASE}/evaluate", json=payload), 422)["code"]
            == "REQUEST_VALIDATION_FAILED"
        )
    for params in ({"limit": 101}, {"offset": -1}, {"offset": 2**63}, {"status": "unconfirmed"}):
        assert (
            error(api.get(f"{BASE}/evaluations", params=params), 422)["code"]
            == "REQUEST_VALIDATION_FAILED"
        )
    assert error(api.get(f"{BASE}/evaluations/invalid"), 422)["code"] == "REQUEST_VALIDATION_FAILED"

    read = evaluation.load_version_series

    async def mutate_source(*args, **kwargs):
        series = await read(*args, **kwargs)
        (data["root"] / "source.csv").write_bytes(b"changed after reading")
        return series

    monkeypatch.setattr(evaluation, "load_version_series", mutate_source)
    rejected = error(post_evaluation(api, model_id), 409)
    assert rejected["code"] == "DATASET_VERSION_MISMATCH"
    rejected_detail = response_data(
        api.get(f"{BASE}/evaluations/{rejected['details']['evaluation_run_id']}")
    )
    assert (
        rejected_detail["status"] == "failed"
        and rejected_detail["result"]["failure_stage"] == "read_data"
    )


async def test_unconfirmed_and_database_errors_are_client_safe(api, monkeypatch):
    run_id, model_id = uuid4(), uuid4()

    async def unconfirmed(*args, **kwargs):
        raise evaluation.ModelEvaluationError(
            evaluation_run_id=run_id, model_id=model_id, stage="final_commit", outcome="unconfirmed"
        ) from SQLAlchemyError("private database information")

    async def database_failure(*args, **kwargs):
        raise SQLAlchemyError("private database information")

    monkeypatch.setattr(routes, "evaluate_saved_model", unconfirmed)
    response = post_evaluation(api, model_id)
    unavailable = error(response, 503)
    assert unavailable["code"] == "MODEL_EVALUATION_UNCONFIRMED"
    assert unavailable["details"]["evaluation_run_id"] == str(run_id)
    assert "private database information" not in response.text

    monkeypatch.setattr(routes, "list_model_evaluations", database_failure)
    monkeypatch.setattr(routes, "get_model_evaluation", database_failure)
    for url in (f"{BASE}/evaluations", f"{BASE}/evaluations/{run_id}"):
        response = api.get(url)
        assert error(response, 500)["code"] == "SYSTEM_INTERNAL_ERROR"
        assert "private database information" not in response.text
