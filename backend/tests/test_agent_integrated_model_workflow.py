"""One durable Agent task from analysis through explicit model execution."""

import asyncio
from datetime import timedelta
from uuid import UUID

import pytest
from algorithms.agent.llm import NullProvider
from algorithms.agent.planner import RuleBasedPlanner, parse_intent
from app.models.dataset import DatasetVersion
from app.schemas.copilot import CopilotConfirmRequest
from app.services import agent_model_execution_service, agent_service
from app.services.agent_execution_service import get_execution
from app.services.agent_tool_adapter import AgentToolResult
from sqlalchemy.exc import SQLAlchemyError

from test_agent_chat_execution import _benchmark_version
from test_agent_chat_execution import chat_harness as chat_harness
from test_agent_model_execution import EXECUTE
from test_agent_model_recommendation import CHAT, CONFIRM, chat_body, choice
from test_model_evaluation_api import response_data
from test_model_evaluation_service import tcn_spec
from test_pls_api import api as api
from test_pls_api import error
from test_pls_training_service import runs
from test_tcn_platform import data as data

LOOKUP = "/api/v1/copilot/modeling/execution"


def test_real_cleaning_advances_version_before_automatic_recommendation(chat_harness):
    api = chat_harness.client
    original = _benchmark_version(api)
    chat = response_data(
        api.post(
            CHAT,
            json={
                "message": "清洗数据，然后选择合适的模型建模",
                "active_version_id": original,
            },
        )
    )
    state = snapshot(api, chat["execution_id"])
    cleaning = next(step for step in state["step_runs"] if step["tool"] == "clean_data")
    assert cleaning["status"] == "SUCCEEDED"
    assert cleaning["source_version_id"] == original
    assert cleaning["result_version_id"] == state["current_version_id"] != original
    assert cleaning["processing_run_ids"]
    recommendation, selection = state["step_runs"][-2:]
    assert recommendation["status"] == "SUCCEEDED"
    assert selection["status"] == "WAITING_CONFIRMATION"
    assert state["pending_confirmation_step_id"] == selection["step_id"]
    spec = recommendation["input_payload"]["recommendation_request"]["experiment_spec"]
    assert spec["dataset_version_id"] == state["current_version_id"]
    source = recommendation["result_payload"]["recommendation"]["source"]
    assert source["csv_sha256"] == spec["dataset_version_sha256"]


def snapshot(api, identity):
    return response_data(api.get(f"/api/v1/copilot/executions/{identity}"))


def spec_confirmation(execution, request):
    step = execution["pending_confirmation_step_id"]
    return {
        "copilot_run_id": execution["copilot_run_id"],
        "execution_id": execution["execution_id"],
        "confirmation_id": step,
        "step_id": step,
        "approved": True,
        "recommendation_request": request,
    }


def selected(execution, model, *, source="manual", overrides=None):
    recommendation = next(
        step for step in execution["step_runs"] if step["tool"] == "recommend_models"
    )
    return choice(
        {
            **execution,
            "step_runs": [
                {
                    "step_id": recommendation["step_id"],
                    "result": recommendation["result_payload"],
                }
            ],
        },
        model,
        source=source,
        overrides=overrides,
    )


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            "分析数据缺失、异常和共线性",
            ["profile_dataset", "detect_anomalies", "analyze_collinearity"],
        ),
        (
            "分析数据质量，然后选择合适的模型进行建模和评价",
            ["profile_dataset", "detect_anomalies", "recommend_models", "confirm_model_selection"],
        ),
        (
            "用 ARX 建模",
            [
                "profile_dataset",
                "estimate_delays",
                "apply_lag_compensation",
                "detect_dynamic_segments",
                "fit_arx",
                "evaluate_model",
            ],
        ),
        ("用 TimeXer 建模", ["profile_dataset", "recommend_models", "confirm_model_selection"]),
        ("建立最佳回归模型", ["profile_dataset", "recommend_models", "confirm_model_selection"]),
        ("查看模型数据", ["profile_dataset"]),
    ],
)
def test_rule_based_paths(message, expected):
    steps, _, _ = RuleBasedPlanner().plan(parse_intent(message))
    assert [step.tool for step in steps] == expected


