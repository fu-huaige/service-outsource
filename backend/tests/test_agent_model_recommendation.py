"""Copilot model recommendation and atomic human selection on isolated SQLite."""

import asyncio
from copy import deepcopy
from uuid import UUID

import pytest
from algorithms.agent.llm import NullProvider
from algorithms.agent.llm_planner import LlmPlanner
from algorithms.agent.planner import parse_intent
from app.api import routes
from app.models.agent_execution import AgentExecutionSession
from app.schemas.copilot import CopilotConfirmRequest
from app.services import (
    agent_arx_modeling_service,
    agent_service,
    modeling_service,
    pls_artifact_service,
    tcn_artifact_service,
    timexer_artifact_service,
    xgboost_artifact_service,
)
from app.services.agent_execution_service import ExecutionStateError, get_execution
from sqlalchemy.exc import SQLAlchemyError

from test_model_evaluation_api import response_data
from test_model_recommendation_service import PARAMETERS, forbid_fitting
from test_pls_api import api as api
from test_pls_api import error
from test_pls_training_service import runs
from test_tcn_platform import data as data

pytestmark = pytest.mark.asyncio
CHAT = "/api/v1/copilot/chat"
CONFIRM = "/api/v1/copilot/confirm"


def chat_body(data, message="推荐适合当前数据的模型"):
    return {
        "message": message,
        "dataset_id": str(data["spec"].dataset_id),
        "active_version_id": str(data["spec"].dataset_version_id),
        "recommendation_request": {
            "experiment_spec": data["spec"].model_dump(mode="json"),
            "parameters": PARAMETERS,
        },
    }


def snapshot(chat):
    return chat["step_runs"][0]["result"]["recommendation"]


def choice(chat, model_id, *, source="agent_recommendation", overrides=None):
    recommendation = snapshot(chat)
    candidate = next(
        item for item in recommendation["candidates"] if item["model_type_id"] == model_id
    )
    return {
        "copilot_run_id": chat["copilot_run_id"],
        "confirmation_id": chat["pending_confirmation_step_id"],
        "execution_id": chat["execution_id"],
        "step_id": chat["pending_confirmation_step_id"],
        "approved": True,
        "model_selection": {
            "recommendation_step_id": chat["step_runs"][0]["step_id"],
            "selected_model_type_id": model_id,
            "selected_parameters": overrides
            if overrides is not None
            else candidate["actual_parameters"],
            "selection_source": source,
            "forecast_spec": candidate["forecast_spec"],
            **{
                name: recommendation["source"][name]
                for name in (
                    "dataset_id",
                    "dataset_version_id",
                    "csv_sha256",
                    "experiment_spec_hash",
                )
            },
        },
    }


def forbid_model_side_effects(monkeypatch):
    forbid_fitting(monkeypatch)

    def forbidden(*args, **kwargs):
        pytest.fail("Recommendation and confirmation must never dispatch training")

    monkeypatch.setattr(agent_service, "fit_arx_core", forbidden)
    monkeypatch.setattr(agent_arx_modeling_service, "fit_arx_core", forbidden)
    monkeypatch.setattr(modeling_service, "fit_arx_core", forbidden)
    monkeypatch.setattr(agent_service, "run_study", forbidden)
    monkeypatch.setattr(agent_service, "_resolve_provider", forbidden)
    monkeypatch.setattr(agent_service, "execute_agent_tool", forbidden)
    monkeypatch.setattr(routes, "continue_agent_execution", forbidden)
    for service, model in (
        (pls_artifact_service, "pls"),
        (xgboost_artifact_service, "xgboost"),
        (tcn_artifact_service, "tcn"),
        (timexer_artifact_service, "timexer"),
    ):
        monkeypatch.setattr(service, f"save_{model}_artifact", forbidden)


@pytest.mark.parametrize("rank", [0, 1])
async def test_accepts_any_shortlisted_model_and_keeps_the_real_snapshot(
    api, data, monkeypatch, rank
):
    forbid_model_side_effects(monkeypatch)
    original = agent_service.recommend_models
    outcomes = []

    async def capture(*args, **kwargs):
        result = await original(*args, **kwargs)
        outcomes.append(result.model_dump(mode="json"))
        return result

    monkeypatch.setattr(agent_service, "recommend_models", capture)
    chat = response_data(api.post(CHAT, json=chat_body(data)))
    assert [item["tool"] for item in chat["plan"]["steps"]] == [
        "recommend_models",
        "confirm_model_selection",
    ]
    assert chat["workflow_status"] == "WAITING_CONFIRMATION"
    assert snapshot(chat) == outcomes[0]
    saved = response_data(api.get(f"/api/v1/copilot/executions/{chat['execution_id']}"))
    assert saved["step_runs"][0]["result_payload"]["recommendation"] == outcomes[0]

    payload = choice(chat, outcomes[0]["recommended_models"][rank])
    result = response_data(api.post(CONFIRM, json=payload))
    assert result["workflow_status"] == result["step_status"] == "SUCCEEDED"
    assert result["confirmation_status"] == "APPROVED"
    locked = result["result_payload"]["model_selection"]
    assert locked["model_type_id"] == payload["model_selection"]["selected_model_type_id"]
    assert locked["parameters"] == payload["model_selection"]["selected_parameters"]
    assert locked["dataset_version_id"] == str(data["spec"].dataset_version_id)
    assert locked["confirmed_at"]
    assert response_data(api.post(CONFIRM, json=payload)) == result
    assert await runs(data) == []
    assert not (data["root"] / "models").exists()


