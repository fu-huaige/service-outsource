"""Real nonlinear OE fitting and fixed prediction through the Agent contract."""

from uuid import UUID

import numpy as np
import pytest
from app.services import agent_model_dispatch_service as dispatch
from app.services import agent_model_execution_service as execution
from app.services import model_artifact_service as artifacts
from app.services import modeling_service
from rq.timeouts import JobTimeoutException

from test_agent_arx_platform import LOOKUP, continuous_dataset, request
from test_agent_model_recommendation import CHAT, CONFIRM
from test_model_evaluation_api import response_data
from test_pls_api import api as api
from test_pls_training_service import runs
from test_tcn_platform import data as data

pytestmark = pytest.mark.asyncio


def recommend(api, data, **overrides):
    body = {
        **request(data),
        "message": "Fit an OE output error model",
        "recommendation_request": {
            "experiment_spec": data["spec"].model_dump(mode="json"),
            "parameters": {"oe": {"na": 1, "simulation_horizons": [1, 8, 0], **overrides}},
        },
    }
    state = response_data(api.post(CHAT, json=body))
    assert "fit_arx" not in [step["tool"] for step in state["plan"]["steps"]]
    step = next(item for item in state["step_runs"] if item["tool"] == "recommend_models")
    result = step["result"]["recommendation"]
    oe = next(item for item in result["candidates"] if item["model_type_id"] == "oe")
    return state, step, result, oe


def authorize(api, data, **overrides):
    state, recommendation, result, oe = recommend(api, data, **overrides)
    assert result["recommended_models"][0] == "oe", oe
    assert {entry["model_type_id"] for entry in result["candidates"]} == {"arx", "fir", "oe"}
    step_id = state["pending_confirmation_step_id"]
    refs = {
        "selection_execution_id": state["execution_id"], "copilot_run_id": state["copilot_run_id"],
        "confirmed_selection_step_id": step_id,
    }
    confirmation = {
        "copilot_run_id": state["copilot_run_id"], "execution_id": state["execution_id"],
        "confirmation_id": step_id, "step_id": step_id, "approved": True, "dispatch_training": True,
        "model_selection": {
            "recommendation_step_id": recommendation["step_id"],
            "selected_model_type_id": "oe", "selected_parameters": oe["actual_parameters"],
            "selection_source": "agent_recommendation", "experiment_spec_hash": oe["experiment_spec_hash"],
            **{key: result["source"][key] for key in ("dataset_id", "dataset_version_id", "csv_sha256")},
        },
    }
    wrong = {**confirmation, "model_selection": {
        **confirmation["model_selection"], "experiment_spec_hash": result["source"]["experiment_spec_hash"],
    }}
    assert api.post(CONFIRM, json=wrong).status_code == 422
    response_data(api.post(CONFIRM, json=confirmation))
    status = response_data(api.get(LOOKUP, params=refs))
    assert status["dispatch_status"] == "queued"
    return UUID(status["execution_id"]), refs, oe


async def test_oe_qualification_train_rows_and_hashes(api, data):
    await continuous_dataset(data)
    _, _, result, eligible = recommend(api, data, sample_weights={"30": 0})
    assert result["recommended_models"][0] == "oe"
    contract = eligible["experiment_spec"]["oe_contract"]
    assert contract["parameters"]["simulation_horizons"] == [1, 8, 0]
    assert contract["simulation_intervals"] == [
        {"start": 1, "stop": 30, "history_start": 0},
        {"start": 32, "stop": 60, "history_start": 31},
    ]
    assert eligible["training_sample_count"] == 57
    _, _, _, changed = recommend(api, data, sample_weights={"30": 0}, simulation_horizons=[1, 0])
    assert eligible["experiment_spec_hash"] != changed["experiment_spec_hash"]
    for overrides, reason in [
        ({"sample_weights": {"30": .5}}, "0/1"),
        ({"sample_weights": {"5": 0}}, "interval"),
        ({"sample_weights": {"95": 0}}, "Train"),
        ({"na": 5}, "1–4"),
        ({"initialization_policy": "past_residual"}, "OE"),
    ]:
        _, _, unavailable, candidate = recommend(api, data, **overrides)
        assert candidate["eligibility_status"] == "excluded"
        assert "oe" not in unavailable["recommended_models"]
        assert reason in " ".join(candidate["reasons"])


