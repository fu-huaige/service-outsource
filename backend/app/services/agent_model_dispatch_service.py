"""Deliver durable model training intents through the existing RQ worker."""

import asyncio
import logging
from uuid import UUID

from redis import Redis
from rq import Queue
from rq.exceptions import NoSuchJobError
from rq.job import Job, JobStatus
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.models.agent_execution import AgentExecutionSession, AgentStepRun
from app.models.dataset import ProcessingRun
from app.services.agent_model_execution_service import MODEL_DISPATCH_SOURCE
from app.services.job_queue import JOB_TIMEOUT_SECONDS, QUEUE_NAME, RESULT_TTL_SECONDS
from app.services.oe_platform_adapter import has_oe_publication_checkpoint
from app.services.pls_training_service import SessionFactory

logger = logging.getLogger(__name__)
_JOB_FUNCTION = "app.worker.run_model_training_job"
_RESCAN_SECONDS = 5
_BATCH_SIZE = 100


def _submit(execution_id: UUID) -> None:
    """A matching RQ job acknowledges delivery. The database owns the right to fit."""
    job_id = str(execution_id)
    with Redis.from_url(get_settings().redis_url, socket_connect_timeout=2, socket_timeout=2) as redis:
        queue = Queue(QUEUE_NAME, connection=redis, default_timeout=JOB_TIMEOUT_SECONDS)
        lock = redis.lock(f"indusopt:model-training:dispatch:{job_id}", timeout=15, blocking=False)
        with lock:
            try:
                existing = Job.fetch(job_id, connection=redis)
            except NoSuchJobError:
                existing = None
            if existing is not None:
                if (
                    existing.func_name != _JOB_FUNCTION
                    or existing.origin != QUEUE_NAME
                    or existing.args != (job_id,)
                ):
                    raise ValueError("Unexpected RQ job identity for model training")
                if existing.get_status() in (JobStatus.QUEUED, JobStatus.STARTED):
                    return
                # A pre-claim failure may leave a terminal RQ job while the intent is pending.
                existing.delete(remove_from_queue=True)
            queue.enqueue(
                _JOB_FUNCTION, job_id, job_id=job_id, unique=True,
                job_timeout=JOB_TIMEOUT_SECONDS, result_ttl=RESULT_TTL_SECONDS,
            )


async def dispatch_model_training(session: AsyncSession, *, execution_id: UUID) -> None:
    try:
        row = (await session.execute(
            select(AgentStepRun.id, AgentStepRun.result_payload)
            .join(AgentExecutionSession)
            .where(
                AgentExecutionSession.id == execution_id,
                AgentExecutionSession.planner_source == MODEL_DISPATCH_SOURCE,
                AgentExecutionSession.workflow_status == "PLANNED",
                AgentStepRun.status == "PENDING",
            )
        )).one_or_none()
        if row is None:
            return
        step_pk, payload = row
        # Release the read transaction before calling Redis; a concurrent worker can claim the row.
        await session.rollback()
        await run_in_threadpool(_submit, execution_id)
        if payload.get("dispatch_status") == "queued":
            return
        await session.execute(
            update(AgentStepRun)
            .where(AgentStepRun.id == step_pk, AgentStepRun.status == "PENDING")
            .values(result_payload={**payload, "dispatch_status": "queued"})
        )
        await session.commit()
    except Exception as error:
        await session.rollback()
        logger.warning("Model training dispatch deferred for %s (%s)", execution_id, type(error).__name__)


async def recover_pending_model_dispatches(factory: SessionFactory) -> None:
    cursor = None
    while True:
        query = (
            select(AgentExecutionSession.id)
            .where(
                AgentExecutionSession.planner_source == MODEL_DISPATCH_SOURCE,
                AgentExecutionSession.workflow_status == "PLANNED",
            )
            .order_by(AgentExecutionSession.id)
            .limit(_BATCH_SIZE)
        )
        if cursor is not None:
            query = query.where(AgentExecutionSession.id > cursor)
        async with factory() as session:
            ids = (await session.scalars(query)).all()
        for execution_id in ids:
            async with factory() as session:
                await dispatch_model_training(session, execution_id=execution_id)
        if len(ids) < _BATCH_SIZE:
            return
        cursor = ids[-1]


async def _recover_oe_publications(factory: SessionFactory) -> None:
    """Redeliver only saved OE models that can resume without entering optimization."""
    cursor = None
    while True:
        query = (select(AgentExecutionSession.id, AgentStepRun.processing_run_ids)
                 .join(AgentStepRun).where(
                     AgentExecutionSession.planner_source == MODEL_DISPATCH_SOURCE,
                     AgentExecutionSession.workflow_status.in_(("RUNNING", "UNCONFIRMED")),
                     AgentStepRun.input_payload["selection"]["model_type_id"].as_string() == "oe",
                     AgentStepRun.processing_run_ids[0].as_string().is_not(None),
                 ).order_by(AgentExecutionSession.id).limit(_BATCH_SIZE))
        if cursor is not None:
            query = query.where(AgentExecutionSession.id > cursor)
        async with factory() as session:
            rows = (await session.execute(query)).all()
            ready = []
            for execution_id, run_ids in rows:
                if len(run_ids) == 1 and has_oe_publication_checkpoint(
                    await session.get(ProcessingRun, UUID(run_ids[0]))
                ):
                    ready.append(execution_id)
        for execution_id in ready:
            await run_in_threadpool(_submit, execution_id)
        if len(rows) < _BATCH_SIZE:
            return
        cursor = rows[-1][0]


async def recover_model_dispatches(factory: SessionFactory) -> None:
    """Recover on startup and retry while the API process is serving."""
    while True:
        try:
            await recover_pending_model_dispatches(factory)
            await _recover_oe_publications(factory)
        except Exception as error:
            logger.warning("Model training dispatch scan deferred (%s)", type(error).__name__)
        await asyncio.sleep(_RESCAN_SECONDS)