async def test_manual_choice_outside_shortlist_is_locked_after_parameter_revalidation(api, data):
    chat = response_data(api.post(CHAT, json=chat_body(data, "我想手动选择 TCN")))
    recommendation = snapshot(chat)
    assert chat["step_runs"][0]["result"]["requested_model_type_id"] == "tcn"
    eligible = {
        item["model_type_id"]
        for item in recommendation["candidates"]
        if item["eligibility_status"] == "eligible"
    }
    (model_id,) = eligible - set(recommendation["recommended_models"])
    assert model_id == "tcn"
    forged = choice(chat, model_id)
    assert error(api.post(CONFIRM, json=forged), 422)["code"] == "MODEL_SELECTION_NOT_RECOMMENDED"
    invalid = choice(chat, model_id, source="manual", overrides={"window_length": 28})
    assert error(api.post(CONFIRM, json=invalid), 422)["code"] == "MODEL_SELECTION_INELIGIBLE"
    manual = choice(chat, model_id, source="manual", overrides={"window_length": 30})
    result = response_data(api.post(CONFIRM, json=manual))
    locked = result["result_payload"]["model_selection"]
    assert locked["selection_source"] == "manual" and locked["parameters"]["window_length"] == 30
    second = response_data(api.post(CHAT, json=chat_body(data, "推荐建模算法")))
    assert second["execution_id"] != chat["execution_id"]
    assert response_data(api.post(CONFIRM, json=manual)) == result
    conflict = choice(chat, recommendation["recommended_models"][0])
    assert error(api.post(CONFIRM, json=conflict), 409)["code"] == "MODEL_SELECTION_CONFLICT"


async def test_missing_spec_version_mismatch_and_deterministic_planner(api, data):
    for message in ("帮我选择建模算法", "我想使用 XGBoost 建模", "建模"):
        intent = parse_intent(message)
        plan = LlmPlanner(NullProvider()).plan(message, intent)
        assert [step.tool for step in plan.steps] == ["recommend_models", "confirm_model_selection"]
        failure = error(api.post(CHAT, json={"message": message}), 422)
        assert failure["code"] == "NEEDS_EXPERIMENT_SPEC" and failure["details"]["missing_fields"]
    invalid = chat_body(data)
    invalid["active_version_id"] = str(data["latest"])
    assert (
        error(api.post(CHAT, json=invalid), 409)["code"] == "MODEL_RECOMMENDATION_SOURCE_MISMATCH"
    )


async def test_multistep_forecast_and_ineligible_choices(api, data):
    body = chat_body(data)
    body["recommendation_request"]["forecast_spec"] = {
        "target_window_length": 8,
        "exogenous_window_length": 11,
        "prediction_length": 3,
    }
    chat = response_data(api.post(CHAT, json=body))
    assert snapshot(chat)["recommended_models"] == ["timexer"]
    excluded = choice(chat, "xgboost", source="manual")
    assert error(api.post(CONFIRM, json=excluded), 422)["code"] == "MODEL_SELECTION_INELIGIBLE"
    valid = choice(chat, "timexer")
    locked = response_data(api.post(CONFIRM, json=valid))["result_payload"]["model_selection"]
    assert locked["forecast_spec"]["prediction_length"] == 3

    unknown = chat_body(data)
    unknown["recommendation_request"]["experiment_spec"]["time_axis"] = {
        "column": "timestamp",
        "sampling_status": "unknown",
    }
    chat = response_data(api.post(CHAT, json=unknown))
    proposed = choice(chat, "tcn", source="manual")
    failure = error(api.post(CONFIRM, json=proposed), 422)
    assert failure["details"]["eligibility_status"] == "unknown"


async def test_confirm_requires_real_step_source_and_a_structured_selection(api, data):
    chat = response_data(api.post(CHAT, json=chat_body(data)))
    valid = choice(chat, "pls")
    without = {k: v for k, v in valid.items() if k != "model_selection"}
    assert error(api.post(CONFIRM, json=without), 422)["code"] == "MODEL_SELECTION_REQUIRED"
    for key, value, expected in (
        ("recommendation_step_id", "wrong", "MODEL_SELECTION_RECOMMENDATION_MISMATCH"),
        ("dataset_version_id", str(data["latest"]), "MODEL_SELECTION_SOURCE_CHANGED"),
        ("experiment_spec_hash", "0" * 64, "MODEL_SELECTION_SOURCE_CHANGED"),
    ):
        bad = deepcopy(valid)
        bad["model_selection"][key] = value
        assert error(api.post(CONFIRM, json=bad), 409)["code"] == expected
    rejected = response_data(api.post(CONFIRM, json={**without, "approved": False}))
    assert rejected["workflow_status"] == "CANCELLED"
    assert error(api.post(CONFIRM, json=valid), 409)["code"] == "AGENT_EXECUTION_STATE_CONFLICT"


