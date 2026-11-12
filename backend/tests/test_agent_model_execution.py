"""Explicit Copilot model execution using the real platform on isolated SQLite."""

import asyncio
from copy import deepcopy
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from app.schemas.copilot import CopilotModelExecuteRequest
from app.services import agent_model_execution_service as modeling
from app.services.agent_execution_service import get_execution

from test_agent_model_recommendation import CHAT, CONFIRM, chat_body, choice, snapshot
from test_model_evaluation_api import response_data
from test_model_evaluation_service import tcn_spec
from test_pls_api import api as api
from test_pls_api import error
from test_pls_training_service import runs
from test_tcn_platform import data as data

pytestmark = pytest.mark.asyncio
EXECUTE = "/api/v1/copilot/modeling/execute"


def prepare(api, data, model, *, horizon=1, validation=True, short=False, anchor=66):
    body = chat_body(data)
    request = body["recommendation_request"]
    request["parameters"] = {
        **request["parameters"],
        "xgboost": {"num_boost_round": 3},
        "tcn": {**request["parameters"]["tcn"], "epochs": 1, "hidden_channels": 4},
        "timexer": {**request["parameters"]["timexer"], "epochs": 1, "embedding_dim": 16},
    }
    spec = data["spec"] if short else tcn_spec(data)
    document = spec.model_dump(mode="json")
    if not validation:
        document["evaluation"]["scopes"] = ["test"]
    elif not short:
        document["evaluation"]["sample_indices"] = {
            "validation": {"ranges": [{"start": anchor - 1, "stop": anchor + 1}]}
        }
    request["experiment_spec"] = document
    if horizon > 1:
        request["forecast_spec"] = {
            "target_window_length": 8,
            "exogenous_window_length": 11,
            "prediction_length": horizon,
        }
    chat = response_data(api.post(CHAT, json=body))
    confirmation = choice(chat, model, source="manual")
    execute = {
        "selection_execution_id": chat["execution_id"],
        "copilot_run_id": chat["copilot_run_id"],
        "confirmed_selection_step_id": chat["pending_confirmation_step_id"],
    }
    return chat, confirmation, execute


def confirmed(api, data, model, **kwargs):
    chat, confirmation, execute = prepare(api, data, model, **kwargs)
    locked = response_data(api.post(CONFIRM, json=confirmation))["result_payload"][
        "model_selection"
    ]
    return chat, execute, locked


@pytest.mark.parametrize(
    "model,horizon", [("pls", 1), ("xgboost", 1), ("tcn", 1), ("timexer", 1), ("timexer", 3)]
)
async def test_real_fit_and_fixed_validation_use_only_the_locked_model(
    api, data, monkeypatch, model, horizon
):
    chat, execute, locked = confirmed(api, data, model, horizon=horizon)
    assert await runs(data) == []
    assert snapshot(chat)["source"]["experiment_spec_hash"] == locked["experiment_spec_hash"]
    fit = modeling._fit
    calls = []

    async def track_fit(factory, spec, params, forecast, root):
        calls.append(params.model_dump(mode="json"))
        assert calls[-1] == locked["parameters"]
        assert spec.training_selection.mode == "full_train"
        assert spec.dataset_version_id == data["spec"].dataset_version_id != data["latest"]
        return await fit(factory, spec, params, forecast, root)

    monkeypatch.setattr(modeling, "_fit", track_fit)
    output = response_data(api.post(EXECUTE, json=execute))
    assert output["execution_status"] == output["training_status"] == "succeeded"
    assert output["model_type_id"] == model
    assert output["manifest_status"] == "published"
    assert output["evaluation_status"] == "succeeded"
    assert output["comparison_status"] == "not_comparable"
    evaluation = output["evaluation"]
    assert evaluation["model_id"] == output["model_id"]
    assert evaluation["training_run_id"] == output["training_run_id"]
    assert evaluation["partition"] == "validation" and evaluation["sample_count"] == 2
    if model == "timexer":
        assert output["forecast_spec"]["prediction_length"] == horizon
        assert len(evaluation["horizon_metrics"]) == horizon
        assert evaluation["metric_aggregation"]["method"] == "macro_average"
    state = response_data(api.get(f"/api/v1/copilot/executions/{output['execution_id']}"))
    assert state["step_runs"][0]["processing_run_ids"] == [
        output["training_run_id"],
        output["evaluation_run_id"],
    ]
    assert response_data(api.post(EXECUTE, json=execute)) == output
    assert len(calls) == 1
    assert {run.run_type for run in await runs(data)} == {
        f"modeling.{model}",
        "modeling.model_evaluation",
    }
    original = response_data(api.get(f"/api/v1/copilot/executions/{chat['execution_id']}"))
    assert original["step_runs"][1]["result_payload"]["model_selection"] == locked