@pytest.mark.asyncio
async def test_preprocessing_final_version_gate_lock_train_and_read_only_recovery(
    api, data, monkeypatch
):
    original = data["spec"]
    async with data["factory"]() as session:
        derived = await session.get(DatasetVersion, data["latest"])
        derived.parent_version_id = original.dataset_version_id
        await session.commit()
        final_sha = derived.sha256

    calls = []
    real_tool = agent_service.execute_agent_tool

    async def cleaning(session, *, execution, step, **kwargs):
        if step.tool_name != "clean_data":
            return await real_tool(session, execution=execution, step=step, **kwargs)
        calls.append(execution.current_version_id)
        return AgentToolResult(
            summary="Fixture points to a different immutable CSV",
            source_version_id=execution.current_version_id,
            result_version_id=data["latest"],
            processing_run_ids=[],
            result_payload={},
        )

    monkeypatch.setattr(agent_service, "execute_agent_tool", cleaning)
    monkeypatch.setattr(agent_service, "_resolve_provider", lambda: NullProvider())
    body = chat_body(data, "清洗并分析数据质量，然后选择合适的模型建模和评价")
    stale = body.pop("recommendation_request")
    chat = response_data(api.post(CHAT, json=body))
    parent_id = chat["execution_id"]
    paused = snapshot(api, parent_id)
    assert paused["workflow_status"] == "WAITING_CONFIRMATION"
    assert paused["current_version_id"] == str(data["latest"])
    assert [step["tool"] for step in paused["step_runs"]] == [
        "profile_dataset",
        "detect_anomalies",
        "clean_data",
        "recommend_models",
        "confirm_model_selection",
    ]
    assert [step["status"] for step in paused["step_runs"]] == [
        "SUCCEEDED",
        "SUCCEEDED",
        "SUCCEEDED",
        "WAITING_CONFIRMATION",
        "PENDING",
    ]
    error(api.post(CONFIRM, json=spec_confirmation(paused, stale)), 409)
    assert snapshot(api, parent_id) == paused

    final_spec = tcn_spec(data).model_copy(
        update={
            "dataset_version_id": data["latest"],
            "dataset_version_sha256": final_sha,
        }
    )
    request = {**stale, "experiment_spec": final_spec.model_dump(mode="json")}
    invalid_sha = {
        **request,
        "experiment_spec": {**request["experiment_spec"], "dataset_version_sha256": "0" * 64},
    }
    error(api.post(CONFIRM, json=spec_confirmation(paused, invalid_sha)), 422)
    assert snapshot(api, parent_id) == paused
    submitted = spec_confirmation(paused, request)
    result = response_data(api.post(CONFIRM, json=submitted))
    assert result["execution_id"] == parent_id
    ready = snapshot(api, parent_id)
    assert ready["step_runs"][:3] == paused["step_runs"][:3]
    rec, selection = ready["step_runs"][3:]
    assert rec["source_version_id"] == str(data["latest"])
    assert rec["result_payload"]["recommendation"]["source"]["csv_sha256"] == final_sha
    assert rec["result_payload"]["analysis_steps"][2]["result_version_id"] == str(data["latest"])
    assert selection["status"] == "WAITING_CONFIRMATION"
    assert selection["input_payload"]["recommendation_step_id"] == rec["step_id"]
    assert response_data(api.post(CONFIRM, json=submitted))["execution_id"] == parent_id
    error(
        api.post(
            CONFIRM,
            json={
                **submitted,
                "recommendation_request": {**request, "goal": "nonlinear_regression"},
            },
        ),
        409,
    )
    assert not [run for run in await runs(data) if run.run_type.startswith("modeling.")]

    refs = {
        "selection_execution_id": parent_id,
        "copilot_run_id": ready["copilot_run_id"],
        "confirmed_selection_step_id": selection["step_id"],
    }
    error(api.post(EXECUTE, json=refs), 409)
    response_data(api.post(CONFIRM, json=selected(ready, "pls", overrides={"n_components": 1})))
    locked = snapshot(api, parent_id)
    assert (
        locked["step_runs"][-1]["result_payload"]["model_selection"]["parameters"]["n_components"]
        == 1
    )
    assert not [run for run in await runs(data) if run.run_type.startswith("modeling.")]
    assert response_data(api.get(LOOKUP, params=refs)) is None

    real_fit = agent_model_execution_service._fit
    fits = []

    async def track_fit(factory, spec, params, forecast, root):
        fits.append((spec.dataset_version_id, params.n_components))
        return await real_fit(factory, spec, params, forecast, root)

    monkeypatch.setattr(agent_model_execution_service, "_fit", track_fit)
    trained = response_data(api.post(EXECUTE, json=refs))
    assert trained["training_status"] == "succeeded"
    assert trained["evaluation_status"] == "succeeded"
    assert trained["evaluation"]["model_id"] == trained["model_id"]
    assert trained["comparison_status"] == "not_comparable"
    assert response_data(api.get(LOOKUP, params=refs)) == trained
    assert response_data(api.post(EXECUTE, json=refs)) == trained
    assert fits == [(data["latest"], 1)]
    assert calls == [original.dataset_version_id]
    assert snapshot(api, parent_id) == locked


