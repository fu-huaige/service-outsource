"""Persistent execution contracts for the Copilot chat endpoint."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import pytest
from algorithms.agent.compliance import verify_plan as verify_plan_core
from algorithms.agent.llm import NullProvider
from app.core.config import Settings
from app.core.db import get_session
from app.main import create_app
from app.models import Base
from app.models.agent_execution import AgentExecutionSession
from app.services import agent_service
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload


@dataclass(frozen=True)
class ChatHarness:
    client: TestClient
    session_factory: async_sessionmaker[AsyncSession]


@pytest.fixture
def chat_harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[ChatHarness]:
    """Run chat against isolated SQLite and an explicitly disabled LLM provider."""

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'agent_chat_execution.db'}")
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
        yield ChatHarness(client=client, session_factory=session_factory)
    asyncio.run(engine.dispose())


def _benchmark_version(client: TestClient) -> str:
    response = client.post(
        "/api/v1/simulation/generate",
        json={"scenario": "S2", "n_steps": 900, "seed": 81, "input_count": 2},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["version_id"]


async def _load_execution(
    factory: async_sessionmaker[AsyncSession], execution_id: UUID
) -> AgentExecutionSession:
    async with factory() as session:
        execution = await session.scalar(
            select(AgentExecutionSession)
            .where(AgentExecutionSession.id == execution_id)
            .options(selectinload(AgentExecutionSession.step_runs))
        )
        assert execution is not None
        return execution


async def _execution_count(factory: async_sessionmaker[AsyncSession]) -> int:
    async with factory() as session:
        return int(
            await session.scalar(select(func.count()).select_from(AgentExecutionSession)) or 0
        )


def test_executable_chat_persists_plan_steps_and_confirmation_gate(
    chat_harness: ChatHarness,
) -> None:
    version_id = _benchmark_version(chat_harness.client)

    response = chat_harness.client.post(
        "/api/v1/copilot/chat",
        json={
            "message": "提取高信噪比的动态数据，估计时滞，处理共线性，然后做 ARX 辨识",
            "active_version_id": version_id,
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    execution_id = UUID(data["execution_id"])
    execution = asyncio.run(_load_execution(chat_harness.session_factory, execution_id))
    assert str(execution.initial_version_id) == version_id
    assert str(execution.current_version_id) == version_id
    assert data["current_version_id"] == version_id
    assert data["workflow_status"] == "WAITING_CONFIRMATION"
    assert execution.workflow_status == "WAITING_CONFIRMATION"
    assert data["pending_confirmation_step_id"] == execution.pending_confirmation_step_id
    assert [step.step_id for step in execution.step_runs] == [
        step["step_id"] for step in data["plan"]["steps"]
    ]

    waiting_step_id = data["pending_confirmation_step_id"]
    by_step = {step.step_id: step for step in execution.step_runs}
    assert by_step[waiting_step_id].status == "WAITING_CONFIRMATION"
    assert by_step[waiting_step_id].confirmation_status == "PENDING"
    waiting_sequence = by_step[waiting_step_id].sequence
    assert all(
        step.status == "PENDING"
        for step in execution.step_runs
        if step.sequence > waiting_sequence
    )
    completed = next(run for run in data["step_runs"] if run["status"] == "completed")
    assert by_step[completed["step_id"]].result_payload["result"] == completed["result"]


def test_plan_only_chat_returns_no_execution_and_writes_no_execution_session(
    chat_harness: ChatHarness,
) -> None:
    response = chat_harness.client.post(
        "/api/v1/copilot/chat", json={"message": "清洗数据后做 ARX 辨识"}
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["execution_id"] is None
    assert data["workflow_status"] is None
    assert data["current_version_id"] is None
    assert data["pending_confirmation_step_id"] is None
    assert data["executed"] is False
    assert asyncio.run(_execution_count(chat_harness.session_factory)) == 0


def test_persistent_state_sync_never_dispatches_a_tool_twice(
    chat_harness: ChatHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    version_id = _benchmark_version(chat_harness.client)
    original_dispatch = agent_service._dispatch
    dispatch_count = 0

    def counted_dispatch(*args: object, **kwargs: object) -> tuple[str, dict[str, object]]:
        nonlocal dispatch_count
        dispatch_count += 1
        return original_dispatch(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(agent_service, "_dispatch", counted_dispatch)
    response = chat_harness.client.post(
        "/api/v1/copilot/chat",
        json={"message": "做动态区间优选", "active_version_id": version_id},
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["execution_id"] is not None
    dispatched_runs = [run for run in data["step_runs"] if run["status"] == "completed"]
    assert dispatch_count == len(dispatched_runs)
    assert dispatch_count > 0


def test_compliance_rejection_does_not_create_execution(
    chat_harness: ChatHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    version_id = _benchmark_version(chat_harness.client)
    rejected = verify_plan_core(
        [
            {
                "step_id": "unsafe",
                "tool": "run_arbitrary_python",
                "depends_on": [],
                "parameters": {},
            }
        ]
    )
    assert rejected.passed is False
    monkeypatch.setattr(agent_service, "verify_plan", lambda *args, **kwargs: rejected)

    response = chat_harness.client.post(
        "/api/v1/copilot/chat",
        json={"message": "做动态区间优选", "active_version_id": version_id},
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["compliance"]["passed"] is False
    assert data["execution_id"] is None
    assert asyncio.run(_execution_count(chat_harness.session_factory)) == 0


def test_failed_step_marks_persistent_execution_failed(
    chat_harness: ChatHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    version_id = _benchmark_version(chat_harness.client)

    def fail_first_step(series: object, steps: list[object], hints: dict[str, object]):
        first = steps[0]
        return [
            agent_service.StepExecution(
                step_id=first.step_id,
                tool=first.tool,
                status="failed",
                parameters=dict(first.parameters),
                summary="deterministic state-sync failure",
                error_code="SYNC_TEST_FAILURE",
            )
        ]

    monkeypatch.setattr(agent_service, "_execute", fail_first_step)
    response = chat_harness.client.post(
        "/api/v1/copilot/chat",
        json={"message": "做动态区间优选", "active_version_id": version_id},
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    execution = asyncio.run(
        _load_execution(chat_harness.session_factory, UUID(data["execution_id"]))
    )
    assert data["workflow_status"] == "FAILED"
    assert execution.workflow_status == "FAILED"
    assert execution.error_code == "SYNC_TEST_FAILURE"
    assert execution.step_runs[0].status == "FAILED"
    assert all(step.status == "PENDING" for step in execution.step_runs[1:])


def test_deferred_step_is_not_persisted_as_completed_workflow(
    chat_harness: ChatHarness,
) -> None:
    version_id = _benchmark_version(chat_harness.client)
    response = chat_harness.client.post(
        "/api/v1/copilot/chat",
        json={"message": "生成报告", "active_version_id": version_id},
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    execution = asyncio.run(
        _load_execution(chat_harness.session_factory, UUID(data["execution_id"]))
    )
    assert execution.workflow_status != "SUCCEEDED"
    deferred = next(run for run in data["step_runs"] if run["result"].get("deferred"))
    persisted = next(step for step in execution.step_runs if step.step_id == deferred["step_id"])
    assert deferred["status"] == "pending"
    assert persisted.status == "PENDING"
