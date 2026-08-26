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
from app.core.config import Settings
from app.core.db import get_session
from app.main import create_app
from app.models import Base, DatasetVersion
from app.models.agent_execution import AgentExecutionSession
from app.schemas.copilot import ExecutionPlan, ExecutionPlanStep
from app.services import agent_service, agent_tool_adapter
from app.services.agent_execution_service import (
    create_execution,
    mark_step_failed,
    mark_step_succeeded,
    start_step,
)
from app.services.agent_tool_adapter import execute_agent_tool
from app.services.cleaning_service import CleaningDomainError
from fastapi.testclient import TestClient
from sqlalchemy import select
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
        ExecutionPlanStep(step_id="s1", tool="clean_data"), dataset_id=dataset_id
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
            step = execution.step_runs[0]
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
    step = execution.step_runs[0]
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
        ExecutionPlanStep(step_id="s1", tool="clean_data"),
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
            cleaning = execution.step_runs[0]
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
    cleaning, delay = execution.step_runs
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
        ExecutionPlanStep(step_id="s1", tool="clean_data"),
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
            step = execution.step_runs[0]
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
    assert execution.step_runs[0].status == "FAILED"
    assert execution.step_runs[1].status == "PENDING"


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