@pytest.mark.parametrize("interrupted", [False, True])
async def test_oe_worker_fixed_prediction_and_checkpoint(api, data, monkeypatch, interrupted):
    await continuous_dataset(data)
    submitted = []
    monkeypatch.setattr(dispatch, "_submit", submitted.append)
    execution_id, refs, candidate = authorize(api, data, sample_weights={"30": 0})
    assert submitted == [execution_id]
    original = modeling_service.fit_multihorizon
    calls = []

    def track(experiments, **options):
        calls.append((options["horizons"], [(item.start, item.stop) for item in experiments]))
        assert options["max_nfev"] == 150
        assert all(np.isnan(item.output[81:]).all() for item in experiments)
        return original(experiments, **options)

    monkeypatch.setattr(modeling_service, "fit_multihorizon", track)

    class WorkerExited(BaseException):
        pass

    publish = artifacts.publish_verified_manifest

    def interrupt(root, manifest):
        if manifest.model_type_id == "oe":
            raise WorkerExited()
        return publish(root, manifest)

    async def deliver():
        await execution.run_dispatched_model(
            data["factory"], execution_id=execution_id, artifact_root=data["root"],
        )

    if interrupted:
        monkeypatch.setattr(artifacts, "publish_verified_manifest", interrupt)
        with pytest.raises(WorkerExited):
            await deliver()
        pending = next(run for run in await runs(data) if run.run_type == "modeling.oe")
        assert pending.status == "running" and pending.result["payload_sha256"]
        await dispatch._recover_oe_publications(data["factory"])
        assert submitted == [execution_id, execution_id]
        monkeypatch.setattr(artifacts, "publish_verified_manifest", publish)

    await deliver()
    await deliver()
    assert calls == [((1, 8, 0), [(1, 30), (32, 60)])]
    result = response_data(api.get(LOOKUP, params=refs))
    assert result["training_status"] == result["evaluation_status"] == "succeeded", result
    assert result["manifest_status"] == "published"
    assert result["comparison_status"] == "not_comparable"
    model_id = UUID(result["model_id"])
    async with data["factory"]() as session:
        loaded = await artifacts.load_model_instance(session, model_id=model_id, artifact_root=data["root"])
    assert loaded.manifest.experiment_spec_hash == candidate["experiment_spec_hash"]
    assert loaded.manifest.effective_training_rows.count == 57
    assert loaded.manifest.payload_uri == f"models/oe/{model_id}.json"
    assert str(loaded.training_run_id) == result["training_run_id"]
    evaluation = result["evaluation"]
    assert evaluation["partition"] == "validation" and evaluation["prediction_mode"] == "free_run"
    predictions = f"/api/v1/modeling/evaluations/{result['evaluation_run_id']}/predictions"
    response = api.get(predictions)
    assert response.status_code == 200, response.text
    assert api.get(predictions).content == response.content
    artifact = response.json()
    assert artifact["model_id"] == str(model_id) and artifact["training_run_id"] == result["training_run_id"]
    assert artifact["experiment_spec_hash"] == candidate["experiment_spec_hash"]
    assert artifact["prediction_mode"] == "free_run"
    assert artifact["initialization_rows"] == {"start": 61, "stop": 62}
    series = artifact["horizons"][0]
    assert min(series["source_row_index"]) >= 62 and max(series["source_row_index"]) < 81
    np.testing.assert_allclose(np.asarray(series["y_true"]) - series["y_pred"], series["residual"])
    records = await runs(data)
    assert [str(run.id) for run in records if run.run_type == "modeling.oe"] == [result["training_run_id"]]
    evaluation_runs = [run for run in records if run.run_type == "modeling.model_evaluation"]
    assert [run.parameters["partition"] for run in evaluation_runs] == ["validation"]


@pytest.mark.parametrize("timeout", [False, True])
async def test_oe_solver_failure_is_not_published(api, data, monkeypatch, timeout):
    await continuous_dataset(data)
    monkeypatch.setattr(dispatch, "_submit", lambda _: None)
    execution_id, refs, _ = authorize(api, data)

    def fail(*args, **kwargs):
        if timeout:
            raise JobTimeoutException("RQ time limit")
        raise modeling_service.ModelingDomainError("OE_NOT_CONVERGED", "solver exceeded evaluation budget")

    monkeypatch.setattr(modeling_service, "fit_multihorizon", fail)
    await execution.run_dispatched_model(
        data["factory"], execution_id=execution_id, artifact_root=data["root"],
    )
    status = response_data(api.get(LOOKUP, params=refs))
    assert status["training_status"] == "failed" and status["model_id"] is None
    assert status["training_error"] == ("OE_OPTIMIZER_TIMEOUT" if timeout else "OE_NOT_CONVERGED")
    assert not list(data["root"].glob("models/**/*.json"))
