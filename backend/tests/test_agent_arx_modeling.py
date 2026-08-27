"""Controlled ARX structure recommendation and confirmed modeling contracts."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import numpy as np
import pytest
from algorithms.agent.llm import NullProvider
from algorithms.agent.planner import RuleBasedPlanner, parse_intent
from app.core.config import Settings
from app.core.db import get_session
from app.main import create_app
from app.models import Base, DatasetVersion, ProcessingRun
from app.models.agent_execution import AgentExecutionSession, AgentStepRun
from app.services import agent_service
from app.services.agent_execution_service import (
    ExecutionStateError,
    approve_step,
    mark_step_failed,
    mark_step_succeeded,
    start_step,
)
from app.services.agent_tool_adapter import AgentToolAdapterError, execute_agent_tool
from app.services.modeling_service import ModelingDomainError
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload


@dataclass(frozen=True)
class ArxHarness:
    client: TestClient
    session_factory: async_sessionmaker[AsyncSession]
    artifact_root: Path


@pytest.fixture
def arx_harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[ArxHarness]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'agent_arx.db'}")
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
        yield ArxHarness(client=client, session_factory=session_factory, artifact_root=tmp_path)
    asyncio.run(engine.dispose())


def _arx_csv(*, alter_test_partition: bool = False) -> bytes:
    sample_count = 1_200
    generator = np.random.default_rng(20260826)
    u1 = np.empty(sample_count, dtype=float)
    u2 = np.empty(sample_count, dtype=float)
    u3 = np.empty(sample_count, dtype=float)
    for start in range(0, sample_count, 13):
        u1[start : start + 13] = generator.uniform(-1.5, 1.5)
    for start in range(0, sample_count, 19):
        u2[start : start + 19] = generator.uniform(-1.2, 1.2)
    for start in range(0, sample_count, 17):
        u3[start : start + 17] = generator.uniform(-0.8, 0.8)

    output = np.zeros(sample_count, dtype=float)
    for index in range(8, sample_count):
        output[index] = (
            1.35 * output[index - 1]
            - 0.42 * output[index - 2]
            + 0.36 * u1[index - 3]
            + 0.12 * u1[index - 4]
            + 0.18 * u2[index - 8]
            + 0.06 * u2[index - 9]
            + generator.normal(0.0, 0.01)
        )
    if alter_test_partition:
        output[int(sample_count * 0.9) :] += 250.0

    started = datetime(2026, 8, 1, tzinfo=UTC)
    rows = ["timestamp,u1,u2,u3,y"]
    for index in range(sample_count):
        timestamp = (started + timedelta(seconds=index)).isoformat()
        rows.append(
            f"{timestamp},{u1[index]:.10f},{u2[index]:.10f},"
            f"{u3[index]:.10f},{output[index]:.10f}"
        )
    return ("\n".join(rows) + "\n").encode("utf-8")


def _upload_and_build_v3(
    harness: ArxHarness, *, alter_test_partition: bool = False
) -> tuple[UUID, UUID]:
    uploaded = harness.client.post(
        "/api/v1/datasets/upload",
        files={
            "file": (
                "controlled-arx.csv",
                _arx_csv(alter_test_partition=alter_test_partition),
                "text/csv",
            )
        },
        data={"name": "Controlled ARX"},
    )
    assert uploaded.status_code == 202, uploaded.text
    dataset = uploaded.json()["data"]["dataset"]
    dataset_id = UUID(dataset["id"])
    v0 = UUID(dataset["latest_version_id"])
    configured = harness.client.post(
        f"/api/v1/datasets/{dataset_id}/config",
        json={
            "columns": [
                {"name": "timestamp", "role": "time"},
                {"name": "u1", "role": "input"},
                {"name": "u2", "role": "input"},
                {"name": "u3", "role": "input"},
                {"name": "y", "role": "output"},
            ]
        },
    )
    assert configured.status_code == 200, configured.text

    cleaned = harness.client.post(
        "/api/v1/preprocessing/clean",
        json={
            "dataset_id": str(dataset_id),
            "version_id": str(v0),
            "interpolation": "none",
            "anomaly_strategy": "keep",
            "smoothing": "none",
        },
    )
    assert cleaned.status_code == 202, cleaned.text
    v1 = UUID(cleaned.json()["data"]["derived_version_id"])
    lagged = harness.client.post(
        "/api/v1/preprocessing/delay/apply",
        json={
            "dataset_id": str(dataset_id),
            "version_id": str(v1),
            "lag_map": {"u1": 3, "u2": 8, "u3": 1},
            "user_confirmed": True,
            "recommendation_source": "manual",
            "evidence_summary": {"fixture": "known_process_lags"},
        },
    )
    assert lagged.status_code == 201, lagged.text
    v2 = UUID(lagged.json()["data"]["result_version_id"])
    selected = harness.client.post(
        "/api/v1/preprocessing/features/apply",
        json={
            "dataset_id": str(dataset_id),
            "version_id": str(v2),
            "drop_columns": ["u3"],
            "user_confirmed": True,
            "recommendation_source": "manual",
            "evidence": {"u3": {"reason": "fixture_noise_input"}},
        },
    )
    assert selected.status_code == 201, selected.text
    return dataset_id, UUID(selected.json()["data"]["result_version_id"])


async def _load_execution(harness: ArxHarness, execution_id: UUID) -> AgentExecutionSession:
    async with harness.session_factory() as session:
        execution = await session.scalar(
            select(AgentExecutionSession)
            .where(AgentExecutionSession.id == execution_id)
            .options(selectinload(AgentExecutionSession.step_runs))
        )
        assert execution is not None
        return execution


async def _model_counts(harness: ArxHarness, dataset_id: UUID) -> tuple[int, set[str]]:
    async with harness.session_factory() as session:
        runs = list(
            (
                await session.scalars(
                    select(ProcessingRun).where(
                        ProcessingRun.dataset_id == dataset_id,
                        ProcessingRun.run_type == "modeling.arx",
                    )
                )
            ).all()
        )
        return len(runs), {
            str(run.result["model_id"])
            for run in runs
            if isinstance(run.result, dict) and "model_id" in run.result
        }


async def _version_bytes(harness: ArxHarness, version_id: UUID) -> bytes:
    async with harness.session_factory() as session:
        version = await session.get(DatasetVersion, version_id)
        assert version is not None
        return (harness.artifact_root / version.artifact_path).read_bytes()


def _chat_to_arx_confirmation(
    harness: ArxHarness,
    *,
    alter_test_partition: bool = False,
    message: str = "使用当前变量进行 ARX 建模并评价模型",
) -> AgentExecutionSession:
    dataset_id, v3 = _upload_and_build_v3(
        harness, alter_test_partition=alter_test_partition
    )
    response = harness.client.post(
        "/api/v1/copilot/chat",
        json={
            "message": message,
            "dataset_id": str(dataset_id),
            "active_version_id": str(v3),
        },
    )
    assert response.status_code == 200, response.text
    execution_id = response.json()["data"]["execution_id"]
    assert execution_id is not None
    return asyncio.run(_load_execution(harness, UUID(execution_id)))


def _validate(
    harness: ArxHarness,
    *,
    execution_id: UUID,
    step_id: str,
    overrides: dict[str, object] | None = None,
):
    return harness.client.post(
        "/api/v1/copilot/arx-structure/validate",
        json={
            "execution_id": str(execution_id),
            "step_id": step_id,
            "manual_overrides": overrides or {},
        },
    )


def _confirm(
    harness: ArxHarness,
    *,
    execution_id: UUID,
    step_id: str,
    approved: bool = True,
    overrides: dict[str, object] | None = None,
):
    return harness.client.post(
        "/api/v1/copilot/confirm",
        json={
            "copilot_run_id": str(execution_id),
            "confirmation_id": step_id,
            "execution_id": str(execution_id),
            "step_id": step_id,
            "approved": approved,
            "arx_structure_overrides": overrides or {},
        },
    )


async def _execute_evaluation_step(
    harness: ArxHarness, execution_id: UUID
) -> tuple[AgentExecutionSession, Exception | None]:
    async with harness.session_factory() as session:
        execution = await session.scalar(
            select(AgentExecutionSession)
            .where(AgentExecutionSession.id == execution_id)
            .options(selectinload(AgentExecutionSession.step_runs))
        )
        assert execution is not None
        evaluation = next(step for step in execution.step_runs if step.tool_name == "evaluate_model")
        execution = await start_step(session, execution_id=execution.id, step_id=evaluation.step_id)
        evaluation = next(step for step in execution.step_runs if step.step_id == evaluation.step_id)
        try:
            result = await execute_agent_tool(
                session,
                execution=execution,
                step=evaluation,
                parameters=dict(evaluation.input_payload["parameters"]),
                artifact_root=harness.artifact_root,
            )
        except Exception as error:
            failed = await mark_step_failed(
                session,
                execution_id=execution.id,
                step_id=evaluation.step_id,
                error_code=getattr(error, "code", "AGENT_STEP_FAILED"),
                error_message=getattr(error, "message", str(error)),
            )
            return failed, error
        succeeded = await mark_step_succeeded(
            session,
            execution_id=execution.id,
            step_id=evaluation.step_id,
            result_payload=result.result_payload,
            source_version_id=result.source_version_id,
            result_version_id=result.result_version_id,
            processing_run_ids=result.processing_run_ids,
        )
        return succeeded, None


async def _prepare_confirmable_optimization_step(
    harness: ArxHarness,
    execution_id: UUID,
    *,
    parameters: dict[str, object] | None = None,
    start: bool = True,
) -> AgentExecutionSession:
    """Turn the deferred evaluation slot into a C2 optimization step for focused tests."""

    async with harness.session_factory() as session:
        execution = await session.scalar(
            select(AgentExecutionSession)
            .where(AgentExecutionSession.id == execution_id)
            .options(selectinload(AgentExecutionSession.step_runs))
        )
        assert execution is not None
        fit = next(step for step in execution.step_runs if step.tool_name == "fit_arx")
        optimization = next(step for step in execution.step_runs if step.tool_name == "evaluate_model")
        assert fit.status == "SUCCEEDED"
        assert optimization.status == "PENDING"

        optimization.tool_name = "optimize_pipeline"
        optimization.requires_confirmation = True
        optimization.confirmation_status = "PENDING"
        optimization.input_payload = {
            "depends_on": [fit.step_id],
            "parameters": parameters
            or {
                "max_trials": 1,
                "random_seed": 20260827,
                "search_space": {"na": [1, 1], "nb": [1, 1], "nk": [3, 3]},
            },
        }
        downstream_step_id = "evaluate_optimized_model"
        execution.step_runs.append(
            AgentStepRun(
                id=uuid4(),
                execution_id=execution.id,
                step_id=downstream_step_id,
                sequence=optimization.sequence + 1,
                tool_name="evaluate_model",
                status="PENDING",
                requires_confirmation=False,
                confirmation_status="NOT_REQUIRED",
                attempt_count=0,
                input_payload={
                    "depends_on": [optimization.step_id],
                    "parameters": {},
                },
                result_payload={},
                processing_run_ids=[],
            )
        )
        plan_steps = []
        for item in execution.plan_json["steps"]:
            if item["step_id"] == optimization.step_id:
                plan_steps.append(
                    {
                        **item,
                        "tool": "optimize_pipeline",
                        "depends_on": [fit.step_id],
                        "parameters": dict(optimization.input_payload["parameters"]),
                        "requires_confirmation": True,
                    }
                )
            else:
                plan_steps.append(item)
        plan_steps.append(
            {
                "step_id": downstream_step_id,
                "tool": "evaluate_model",
                "depends_on": [optimization.step_id],
                "parameters": {},
                "requires_confirmation": False,
                "status": "pending",
            }
        )
        execution.plan_json = {**execution.plan_json, "steps": plan_steps}
        await session.commit()
        if not start:
            return execution
        return await start_step(
            session,
            execution_id=execution.id,
            step_id=optimization.step_id,
        )

async def _evaluation_run_count(harness: ArxHarness, dataset_id: UUID) -> int:
    async with harness.session_factory() as session:
        runs = list(
            (
                await session.scalars(
                    select(ProcessingRun).where(
                        ProcessingRun.dataset_id == dataset_id,
                        ProcessingRun.run_type == "modeling.arx_evaluation",
                    )
                )
            ).all()
        )
        return len(runs)

async def _dataset_version_count(harness: ArxHarness, dataset_id: UUID) -> int:
    async with harness.session_factory() as session:
        versions = list(
            (
                await session.scalars(
                    select(DatasetVersion).where(DatasetVersion.dataset_id == dataset_id)
                )
            ).all()
        )
        return len(versions)

async def _load_processing_run(harness: ArxHarness, run_id: UUID) -> ProcessingRun:
    async with harness.session_factory() as session:
        run = await session.get(ProcessingRun, run_id)
        assert run is not None
        return run

def test_planner_requires_confirmation_for_arx_modeling() -> None:
    steps, _, _ = RuleBasedPlanner().plan(parse_intent("进行 ARX 建模"))
    by_tool = {step.tool: step for step in steps}
    assert by_tool["fit_arx"].requires_confirmation is True
    assert by_tool["evaluate_model"].depends_on == (by_tool["fit_arx"].step_id,)
    assert "evaluate_model" in agent_service._FORMAL_ADAPTER_TOOLS
    assert "evaluate_model" not in agent_service._DEFERRED_TOOLS


def test_recommendation_is_validation_only_and_derived_from_lagged_v3(
    arx_harness: ArxHarness,
) -> None:
    execution = _chat_to_arx_confirmation(arx_harness)
    fit = next(step for step in execution.step_runs if step.tool_name == "fit_arx")
    evaluate = next(step for step in execution.step_runs if step.tool_name == "evaluate_model")
    recommendation = fit.input_payload["arx_structure_recommendation"]

    assert execution.workflow_status == "WAITING_CONFIRMATION"
    assert execution.pending_confirmation_step_id == fit.step_id
    assert fit.status == "WAITING_CONFIRMATION"
    assert fit.confirmation_status == "PENDING"
    assert fit.source_version_id is None
    assert recommendation["source_version_id"] == str(execution.current_version_id)
    assert recommendation["recommended_na"] in {1, 2, 3, 4}
    assert set(recommendation["recommended_nb"]) == {"u1", "u2"}
    assert set(recommendation["recommended_nb"].values()) <= {1, 2, 3}
    assert recommendation["recommended_delays"] == {"u1": 0, "u2": 0}
    assert recommendation["delay_source"] == "derived_from_lag_compensated_version"
    assert recommendation["validation_metric"] == "optimization_objective_validation_only"
    assert recommendation["candidate_summary"]
    assert all("test" not in item for item in recommendation["candidate_summary"])
    assert evaluate.status == "PENDING"


def test_recommendation_does_not_use_held_out_test_partition(
    arx_harness: ArxHarness,
) -> None:
    original = _chat_to_arx_confirmation(arx_harness)
    altered = _chat_to_arx_confirmation(arx_harness, alter_test_partition=True)
    original_fit = next(step for step in original.step_runs if step.tool_name == "fit_arx")
    altered_fit = next(step for step in altered.step_runs if step.tool_name == "fit_arx")
    original_recommendation = original_fit.input_payload["arx_structure_recommendation"]
    altered_recommendation = altered_fit.input_payload["arx_structure_recommendation"]

    for key in ("recommended_na", "recommended_nb", "recommended_delays", "recommended_estimator"):
        assert original_recommendation[key] == altered_recommendation[key]


def test_manual_override_runs_formal_arx_once_and_keeps_v3_immutable(
    arx_harness: ArxHarness,
) -> None:
    execution = _chat_to_arx_confirmation(arx_harness)
    fit = next(step for step in execution.step_runs if step.tool_name == "fit_arx")
    recommendation = fit.input_payload["arx_structure_recommendation"]
    manual_na = 1 if recommendation["recommended_na"] != 1 else 2
    source = execution.current_version_id
    source_before = asyncio.run(_version_bytes(arx_harness, source))
    before = asyncio.run(_model_counts(arx_harness, execution.dataset_id))

    preview = _validate(
        arx_harness,
        execution_id=execution.id,
        step_id=fit.step_id,
        overrides={"na": manual_na},
    )
    assert preview.status_code == 200, preview.text
    validation = preview.json()["data"]
    assert validation["overall_status"] == "VALID"
    assert validation["final_structure"]["na"] == manual_na
    assert validation["final_structure"]["nb"] == recommendation["recommended_nb"]
    assert validation["structure_sources"]["na"] == "manual_override"

    confirmed = _confirm(
        arx_harness,
        execution_id=execution.id,
        step_id=fit.step_id,
        overrides={"na": manual_na},
    )
    assert confirmed.status_code == 200, confirmed.text
    data = confirmed.json()["data"]
    assert data["step_status"] == "SUCCEEDED"
    assert data["confirmation_status"] == "APPROVED"
    assert UUID(data["current_version_id"]) == source
    assert data["result_version_id"] is None
    assert data["result_payload"]["model_id"]
    assert data["result_payload"]["artifact_uri"]

    persisted = asyncio.run(_load_execution(arx_harness, execution.id))
    fitted = next(step for step in persisted.step_runs if step.tool_name == "fit_arx")
    evaluate = next(step for step in persisted.step_runs if step.tool_name == "evaluate_model")
    assert fitted.source_version_id == source
    assert fitted.result_version_id is None
    assert len(fitted.processing_run_ids) == 1
    assert fitted.input_payload["manual_overrides"] == {"na": manual_na}
    assert fitted.input_payload["final_structure"]["na"] == manual_na
    assert fitted.result_payload["metrics"]["test_free_run_fit"] is None
    assert persisted.workflow_status == "RUNNING"
    assert persisted.current_version_id == source
    assert evaluate.status == "PENDING"
    assert asyncio.run(_version_bytes(arx_harness, source)) == source_before

    after_first = asyncio.run(_model_counts(arx_harness, execution.dataset_id))
    assert after_first[0] == before[0] + 1
    assert len(after_first[1]) == len(before[1]) + 1
    replay = _confirm(
        arx_harness,
        execution_id=execution.id,
        step_id=fit.step_id,
        overrides={"na": manual_na},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["data"]["result_payload"]["model_id"] == data["result_payload"]["model_id"]
    assert asyncio.run(_model_counts(arx_harness, execution.dataset_id)) == after_first


def test_invalid_structure_is_rejected_without_training(arx_harness: ArxHarness) -> None:
    execution = _chat_to_arx_confirmation(arx_harness)
    fit = next(step for step in execution.step_runs if step.tool_name == "fit_arx")
    before = asyncio.run(_model_counts(arx_harness, execution.dataset_id))

    preview = _validate(
        arx_harness,
        execution_id=execution.id,
        step_id=fit.step_id,
        overrides={"na": 0, "nb": {"missing": 2}},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["data"]["overall_status"] == "INVALID"
    confirmed = _confirm(
        arx_harness,
        execution_id=execution.id,
        step_id=fit.step_id,
        overrides={"na": 0, "nb": {"missing": 2}},
    )
    assert confirmed.status_code == 422, confirmed.text
    assert asyncio.run(_model_counts(arx_harness, execution.dataset_id)) == before


def test_completed_arx_rejects_different_structure_replay(arx_harness: ArxHarness) -> None:
    execution = _chat_to_arx_confirmation(arx_harness)
    fit = next(step for step in execution.step_runs if step.tool_name == "fit_arx")
    first = _confirm(arx_harness, execution_id=execution.id, step_id=fit.step_id)
    assert first.status_code == 200, first.text
    before = asyncio.run(_model_counts(arx_harness, execution.dataset_id))
    recommended = fit.input_payload["arx_structure_recommendation"]["recommended_na"]
    different = 1 if recommended != 1 else 2

    replay = _confirm(
        arx_harness,
        execution_id=execution.id,
        step_id=fit.step_id,
        overrides={"na": different},
    )
    assert replay.status_code == 409, replay.text
    assert asyncio.run(_model_counts(arx_harness, execution.dataset_id)) == before


def test_reject_does_not_train_arx(arx_harness: ArxHarness) -> None:
    execution = _chat_to_arx_confirmation(arx_harness)
    fit = next(step for step in execution.step_runs if step.tool_name == "fit_arx")
    source = execution.current_version_id
    before = asyncio.run(_model_counts(arx_harness, execution.dataset_id))

    rejected = _confirm(
        arx_harness,
        execution_id=execution.id,
        step_id=fit.step_id,
        approved=False,
    )
    assert rejected.status_code == 200, rejected.text
    persisted = asyncio.run(_load_execution(arx_harness, execution.id))
    rejected_step = next(step for step in persisted.step_runs if step.tool_name == "fit_arx")
    assert persisted.workflow_status == "CANCELLED"
    assert persisted.current_version_id == source
    assert rejected_step.status == "CANCELLED"
    assert rejected_step.confirmation_status == "REJECTED"
    assert asyncio.run(_model_counts(arx_harness, execution.dataset_id)) == before

def test_agent_evaluation_consumes_confirmed_model_without_refit(
    arx_harness: ArxHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execution = _chat_to_arx_confirmation(arx_harness)
    fit = next(step for step in execution.step_runs if step.tool_name == "fit_arx")
    confirmed = _confirm(arx_harness, execution_id=execution.id, step_id=fit.step_id)
    assert confirmed.status_code == 200, confirmed.text
    source_version_id = execution.current_version_id
    before_bytes = asyncio.run(_version_bytes(arx_harness, source_version_id))
    before_runs = asyncio.run(_evaluation_run_count(arx_harness, execution.dataset_id))
    before_versions = asyncio.run(_dataset_version_count(arx_harness, execution.dataset_id))

    def fail_if_refit(*args: object, **kwargs: object) -> None:
        raise AssertionError("evaluate_model must not enter an ARX fitting path")

    monkeypatch.setattr("app.services.agent_tool_adapter.fit_arx_on_version", fail_if_refit)
    monkeypatch.setattr("app.services.modeling_service.fit_arx_core", fail_if_refit)
    persisted, error = asyncio.run(_execute_evaluation_step(arx_harness, execution.id))

    assert error is None
    fitted = next(step for step in persisted.step_runs if step.tool_name == "fit_arx")
    evaluated = next(step for step in persisted.step_runs if step.tool_name == "evaluate_model")
    assert evaluated.status == "SUCCEEDED"
    assert evaluated.source_version_id == fitted.source_version_id == source_version_id
    assert evaluated.result_version_id is None
    assert len(evaluated.processing_run_ids) == 1
    processing_run_id = UUID(evaluated.processing_run_ids[0])
    processing_run = asyncio.run(_load_processing_run(arx_harness, processing_run_id))
    assert processing_run.run_type == "modeling.arx_evaluation"
    assert processing_run.status == "succeeded"
    assert evaluated.result_payload["model_id"] == fitted.result_payload["model_id"]
    assert evaluated.result_payload["processing_run_id"] == str(processing_run_id)
    assert evaluated.result_payload["source_version_id"] == str(source_version_id)
    assert evaluated.result_payload["test"]["one_step"]["rmse"] is not None
    assert evaluated.result_payload["test"]["free_run"]["rmse"] is not None
    assert persisted.current_version_id == source_version_id
    assert asyncio.run(_version_bytes(arx_harness, source_version_id)) == before_bytes
    assert asyncio.run(_evaluation_run_count(arx_harness, execution.dataset_id)) == before_runs + 1
    assert asyncio.run(_dataset_version_count(arx_harness, execution.dataset_id)) == before_versions

    async def replay() -> None:
        async with arx_harness.session_factory() as session:
            with pytest.raises(ExecutionStateError):
                await start_step(session, execution_id=execution.id, step_id=evaluated.step_id)

    asyncio.run(replay())
    assert asyncio.run(_evaluation_run_count(arx_harness, execution.dataset_id)) == before_runs + 1
    assert asyncio.run(_dataset_version_count(arx_harness, execution.dataset_id)) == before_versions


def test_agent_evaluation_fails_when_fit_model_id_is_missing(arx_harness: ArxHarness) -> None:
    execution = _chat_to_arx_confirmation(arx_harness)
    fit = next(step for step in execution.step_runs if step.tool_name == "fit_arx")
    confirmed = _confirm(arx_harness, execution_id=execution.id, step_id=fit.step_id)
    assert confirmed.status_code == 200, confirmed.text

    async def remove_model_id() -> None:
        async with arx_harness.session_factory() as session:
            current = await session.scalar(
                select(AgentExecutionSession)
                .where(AgentExecutionSession.id == execution.id)
                .options(selectinload(AgentExecutionSession.step_runs))
            )
            assert current is not None
            fitted = next(step for step in current.step_runs if step.tool_name == "fit_arx")
            fitted.result_payload = {}
            await session.commit()

    asyncio.run(remove_model_id())
    persisted, error = asyncio.run(_execute_evaluation_step(arx_harness, execution.id))

    assert isinstance(error, AgentToolAdapterError)
    assert error.code == "EVALUATION_FIT_MODEL_ID_MISSING"
    evaluated = next(step for step in persisted.step_runs if step.tool_name == "evaluate_model")
    assert evaluated.status == "FAILED"
    assert evaluated.processing_run_ids == []

def test_agent_evaluation_blocks_downstream_when_fit_fails_formally(
    arx_harness: ArxHarness,
) -> None:
    execution = _chat_to_arx_confirmation(arx_harness)
    fit = next(step for step in execution.step_runs if step.tool_name == "fit_arx")
    evaluation = next(step for step in execution.step_runs if step.tool_name == "evaluate_model")
    before_runs = asyncio.run(_evaluation_run_count(arx_harness, execution.dataset_id))

    async def fail_fit_through_lifecycle() -> AgentExecutionSession:
        async with arx_harness.session_factory() as session:
            await approve_step(session, execution_id=execution.id, step_id=fit.step_id)
            return await mark_step_failed(
                session,
                execution_id=execution.id,
                step_id=fit.step_id,
                error_code="FIT_TEST_FAILURE",
                error_message="deterministic formal fit failure",
            )

    failed = asyncio.run(fail_fit_through_lifecycle())
    fitted = next(step for step in failed.step_runs if step.tool_name == "fit_arx")
    assert failed.workflow_status == "FAILED"
    assert fitted.status == "FAILED"
    assert evaluation.status == "PENDING"

    async def start_downstream() -> None:
        async with arx_harness.session_factory() as session:
            with pytest.raises(ExecutionStateError, match="execution_status=FAILED"):
                await start_step(session, execution_id=execution.id, step_id=evaluation.step_id)

    asyncio.run(start_downstream())
    persisted = asyncio.run(_load_execution(arx_harness, execution.id))
    evaluated = next(step for step in persisted.step_runs if step.tool_name == "evaluate_model")
    assert evaluated.status == "PENDING"
    assert evaluated.processing_run_ids == []
    assert asyncio.run(_evaluation_run_count(arx_harness, execution.dataset_id)) == before_runs

def test_agent_evaluation_fails_on_saved_model_source_version_mismatch(
    arx_harness: ArxHarness,
) -> None:
    execution = _chat_to_arx_confirmation(arx_harness)
    fit = next(step for step in execution.step_runs if step.tool_name == "fit_arx")
    confirmed = _confirm(arx_harness, execution_id=execution.id, step_id=fit.step_id)
    assert confirmed.status_code == 200, confirmed.text

    async def change_source_version() -> None:
        async with arx_harness.session_factory() as session:
            current = await session.scalar(
                select(AgentExecutionSession)
                .where(AgentExecutionSession.id == execution.id)
                .options(selectinload(AgentExecutionSession.step_runs))
            )
            assert current is not None
            fitted = next(step for step in current.step_runs if step.tool_name == "fit_arx")
            fitted.source_version_id = UUID("00000000-0000-4000-8000-000000000001")
            await session.commit()

    asyncio.run(change_source_version())
    persisted, error = asyncio.run(_execute_evaluation_step(arx_harness, execution.id))

    assert isinstance(error, ModelingDomainError)
    assert error.code == "MODEL_SOURCE_VERSION_MISMATCH"
    evaluated = next(step for step in persisted.step_runs if step.tool_name == "evaluate_model")
    assert evaluated.status == "FAILED"
    assert evaluated.processing_run_ids == []

def test_explicit_evaluation_trigger_executes_saved_model_once(
    arx_harness: ArxHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execution = _chat_to_arx_confirmation(arx_harness)
    fit = next(step for step in execution.step_runs if step.tool_name == "fit_arx")
    confirmed = _confirm(arx_harness, execution_id=execution.id, step_id=fit.step_id)
    assert confirmed.status_code == 200, confirmed.text
    source_version_id = execution.current_version_id
    before_bytes = asyncio.run(_version_bytes(arx_harness, source_version_id))
    before_runs = asyncio.run(_evaluation_run_count(arx_harness, execution.dataset_id))
    before_versions = asyncio.run(_dataset_version_count(arx_harness, execution.dataset_id))

    def fail_if_refit(*args: object, **kwargs: object) -> None:
        raise AssertionError("evaluate_model trigger must not enter an ARX fitting path")

    monkeypatch.setattr("app.services.agent_tool_adapter.fit_arx_on_version", fail_if_refit)
    monkeypatch.setattr("app.services.modeling_service.fit_arx_core", fail_if_refit)
    response = arx_harness.client.post(
        "/api/v1/copilot/evaluate-model/execute",
        json={"execution_id": str(execution.id)},
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    persisted = asyncio.run(_load_execution(arx_harness, execution.id))
    fitted = next(step for step in persisted.step_runs if step.tool_name == "fit_arx")
    evaluated = next(step for step in persisted.step_runs if step.tool_name == "evaluate_model")
    assert data["execution_id"] == str(execution.id)
    assert data["workflow_status"] == "SUCCEEDED"
    assert data["step_id"] == evaluated.step_id
    assert data["step_status"] == "SUCCEEDED"
    assert data["result_payload"] == evaluated.result_payload
    assert data["processing_run_ids"] == evaluated.processing_run_ids
    assert evaluated.source_version_id == fitted.source_version_id == source_version_id
    assert evaluated.result_version_id is None
    assert evaluated.result_payload["model_id"] == fitted.result_payload["model_id"]
    assert evaluated.result_payload["test"]["one_step"]["rmse"] is not None
    assert evaluated.result_payload["test"]["free_run"]["rmse"] is not None
    assert len(evaluated.processing_run_ids) == 1
    processing_run = asyncio.run(_load_processing_run(arx_harness, UUID(evaluated.processing_run_ids[0])))
    assert processing_run.run_type == "modeling.arx_evaluation"
    assert persisted.current_version_id == source_version_id
    assert asyncio.run(_version_bytes(arx_harness, source_version_id)) == before_bytes
    assert asyncio.run(_evaluation_run_count(arx_harness, execution.dataset_id)) == before_runs + 1
    assert asyncio.run(_dataset_version_count(arx_harness, execution.dataset_id)) == before_versions

    replay = arx_harness.client.post(
        "/api/v1/copilot/evaluate-model/execute",
        json={"execution_id": str(execution.id)},
    )
    assert replay.status_code == 409, replay.text
    assert asyncio.run(_evaluation_run_count(arx_harness, execution.dataset_id)) == before_runs + 1
    assert asyncio.run(_dataset_version_count(arx_harness, execution.dataset_id)) == before_versions


def test_explicit_evaluation_trigger_rejects_waiting_confirmation(
    arx_harness: ArxHarness,
) -> None:
    execution = _chat_to_arx_confirmation(arx_harness)
    before_runs = asyncio.run(_evaluation_run_count(arx_harness, execution.dataset_id))
    before_versions = asyncio.run(_dataset_version_count(arx_harness, execution.dataset_id))

    response = arx_harness.client.post(
        "/api/v1/copilot/evaluate-model/execute",
        json={"execution_id": str(execution.id)},
    )

    assert response.status_code == 409, response.text
    persisted = asyncio.run(_load_execution(arx_harness, execution.id))
    evaluated = next(step for step in persisted.step_runs if step.tool_name == "evaluate_model")
    assert persisted.workflow_status == "WAITING_CONFIRMATION"
    assert evaluated.status == "PENDING"
    assert persisted.current_version_id == execution.current_version_id
    assert asyncio.run(_evaluation_run_count(arx_harness, execution.dataset_id)) == before_runs
    assert asyncio.run(_dataset_version_count(arx_harness, execution.dataset_id)) == before_versions


def test_explicit_evaluation_trigger_rejects_failed_execution(
    arx_harness: ArxHarness,
) -> None:
    execution = _chat_to_arx_confirmation(arx_harness)
    fit = next(step for step in execution.step_runs if step.tool_name == "fit_arx")
    before_runs = asyncio.run(_evaluation_run_count(arx_harness, execution.dataset_id))
    before_versions = asyncio.run(_dataset_version_count(arx_harness, execution.dataset_id))

    async def fail_fit_through_lifecycle() -> None:
        async with arx_harness.session_factory() as session:
            await approve_step(session, execution_id=execution.id, step_id=fit.step_id)
            await mark_step_failed(
                session,
                execution_id=execution.id,
                step_id=fit.step_id,
                error_code="FIT_TEST_FAILURE",
                error_message="deterministic formal fit failure",
            )

    asyncio.run(fail_fit_through_lifecycle())
    response = arx_harness.client.post(
        "/api/v1/copilot/evaluate-model/execute",
        json={"execution_id": str(execution.id)},
    )

    assert response.status_code == 409, response.text
    persisted = asyncio.run(_load_execution(arx_harness, execution.id))
    evaluated = next(step for step in persisted.step_runs if step.tool_name == "evaluate_model")
    assert persisted.workflow_status == "FAILED"
    assert evaluated.status == "PENDING"
    assert persisted.current_version_id == execution.current_version_id
    assert asyncio.run(_evaluation_run_count(arx_harness, execution.dataset_id)) == before_runs
    assert asyncio.run(_dataset_version_count(arx_harness, execution.dataset_id)) == before_versions


def test_explicit_evaluation_trigger_returns_failed_snapshot_for_business_error(
    arx_harness: ArxHarness,
) -> None:
    execution = _chat_to_arx_confirmation(arx_harness)
    fit = next(step for step in execution.step_runs if step.tool_name == "fit_arx")
    confirmed = _confirm(arx_harness, execution_id=execution.id, step_id=fit.step_id)
    assert confirmed.status_code == 200, confirmed.text
    source_version_id = execution.current_version_id
    before_versions = asyncio.run(_dataset_version_count(arx_harness, execution.dataset_id))

    async def change_source_version() -> None:
        async with arx_harness.session_factory() as session:
            current = await session.scalar(
                select(AgentExecutionSession)
                .where(AgentExecutionSession.id == execution.id)
                .options(selectinload(AgentExecutionSession.step_runs))
            )
            assert current is not None
            fitted = next(step for step in current.step_runs if step.tool_name == "fit_arx")
            fitted.source_version_id = UUID("00000000-0000-4000-8000-000000000001")
            await session.commit()

    asyncio.run(change_source_version())
    response = arx_harness.client.post(
        "/api/v1/copilot/evaluate-model/execute",
        json={"execution_id": str(execution.id)},
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    persisted = asyncio.run(_load_execution(arx_harness, execution.id))
    evaluated = next(step for step in persisted.step_runs if step.tool_name == "evaluate_model")
    assert data["workflow_status"] == "FAILED"
    assert data["step_status"] == "FAILED"
    assert data["error_code"] == "MODEL_SOURCE_VERSION_MISMATCH"
    assert data["error_message"]
    assert evaluated.status == "FAILED"
    assert evaluated.processing_run_ids == []
    assert persisted.current_version_id == source_version_id
    assert asyncio.run(_dataset_version_count(arx_harness, execution.dataset_id)) == before_versions


def test_explicit_optimization_trigger_requires_confirmation_and_persists_real_result(
    arx_harness: ArxHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execution = _chat_to_arx_confirmation(arx_harness)
    fit = next(step for step in execution.step_runs if step.tool_name == "fit_arx")
    confirmed_fit = _confirm(arx_harness, execution_id=execution.id, step_id=fit.step_id)
    assert confirmed_fit.status_code == 200, confirmed_fit.text
    source_version_id = execution.current_version_id
    before_versions = asyncio.run(_dataset_version_count(arx_harness, execution.dataset_id))
    calls: list[dict[str, object]] = []

    from app.services import agent_tool_adapter

    formal_entry = agent_tool_adapter.execute_agent_optimization_study

    async def spy_safe_entry(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        calls.append(dict(kwargs))
        return await formal_entry(*args, **kwargs)  # type: ignore[arg-type]

    def fail_if_evaluated(*args: object, **kwargs: object) -> None:
        raise AssertionError("C2 optimization trigger must not open held-out model evaluation")

    monkeypatch.setattr(agent_tool_adapter, "execute_agent_optimization_study", spy_safe_entry)
    monkeypatch.setattr(agent_tool_adapter, "evaluate_saved_arx_model", fail_if_evaluated)

    pending_execution = asyncio.run(
        _prepare_confirmable_optimization_step(arx_harness, execution.id, start=False)
    )
    optimization = next(
        step for step in pending_execution.step_runs if step.tool_name == "optimize_pipeline"
    )
    assert optimization.status == "PENDING"
    pending = arx_harness.client.post(
        "/api/v1/copilot/optimize-pipeline/execute",
        json={"execution_id": str(execution.id)},
    )
    assert pending.status_code == 409, pending.text

    async def start_optimization() -> AgentExecutionSession:
        async with arx_harness.session_factory() as session:
            return await start_step(
                session,
                execution_id=execution.id,
                step_id=optimization.step_id,
            )

    waiting = asyncio.run(start_optimization())
    optimization = next(step for step in waiting.step_runs if step.tool_name == "optimize_pipeline")
    assert waiting.workflow_status == "WAITING_CONFIRMATION"
    assert optimization.status == "WAITING_CONFIRMATION"
    forbidden = arx_harness.client.post(
        "/api/v1/copilot/optimize-pipeline/execute",
        json={"execution_id": str(execution.id)},
    )
    assert forbidden.status_code == 409, forbidden.text

    approved = _confirm(arx_harness, execution_id=execution.id, step_id=optimization.step_id)
    assert approved.status_code == 200, approved.text
    assert approved.json()["data"]["step_status"] == "RUNNING"
    assert approved.json()["data"]["confirmation_status"] == "APPROVED"

    response = arx_harness.client.post(
        "/api/v1/copilot/optimize-pipeline/execute",
        json={"execution_id": str(execution.id)},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    persisted = asyncio.run(_load_execution(arx_harness, execution.id))
    fitted = next(step for step in persisted.step_runs if step.tool_name == "fit_arx")
    optimized = next(step for step in persisted.step_runs if step.tool_name == "optimize_pipeline")
    downstream = next(
        step for step in persisted.step_runs if step.step_id == "evaluate_optimized_model"
    )

    assert data["execution_id"] == str(execution.id)
    assert data["step_id"] == optimized.step_id
    assert data["step_status"] == "SUCCEEDED"
    assert data["result_payload"] == optimized.result_payload
    assert data["processing_run_ids"] == optimized.processing_run_ids
    assert optimized.source_version_id == fitted.source_version_id == source_version_id
    assert optimized.result_version_id is None
    assert optimized.result_payload["baseline_model_id"] == fitted.result_payload["model_id"]
    assert optimized.result_payload["model_id"] == optimized.result_payload["optimized_model_id"]
    assert len(optimized.processing_run_ids) == 2
    processing_runs = [
        asyncio.run(_load_processing_run(arx_harness, UUID(run_id)))
        for run_id in optimized.processing_run_ids
    ]
    assert [run.run_type for run in processing_runs] == [
        "optimization.baseline",
        "modeling.arx",
    ]
    assert downstream.status == "PENDING"
    assert persisted.current_version_id == source_version_id
    assert asyncio.run(_dataset_version_count(arx_harness, execution.dataset_id)) == before_versions
    assert len(calls) == 1
    payload = calls[0]["payload"]
    assert payload.version_id == source_version_id
    assert payload.search_space["nk"] == [0, 0]
    assert calls[0]["baseline_model_id"] == UUID(fitted.result_payload["model_id"])

    replay = arx_harness.client.post(
        "/api/v1/copilot/optimize-pipeline/execute",
        json={"execution_id": str(execution.id)},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["data"] == data
    assert len(calls) == 1


def test_explicit_optimization_trigger_persists_business_failure_without_replay(
    arx_harness: ArxHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execution = _chat_to_arx_confirmation(arx_harness)
    fit = next(step for step in execution.step_runs if step.tool_name == "fit_arx")
    confirmed_fit = _confirm(arx_harness, execution_id=execution.id, step_id=fit.step_id)
    assert confirmed_fit.status_code == 200, confirmed_fit.text
    source_version_id = execution.current_version_id
    before_versions = asyncio.run(_dataset_version_count(arx_harness, execution.dataset_id))
    waiting = asyncio.run(_prepare_confirmable_optimization_step(arx_harness, execution.id))
    optimization = next(step for step in waiting.step_runs if step.tool_name == "optimize_pipeline")
    approved = _confirm(arx_harness, execution_id=execution.id, step_id=optimization.step_id)
    assert approved.status_code == 200, approved.text
    calls = 0

    from app.services.optimization_service import OptimizationDomainError

    async def fail_safe_entry(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        raise OptimizationDomainError("OPTIMIZATION_TEST_FAILURE", "deterministic study failure")

    monkeypatch.setattr(
        "app.services.agent_tool_adapter.execute_agent_optimization_study", fail_safe_entry
    )
    response = arx_harness.client.post(
        "/api/v1/copilot/optimize-pipeline/execute",
        json={"execution_id": str(execution.id)},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["workflow_status"] == "FAILED"
    assert data["step_status"] == "FAILED"
    assert data["error_code"] == "OPTIMIZATION_TEST_FAILURE"
    assert data["error_message"] == "deterministic study failure"
    assert data["processing_run_ids"] == []
    assert calls == 1

    persisted = asyncio.run(_load_execution(arx_harness, execution.id))
    optimized = next(step for step in persisted.step_runs if step.tool_name == "optimize_pipeline")
    assert optimized.status == "FAILED"
    assert persisted.current_version_id == source_version_id
    assert asyncio.run(_dataset_version_count(arx_harness, execution.dataset_id)) == before_versions

    replay = arx_harness.client.post(
        "/api/v1/copilot/optimize-pipeline/execute",
        json={"execution_id": str(execution.id)},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["data"] == data
    assert calls == 1

def test_optimization_adapter_rejects_missing_declared_fit_predecessor(
    arx_harness: ArxHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execution = _chat_to_arx_confirmation(arx_harness)
    fit = next(step for step in execution.step_runs if step.tool_name == "fit_arx")
    confirmed_fit = _confirm(arx_harness, execution_id=execution.id, step_id=fit.step_id)
    assert confirmed_fit.status_code == 200, confirmed_fit.text
    waiting = asyncio.run(_prepare_confirmable_optimization_step(arx_harness, execution.id))
    optimization = next(step for step in waiting.step_runs if step.tool_name == "optimize_pipeline")
    approved = _confirm(arx_harness, execution_id=execution.id, step_id=optimization.step_id)
    assert approved.status_code == 200, approved.text
    calls = 0

    async def fail_if_safe_entry_called(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        raise AssertionError("missing declared fit predecessor must stop before C1")

    monkeypatch.setattr(
        "app.services.agent_tool_adapter.execute_agent_optimization_study",
        fail_if_safe_entry_called,
    )

    async def remove_declared_dependency() -> None:
        async with arx_harness.session_factory() as session:
            current = await session.scalar(
                select(AgentExecutionSession)
                .where(AgentExecutionSession.id == execution.id)
                .options(selectinload(AgentExecutionSession.step_runs))
            )
            assert current is not None
            current_optimization = next(
                step for step in current.step_runs if step.tool_name == "optimize_pipeline"
            )
            current_optimization.input_payload = {
                **current_optimization.input_payload,
                "depends_on": [],
            }
            await session.commit()

    asyncio.run(remove_declared_dependency())
    response = arx_harness.client.post(
        "/api/v1/copilot/optimize-pipeline/execute",
        json={"execution_id": str(execution.id)},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["workflow_status"] == "FAILED"
    assert data["step_status"] == "FAILED"
    assert data["error_code"] == "OPTIMIZATION_FIT_DEPENDENCY_REQUIRED"
    assert calls == 0

def test_optimized_model_is_the_only_new_dag_evaluation_predecessor(
    arx_harness: ArxHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execution = _chat_to_arx_confirmation(
        arx_harness,
        message="使用当前变量进行 ARX 建模并闭环寻优 1 次试验",
    )
    fit = next(step for step in execution.step_runs if step.tool_name == "fit_arx")
    optimization = next(
        step for step in execution.step_runs if step.tool_name == "optimize_pipeline"
    )
    evaluation = next(step for step in execution.step_runs if step.tool_name == "evaluate_model")
    assert optimization.input_payload["depends_on"] == [fit.step_id]
    assert evaluation.input_payload["depends_on"] == [optimization.step_id]
    assert optimization.status == "PENDING"
    assert evaluation.status == "PENDING"

    confirmed_fit = _confirm(arx_harness, execution_id=execution.id, step_id=fit.step_id)
    assert confirmed_fit.status_code == 200, confirmed_fit.text
    source_version_id = execution.current_version_id

    async def start_optimization() -> AgentExecutionSession:
        async with arx_harness.session_factory() as session:
            return await start_step(
                session,
                execution_id=execution.id,
                step_id=optimization.step_id,
            )

    waiting = asyncio.run(start_optimization())
    pending_optimization = next(
        step for step in waiting.step_runs if step.step_id == optimization.step_id
    )
    assert waiting.workflow_status == "WAITING_CONFIRMATION"
    assert pending_optimization.status == "WAITING_CONFIRMATION"
    assert next(step for step in waiting.step_runs if step.step_id == evaluation.step_id).status == "PENDING"

    approved = _confirm(
        arx_harness,
        execution_id=execution.id,
        step_id=optimization.step_id,
    )
    assert approved.status_code == 200, approved.text
    optimization_response = arx_harness.client.post(
        "/api/v1/copilot/optimize-pipeline/execute",
        json={"execution_id": str(execution.id)},
    )
    assert optimization_response.status_code == 200, optimization_response.text
    optimized_execution = asyncio.run(_load_execution(arx_harness, execution.id))
    fitted = next(step for step in optimized_execution.step_runs if step.tool_name == "fit_arx")
    optimized = next(
        step for step in optimized_execution.step_runs if step.tool_name == "optimize_pipeline"
    )
    pending_evaluation = next(
        step for step in optimized_execution.step_runs if step.tool_name == "evaluate_model"
    )
    assert optimized.status == "SUCCEEDED"
    assert optimized.source_version_id == fitted.source_version_id == source_version_id
    assert optimized.result_payload["model_id"] == optimized.result_payload["optimized_model_id"]
    assert optimized.result_payload["model_id"] != fitted.result_payload["model_id"]
    assert pending_evaluation.status == "PENDING"

    from app.services import agent_tool_adapter

    observed_model_ids: list[UUID] = []
    formal_evaluation = agent_tool_adapter.evaluate_saved_arx_model

    async def spy_saved_evaluation(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        observed_model_ids.append(kwargs["model_id"])  # type: ignore[index]
        return await formal_evaluation(*args, **kwargs)  # type: ignore[arg-type]

    def fail_if_refit(*args: object, **kwargs: object) -> None:
        raise AssertionError("evaluate_model must only evaluate the frozen optimized artifact")

    monkeypatch.setattr(agent_tool_adapter, "evaluate_saved_arx_model", spy_saved_evaluation)
    monkeypatch.setattr(agent_tool_adapter, "fit_arx_on_version", fail_if_refit)
    monkeypatch.setattr("app.services.modeling_service.fit_arx_core", fail_if_refit)
    before_versions = asyncio.run(_dataset_version_count(arx_harness, execution.dataset_id))
    before_runs = asyncio.run(_evaluation_run_count(arx_harness, execution.dataset_id))
    evaluation_response = arx_harness.client.post(
        "/api/v1/copilot/evaluate-model/execute",
        json={"execution_id": str(execution.id)},
    )
    assert evaluation_response.status_code == 200, evaluation_response.text

    persisted = asyncio.run(_load_execution(arx_harness, execution.id))
    evaluated = next(step for step in persisted.step_runs if step.tool_name == "evaluate_model")
    assert observed_model_ids == [UUID(optimized.result_payload["model_id"])]
    assert evaluated.status == "SUCCEEDED"
    assert evaluated.source_version_id == optimized.source_version_id == source_version_id
    assert evaluated.result_version_id is None
    assert evaluated.result_payload["model_id"] == optimized.result_payload["model_id"]
    assert len(evaluated.processing_run_ids) == 1
    run = asyncio.run(_load_processing_run(arx_harness, UUID(evaluated.processing_run_ids[0])))
    assert run.run_type == "modeling.arx_evaluation"
    assert persisted.current_version_id == source_version_id
    assert asyncio.run(_evaluation_run_count(arx_harness, execution.dataset_id)) == before_runs + 1
    assert asyncio.run(_dataset_version_count(arx_harness, execution.dataset_id)) == before_versions

def test_evaluation_resolver_requires_one_declared_model_producer() -> None:
    source_version_id = uuid4()
    dataset_id = uuid4()
    execution = AgentExecutionSession(
        id=uuid4(),
        dataset_id=dataset_id,
        initial_version_id=source_version_id,
        current_version_id=source_version_id,
        planner_source="test",
        plan_json={"steps": []},
        workflow_status="RUNNING",
        artifacts={},
    )
    fit_model_id = uuid4()
    optimized_model_id = uuid4()
    fit = AgentStepRun(
        id=uuid4(),
        execution_id=execution.id,
        step_id="fit",
        sequence=1,
        tool_name="fit_arx",
        status="SUCCEEDED",
        requires_confirmation=True,
        confirmation_status="APPROVED",
        attempt_count=1,
        source_version_id=source_version_id,
        input_payload={},
        result_payload={"model_id": str(fit_model_id)},
        processing_run_ids=[],
    )
    optimization = AgentStepRun(
        id=uuid4(),
        execution_id=execution.id,
        step_id="optimize",
        sequence=2,
        tool_name="optimize_pipeline",
        status="SUCCEEDED",
        requires_confirmation=True,
        confirmation_status="APPROVED",
        attempt_count=1,
        source_version_id=source_version_id,
        input_payload={},
        result_payload={
            "model_id": str(optimized_model_id),
            "optimized_model_id": str(optimized_model_id),
            "source_version_id": str(source_version_id),
        },
        processing_run_ids=[],
    )
    execution.step_runs = [fit, optimization]
    evaluation = AgentStepRun(
        id=uuid4(),
        execution_id=execution.id,
        step_id="evaluate",
        sequence=3,
        tool_name="evaluate_model",
        status="PENDING",
        requires_confirmation=False,
        confirmation_status="NOT_REQUIRED",
        attempt_count=0,
        input_payload={"depends_on": [optimization.step_id]},
        result_payload={},
        processing_run_ids=[],
    )

    from app.services import agent_tool_adapter

    assert agent_tool_adapter._model_producing_predecessor(execution, evaluation) == (
        optimized_model_id,
        source_version_id,
    )
    evaluation.input_payload = {"depends_on": [fit.step_id, optimization.step_id]}
    with pytest.raises(AgentToolAdapterError) as ambiguous:
        agent_tool_adapter._model_producing_predecessor(execution, evaluation)
    assert ambiguous.value.code == "EVALUATION_MODEL_PRODUCER_DEPENDENCY_REQUIRED"

    evaluation.input_payload = {"depends_on": ["profile"]}
    with pytest.raises(AgentToolAdapterError) as invalid:
        agent_tool_adapter._model_producing_predecessor(execution, evaluation)
    assert invalid.value.code == "EVALUATION_MODEL_PRODUCER_DEPENDENCY_REQUIRED"

def test_optimized_artifact_source_mismatch_fails_evaluation_without_refit(
    arx_harness: ArxHarness,
) -> None:
    execution = _chat_to_arx_confirmation(
        arx_harness,
        message="使用当前变量进行 ARX 建模并闭环寻优 1 次试验",
    )
    fit = next(step for step in execution.step_runs if step.tool_name == "fit_arx")
    optimization = next(
        step for step in execution.step_runs if step.tool_name == "optimize_pipeline"
    )
    evaluation = next(step for step in execution.step_runs if step.tool_name == "evaluate_model")
    confirmed_fit = _confirm(arx_harness, execution_id=execution.id, step_id=fit.step_id)
    assert confirmed_fit.status_code == 200, confirmed_fit.text
    source_version_id = execution.current_version_id

    async def start_and_corrupt_optimization_source() -> None:
        async with arx_harness.session_factory() as session:
            await start_step(
                session,
                execution_id=execution.id,
                step_id=optimization.step_id,
            )

    asyncio.run(start_and_corrupt_optimization_source())
    approved = _confirm(
        arx_harness,
        execution_id=execution.id,
        step_id=optimization.step_id,
    )
    assert approved.status_code == 200, approved.text
    optimized = arx_harness.client.post(
        "/api/v1/copilot/optimize-pipeline/execute",
        json={"execution_id": str(execution.id)},
    )
    assert optimized.status_code == 200, optimized.text
    assert optimized.json()["data"]["step_status"] == "SUCCEEDED"
    before_versions = asyncio.run(_dataset_version_count(arx_harness, execution.dataset_id))

    mismatched_source_version_id = UUID("00000000-0000-4000-8000-000000000001")

    async def corrupt_optimized_lineage() -> None:
        async with arx_harness.session_factory() as session:
            current = await session.scalar(
                select(AgentExecutionSession)
                .where(AgentExecutionSession.id == execution.id)
                .options(selectinload(AgentExecutionSession.step_runs))
            )
            assert current is not None
            current_optimization = next(
                step for step in current.step_runs if step.tool_name == "optimize_pipeline"
            )
            current_optimization.source_version_id = mismatched_source_version_id
            current_optimization.result_payload = {
                **current_optimization.result_payload,
                "source_version_id": str(mismatched_source_version_id),
            }
            await session.commit()

    asyncio.run(corrupt_optimized_lineage())
    response = arx_harness.client.post(
        "/api/v1/copilot/evaluate-model/execute",
        json={"execution_id": str(execution.id)},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["workflow_status"] == "FAILED"
    assert data["step_status"] == "FAILED"
    assert data["error_code"] == "MODEL_SOURCE_VERSION_MISMATCH"
    persisted = asyncio.run(_load_execution(arx_harness, execution.id))
    evaluated = next(step for step in persisted.step_runs if step.step_id == evaluation.step_id)
    assert evaluated.status == "FAILED"
    assert evaluated.processing_run_ids == []
    assert persisted.current_version_id == source_version_id
    assert asyncio.run(_dataset_version_count(arx_harness, execution.dataset_id)) == before_versions