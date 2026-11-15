"""Unified ARX/FIR from Agent recommendation through the durable training claim."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

import numpy as np
import pytest
from app.models.dataset import DatasetVersion
from app.services import agent_model_dispatch_service as dispatch
from app.services import agent_model_execution_service as execution
from app.services import arx_platform_adapter as arx
from app.services.arx_platform_adapter import dynamic_parameters
from app.services.model_artifact_service import load_model_instance
from app.services.model_registry import get_model, list_models, validate_parameters

from test_agent_model_recommendation import CHAT, CONFIRM
from test_model_evaluation_api import response_data
from test_pls_api import api as api
from test_pls_training_service import runs
from test_tcn_platform import data as data

pytestmark = pytest.mark.asyncio
LOOKUP = "/api/v1/copilot/modeling/execution"


async def continuous_dataset(data):
    async with data["factory"]() as session:
        version = await session.get(DatasetVersion, data["spec"].dataset_version_id)
        path = data["root"] / version.artifact_path
        header, *records = path.read_text().splitlines()
        start = datetime(2026, 1, 1, tzinfo=UTC)
        raw = ("\n".join([
            header,
            *(f"{(start + timedelta(seconds=i)).isoformat()},{row.split(',', 1)[1]}"
              for i, row in enumerate(records)),
        ]) + "\n").encode()
        path.write_bytes(raw)
        version.sha256 = sha256(raw).hexdigest()
        await session.commit()


def request(data):
    return {
        "message": "Run ARX system identification",
        "dataset_id": str(data["spec"].dataset_id),
        "active_version_id": str(data["spec"].dataset_version_id),
    }


def prepare(api, data, model):
    body = request(data)
    if model == "fir":
        body["recommendation_request"] = {
            "experiment_spec": data["spec"].model_dump(mode="json"),
            "parameters": {"fir": {
                "nb": {"a": 2, "b": 2}, "regularization_kernel": "tc", "kernel_decay": 0.8,
            }},
        }
    state = response_data(api.post(CHAT, json=body))
    assert [step["tool"] for step in state["plan"]["steps"]][-2:] == [
        "recommend_models", "confirm_model_selection",
    ]
    assert not any(step["tool"] == "fit_arx" for step in state["plan"]["steps"])
    recommendation = next(step for step in state["step_runs"] if step["tool"] == "recommend_models")
    result = recommendation["result"]["recommendation"]
    assert result["task_type"] == "dynamic_system_identification"
    assert result["recommended_models"] == ["arx", "fir", "oe"]
    candidates = {item["model_type_id"]: item for item in result["candidates"]}
    assert candidates.keys() == {"arx", "fir", "oe"}
    catalogue = {entry["model_type_id"]: entry for entry in result["catalog_models"]}
    assert catalogue.keys() == {model.model_type_id for model in list_models()}
    assert {kind for kind, entry in catalogue.items() if entry["eligibility_status"] == "eligible"} == {"arx", "fir", "oe"}
    assert all(catalogue[kind]["eligibility_status"] == "task_mismatch" for kind in ("pls", "xgboost", "tcn", "timexer"))
    assert candidates["arx"]["experiment_spec_hash"] != candidates["fir"]["experiment_spec_hash"]
    candidate = candidates[model]
    if model == "fir":
        assert candidate["experiment_spec"]["feature_spec"]["target_lags"] == []
        assert "na" not in candidate["actual_parameters"]
        assert candidate["actual_parameters"]["regularization_kernel"] == "tc"
    assert candidate["experiment_spec"]["evaluation"]["scopes"] == ["validation"]
    step_id = state["pending_confirmation_step_id"]
    assert step_id is not None
    confirmation = {
        "copilot_run_id": state["copilot_run_id"], "execution_id": state["execution_id"],
        "confirmation_id": step_id, "step_id": step_id, "approved": True, "dispatch_training": True,
        "model_selection": {
            "recommendation_step_id": recommendation["step_id"],
            "selected_model_type_id": model, "selected_parameters": candidate["actual_parameters"],
            "selection_source": "agent_recommendation" if model == "arx" else "manual",
            "experiment_spec_hash": candidate["experiment_spec_hash"],
            **{key: result["source"][key] for key in ("dataset_id", "dataset_version_id", "csv_sha256")},
        },
    }
    refs = {
        "selection_execution_id": state["execution_id"], "copilot_run_id": state["copilot_run_id"],
        "confirmed_selection_step_id": step_id,
    }
    return candidate, confirmation, refs


@pytest.mark.parametrize("model", ["arx", "fir"])
@pytest.mark.parametrize("interrupt_after_save", [False, True])
async def test_dynamic_worker_uses_locked_contract_once(api, data, monkeypatch, model, interrupt_after_save):
    await continuous_dataset(data)
    monkeypatch.setattr(dispatch, "_submit", lambda _: None)
    candidate, confirmation, refs = prepare(api, data, model)
    altered = {**confirmation, "model_selection": {
        **confirmation["model_selection"],
        "selected_parameters": {**candidate["actual_parameters"], "na": 2},
    }}
    assert api.post(CONFIRM, json=altered).status_code == 422
    incorrect_hash = {**confirmation, "model_selection": {
        **confirmation["model_selection"], "experiment_spec_hash": "0" * 64,
    }}
    assert api.post(CONFIRM, json=incorrect_hash).status_code == 422
    response_data(api.post(CONFIRM, json=confirmation))
    response_data(api.post(CONFIRM, json=confirmation))
    pending = response_data(api.get(LOOKUP, params=refs))
    assert pending["dispatch_status"] == "queued"
    assert not [run for run in await runs(data) if run.run_type == f"modeling.{model}"]

    calls = []
    original = execution._fit

    class Interrupted(BaseException):
        pass

    async def fit(*args):
        calls.append(dynamic_parameters(args[2]))
        outcome = await original(*args)
        if interrupt_after_save:
            raise Interrupted
        return outcome

    evaluate = execution.evaluate_saved_model
    evaluation_errors = []

    async def track_evaluation(*args, **kwargs):
        try:
            return await evaluate(*args, **kwargs)
        except Exception as error:
            evaluation_errors.append(repr(error.__cause__ or error))
            raise

    monkeypatch.setattr(execution, "_fit", fit)
    monkeypatch.setattr(execution, "evaluate_saved_model", track_evaluation)
    if interrupt_after_save:
        monkeypatch.setattr(execution, "JOB_TIMEOUT_SECONDS", 0)
        monkeypatch.setattr(execution, "_RECOVERY_AFTER", timedelta(0))

    async def deliver():
        await execution.run_dispatched_model(
            data["factory"], execution_id=UUID(pending["execution_id"]), artifact_root=data["root"]
        )

    if interrupt_after_save:
        with pytest.raises(Interrupted):
            await deliver()
    else:
        await deliver()
    await deliver()
    assert calls == [candidate["actual_parameters"]]
    status = response_data(api.get(LOOKUP, params=refs))
    assert status["training_status"] == "succeeded", status
    assert status["manifest_status"] == "published"
    async with data["factory"]() as session:
        loaded = await load_model_instance(
            session, model_id=UUID(status["model_id"]), artifact_root=data["root"],
        )
    assert str(loaded.training_run_id) == status["training_run_id"]
    assert loaded.manifest.experiment_spec_hash == candidate["experiment_spec_hash"]
    assert loaded.model_type_id == model
    assert loaded.manifest.payload_uri == f"models/{model}/{status['model_id']}.json"
    if model == "fir":
        assert loaded.payload.structure.na == 0
        assert loaded.payload.payload.regularization_kernel == "tc"
    if interrupt_after_save:
        assert status["evaluation_status"] in {"pending", "unconfirmed"}
        return
    assert not evaluation_errors, evaluation_errors
    assert status["evaluation_status"] == "succeeded", status["evaluation_error"]
    evaluated = status["evaluation"]
    assert evaluated["model_id"] == status["model_id"]
    assert evaluated["training_run_id"] == status["training_run_id"]
    assert evaluated["partition"] == "validation"
    if model == "arx":
        assert evaluated["validation"]["free_run"]["fit"] is not None
    else:
        assert "validation" not in evaluated
        assert evaluated["metrics"]["rmse"] >= 0
    assert status["comparison_status"] == "not_comparable"
    evaluation_runs = [run for run in await runs(data) if run.run_type == "modeling.model_evaluation"]
    assert [run.parameters["partition"] for run in evaluation_runs] == ["validation"]
    url = f"/api/v1/modeling/evaluations/{evaluated['evaluation_run_id']}/predictions"
    response = api.get(url)
    assert response.status_code == 200, response.text
    artifact = response.json()
    assert artifact["partition"] == "validation"
    assert artifact["experiment_spec_hash"] == candidate["experiment_spec_hash"]
    assert artifact["model_id"] == status["model_id"]
    assert artifact["training_run_id"] == status["training_run_id"]
    horizon = artifact["horizons"][0]
    assert max(horizon["source_row_index"]) < loaded.manifest.experiment_spec.split.test[0].start
    assert np.allclose(
        np.asarray(horizon["y_true"]) - np.asarray(horizon["y_pred"]), horizon["residual"],
    )
    if model == "arx":
        assert np.allclose(
            np.asarray(horizon["y_true"]) - np.asarray(artifact["prediction_modes"]["one_step"]),
            artifact["prediction_modes"]["one_step_residual"],
        )
    else:
        assert "prediction_modes" not in artifact


async def test_arx_preflight_changes_hash_and_excludes_unsupported_training(data):
    from app.schemas.experiment_spec import RowRange, TimeAxis
    from app.services.experiment_spec_service import spec_hash
    from app.services.version_data import load_version_series

    await continuous_dataset(data)
    async with data["factory"]() as session:
        version = await session.get(DatasetVersion, data["spec"].dataset_version_id)
        spec_args = {
            "version": version, "inputs": ("a", "b"), "target": "quality",
            "axis": TimeAxis(column="timestamp", sampling_status="uniform", sample_period_seconds=1),
            "runs": (RowRange(start=0, stop=version.row_count),),
        }
        series = await load_version_series(
            session, version_id=version.id, artifact_root=data["root"], dataset_id=version.dataset_id
        )
        default = await arx.build_arx_spec(session, **spec_args, overrides={})
        wider = await arx.build_arx_spec(session, **spec_args, overrides={"na": 2})
        selected = await arx.build_arx_spec(session, **spec_args, overrides={"training_sample_indices": [3]})
        assert spec_hash(default) != spec_hash(wider)
        assert arx.validate_arx_source(default, series)[1] != arx.validate_arx_source(wider, series)[1]
        with pytest.raises(ValueError, match="full-Train"):
            arx.validate_arx_source(selected, series)


async def test_fir_preference_constraints_and_parameter_hash(api, data):
    await continuous_dataset(data)
    assert get_model("fir").supported_tasks == ("dynamic_system_identification",)
    dataset = data["spec"].model_dump(mode="json")

    def recommend(overrides):
        body = request(data)
        body["message"] = "Run FIR system identification"
        body["recommendation_request"] = {
            "experiment_spec": dataset, "parameters": {"fir": overrides},
        }
        snapshot = response_data(api.post(CHAT, json=body))
        step = next(item for item in snapshot["step_runs"] if item["tool"] == "recommend_models")
        return step["result"]["recommendation"]

    one = recommend({"nb": {"a": 1, "b": 1}})
    two = recommend({"nb": {"a": 2, "b": 1}})
    assert one["recommended_models"] == two["recommended_models"] == ["fir", "arx", "oe"]
    fir_one = next(item for item in one["candidates"] if item["model_type_id"] == "fir")
    fir_two = next(item for item in two["candidates"] if item["model_type_id"] == "fir")
    assert fir_one["experiment_spec_hash"] != fir_two["experiment_spec_hash"]
    with pytest.raises(ValueError, match="TC"):
        validate_parameters("fir", {**fir_one["actual_parameters"], "regularization_kernel": "tc", "standardize": False})
    rejected = recommend({"na": 1, "regularization_kernel": "tc"})
    assert rejected["recommended_models"] == ["arx", "oe"]
    assert "fir" in rejected["excluded_models"]
    fir_entry = next(item for item in rejected["catalog_models"] if item["model_type_id"] == "fir")
    assert fir_entry["eligibility_status"] == "excluded"
    assert fir_entry["reasons"] == rejected["excluded_models"]["fir"]