async def test_an_accepted_recommendation_can_be_executed(api, data):
    chat, _, execute = prepare(api, data, "pls")
    model = snapshot(chat)["recommended_models"][0]
    locked = response_data(api.post(CONFIRM, json=choice(chat, model)))["result_payload"][
        "model_selection"
    ]
    assert locked["selection_source"] == "agent_recommendation"
    assert await runs(data) == []
    output = response_data(api.post(EXECUTE, json=execute))
    assert output["training_status"] == output["evaluation_status"] == "succeeded"
    assert output["model_type_id"] == model


async def test_unconfirmed_rejected_or_forged_selections_never_train(api, data, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Unapproved input must never dispatch training")

    monkeypatch.setattr(modeling, "_fit", forbidden)
    _, confirmation, execute = prepare(api, data, "pls")
    assert (
        error(api.post(EXECUTE, json=execute), 409)["code"] == "MODEL_EXECUTION_SELECTION_INVALID"
    )
    wrong = {**execute, "copilot_run_id": str(uuid4())}
    assert error(api.post(EXECUTE, json=wrong), 404)["code"] == "MODEL_SELECTION_NOT_FOUND"
    wrong = {**execute, "confirmed_selection_step_id": "forged"}
    error(api.post(EXECUTE, json=wrong), 409)
    rejection = {k: v for k, v in confirmation.items() if k != "model_selection"}
    response_data(api.post(CONFIRM, json={**rejection, "approved": False}))
    error(api.post(EXECUTE, json=execute), 409)
    error(api.post(EXECUTE, json={**execute, "model_type_id": "xgboost"}), 422)
    assert await runs(data) == []


@pytest.mark.parametrize("change", ["version", "csv", "spec", "forecast"])
async def test_changed_selection_sources_are_rejected_before_claim(api, data, change):
    chat, execute, _ = confirmed(api, data, "timexer", horizon=3)
    if change == "csv":
        (data["root"] / "source.csv").write_bytes(b"changed")
    else:
        async with data["factory"]() as session:
            workflow = await get_execution(session, execution_id=UUID(chat["execution_id"]))
            if change == "version":
                workflow.current_version_id = data["latest"]
            elif change == "spec":
                step = workflow.step_runs[0]
                new = deepcopy(step.input_payload)
                new["recommendation_request"]["experiment_spec"]["input_columns"].reverse()
                step.input_payload = new
            else:
                step = workflow.step_runs[1]
                new = deepcopy(step.result_payload["model_selection"])
                new["forecast_spec"]["prediction_length"] = 1
                step.input_payload = {**step.input_payload, "confirmed_model_selection": new}
                step.result_payload = {"model_selection": new}
            await session.commit()
    assert (
        error(api.post(EXECUTE, json=execute), 409)["code"] == "MODEL_EXECUTION_SELECTION_INVALID"
    )
    assert await runs(data) == []


async def direct(data, execute):
    return await modeling.execute_confirmed_model(
        data["factory"],
        request=CopilotModelExecuteRequest.model_validate(execute),
        artifact_root=data["root"],
    )


async def test_simultaneous_requests_share_one_durable_claim(api, data, monkeypatch):
    _, execute, _ = confirmed(api, data, "pls")
    ready, release = asyncio.Event(), asyncio.Event()
    preflight = modeling._preflight
    arrived = 0
    fit = modeling._fit
    calls = []

    async def prepare_together(*args):
        nonlocal arrived
        spec = await preflight(*args)
        arrived += 1
        if arrived == 2:
            ready.set()
        await asyncio.wait_for(ready.wait(), timeout=20)
        return spec

    async def hold_fit(*args):
        calls.append(1)
        await asyncio.wait_for(release.wait(), timeout=20)
        return await fit(*args)

    monkeypatch.setattr(modeling, "_preflight", prepare_together)
    monkeypatch.setattr(modeling, "_fit", hold_fit)
    tasks = [asyncio.create_task(direct(data, execute)) for _ in range(2)]
    try:
        done, pending = await asyncio.wait(tasks, timeout=15, return_when=asyncio.FIRST_COMPLETED)
        assert len(done) == len(pending) == 1
        running = next(iter(done)).result()
        assert running.execution_status == "running"
    finally:
        release.set()
        final = await asyncio.gather(*tasks)
    assert len(calls) == 1
    assert {item.execution_status for item in final} == {"running", "succeeded"}
    assert len({item.execution_id for item in final}) == 1


@pytest.mark.parametrize("short,validation", [(False, False), (True, True)])
async def test_training_survives_unavailable_validation(api, data, short, validation):
    _, execute, _ = confirmed(api, data, "tcn", short=short, validation=validation)
    output = response_data(api.post(EXECUTE, json=execute))
    assert output["training_status"] == "succeeded" and output["model_id"]
    assert output["evaluation_status"] == ("failed" if validation else "skipped")
    assert output["comparison_status"] == "skipped"
    assert "VALIDATION" in output["evaluation_error"]
    all_runs = await runs(data)
    assert not any(run.parameters.get("partition") == "test" for run in all_runs)


async def test_compatible_history_is_compared_but_different_rows_are_not(api, data):
    _, first, _ = confirmed(api, data, "pls")
    one = response_data(api.post(EXECUTE, json=first))
    _, mismatch, _ = confirmed(api, data, "xgboost", anchor=67)
    two = response_data(api.post(EXECUTE, json=mismatch))
    assert two["comparison_status"] == "not_comparable"
    assert "target_rows" in two["comparison_reason"]
    _, match, locked = confirmed(api, data, "xgboost")
    three = response_data(api.post(EXECUTE, json=match))
    assert three["comparison_status"] == "succeeded"
    assert set(three["compared_evaluation_run_ids"]) == {
        one["evaluation_run_id"],
        three["evaluation_run_id"],
    }
    assert three["model_type_id"] == locked["model_type_id"]
    assert (
        len(
            [
                run
                for run in await runs(data)
                if run.run_type in {"modeling.pls", "modeling.xgboost"}
            ]
        )
        == 3
    )


async def test_interrupted_result_recovers_by_exact_link_and_never_refits(api, data, monkeypatch):
    _, execute, _ = confirmed(api, data, "pls")
    real = modeling._checkpoint

    async def lose_agent_update(*args):
        raise RuntimeError("lost Agent update after the platform committed")

    monkeypatch.setattr(modeling, "_checkpoint", lose_agent_update)
    with pytest.raises(RuntimeError, match="lost Agent update"):
        await direct(data, execute)
    monkeypatch.setattr(modeling, "_checkpoint", real)
    monkeypatch.setattr(modeling, "_RECOVERY_AFTER", timedelta(0))
    recovered = await direct(data, execute)
    (training,) = await runs(data)
    assert recovered.execution_status == "unconfirmed"
    assert recovered.training_status == "succeeded"
    assert recovered.manifest_status == "published"
    assert recovered.training_run_id == training.id
    assert str(recovered.model_id) == training.result["model_id"]
    assert (await direct(data, execute)) == recovered
    assert len(await runs(data)) == 1


async def test_confirmed_training_failure_does_not_publish_or_retry(api, data, monkeypatch):
    _, execute, _ = confirmed(api, data, "pls")

    def broken_fit(*args, **kwargs):
        raise RuntimeError("synthetic failure inside the platform fit")

    from app.services import pls_training_service

    monkeypatch.setattr(pls_training_service, "fit_pls_core", broken_fit)
    first = await direct(data, execute)
    assert first.execution_status == first.training_status == "failed"
    assert first.model_id is None
    assert first.evaluation_status == first.comparison_status == "skipped"
    (run,) = await runs(data)
    assert run.id == first.training_run_id and run.status == "failed"
    assert await direct(data, execute) == first
    assert len(await runs(data)) == 1


async def test_multistep_history_cannot_rank_against_single_step(api, data):
    _, first, _ = confirmed(api, data, "pls")
    assert (await direct(data, first)).evaluation_status == "succeeded"
    _, second, _ = confirmed(api, data, "timexer", horizon=3)
    result = await direct(data, second)
    assert result.evaluation_status == "succeeded"
    assert result.comparison_status == "not_comparable"
    assert result.comparison_reason.endswith("prediction_length")


async def test_unknown_training_outcome_is_not_retryable(api, data, monkeypatch):
    _, execute, _ = confirmed(api, data, "pls")
    attempts = []

    async def fail(*args):
        attempts.append(1)
        raise RuntimeError("lost platform response before Run identity was linked")

    monkeypatch.setattr(modeling, "_fit", fail)
    first = await direct(data, execute)
    assert first.execution_status == first.training_status == "unconfirmed"
    assert first.model_id is first.training_run_id is None
    assert await direct(data, execute) == first
    assert attempts == [1]


async def test_failed_claim_cannot_dispatch_and_comparison_failure_keeps_results(
    api, data, monkeypatch
):
    _, execute, _ = confirmed(api, data, "pls")
    with monkeypatch.context() as patch:

        async def fail_claim(*args):
            raise RuntimeError("claim transaction failed")

        patch.setattr(modeling, "_claim", fail_claim)
        with pytest.raises(RuntimeError, match="claim transaction failed"):
            await direct(data, execute)
        assert await runs(data) == []

    async def fail_comparison(*args):
        raise RuntimeError("comparison unavailable")

    monkeypatch.setattr(modeling, "_comparison", fail_comparison)
    output = await direct(data, execute)
    assert output.training_status == output.evaluation_status == "succeeded"
    assert output.comparison_status == "failed"
    assert output.model_id and output.training_run_id and output.evaluation_run_id
