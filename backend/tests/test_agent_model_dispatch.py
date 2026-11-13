"""Durable model dispatch uses the existing Agent records and a single Worker claim."""

import asyncio
from datetime import timedelta
from threading import Event
from time import monotonic, sleep
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from app.core.db import get_session_factory
from app.main import create_app
from app.models.agent_execution import AgentExecutionSession
from app.services import agent_model_dispatch_service as dispatch
from app.services import agent_model_execution_service as modeling
from app.services import pls_training_service
from fastapi.testclient import TestClient
from rq.exceptions import NoSuchJobError
from rq.job import JobStatus
from sqlalchemy import select

from test_agent_model_execution import EXECUTE, prepare
from test_agent_model_recommendation import CONFIRM
from test_model_evaluation_api import response_data
from test_pls_api import api as api
from test_pls_training_service import runs
from test_tcn_platform import data as data

pytestmark = pytest.mark.asyncio
LOOKUP = "/api/v1/copilot/modeling/execution"


def authorize(api, data, *, model="pls", horizon=1):
    chat, confirmation, refs = prepare(api, data, model, horizon=horizon)
    return chat, {**confirmation, "dispatch_training": True}, refs


async def children(data):
    async with data["factory"]() as session:
        return (await session.scalars(select(AgentExecutionSession).where(
            AgentExecutionSession.planner_source == modeling.MODEL_DISPATCH_SOURCE,
        ))).all()


async def test_confirmation_and_intent_commit_together(api, data, monkeypatch):
    chat, confirmation, refs = authorize(api, data)
    reserve = modeling.reserve_model_training

    def fail_after_insert(*args, **kwargs):
        reserve(*args, **kwargs)
        raise RuntimeError("simulated write failure before commit")

    monkeypatch.setattr(modeling, "reserve_model_training", fail_after_insert)
    assert api.post(CONFIRM, json=confirmation).status_code == 500
    state = response_data(api.get(f"/api/v1/copilot/executions/{chat['execution_id']}"))
    assert state["pending_confirmation_step_id"] == confirmation["step_id"]
    assert state["step_runs"][-1]["status"] == "WAITING_CONFIRMATION"
    assert not await children(data)

    monkeypatch.setattr(modeling, "reserve_model_training", reserve)

    observed = []

    def reject_publish(execution_id):
        # Observe the committed parent and child via a separate request/session.
        observed.append(response_data(api.get(LOOKUP, params=refs))["execution_id"])
        assert observed[-1] == str(execution_id)
        raise ConnectionError("Redis unavailable")

    monkeypatch.setattr(dispatch, "_submit", reject_publish)
    locked = response_data(api.post(CONFIRM, json=confirmation))
    assert response_data(api.post(CONFIRM, json=confirmation)) == locked
    (child,) = await children(data)
    result = response_data(api.get(LOOKUP, params=refs))
    assert result["execution_id"] == str(child.id)
    assert observed == [str(child.id)] * 2
    assert result["dispatch_status"] == result["training_status"] == "pending"
    assert response_data(api.post(EXECUTE, json=refs)) == result
    assert not [run for run in await runs(data) if run.run_type.startswith("modeling.")]


async def test_restart_recovers_database_intent_after_commit(api, data, monkeypatch):
    from app.api import routes

    _, confirmation, refs = authorize(api, data)

    async def process_exits(*args, **kwargs):
        raise RuntimeError("simulated process exit before Redis enqueue")

    monkeypatch.setattr(routes, "dispatch_model_training", process_exits)
    assert api.post(CONFIRM, json=confirmation).status_code == 500
    pending = response_data(api.get(LOOKUP, params=refs))
    assert pending["dispatch_status"] == "pending"

    published = []

    def first_publish_fails(execution_id):
        published.append(execution_id)
        raise ConnectionError("Redis unavailable")

    monkeypatch.setattr(dispatch, "_submit", first_publish_fails)
    await dispatch.recover_pending_model_dispatches(data["factory"])
    assert response_data(api.get(LOOKUP, params=refs))["dispatch_status"] == "pending"
    delivered = Event()
    release_redis = Event()

    def publish(execution_id):
        published.append(execution_id)
        delivered.set()
        assert release_redis.wait(5), "Test did not release the simulated Redis connection"

    monkeypatch.setattr(dispatch, "_submit", publish)
    app = create_app()
    app.dependency_overrides[get_session_factory] = lambda: data["factory"]
    with TestClient(app) as restarted:
        try:
            assert delivered.wait(3), "Backend startup did not discover the pending intent"
            assert restarted.get("/api/v1/health/live").status_code == 200
        finally:
            release_redis.set()
        deadline = monotonic() + 3
        queued = response_data(api.get(LOOKUP, params=refs))
        while queued["dispatch_status"] != "queued" and monotonic() < deadline:
            sleep(0.02)
            queued = response_data(api.get(LOOKUP, params=refs))
    assert queued["dispatch_status"] == "queued" and queued["training_status"] == "pending"
    assert published == [UUID(pending["execution_id"])] * 2


async def test_old_confirmation_only_locks_model(api, data, monkeypatch):
    _, confirmation, refs = prepare(api, data, "pls")
    submit = MagicMock()
    monkeypatch.setattr(dispatch, "_submit", submit)
    locked = response_data(api.post(CONFIRM, json=confirmation))
    assert locked["result_payload"]["model_selection"]["model_type_id"] == "pls"
    assert response_data(api.get(LOOKUP, params=refs)) is None
    assert not await children(data)
    submit.assert_not_called()