@pytest.mark.asyncio
async def test_current_spec_reuses_gate_and_rejects_ineligible_manual_choices(api, data):
    body = chat_body(data, "分析数据后选择模型建模")
    request = body["recommendation_request"]
    request["experiment_spec"]["time_axis"]["sampling_status"] = "unknown"
    request["parameters"] = {**request["parameters"], "pls": {"n_components": 100}}
    chat = response_data(api.post(CHAT, json=body))
    state = snapshot(api, chat["execution_id"])
    assert state["step_runs"][-2]["status"] == "SUCCEEDED"
    assert state["step_runs"][-1]["status"] == "WAITING_CONFIRMATION"
    for model, eligibility in (("pls", "excluded"), ("tcn", "unknown")):
        recommendation = state["step_runs"][-2]["result_payload"]["recommendation"]
        candidate = next(
            item for item in recommendation["candidates"] if item["model_type_id"] == model
        )
        assert candidate["eligibility_status"] == eligibility
        failure = error(api.post(CONFIRM, json=selected(state, model, overrides={})), 422)
        assert failure["code"] == "MODEL_SELECTION_UNAVAILABLE"
    assert snapshot(api, chat["execution_id"]) == state
    assert not [run for run in await runs(data) if run.run_type.startswith("modeling.")]


@pytest.mark.asyncio
async def test_spec_commit_failure_keeps_original_gate(api, data, monkeypatch):
    body = chat_body(data, "分析数据后选择模型建模")
    draft = body.pop("recommendation_request")
    chat = response_data(api.post(CHAT, json=body))
    paused = snapshot(api, chat["execution_id"])
    submitted = spec_confirmation(paused, draft)
    async with data["factory"]() as session:
        execution = await get_execution(session, execution_id=UUID(chat["execution_id"]))

        async def fail_commit():
            raise SQLAlchemyError("injected recommendation commit failure")

        monkeypatch.setattr(session, "commit", fail_commit)
        with pytest.raises(SQLAlchemyError, match="recommendation commit failure"):
            await agent_service.provide_model_spec(
                session,
                payload=CopilotConfirmRequest.model_validate(submitted),
                execution=execution,
                artifact_root=data["root"],
            )
    assert snapshot(api, chat["execution_id"]) == paused
    response_data(api.post(CONFIRM, json=submitted))
    assert snapshot(api, chat["execution_id"])["step_runs"][-1]["status"] == "WAITING_CONFIRMATION"


@pytest.mark.asyncio
async def test_read_only_lookup_recovers_committed_fit_after_lost_response(api, data, monkeypatch):
    body = chat_body(data, "分析数据后选择模型建模")
    body["recommendation_request"]["experiment_spec"] = tcn_spec(data).model_dump(mode="json")
    chat = response_data(api.post(CHAT, json=body))
    ready = snapshot(api, chat["execution_id"])
    response_data(api.post(CONFIRM, json=selected(ready, "pls")))
    refs = {
        "selection_execution_id": ready["execution_id"],
        "copilot_run_id": ready["copilot_run_id"],
        "confirmed_selection_step_id": ready["pending_confirmation_step_id"],
    }

    async def lose_agent_checkpoint(*args):
        raise RuntimeError("injected lost response after platform commit")

    monkeypatch.setattr(agent_model_execution_service, "_checkpoint", lose_agent_checkpoint)
    monkeypatch.setattr(agent_model_execution_service, "_RECOVERY_AFTER", timedelta(0))
    assert api.post(EXECUTE, json=refs).status_code == 500
    before = [run for run in await runs(data) if run.run_type.startswith("modeling.")]
    (training,) = before
    recovered = response_data(api.get(LOOKUP, params=refs))
    assert recovered["execution_status"] == "unconfirmed"
    assert recovered["training_status"] == "succeeded"
    assert recovered["training_run_id"] == str(training.id)
    assert recovered["model_id"] == training.result["model_id"]
    assert response_data(api.post(EXECUTE, json=refs)) == recovered
    after = [run for run in await runs(data) if run.run_type.startswith("modeling.")]
    assert [run.id for run in after] == [training.id]


@pytest.mark.asyncio
async def test_two_specs_cannot_bind_the_same_gate(api, data, monkeypatch):
    body = chat_body(data, "分析数据后选择模型建模")
    draft = body.pop("recommendation_request")
    chat = response_data(api.post(CHAT, json=body))
    paused = snapshot(api, chat["execution_id"])
    proposals = [draft, {**draft, "goal": "nonlinear_regression"}]
    real = agent_service.recommend_models
    entered = 0
    both = asyncio.Event()

    async def overlap(*args, **kwargs):
        nonlocal entered
        entered += 1
        if entered == 2:
            both.set()
        await asyncio.wait_for(both.wait(), timeout=5)
        return await real(*args, **kwargs)

    monkeypatch.setattr(agent_service, "recommend_models", overlap)
    results = await asyncio.gather(
        *(
            asyncio.to_thread(api.post, CONFIRM, json=spec_confirmation(paused, proposal))
            for proposal in proposals
        )
    )
    assert sorted(response.status_code for response in results) == [200, 409]
    ready = snapshot(api, chat["execution_id"])
    assert ready["step_runs"][-2]["status"] == "SUCCEEDED"
    assert ready["step_runs"][-1]["status"] == "WAITING_CONFIRMATION"
    assert not [run for run in await runs(data) if run.run_type.startswith("modeling.")]
