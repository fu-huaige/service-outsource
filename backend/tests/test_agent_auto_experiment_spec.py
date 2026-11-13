"""Auto-generated Spec contracts for the integrated four-model recommendation gate."""

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from app.models.agent_execution import AgentExecutionSession, AgentStepRun
from app.models.dataset import DatasetColumn, DatasetVersion, ProcessingRun
from app.schemas.experiment_spec import ExperimentSpec
from app.schemas.model_recommendation import ModelRecommendationRequest
from app.services import agent_model_dispatch_service
from app.services.agent_experiment_spec_service import build_agent_recommendation_request
from app.services.agent_model_execution_service import run_dispatched_model
from app.services.experiment_spec_service import bind_experiment_spec, spec_hash
from sqlalchemy import select

from test_agent_integrated_model_workflow import selected, snapshot, spec_confirmation
from test_agent_model_execution import EXECUTE
from test_agent_model_recommendation import CHAT, CONFIRM, chat_body
from test_model_evaluation_api import response_data
from test_pls_api import api as api
from test_pls_training_service import runs
from test_tcn_platform import data as data

pytestmark = pytest.mark.asyncio


async def rewrite_clock(data, *, offsets, version_id=None, update_sha=True):
    async with data["factory"]() as session:
        version = await session.get(DatasetVersion, version_id or data["spec"].dataset_version_id)
        path = data["root"] / version.artifact_path
        header, *rows = path.read_text(encoding="utf-8").splitlines()
        start = datetime(2026, 1, 1, tzinfo=UTC)
        lines = [
            f"{(start + timedelta(seconds=offset)).isoformat()},{row.split(',', 1)[1]}"
            for row, offset in zip(rows, offsets, strict=True)
        ]
        content = ("\n".join([header, *lines]) + "\n").encode()
        path.write_bytes(content)
        if update_sha:
            version.sha256 = sha256(content).hexdigest()
            await session.commit()
        return version.sha256


def open_workflow(api, data, request=None, message="分析数据后选择模型建模"):
    body = chat_body(data, message)
    if request is None:
        body.pop("recommendation_request")
    else:
        body["recommendation_request"] = request
    chat = response_data(api.post(CHAT, json=body))
    return snapshot(api, chat["execution_id"])