async def test_concurrent_recovery_scans_keep_one_pending_intent(api, data, monkeypatch):
    _, confirmation, refs = authorize(api, data)
    submit = MagicMock(side_effect=ConnectionError("Redis unavailable"))
    monkeypatch.setattr(dispatch, "_submit", submit)
    response_data(api.post(CONFIRM, json=confirmation))
    submit.reset_mock(side_effect=True)

    await asyncio.gather(*(
        dispatch.recover_pending_model_dispatches(data["factory"]) for _ in range(2)
    ))
    (child,) = await children(data)
    assert submit.call_count >= 2
    assert {call.args for call in submit.call_args_list} == {(child.id,)}
    result = response_data(api.get(LOOKUP, params=refs))
    assert result["dispatch_status"] == "queued"
    assert result["training_status"] == "pending"


@pytest.mark.parametrize(("model", "horizon"), [("pls", 1), ("xgboost", 1), ("tcn", 1), ("timexer", 3)])
async def test_duplicate_delivery_fits_once_and_preserves_validation(api, data, monkeypatch, model, horizon):
    monkeypatch.setattr(dispatch, "_submit", lambda _: None)
    _, confirmation, refs = authorize(api, data, model=model, horizon=horizon)
    response_data(api.post(CONFIRM, json=confirmation))
    result = response_data(api.get(LOOKUP, params=refs))
    assert result["dispatch_status"] == "queued"
    execution_id = UUID(result["execution_id"])
    fit = modeling._fit
    calls = []

    async def count_fit(*args):
        calls.append(args[2])
        return await fit(*args)

    monkeypatch.setattr(modeling, "_fit", count_fit)
    preflight = modeling._preflight
    workers_ready = asyncio.Barrier(2)

    async def preflight_together(*args):
        result = await preflight(*args)
        await asyncio.wait_for(workers_ready.wait(), timeout=5)
        return result

    monkeypatch.setattr(modeling, "_preflight", preflight_together)

    async def deliver():
        await modeling.run_dispatched_model(
            data["factory"], execution_id=execution_id, artifact_root=data["root"]
        )

    await asyncio.gather(deliver(), deliver())
    await deliver()
    assert len(calls) == 1
    result = response_data(api.get(LOOKUP, params=refs))
    assert result["training_status"] == "succeeded"
    assert result["manifest_status"] == "published"
    assert result["evaluation_status"] == "succeeded"
    assert result["evaluation"]["partition"] == "validation"
    assert result["evaluation"]["model_id"] == result["model_id"]


@pytest.mark.parametrize("phase", ["before_run", "running_run", "saved_model"])
async def test_worker_interruption_never_restarts_claim(api, data, monkeypatch, phase):
    monkeypatch.setattr(dispatch, "_submit", lambda _: None)
    _, confirmation, refs = authorize(api, data)
    response_data(api.post(CONFIRM, json=confirmation))
    result = response_data(api.get(LOOKUP, params=refs))
    execution_id = UUID(result["execution_id"])
    original_fit = modeling._fit

    class WorkerExited(BaseException):
        pass

    calls = []

    def interrupt_core(*args, **kwargs):
        raise WorkerExited

    if phase == "running_run":
        monkeypatch.setattr(pls_training_service, "fit_pls_core", interrupt_core)

    async def interrupt(*args):
        calls.append(1)
        if phase != "before_run":
            await original_fit(*args)
        raise WorkerExited

    monkeypatch.setattr(modeling, "_fit", interrupt)
    monkeypatch.setattr(modeling, "JOB_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(modeling, "_RECOVERY_AFTER", timedelta(0))
    with pytest.raises(WorkerExited):
        await modeling.run_dispatched_model(
            data["factory"], execution_id=execution_id, artifact_root=data["root"]
        )
    await modeling.run_dispatched_model(
        data["factory"], execution_id=execution_id, artifact_root=data["root"]
    )
    result = response_data(api.get(LOOKUP, params=refs))
    assert result["dispatch_status"] == "started"
    assert result["execution_status"] == "unconfirmed"
    assert len(calls) == 1
    if phase == "saved_model":
        assert result["training_status"] == "succeeded"
        assert result["model_id"] and result["training_run_id"]
        assert result["manifest_status"] == "published"
    else:
        assert result["training_status"] == "unconfirmed"
        assert result["model_id"] is None
        assert (result["training_run_id"] is not None) == (phase == "running_run")
    training_runs = [run for run in await runs(data) if run.run_type == "modeling.pls"]
    assert len(training_runs) == int(phase != "before_run")
    if phase == "running_run":
        assert training_runs[0].status == "running"


async def test_rq_uses_stable_job_identity_and_checks_existing_delivery(monkeypatch):
    execution_id = uuid4()
    redis = MagicMock()
    redis.__enter__.return_value = redis
    monkeypatch.setattr(dispatch.Redis, "from_url", lambda *args, **kwargs: redis)
    queue = MagicMock()
    monkeypatch.setattr(dispatch, "Queue", lambda *args, **kwargs: queue)
    job = MagicMock(origin=dispatch.QUEUE_NAME, func_name=dispatch._JOB_FUNCTION, args=(str(execution_id),))
    job.get_status.side_effect = [JobStatus.QUEUED, JobStatus.FAILED]
    fetch = MagicMock(side_effect=[NoSuchJobError(), job, job])
    monkeypatch.setattr(dispatch.Job, "fetch", fetch)

    dispatch._submit(execution_id)
    dispatch._submit(execution_id)
    assert queue.enqueue.call_count == 1
    assert queue.enqueue.call_args.args == (dispatch._JOB_FUNCTION, str(execution_id))
    assert queue.enqueue.call_args.kwargs["job_id"] == str(execution_id)
    assert queue.enqueue.call_args.kwargs["unique"] is True
    dispatch._submit(execution_id)
    assert queue.enqueue.call_count == 2
    job.delete.assert_called_once_with(remove_from_queue=True)
