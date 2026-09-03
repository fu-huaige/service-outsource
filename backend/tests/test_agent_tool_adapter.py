"""Formal Agent tool-adapter contracts for cleaning and delay analysis."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from algorithms.agent.compliance import verify_plan
from algorithms.agent.llm import NullProvider
from algorithms.agent.planner import RuleBasedPlanner, parse_intent
from app.core.config import Settings
from app.core.db import get_session
from app.main import create_app
from app.models import Base, DatasetVersion, ProcessingRun
from app.models.agent_execution import AgentExecutionSession
from app.schemas.copilot import ExecutionPlan, ExecutionPlanStep
from app.services import agent_service, agent_tool_adapter
from app.services.agent_execution_service import (
    approve_step,
    create_execution,
    get_execution,
    mark_step_failed,
    mark_step_succeeded,
    start_step,
)
from app.services.agent_tool_adapter import execute_agent_tool
from app.services.agent_arx_modeling_service import ArxStructureError
from app.services.cleaning_service import CleaningDomainError
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload


@dataclass(frozen=True)
class AdapterHarness:
    client: TestClient
    session_factory: async_sessionmaker[AsyncSession]
    artifact_root: Path


@pytest.fixture
def adapter_harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[AdapterHarness]:
    """Run formal preprocessing against isolated SQLite and real CSV artifacts."""

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'agent_tool_adapter.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def prepare() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def session_override() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    asyncio.run(prepare())
    monkeypatch.setattr("app.api.routes.get_settings", lambda: Settings(artifact_root=tmp_path))
    monkeypatch.setattr(agent_service, "_resolve_provider", lambda: NullProvider())
    app = create_app()
    app.dependency_overrides[get_session] = session_override
    with TestClient(app) as client:
        yield AdapterHarness(
            client=client, session_factory=session_factory, artifact_root=tmp_path
        )
    asyncio.run(engine.dispose())


def _controlled_csv(*, numeric: bool = True) -> bytes:
    """A real 1 Hz process CSV with a repairable spike and short gap."""

    start = datetime(2026, 1, 1, tzinfo=UTC)
    headers = "timestamp,u1,y" if numeric else "timestamp,label"
    rows = [headers]
    for index in range(480):
        timestamp = (start + timedelta(seconds=index)).isoformat()
        if not numeric:
            rows.append(f"{timestamp},normal")
            continue
        u1 = 1.0 if index % 80 < 40 else -1.0
        y = 0.6 * u1 + 0.01 * index
        if index == 140:
            y += 40.0
        if 230 <= index < 235:
            rows.append(f"{timestamp},{u1},")
        else:
            rows.append(f"{timestamp},{u1:.6f},{y:.6f}")
    return ("\n".join(rows) + "\n").encode("utf-8")


def _upload_controlled_version(harness: AdapterHarness, *, numeric: bool = True) -> tuple[UUID, UUID]:
    uploaded = harness.client.post(
        "/api/v1/datasets/upload",
        files={"file": ("agent-tool.csv", _controlled_csv(numeric=numeric), "text/csv")},
        data={"name": "Agent Tool Adapter"},
    )
    assert uploaded.status_code == 202, uploaded.text
    dataset = uploaded.json()["data"]["dataset"]
    dataset_id = UUID(dataset["id"])
    version_id = UUID(dataset["latest_version_id"])
    if numeric:
        configured = harness.client.post(
            f"/api/v1/datasets/{dataset_id}/config",
            json={
                "columns": [
                    {"name": "timestamp", "role": "time"},
                    {"name": "u1", "role": "input"},
                    {"name": "y", "role": "output"},
                ]
            },
        )
        assert configured.status_code == 200, configured.text
    return dataset_id, version_id


def _plan(*steps: ExecutionPlanStep, dataset_id: UUID) -> tuple[ExecutionPlan, object]:
    plan = ExecutionPlan(goal="formal preprocessing", dataset_id=dataset_id, steps=list(steps))
    proof = verify_plan(
        [
            {
                "step_id": step.step_id,
                "tool": step.tool,
                "depends_on": list(step.depends_on),
                "parameters": dict(step.parameters),
                "requires_confirmation": step.requires_confirmation,
            }
            for step in steps
        ],
        code_version=agent_service.CODE_VERSION,
    )
    assert proof.passed
    return plan, proof


async def _create_and_start(
    harness: AdapterHarness,
    *,
    dataset_id: UUID,
    version_id: UUID,
    plan: ExecutionPlan,
    proof: object,
    step_id: str,
) -> AgentExecutionSession:
    async with harness.session_factory() as session:
        execution = await create_execution(
            session,
            dataset_id=dataset_id,
            initial_version_id=version_id,
            planner_source="test",
            plan=plan,
            compliance_proof=proof,  # type: ignore[arg-type]
        )
        execution = await get_execution(session, execution_id=execution.id)
        target = next(step for step in execution.step_runs if step.step_id == step_id)
        for prerequisite in sorted(execution.step_runs, key=lambda item: item.sequence):
            if prerequisite.sequence >= target.sequence:
                break
            execution = await start_step(
                session, execution_id=execution.id, step_id=prerequisite.step_id
            )
            execution = await mark_step_succeeded(
                session, execution_id=execution.id, step_id=prerequisite.step_id
            )
        return await start_step(session, execution_id=execution.id, step_id=step_id)


async def _load_execution(
    harness: AdapterHarness, execution_id: UUID
) -> AgentExecutionSession:
    async with harness.session_factory() as session:
        execution = await session.scalar(
            select(AgentExecutionSession)
            .where(AgentExecutionSession.id == execution_id)
            .options(selectinload(AgentExecutionSession.step_runs))
        )
        assert execution is not None
        return execution


async def _version_artifact(
    harness: AdapterHarness, version_id: UUID
) -> tuple[DatasetVersion, bytes]:
    async with harness.session_factory() as session:
        version = await session.get(DatasetVersion, version_id)
        assert version is not None
        return version, (harness.artifact_root / version.artifact_path).read_bytes()


def test_cleaning_adapter_uses_formal_service_and_preserves_source_version(
    adapter_harness: AdapterHarness,
) -> None:
    dataset_id, v0 = _upload_controlled_version(adapter_harness)
    plan, proof = _plan(
        ExecutionPlanStep(step_id="p1", tool="profile_dataset"),
        ExecutionPlanStep(step_id="p2", tool="detect_anomalies", depends_on=["p1"]),
        ExecutionPlanStep(step_id="s1", tool="clean_data", depends_on=["p2"]),
        dataset_id=dataset_id,
    )
    started = asyncio.run(
        _create_and_start(
            adapter_harness,
            dataset_id=dataset_id,
            version_id=v0,
            plan=plan,
            proof=proof,
            step_id="s1",
        )
    )
    _, v0_bytes_before = asyncio.run(_version_artifact(adapter_harness, v0))

    async def run() -> tuple[UUID, object]:
        async with adapter_harness.session_factory() as session:
            execution = await _load_execution(adapter_harness, started.id)
            step = next(item for item in execution.step_runs if item.step_id == "s1")
            result = await execute_agent_tool(
                session,
                execution=execution,
                step=step,
                parameters=step.input_payload["parameters"],
                artifact_root=adapter_harness.artifact_root,
            )
            persisted = await mark_step_succeeded(
                session,
                execution_id=execution.id,
                step_id=step.step_id,
                result_payload=result.result_payload,
                source_version_id=result.source_version_id,
                result_version_id=result.result_version_id,
                processing_run_ids=result.processing_run_ids,
            )
            return persisted.id, result

    execution_id, result = asyncio.run(run())
    assert result.source_version_id == v0
    assert result.result_version_id is not None
    assert result.result_version_id != v0
    assert result.processing_run_ids
    execution = asyncio.run(_load_execution(adapter_harness, execution_id))
    step = next(item for item in execution.step_runs if item.step_id == "s1")
    assert step.source_version_id == v0
    assert step.result_version_id == result.result_version_id
    assert execution.current_version_id == result.result_version_id
    assert execution.initial_version_id == v0
    _, v0_bytes_after = asyncio.run(_version_artifact(adapter_harness, v0))
    v1, _ = asyncio.run(_version_artifact(adapter_harness, result.result_version_id))
    assert v0_bytes_after == v0_bytes_before
    assert v1.parent_version_id == v0
    assert v1.operation_name == "preprocessing.clean"


def test_delay_adapter_reads_cleaned_current_version_without_creating_another_version(
    adapter_harness: AdapterHarness,
) -> None:
    dataset_id, v0 = _upload_controlled_version(adapter_harness)
    plan, proof = _plan(
        ExecutionPlanStep(step_id="p1", tool="profile_dataset"),
        ExecutionPlanStep(step_id="p2", tool="detect_anomalies", depends_on=["p1"]),
        ExecutionPlanStep(step_id="s1", tool="clean_data", depends_on=["p2"]),
        ExecutionPlanStep(step_id="s2", tool="estimate_delays", depends_on=["s1"]),
        dataset_id=dataset_id,
    )
    started = asyncio.run(
        _create_and_start(
            adapter_harness,
            dataset_id=dataset_id,
            version_id=v0,
            plan=plan,
            proof=proof,
            step_id="s1",
        )
    )

    async def run() -> AgentExecutionSession:
        async with adapter_harness.session_factory() as session:
            execution = await _load_execution(adapter_harness, started.id)
            cleaning = next(item for item in execution.step_runs if item.step_id == "s1")
            cleaned = await execute_agent_tool(
                session,
                execution=execution,
                step=cleaning,
                parameters=cleaning.input_payload["parameters"],
                artifact_root=adapter_harness.artifact_root,
            )
            execution = await mark_step_succeeded(
                session,
                execution_id=execution.id,
                step_id=cleaning.step_id,
                result_payload=cleaned.result_payload,
                source_version_id=cleaned.source_version_id,
                result_version_id=cleaned.result_version_id,
                processing_run_ids=cleaned.processing_run_ids,
            )
            execution = await start_step(session, execution_id=execution.id, step_id="s2")
            delay = next(step for step in execution.step_runs if step.step_id == "s2")
            delayed = await execute_agent_tool(
                session,
                execution=execution,
                step=delay,
                parameters=delay.input_payload["parameters"],
                artifact_root=adapter_harness.artifact_root,
            )
            return await mark_step_succeeded(
                session,
                execution_id=execution.id,
                step_id=delay.step_id,
                result_payload=delayed.result_payload,
                source_version_id=delayed.source_version_id,
                result_version_id=delayed.result_version_id,
                processing_run_ids=delayed.processing_run_ids,
            )

    execution = asyncio.run(run())
    cleaning = next(item for item in execution.step_runs if item.step_id == "s1")
    delay = next(item for item in execution.step_runs if item.step_id == "s2")
    assert cleaning.source_version_id == v0
    assert cleaning.result_version_id is not None
    assert delay.source_version_id == cleaning.result_version_id
    assert delay.result_version_id is None
    assert delay.processing_run_ids
    assert execution.current_version_id == cleaning.result_version_id


def test_failed_formal_cleaning_keeps_current_version_and_stops_downstream(
    adapter_harness: AdapterHarness,
) -> None:
    dataset_id, v0 = _upload_controlled_version(adapter_harness, numeric=False)
    plan, proof = _plan(
        ExecutionPlanStep(step_id="p1", tool="profile_dataset"),
        ExecutionPlanStep(step_id="p2", tool="detect_anomalies", depends_on=["p1"]),
        ExecutionPlanStep(step_id="s1", tool="clean_data", depends_on=["p2"]),
        ExecutionPlanStep(step_id="s2", tool="estimate_delays", depends_on=["s1"]),
        dataset_id=dataset_id,
    )
    started = asyncio.run(
        _create_and_start(
            adapter_harness,
            dataset_id=dataset_id,
            version_id=v0,
            plan=plan,
            proof=proof,
            step_id="s1",
        )
    )

    async def run() -> AgentExecutionSession:
        async with adapter_harness.session_factory() as session:
            execution = await _load_execution(adapter_harness, started.id)
            step = next(item for item in execution.step_runs if item.step_id == "s1")
            with pytest.raises(CleaningDomainError) as raised:
                await execute_agent_tool(
                    session,
                    execution=execution,
                    step=step,
                    parameters=step.input_payload["parameters"],
                    artifact_root=adapter_harness.artifact_root,
                )
            return await mark_step_failed(
                session,
                execution_id=execution.id,
                step_id=step.step_id,
                error_code=raised.value.code,
                error_message=raised.value.message,
            )

    execution = asyncio.run(run())
    assert execution.workflow_status == "FAILED"
    assert execution.current_version_id == v0
    assert next(item for item in execution.step_runs if item.step_id == "s1").status == "FAILED"
    assert next(item for item in execution.step_runs if item.step_id == "s2").status == "PENDING"


def test_chat_cleaning_then_delay_persists_v1_as_delay_source(
    adapter_harness: AdapterHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset_id, v0 = _upload_controlled_version(adapter_harness)
    legacy_tools: list[str] = []
    formal_clean_calls = 0
    original_dispatch = agent_service._dispatch
    original_clean = agent_tool_adapter.clean_dataset_version

    def tracked_dispatch(*args: object, **kwargs: object) -> tuple[str, dict[str, object]]:
        step = args[0]
        legacy_tools.append(step.tool)  # type: ignore[union-attr]
        return original_dispatch(*args, **kwargs)  # type: ignore[arg-type]

    async def tracked_clean(*args: object, **kwargs: object) -> object:
        nonlocal formal_clean_calls
        formal_clean_calls += 1
        return await original_clean(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(agent_service, "_dispatch", tracked_dispatch)
    monkeypatch.setattr(agent_tool_adapter, "clean_dataset_version", tracked_clean)
    response = adapter_harness.client.post(
        "/api/v1/copilot/chat",
        json={
            "message": "清洗数据并估计时滞",
            "dataset_id": str(dataset_id),
            "active_version_id": str(v0),
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    execution = asyncio.run(
        _load_execution(adapter_harness, UUID(data["execution_id"]))
    )
    by_tool = {step.tool_name: step for step in execution.step_runs}
    cleaning = by_tool["clean_data"]
    delay = by_tool["estimate_delays"]
    assert cleaning.source_version_id == v0
    assert cleaning.result_version_id is not None
    assert delay.source_version_id == cleaning.result_version_id
    assert delay.result_version_id is None
    assert execution.current_version_id == cleaning.result_version_id
    assert data["current_version_id"] == str(cleaning.result_version_id)
    assert formal_clean_calls == 1
    assert "clean_data" not in legacy_tools
    assert "estimate_delays" not in legacy_tools

def _benchmark_dataset_version(harness: AdapterHarness) -> tuple[UUID, UUID]:
    response = harness.client.post(
        "/api/v1/simulation/generate",
        json={"scenario": "S2", "n_steps": 900, "seed": 81, "input_count": 2},
    )
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    return UUID(data["dataset_id"]), UUID(data["version_id"])


def _chat_to_lag_confirmation(
    harness: AdapterHarness,
) -> tuple[dict[str, object], AgentExecutionSession, dict[str, int]]:
    dataset_id, v0 = _benchmark_dataset_version(harness)
    response = harness.client.post(
        "/api/v1/copilot/chat",
        json={
            "message": "清洗数据、估计时滞，然后做 ARX 辨识",
            "dataset_id": str(dataset_id),
            "active_version_id": str(v0),
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    execution = asyncio.run(_load_execution(harness, UUID(data["execution_id"])))
    delay = next(step for step in execution.step_runs if step.tool_name == "estimate_delays")
    lag = next(step for step in execution.step_runs if step.tool_name == "apply_lag_compensation")
    recommended = {key: int(value) for key, value in delay.result_payload["best_delays"].items()}
    assert lag.status == "WAITING_CONFIRMATION"
    assert lag.confirmation_status == "PENDING"
    assert lag.input_payload["recommended_lag_map"] == recommended
    return data, execution, recommended


def _lag_validation(
    harness: AdapterHarness,
    *,
    execution_id: UUID,
    step_id: str,
    overrides: list[dict[str, object]],
):
    return harness.client.post(
        "/api/v1/copilot/lag-overrides/validate",
        json={
            "execution_id": str(execution_id),
            "step_id": step_id,
            "manual_overrides": overrides,
        },
    )


def _lag_confirm(
    harness: AdapterHarness,
    *,
    execution_id: UUID,
    step_id: str,
    approved: bool = True,
    overrides: list[dict[str, object]] | None = None,
    warning_acknowledged: bool = False,
):
    return harness.client.post(
        "/api/v1/copilot/confirm",
        json={
            "copilot_run_id": str(execution_id),
            "confirmation_id": step_id,
            "execution_id": str(execution_id),
            "step_id": step_id,
            "approved": approved,
            "manual_overrides": overrides or [],
            "warning_acknowledged": warning_acknowledged,
        },
    )


async def _counts(harness: AdapterHarness, dataset_id: UUID) -> tuple[int, int]:
    async with harness.session_factory() as session:
        versions = int(
            await session.scalar(
                select(func.count())
                .select_from(DatasetVersion)
                .where(DatasetVersion.dataset_id == dataset_id)
            )
            or 0
        )
        lag_runs = int(
            await session.scalar(
                select(func.count())
                .select_from(ProcessingRun)
                .where(
                    ProcessingRun.dataset_id == dataset_id,
                    ProcessingRun.run_type == "preprocessing.lag_compensation",
                )
            )
            or 0
        )
        return versions, lag_runs


def _different_valid_lag(recommended: int, analyzed_max: int) -> int:
    return next(value for value in range(analyzed_max + 1) if value != recommended)


def test_planner_emits_confirmed_lag_apply_after_delay() -> None:
    steps, _, _ = RuleBasedPlanner().plan(parse_intent("估计时滞并应用补偿"))
    by_tool = {step.tool: step for step in steps}
    assert "apply_lag_compensation" in by_tool
    apply = by_tool["apply_lag_compensation"]
    assert apply.requires_confirmation is True
    assert apply.depends_on == (by_tool["estimate_delays"].step_id,)


def test_lag_override_validation_is_deterministic_and_aggregated(
    adapter_harness: AdapterHarness,
) -> None:
    _, execution, recommended = _chat_to_lag_confirmation(adapter_harness)
    lag = next(step for step in execution.step_runs if step.tool_name == "apply_lag_compensation")
    delay = next(step for step in execution.step_runs if step.tool_name == "estimate_delays")
    first, second = list(recommended)[:2]
    first_max = len(delay.result_payload["correlations"][first]) - 1
    second_max = len(delay.result_payload["correlations"][second]) - 1
    valid_value = _different_valid_lag(recommended[first], first_max)
    warning_value = second_max + 1

    valid = _lag_validation(
        adapter_harness,
        execution_id=execution.id,
        step_id=lag.step_id,
        overrides=[{"variable": first, "value": valid_value}],
    )
    assert valid.status_code == 200, valid.text
    assert valid.json()["data"]["overall_status"] == "VALID"
    assert valid.json()["data"]["final_lag_map"][second] == recommended[second]

    warning = _lag_validation(
        adapter_harness,
        execution_id=execution.id,
        step_id=lag.step_id,
        overrides=[
            {"variable": first, "value": valid_value},
            {"variable": second, "value": warning_value},
        ],
    )
    assert warning.status_code == 200, warning.text
    warning_data = warning.json()["data"]
    assert warning_data["overall_status"] == "WARNING"
    assert {item["status"] for item in warning_data["per_parameter_validation"]} == {
        "VALID",
        "WARNING",
    }

    duplicate = _lag_validation(
        adapter_harness,
        execution_id=execution.id,
        step_id=lag.step_id,
        overrides=[
            {"variable": first, "value": valid_value},
            {"variable": first, "value": valid_value + 1},
        ],
    )
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["data"]["overall_status"] == "INVALID"

    unknown = _lag_validation(
        adapter_harness,
        execution_id=execution.id,
        step_id=lag.step_id,
        overrides=[{"variable": "u99", "value": 1}],
    )
    assert unknown.status_code == 200, unknown.text
    assert unknown.json()["data"]["overall_status"] == "INVALID"

    invalid = _lag_validation(
        adapter_harness,
        execution_id=execution.id,
        step_id=lag.step_id,
        overrides=[
            {"variable": first, "value": "not-an-integer"},
            {"variable": second, "value": 900},
        ],
    )
    assert invalid.status_code == 200, invalid.text
    invalid_data = invalid.json()["data"]
    assert invalid_data["overall_status"] == "INVALID"
    assert any(item["status"] == "INVALID" for item in invalid_data["per_parameter_validation"])


def test_direct_lag_approve_creates_v2_once_and_duplicate_is_idempotent(
    adapter_harness: AdapterHarness,
) -> None:
    _, execution, _ = _chat_to_lag_confirmation(adapter_harness)
    lag = next(step for step in execution.step_runs if step.tool_name == "apply_lag_compensation")
    v1 = execution.current_version_id
    _, v1_bytes_before = asyncio.run(_version_artifact(adapter_harness, v1))
    before = asyncio.run(_counts(adapter_harness, execution.dataset_id))

    first = _lag_confirm(adapter_harness, execution_id=execution.id, step_id=lag.step_id)
    assert first.status_code == 200, first.text
    first_data = first.json()["data"]
    assert first_data["step_status"] == "SUCCEEDED"
    assert first_data["confirmation_status"] == "APPROVED"
    v2 = UUID(first_data["result_version_id"])
    assert UUID(first_data["current_version_id"]) == v2

    persisted = asyncio.run(_load_execution(adapter_harness, execution.id))
    persisted_lag = next(
        step for step in persisted.step_runs if step.tool_name == "apply_lag_compensation"
    )
    assert persisted_lag.source_version_id == v1
    assert persisted_lag.result_version_id == v2
    assert persisted_lag.processing_run_ids
    assert persisted.current_version_id == v2
    fit = next(step for step in persisted.step_runs if step.tool_name == "fit_arx")
    assert fit.status == "WAITING_CONFIRMATION"
    assert fit.input_payload["arx_structure_recommendation"]["source_version_id"] == str(v2)
    assert next(
        step for step in persisted.step_runs if step.sequence > persisted_lag.sequence
    ).status == "SUCCEEDED"
    v2_node, _ = asyncio.run(_version_artifact(adapter_harness, v2))
    _, v1_bytes_after = asyncio.run(_version_artifact(adapter_harness, v1))
    assert v2_node.parent_version_id == v1
    assert v1_bytes_after == v1_bytes_before

    after_first = asyncio.run(_counts(adapter_harness, execution.dataset_id))
    assert after_first == (before[0] + 1, before[1] + 1)
    replay = _lag_confirm(adapter_harness, execution_id=execution.id, step_id=lag.step_id)
    assert replay.status_code == 200, replay.text
    assert replay.json()["data"]["result_version_id"] == str(v2)
    assert asyncio.run(_counts(adapter_harness, execution.dataset_id)) == after_first

    changed = _lag_confirm(
        adapter_harness,
        execution_id=execution.id,
        step_id=lag.step_id,
        overrides=[
            {
                "variable": next(iter(persisted_lag.input_payload["final_lag_map"])),
                "value": 0,
            }
        ],
    )
    assert changed.status_code == 409, changed.text
    assert asyncio.run(_counts(adapter_harness, execution.dataset_id)) == after_first


def test_fit_adapter_rejects_raw_version_before_creating_model_run(
    adapter_harness: AdapterHarness,
) -> None:
    dataset_id, v0 = _upload_controlled_version(adapter_harness)
    plan = ExecutionPlan(
        goal="direct adapter hard guard",
        dataset_id=dataset_id,
        steps=[
            ExecutionPlanStep(step_id="p1", tool="profile_dataset"),
            ExecutionPlanStep(
                step_id="s1",
                tool="fit_arx",
                depends_on=["p1"],
                parameters={
                    "input_columns": ["u1"],
                    "output_column": "y",
                    "na": 1,
                    "nb": {"u1": 1},
                    "delays": {"u1": 0},
                },
                requires_confirmation=True,
            ),
        ],
    )
    proof = verify_plan(
        [step.model_dump() for step in plan.steps],
        code_version=agent_service.CODE_VERSION,
        lag_ready=True,
    )
    assert proof.passed

    async def run() -> tuple[str, int]:
        async with adapter_harness.session_factory() as session:
            execution = await create_execution(
                session,
                dataset_id=dataset_id,
                initial_version_id=v0,
                planner_source="test-bypass",
                plan=plan,
                compliance_proof=proof,
            )
            execution = await start_step(session, execution_id=execution.id, step_id="p1")
            execution = await mark_step_succeeded(
                session, execution_id=execution.id, step_id="p1"
            )
            execution = await start_step(session, execution_id=execution.id, step_id="s1")
            execution = await approve_step(session, execution_id=execution.id, step_id="s1")
            fit = next(step for step in execution.step_runs if step.step_id == "s1")
            with pytest.raises(ArxStructureError) as raised:
                await execute_agent_tool(
                    session,
                    execution=execution,
                    step=fit,
                    parameters=fit.input_payload["parameters"],
                    artifact_root=adapter_harness.artifact_root,
                )
            run_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(ProcessingRun)
                    .where(
                        ProcessingRun.dataset_id == dataset_id,
                        ProcessingRun.run_type == "modeling.arx",
                    )
                )
                or 0
            )
            return raised.value.code, run_count

    error_code, run_count = asyncio.run(run())
    assert error_code == "ARX_LAG_COMPENSATED_VERSION_REQUIRED"
    assert run_count == 0


def test_valid_partial_override_merges_with_recommendation(
    adapter_harness: AdapterHarness,
) -> None:
    _, execution, recommended = _chat_to_lag_confirmation(adapter_harness)
    lag = next(step for step in execution.step_runs if step.tool_name == "apply_lag_compensation")
    delay = next(step for step in execution.step_runs if step.tool_name == "estimate_delays")
    variable = next(iter(recommended))
    analyzed_max = len(delay.result_payload["correlations"][variable]) - 1
    manual_value = _different_valid_lag(recommended[variable], analyzed_max)

    response = _lag_confirm(
        adapter_harness,
        execution_id=execution.id,
        step_id=lag.step_id,
        overrides=[{"variable": variable, "value": manual_value}],
    )

    assert response.status_code == 200, response.text
    persisted = asyncio.run(_load_execution(adapter_harness, execution.id))
    applied = next(
        step for step in persisted.step_runs if step.tool_name == "apply_lag_compensation"
    )
    assert applied.input_payload["manual_overrides"] == {variable: manual_value}
    assert applied.input_payload["final_lag_map"][variable] == manual_value
    assert all(
        applied.input_payload["final_lag_map"][name] == value
        for name, value in recommended.items()
        if name != variable
    )
    assert applied.input_payload["parameter_sources"][variable] == "manual_override"


def test_warning_requires_acknowledgement_before_lag_apply(
    adapter_harness: AdapterHarness,
) -> None:
    _, execution, recommended = _chat_to_lag_confirmation(adapter_harness)
    lag = next(step for step in execution.step_runs if step.tool_name == "apply_lag_compensation")
    delay = next(step for step in execution.step_runs if step.tool_name == "estimate_delays")
    variable = next(iter(recommended))
    warning_value = len(delay.result_payload["correlations"][variable])
    before = asyncio.run(_counts(adapter_harness, execution.dataset_id))
    overrides = [{"variable": variable, "value": warning_value}]

    blocked = _lag_confirm(
        adapter_harness,
        execution_id=execution.id,
        step_id=lag.step_id,
        overrides=overrides,
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["error"]["code"] == "LAG_OVERRIDE_WARNING_ACK_REQUIRED"
    assert asyncio.run(_counts(adapter_harness, execution.dataset_id)) == before

    confirmed = _lag_confirm(
        adapter_harness,
        execution_id=execution.id,
        step_id=lag.step_id,
        overrides=overrides,
        warning_acknowledged=True,
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["data"]["step_status"] == "SUCCEEDED"
    after = asyncio.run(_load_execution(adapter_harness, execution.id))
    applied = next(step for step in after.step_runs if step.tool_name == "apply_lag_compensation")
    assert applied.input_payload["warning_acknowledged"] is True


def test_reject_does_not_apply_lag_or_create_v2(adapter_harness: AdapterHarness) -> None:
    _, execution, _ = _chat_to_lag_confirmation(adapter_harness)
    lag = next(step for step in execution.step_runs if step.tool_name == "apply_lag_compensation")
    before = asyncio.run(_counts(adapter_harness, execution.dataset_id))
    v1 = execution.current_version_id

    response = _lag_confirm(
        adapter_harness,
        execution_id=execution.id,
        step_id=lag.step_id,
        approved=False,
    )

    assert response.status_code == 200, response.text
    persisted = asyncio.run(_load_execution(adapter_harness, execution.id))
    rejected = next(
        step for step in persisted.step_runs if step.tool_name == "apply_lag_compensation"
    )
    assert persisted.workflow_status == "CANCELLED"
    assert persisted.current_version_id == v1
    assert rejected.status == "CANCELLED"
    assert rejected.confirmation_status == "REJECTED"
    assert asyncio.run(_counts(adapter_harness, execution.dataset_id)) == before