@pytest.mark.parametrize("change", ["version", "csv"])
async def test_stale_source_blocks_replay_of_a_confirmed_selection(api, data, change):
    chat = response_data(api.post(CHAT, json=chat_body(data)))
    payload = choice(chat, "pls")
    original = response_data(api.post(CONFIRM, json=payload))
    if change == "version":
        async with data["factory"]() as session:
            execution = await session.get(AgentExecutionSession, UUID(chat["execution_id"]))
            execution.current_version_id = data["latest"]
            await session.commit()
    else:
        (data["root"] / "source.csv").write_bytes(b"changed")
    assert error(api.post(CONFIRM, json=payload), 409)["code"] == "MODEL_SELECTION_SOURCE_CHANGED"
    state = response_data(api.get(f"/api/v1/copilot/executions/{chat['execution_id']}"))
    assert state["step_runs"][1]["result_payload"] == original["result_payload"]


@pytest.mark.parametrize("changed_field", ["spec", "rule_version"])
async def test_expired_snapshot_cannot_be_used_for_confirmation(api, data, changed_field):
    chat = response_data(api.post(CHAT, json=chat_body(data)))
    async with data["factory"]() as session:
        execution = await get_execution(session, execution_id=UUID(chat["execution_id"]))
        step = execution.step_runs[0]
        if changed_field == "spec":
            changed = deepcopy(step.input_payload)
            changed["recommendation_request"]["experiment_spec"]["input_columns"].reverse()
            step.input_payload = changed
        else:
            changed = deepcopy(step.result_payload)
            changed["recommendation"]["rule_version"] = "obsolete"
            step.result_payload = changed
        await session.commit()
    assert error(api.post(CONFIRM, json=choice(chat, "pls")), 409)["code"] == (
        "MODEL_SELECTION_SOURCE_CHANGED"
    )
    state = response_data(api.get(f"/api/v1/copilot/executions/{chat['execution_id']}"))
    assert state["workflow_status"] == "WAITING_CONFIRMATION"
    assert state["step_runs"][1]["result_payload"] == {}


async def confirm_direct(data, payload, *, fail_commit=False):
    request = CopilotConfirmRequest.model_validate(payload)
    async with data["factory"]() as session:
        execution = await get_execution(session, execution_id=request.execution_id)
        if fail_commit:

            async def fail():
                raise SQLAlchemyError("injected commit failure")

            session.commit = fail
        result = await agent_service.confirm_model_selection(
            session, payload=request, execution=execution, artifact_root=data["root"]
        )
        return result.step_runs[1].result_payload["model_selection"]


async def test_concurrent_conflicting_choices_persist_exactly_one(api, data, monkeypatch):
    chat = response_data(api.post(CHAT, json=chat_body(data)))
    both_ready = asyncio.Event()
    ready = 0
    finish = agent_service.finish_model_selection_step

    async def wait_at_write(*args, **kwargs):
        nonlocal ready
        ready += 1
        if ready == 2:
            both_ready.set()
        await asyncio.wait_for(both_ready.wait(), timeout=15)
        return await finish(*args, **kwargs)

    monkeypatch.setattr(agent_service, "finish_model_selection_step", wait_at_write)
    left, right = await asyncio.gather(
        confirm_direct(data, choice(chat, "pls")),
        confirm_direct(data, choice(chat, "xgboost")),
        return_exceptions=True,
    )
    successes = [item for item in (left, right) if isinstance(item, dict)]
    failures = [item for item in (left, right) if isinstance(item, ExecutionStateError)]
    assert len(successes) == len(failures) == 1
    state = response_data(api.get(f"/api/v1/copilot/executions/{chat['execution_id']}"))
    assert state["step_runs"][1]["result_payload"]["model_selection"] == successes[0]
    assert await runs(data) == []


async def test_commit_failure_rolls_back_both_state_changes(api, data):
    chat = response_data(api.post(CHAT, json=chat_body(data)))
    payload = choice(chat, "pls")
    with pytest.raises(SQLAlchemyError, match="injected commit failure"):
        await confirm_direct(data, payload, fail_commit=True)
    state = response_data(api.get(f"/api/v1/copilot/executions/{chat['execution_id']}"))
    assert state["workflow_status"] == "WAITING_CONFIRMATION"
    assert state["step_runs"][1]["result_payload"] == {}
    assert (await confirm_direct(data, payload))["model_type_id"] == "pls"