def assert_evaluation_contract(rec):
    document = rec["input_payload"]["recommendation_request"]["experiment_spec"]
    result = rec["result_payload"]["recommendation"]
    assert document["evaluation"]["scopes"] == ["validation", "test"]
    # The recommendation hashes the bound Spec, including the verified leakage status.
    bound = {**document, "leakage": result["leakage"]}
    digest = sha256(json.dumps(
        bound, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode()).hexdigest()
    assert result["source"]["experiment_spec_hash"] == digest


async def test_auto_spec_splits_on_gap_and_waits_for_model_selection(api, data, monkeypatch):
    size = data["spec"].row_count
    digest = await rewrite_clock(data, offsets=[i + (5 if i >= 40 else 0) for i in range(size)])
    execution = open_workflow(api, data)
    rec, selection = execution["step_runs"][-2:]
    assert rec["status"] == "SUCCEEDED"
    assert selection["step_id"] == execution["pending_confirmation_step_id"]
    spec = ExperimentSpec.model_validate(rec["input_payload"]["recommendation_request"]["experiment_spec"])
    assert spec.dataset_version_id == data["spec"].dataset_version_id != data["latest"]
    assert spec.dataset_version_sha256 == digest and spec.row_count == size
    assert spec.target_column == "quality" and spec.input_columns == ("a", "b")
    assert spec.application == "regression"
    async with data["factory"]() as session:
        bound = await bind_experiment_spec(session, spec=spec, artifact_root=data["root"])
    assert bound == spec.model_copy(update={"leakage": bound.leakage})
    assert [(r.start, r.stop) for r in spec.continuous_runs] == [(0, 40), (40, 102)]
    assert [(r.start, r.stop) for r in spec.split.train] == [(0, 40), (40, 61)]
    assert [(r.start, r.stop) for r in spec.split.validation] == [(61, 81)]
    assert [(r.start, r.stop) for r in spec.split.test] == [(81, 102)]
    assert spec.time_axis.sampling_status == "uniform" and spec.time_axis.sample_period_seconds == 1
    assert spec.feature_spec.prediction_horizon == 1 and spec.leakage.status == "unknown"
    result = rec["result_payload"]["recommendation"]
    assert {item["model_type_id"] for item in result["candidates"]} == {
        "pls", "xgboost", "tcn", "timexer",
    }
    assert result["source"]["csv_sha256"] == digest
    assert_evaluation_contract(rec)
    assert result["candidates"][3]["eligibility_status"] == "excluded"
    assert not [run for run in await runs(data) if run.run_type.startswith("modeling.")]
    assert result["source"]["experiment_spec_hash"] == spec_hash(bound)

    delivered = []
    monkeypatch.setattr(agent_model_dispatch_service, "_submit", delivered.append)
    confirmation = selected(execution, "pls", source="agent_recommendation")
    response_data(api.post(CONFIRM, json={**confirmation, "dispatch_training": True}))
    (execution_id,) = delivered
    await run_dispatched_model(data["factory"], execution_id=execution_id, artifact_root=data["root"])
    trained = response_data(api.get("/api/v1/copilot/modeling/execution", params={
        "selection_execution_id": execution["execution_id"],
        "copilot_run_id": execution["copilot_run_id"],
        "confirmed_selection_step_id": selection["step_id"],
    }))
    assert trained["training_status"] == "succeeded" and trained["manifest_status"] == "published"
    assert trained["evaluation_status"] == "succeeded" and trained["model_id"]
    (training_run,) = [run for run in await runs(data) if run.run_type == "modeling.pls"]
    assert str(training_run.id) == trained["training_run_id"]
    assert training_run.parameters["experiment_spec"] == bound.model_dump(mode="json")
    assert training_run.parameters["experiment_spec_hash"] == spec_hash(bound)


async def test_unknown_cadence_does_not_claim_continuity(api, data):
    await rewrite_clock(data, offsets=[i * (i + 1) for i in range(data["spec"].row_count)])
    execution = open_workflow(api, data)
    rec = execution["step_runs"][-2]
    spec = rec["input_payload"]["recommendation_request"]["experiment_spec"]
    assert spec["time_axis"]["sampling_status"] == "unknown"
    assert spec["time_axis"]["sample_period_seconds"] is None
    assert all(run["stop"] - run["start"] == 1 for run in spec["continuous_runs"])
    models = rec["result_payload"]["recommendation"]["candidates"]
    assert {item["eligibility_status"] for item in models if item["model_type_id"] in ("tcn", "timexer")} == {"unknown"}


@pytest.mark.parametrize(("resolved", "application"), [
    (False, None), (False, "regression"), (True, "soft_sensor"),
])
async def test_matching_explicit_split_is_kept_and_stale_digest_is_not_reused(
    api, data, resolved, application
):
    supplied = chat_body(data)["recommendation_request"]
    original = supplied["experiment_spec"]
    original["application"] = application
    if not resolved:
        original["evaluation"]["scopes"] = ["validation", "test"]
    if resolved:
        original["evaluation"].update(
            resolution_status="resolved",
            sample_indices={"validation": {"ranges": original["split"]["validation"]}},
        )
    original_request = deepcopy(supplied)
    execution = open_workflow(api, data, supplied)
    rec = execution["step_runs"][-2]
    assert rec["input_payload"]["draft_recommendation_request"] == (
        ModelRecommendationRequest.model_validate(original_request).model_dump(mode="json")
    )
    assert_evaluation_contract(rec)
    spec = rec["input_payload"]["recommendation_request"]["experiment_spec"]
    assert spec["split"] == original["split"]
    assert spec["application"] == (application or "regression")
    assert ExperimentSpec.model_validate(spec).evaluation.sample_indices == (
        ExperimentSpec.model_validate(original).evaluation.sample_indices
    )
    assert spec["evaluation"]["resolution_status"] == "unresolved"
    assert supplied == original_request
    digest = await rewrite_clock(data, offsets=list(range(data["spec"].row_count)))
    execution = open_workflow(api, data, supplied)
    spec = execution["step_runs"][-2]["input_payload"]["recommendation_request"]["experiment_spec"]
    assert spec["dataset_version_sha256"] == digest
    assert spec["split"]["train"] == [{"start": 0, "stop": 61}]
    assert spec["application"] == (application or "regression")
    assert_evaluation_contract(execution["step_runs"][-2])


@pytest.mark.parametrize(
    ("condition", "field"),
    [("time_order", "split"), ("sha", "dataset_version_sha256"), ("roles", "input_columns"), ("target", "target_column")],
)
async def test_unverified_sources_request_only_the_missing_field(api, data, condition, field):
    message = "分析数据后选择模型建模"
    if condition == "sha":
        await rewrite_clock(data, offsets=list(range(data["spec"].row_count)), update_sha=False)
    if condition == "roles":
        async with data["factory"]() as session:
            columns = await session.scalars(select(DatasetColumn).where(
                DatasetColumn.version_id == data["spec"].dataset_version_id,
                DatasetColumn.role == "input",
            ))
            for column in columns:
                column.role = "ignore"
            await session.commit()
    if condition == "target":
        message += "，目标变量为 a"
    execution = open_workflow(api, data, message=message)
    rec, selection = execution["step_runs"][-2:]
    assert rec["status"] == "WAITING_CONFIRMATION" and selection["status"] == "PENDING"
    assert rec["result_payload"]["spec_requirement"]["field"] == field
    assert "recommendation_request" not in rec["input_payload"]


async def test_overlapping_explicit_partition_is_rejected(api, data):
    body = chat_body(data, "分析数据后选择模型建模")
    body["recommendation_request"]["experiment_spec"]["split"]["validation"][0]["start"] = 69
    assert api.post(CHAT, json=body).status_code == 422


@pytest.mark.parametrize("latest_approved", [True, False])
async def test_applied_selection_requires_matching_formal_version_and_keeps_order(data, latest_approved):
    version_id = data["latest"]
    await rewrite_clock(data, version_id=version_id, offsets=list(range(data["spec"].row_count)))
    dataset_id = data["spec"].dataset_id
    origin = data["spec"].dataset_version_id
    run_id = uuid4()
    names = ["b", "quality", "removed", "a"]
    async with data["factory"]() as session:
        session.add(ProcessingRun(
            id=run_id, dataset_id=dataset_id, source_version_id=origin,
            run_type="preprocessing.feature_selection", status="succeeded",
            result={"result_version_id": str(version_id), "kept_input_columns": names, "user_confirmed": True},
        ))
        await session.flush()
        execution = AgentExecutionSession(
            dataset_id=dataset_id, initial_version_id=origin, current_version_id=version_id,
            step_runs=[
                AgentStepRun(
                    sequence=1, tool_name="select_variables", status="SUCCEEDED",
                    confirmation_status="APPROVED", source_version_id=origin,
                    result_payload={
                        "operation_name": "feature_selection_noop",
                        "summary": {"kept_input_columns": ["b"], "user_confirmed": True},
                    },
                ),
                AgentStepRun(
                    sequence=2, tool_name="select_variables", status="SUCCEEDED",
                    confirmation_status="APPROVED" if latest_approved else "PENDING",
                    source_version_id=origin, result_version_id=version_id,
                    processing_run_ids=[str(run_id)],
                    result_payload={"summary": {"kept_input_columns": names, "user_confirmed": True}},
                ),
            ],
        )
        request = await build_agent_recommendation_request(
            session, execution=execution, sequence=3, artifact_root=data["root"], draft=None
        )
    assert request.experiment_spec.dataset_version_id == version_id
    assert request.experiment_spec.input_columns == (("b", "a") if latest_approved else ("a", "b"))



async def test_explicit_split_crossing_verified_gap_is_replaced(api, data):
    size = data["spec"].row_count
    digest = await rewrite_clock(data, offsets=[i + (8 if i >= 52 else 0) for i in range(size)])
    supplied = chat_body(data)["recommendation_request"]
    supplied["experiment_spec"]["dataset_version_sha256"] = digest
    supplied["experiment_spec"]["time_axis"] = {"column": "timestamp", "sampling_status": "unknown"}
    supplied["experiment_spec"]["continuous_runs"] = [{"start": 0, "stop": size}]
    execution = open_workflow(api, data, supplied)
    spec = execution["step_runs"][-2]["input_payload"]["recommendation_request"]["experiment_spec"]
    assert spec["continuous_runs"] == [{"start": 0, "stop": 52}, {"start": 52, "stop": 102}]
    assert spec["split"]["train"] == [{"start": 0, "stop": 52}, {"start": 52, "stop": 61}]


async def test_row_count_mismatch_does_not_bind_spec(api, data):
    async with data["factory"]() as session:
        version = await session.get(DatasetVersion, data["spec"].dataset_version_id)
        version.row_count += 1
        await session.commit()
    rec = open_workflow(api, data)["step_runs"][-2]
    assert rec["status"] == "WAITING_CONFIRMATION"
    assert rec["result_payload"]["spec_requirement"]["field"] == "row_count"


async def test_manual_fallback_rejects_a_run_crossing_a_verified_gap(api, data):
    size = data["spec"].row_count
    digest = await rewrite_clock(data, offsets=[i + (5 if i >= 40 else 0) for i in range(size)])
    async with data["factory"]() as session:
        columns = await session.scalars(select(DatasetColumn).where(
            DatasetColumn.version_id == data["spec"].dataset_version_id,
            DatasetColumn.role == "input",
        ))
        for column in columns:
            column.role = "ignore"
        await session.commit()
    execution = open_workflow(api, data)
    request = chat_body(data)["recommendation_request"]
    request["experiment_spec"]["dataset_version_sha256"] = digest
    request["experiment_spec"]["time_axis"] = {"column": "timestamp", "sampling_status": "unknown"}
    request["experiment_spec"]["continuous_runs"] = [{"start": 0, "stop": size}]
    response = api.post(CONFIRM, json=spec_confirmation(execution, request))
    assert response.status_code == 422
    assert response.json()["error"]["details"]["required_fields"] == ["split"]
    assert snapshot(api, execution["execution_id"]) == execution


@pytest.mark.parametrize("model", ["pls", "xgboost"])
async def test_confirmed_untimed_order_is_version_bound_and_static_only(api, data, model):
    async with data["factory"]() as session:
        for version_id in (data["spec"].dataset_version_id, data["latest"]):
            version = await session.get(DatasetVersion, version_id)
            csv = "a,b,quality\n" + "".join(
                f"{i + 2},{i % 17 + 2},{i * 2 + i % 17 + 5}\n" for i in range(1000)
            )
            raw = csv.encode()
            (data["root"] / version.artifact_path).write_bytes(raw)
            version.row_count = 1000
            version.sha256 = sha256(raw).hexdigest()
        await session.commit()
    original = data["spec"].dataset_version_id
    digest = sha256(raw).hexdigest()
    execution = open_workflow(api, data)
    gate, select_step = execution["step_runs"][-2:]
    assert gate["result_payload"]["spec_requirement"]["field"] == "row_order"
    assert select_step["status"] == "PENDING"
    payload = spec_confirmation(execution, None)
    payload.pop("recommendation_request")
    order = {"dataset_version_id": str(original), "csv_sha256": digest}
    for wrong in ({"dataset_version_id": str(data["latest"])}, {"csv_sha256": "0" * 64}):
        response = api.post(CONFIRM, json={**payload, "row_order_confirmation": {**order, **wrong}})
        assert response.status_code == 409, response.text
        assert snapshot(api, execution["execution_id"]) == execution
    response_data(api.post(CONFIRM, json={**payload, "row_order_confirmation": order}))
    saved = snapshot(api, execution["execution_id"])
    rec, select_step = saved["step_runs"][-2:]
    assert select_step["status"] == "WAITING_CONFIRMATION"
    spec = rec["input_payload"]["recommendation_request"]["experiment_spec"]
    assert spec["application"] == "regression"
    assert spec["row_order"] == {**order, "row_order_status": "user_confirmed"}
    assert spec["continuous_runs"] == []
    assert spec["ordered_record_ranges"] == [{"start": 0, "stop": 1000}]
    assert spec["time_axis"]["sampling_status"] == "unknown"
    assert spec["time_axis"]["column"] is spec["time_axis"]["sample_period_seconds"] is None
    for name, start, stop in (("train", 0, 600), ("validation", 600, 800), ("test", 800, 1000)):
        assert spec["split"][name] == [{"start": start, "stop": stop}]
    result = rec["result_payload"]["recommendation"]
    assert result["leakage"]["status"] == "unknown"
    assert {item["model_type_id"]: item["eligibility_status"] for item in result["candidates"]} == {
        "pls": "eligible", "xgboost": "eligible", "tcn": "unknown", "timexer": "unknown",
    }
    assert_evaluation_contract(rec)
    assert result["profile"]["continuous_run_count"] == 0
    assert not [run for run in await runs(data) if run.run_type.startswith("modeling.")]
    response_data(api.post(CONFIRM, json=selected(saved, model, source="agent_recommendation")))
    trained = response_data(api.post(EXECUTE, json={
        "selection_execution_id": saved["execution_id"],
        "copilot_run_id": saved["copilot_run_id"],
        "confirmed_selection_step_id": saved["pending_confirmation_step_id"],
    }))
    assert trained["training_status"] == "succeeded" and trained["manifest_status"] == "published", trained
    assert trained["evaluation_status"] == "succeeded", trained
    assert trained["evaluation"]["model_id"] == trained["model_id"]
    assert trained["evaluation"]["sample_count"] == 200
    new_chat = response_data(api.post(CHAT, json={
        "message": "分析数据后选择模型建模",
        "dataset_id": str(data["spec"].dataset_id),
        "active_version_id": str(data["latest"]),
    }))
    new_state = snapshot(api, new_chat["execution_id"])
    assert new_state["step_runs"][-2]["result_payload"]["spec_requirement"]["field"] == "row_order"
    assert api.post(CONFIRM, json={
        **spec_confirmation(new_state, None), "row_order_confirmation": order,
    }).status_code == 409


async def test_inherited_dynamic_spec_keeps_null_application(data):
    spec = ExperimentSpec.model_validate({
        **data["spec"].model_dump(),
        "task_type": "dynamic_system_identification",
        "application": None,
        "feature_spec": {"kind": "dynamic_lags"},
    })
    draft = ModelRecommendationRequest(experiment_spec=spec)
    execution = AgentExecutionSession(dataset_id=spec.dataset_id, current_version_id=spec.dataset_version_id)
    async with data["factory"]() as session:
        request = await build_agent_recommendation_request(
            session, execution=execution, sequence=1, artifact_root=data["root"], draft=draft,
        )
    assert request.experiment_spec.task_type == "dynamic_system_identification"
    assert request.experiment_spec.application is None
    assert draft.experiment_spec == spec


@pytest.mark.parametrize("application", [None, "soft_sensor"])
async def test_legacy_spec_serialization_keeps_original_hash(data, application):
    spec = data["spec"].model_copy(update={"application": application})
    original = {key: value for key, value in spec.model_dump(mode="json").items()
                if key not in ("ordered_record_ranges", "row_order")}
    expected = sha256(json.dumps(
        original, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode()).hexdigest()
    restored = ExperimentSpec.model_validate(original)
    assert restored.application == application
    assert restored.evaluation.scopes == ("validation",)
    assert restored.model_dump(mode="json") == original
    assert spec_hash(restored) == expected
