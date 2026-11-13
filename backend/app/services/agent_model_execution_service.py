"""Execute one explicitly authorized model without replaying a training claim."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import event, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models.agent_execution import AgentExecutionSession, AgentStepRun
from app.models.dataset import ProcessingRun
from app.schemas.common import Schema
from app.schemas.copilot import (
    CopilotModelExecuteRequest,
    CopilotModelExecutionData,
    CopilotModelSelection,
    ExecutionPlan,
    ExecutionPlanStep,
)
from app.schemas.experiment_spec import Digest, ExperimentSpec
from app.schemas.model_comparison import ModelComparisonRequest
from app.schemas.model_evaluation import ModelEvaluationRequest, ModelEvaluationResult
from app.schemas.model_recommendation import (
    ModelRecommendationRequest,
    ModelRecommendationResult,
    RecommendationModelType,
)
from app.schemas.pls import PLSParameters
from app.schemas.tcn import TCNParameters
from app.schemas.timexer import TimeXerParameters
from app.schemas.timexer_platform import TimeXerForecastSpec
from app.schemas.xgboost import XGBoostParameters
from app.services.agent_service import AgentDomainError
from app.services.dataset_csv import DatasetCsvError
from app.services.dataset_version_io import DatasetVersionArtifactError
from app.services.experiment_spec_service import bind_experiment_spec, spec_hash
from app.services.job_queue import JOB_TIMEOUT_SECONDS
from app.services.model_artifact_service import load_model_instance
from app.services.model_comparison_service import ModelComparisonError, compare_model_evaluations
from app.services.model_evaluation_service import (
    RUN_TYPE as EVALUATION_RUN_TYPE,
)
from app.services.model_evaluation_service import (
    ModelEvaluationError,
    evaluate_saved_model,
    get_model_evaluation,
)
from app.services.model_registry import validate_parameters
from app.services.pls_training_service import (
    PLSTrainingError,
    SessionFactory,
    fit_pls_with_manifest,
)
from app.services.tcn_platform_adapter import TCNTrainingError, fit_tcn_on_version
from app.services.timexer_platform_adapter import TimeXerTrainingError, fit_timexer_on_version
from app.services.version_data import VersionDataError
from app.services.xgboost_platform_adapter import XGBoostTrainingError, fit_xgboost_on_version

_TOOL = "execute_confirmed_model"
MODEL_DISPATCH_SOURCE = "queued_model_selection"
_RECOVERY_AFTER = timedelta(minutes=15)
_TRAINING_ERRORS = (PLSTrainingError, XGBoostTrainingError, TCNTrainingError, TimeXerTrainingError)


class _LockedSelection(Schema):
    model_type_id: RecommendationModelType
    parameters: dict[str, object]
    dataset_id: UUID
    dataset_version_id: UUID
    csv_sha256: Digest
    experiment_spec_hash: Digest
    forecast_spec: TimeXerForecastSpec | None
    selection_source: Literal["agent_recommendation", "manual"]
    recommendation_step_id: str
    confirmation_status: Literal["APPROVED"]
    confirmed_at: datetime


def _conflict() -> AgentDomainError:
    return AgentDomainError(
        "MODEL_EXECUTION_SELECTION_INVALID",
        "已确认模型选择或来源证据无效，请重新生成推荐并确认。",
        status_code=409,
    )


async def _selection(factory, request):
    async with factory() as session:
        execution = await session.scalar(
            select(AgentExecutionSession)
            .where(
                AgentExecutionSession.id == request.selection_execution_id,
                AgentExecutionSession.copilot_run_id == request.copilot_run_id,
            )
            .options(selectinload(AgentExecutionSession.step_runs))
        )
        if execution is None:
            raise AgentDomainError(
                "MODEL_SELECTION_NOT_FOUND", "未找到对应的模型选择会话。", status_code=404
            )
        steps = {step.step_id: step for step in execution.step_runs}
        step = steps.get(request.confirmed_selection_step_id)
        if (
            execution.workflow_status != "SUCCEEDED"
            or step is None
            or step.tool_name != "confirm_model_selection"
            or step.status != "SUCCEEDED"
            or not step.requires_confirmation
            or step.confirmation_status != "APPROVED"
        ):
            raise _conflict()
        try:
            raw = step.input_payload["confirmed_model_selection"]
            locked = _LockedSelection.model_validate(raw)
            submitted = CopilotModelSelection.model_validate(
                step.input_payload["submitted_model_selection"]
            )
            recommendation = steps[locked.recommendation_step_id]
            snapshot = ModelRecommendationResult.model_validate(
                recommendation.result_payload["recommendation"]
            )
            recommendation_request = ModelRecommendationRequest.model_validate(
                recommendation.input_payload["recommendation_request"]
            )
            original = recommendation_request.experiment_spec
        except (ValueError, KeyError) as error:
            raise _conflict() from error
        version_id = execution.initial_version_id
        for prior in sorted(execution.step_runs, key=lambda item: item.sequence):
            if prior.sequence >= recommendation.sequence:
                break
            if prior.status != "SUCCEEDED" or prior.source_version_id != version_id:
                raise _conflict()
            if prior.result_version_id is not None:
                version_id = prior.result_version_id
        source = snapshot.source
        if (
            step.result_payload.get("model_selection") != raw
            or step.input_payload.get("recommendation_step_id") != locked.recommendation_step_id
            or locked.recommendation_step_id not in step.input_payload.get("depends_on", [])
            or recommendation.tool_name != "recommend_models"
            or recommendation.status != "SUCCEEDED"
            or (execution.dataset_id, version_id, execution.current_version_id)
            != (locked.dataset_id, locked.dataset_version_id, locked.dataset_version_id)
            or step.source_version_id != locked.dataset_version_id
            or recommendation.source_version_id != locked.dataset_version_id
            or (
                source.dataset_id,
                source.dataset_version_id,
                source.csv_sha256,
                source.experiment_spec_hash,
            )
            != (
                locked.dataset_id,
                locked.dataset_version_id,
                locked.csv_sha256,
                locked.experiment_spec_hash,
            )
            or (original.dataset_id, original.dataset_version_id, original.dataset_version_sha256)
            != (locked.dataset_id, locked.dataset_version_id, locked.csv_sha256)
            or original.training_selection.mode != "full_train"
            or source.target_name != original.target_column
            or source.feature_names != original.input_columns
            or (
                submitted.selected_model_type_id,
                submitted.selection_source,
                submitted.forecast_spec,
            )
            != (locked.model_type_id, locked.selection_source, locked.forecast_spec)
            or (
                submitted.recommendation_step_id,
                submitted.dataset_id,
                submitted.dataset_version_id,
                submitted.csv_sha256,
                submitted.experiment_spec_hash,
            )
            != (
                locked.recommendation_step_id,
                locked.dataset_id,
                locked.dataset_version_id,
                locked.csv_sha256,
                locked.experiment_spec_hash,
            )
        ):
            raise _conflict()
        accepted_recommendation = locked.selection_source == "agent_recommendation"
        if accepted_recommendation or step.input_payload.get("dispatch_training") is True:
            candidate = next(
                (
                    item
                    for item in snapshot.candidates
                    if item.model_type_id == locked.model_type_id
                ),
                None,
            )
            if (
                (accepted_recommendation and locked.model_type_id not in snapshot.recommended_models)
                or candidate is None
                or candidate.eligibility_status != "eligible"
                or candidate.actual_parameters != locked.parameters
                or candidate.forecast_spec != locked.forecast_spec
                or submitted.selected_parameters != locked.parameters
            ):
                raise _conflict()
        return step.id, locked, recommendation_request


async def _preflight(factory, locked, recommendation_request, root):
    try:
        parameters = validate_parameters(locked.model_type_id, locked.parameters)
        if parameters.model_dump(mode="json") != locked.parameters:
            raise ValueError("Confirmed parameters are incomplete")
        original_forecast = recommendation_request.forecast_spec
        horizon = original_forecast.prediction_length if original_forecast else 1
        if isinstance(parameters, TimeXerParameters):
            if locked.forecast_spec is None or locked.forecast_spec.prediction_length != horizon:
                raise ValueError("Forecast contract has changed")
            locked.forecast_spec.validate_parameters(parameters)
        elif locked.forecast_spec is not None or horizon != 1:
            raise ValueError("Forecast contract has changed")
        async with factory() as session:
            bound = await bind_experiment_spec(
                session, spec=recommendation_request.experiment_spec, artifact_root=root
            )
        if spec_hash(bound) != locked.experiment_spec_hash:
            raise ValueError("Bound ExperimentSpec has changed")
    except (ValueError, VersionDataError, DatasetCsvError, DatasetVersionArtifactError) as error:
        raise _conflict() from error
    return bound, parameters


async def _linked_evaluation_id(factory, step_pk):
    async with factory() as session:
        step = await session.get(AgentStepRun, step_pk)
        if step is not None and len(step.processing_run_ids) == 2:
            return UUID(step.processing_run_ids[1])
        return None


def _record_matches(run, locked):
    try:
        spec = ExperimentSpec.model_validate(run.parameters.get("experiment_spec"))
    except ValueError:
        return False
    return (
        spec_hash(spec) == locked.experiment_spec_hash
        and spec.dataset_version_sha256 == locked.csv_sha256
        and run.run_type == f"modeling.{locked.model_type_id}"
        and (run.dataset_id, run.source_version_id)
        == (locked.dataset_id, locked.dataset_version_id)
        and run.result.get("model_type_id") == locked.model_type_id
        and run.parameters.get("experiment_spec_hash") == locked.experiment_spec_hash
        and run.parameters.get(f"{locked.model_type_id}_parameters") == locked.parameters
        and run.parameters.get("forecast_spec")
        == (locked.forecast_spec.model_dump(mode="json") if locked.forecast_spec else None)
    )


async def _claim(factory, data, locked, copilot_run_id, selection_pk):
    step_pk = uuid4()
    plan = ExecutionPlan(
        goal="Execute the confirmed model selection",
        dataset_id=locked.dataset_id,
        steps=[ExecutionPlanStep(step_id=_TOOL, tool=_TOOL)],
    )
    async with factory() as session:
        session.add(
            AgentExecutionSession(
                id=data.execution_id,
                copilot_run_id=copilot_run_id,
                dataset_id=locked.dataset_id,
                initial_version_id=locked.dataset_version_id,
                current_version_id=locked.dataset_version_id,
                planner_source="confirmed_model_selection",
                plan_json=plan.model_dump(mode="json"),
                workflow_status="RUNNING",
                current_step_id=_TOOL,
            )
        )
        try:
            await session.flush()
            session.add(
                AgentStepRun(
                    id=step_pk,
                    execution_id=data.execution_id,
                    step_id=_TOOL,
                    sequence=1,
                    tool_name=_TOOL,
                    status="RUNNING",
                    attempt_count=1,
                    started_at=datetime.now(UTC),
                    source_version_id=locked.dataset_version_id,
                    input_payload={
                        "selection_step_pk": str(selection_pk),
                        "selection_execution_id": str(data.selection_execution_id),
                    },
                    result_payload=data.model_dump(mode="json"),
                    processing_run_ids=[],
                )
            )
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return None
    return step_pk


def _linked_factory(factory, step_pk, locked, *, model_id=None, training_run_id=None):
    """Link the real Run atomically with its initial INSERT in the platform session."""

    @asynccontextmanager
    async def open_session():
        async with factory() as session:

            def link(sync_session: Session, _context, _instances):
                runs = [item for item in sync_session.new if isinstance(item, ProcessingRun)]
                if not runs:
                    return
                if len(runs) != 1:
                    raise RuntimeError("Expected one new platform Run")
                (run,) = runs
                if model_id is None:
                    valid = _record_matches(run, locked) and bool(UUID(run.result["model_id"]))
                    previous = []
                else:
                    valid = (
                        run.run_type == EVALUATION_RUN_TYPE
                        and run.parameters.get("model_id") == str(model_id)
                        and run.parameters.get("partition") == "validation"
                    )
                    previous = [str(training_run_id)]
                if not valid or run.status != "running" or not isinstance(run.id, UUID):
                    raise RuntimeError("Platform Run does not match the execution claim")
                conditions = [
                    AgentStepRun.id == step_pk,
                    AgentStepRun.status == "RUNNING",
                    AgentStepRun.processing_run_ids[len(previous)].as_string().is_(None),
                ]
                if previous:
                    conditions.append(AgentStepRun.processing_run_ids[0].as_string() == previous[0])
                result = sync_session.connection().execute(
                    update(AgentStepRun)
                    .where(*conditions)
                    .values(processing_run_ids=[*previous, str(run.id)])
                )
                if result.rowcount != 1:
                    raise RuntimeError("Execution claim already has a platform Run")

            event.listen(session.sync_session, "before_flush", link)
            try:
                yield session
            finally:
                event.remove(session.sync_session, "before_flush", link)

    return open_session


async def _fit(factory, spec, params, forecast, root):
    if isinstance(params, PLSParameters):
        return await fit_pls_with_manifest(
            factory, spec=spec, parameters=params, artifact_root=root
        )
    if isinstance(params, XGBoostParameters):
        return await fit_xgboost_on_version(
            factory, spec=spec, parameters=params, artifact_root=root
        )
    if isinstance(params, TCNParameters):
        return await fit_tcn_on_version(factory, spec=spec, parameters=params, artifact_root=root)
    if isinstance(params, TimeXerParameters) and forecast is not None:
        return await fit_timexer_on_version(
            factory, spec=spec, parameters=params, forecast_spec=forecast, artifact_root=root
        )
    raise ValueError("Unsupported confirmed model parameters")


async def _checkpoint(factory, step_pk, data):
    async with factory() as session:
        execution = await session.get(AgentExecutionSession, data.execution_id)
        step = await session.get(AgentStepRun, step_pk)
        if execution is None or step is None or step.status != "RUNNING":
            raise RuntimeError("Model execution claim is unavailable")
        step.result_payload = data.model_dump(mode="json")
        execution.updated_at = datetime.now(UTC)
        if data.execution_status != "running":
            execution.workflow_status = step.status = data.execution_status.upper()
            execution.finished_at = step.finished_at = execution.updated_at
            execution.current_step_id = None
        await session.commit()


def _evaluation_matches(result, data):
    return (
        isinstance(result, ModelEvaluationResult)
        and (result.model_id, result.training_run_id) == (data.model_id, data.training_run_id)
        and result.model_type_id == data.model_type_id
        and result.dataset_version_id == data.dataset_version_id
        and result.experiment_spec_hash == data.experiment_spec_hash
        and result.partition == "validation"
        and getattr(result, "forecast_spec", None) == data.forecast_spec
    )


async def _replay(factory, identity, selection_pk, locked, root, *, interrupted=False):
    """Read only evidence explicitly linked by the claimant's platform transactions."""
    async with factory() as session:
        execution = await session.scalar(
            select(AgentExecutionSession)
            .where(AgentExecutionSession.id == identity.execution_id)
            .options(selectinload(AgentExecutionSession.step_runs))
        )
        if execution is None:
            return None
        if len(execution.step_runs) != 1:
            raise _conflict()
        step = execution.step_runs[0]
        if (
            step.tool_name != _TOOL
            or step.input_payload.get("selection_step_pk") != str(selection_pk)
            or step.input_payload.get("selection_execution_id")
            != str(identity.selection_execution_id)
        ):
            raise _conflict()
        data = CopilotModelExecutionData.model_validate(step.result_payload)
        if data.execution_status not in {"running", "unconfirmed"}:
            return data
        expired = (
            interrupted
            or data.execution_status == "unconfirmed"
            or datetime.now(UTC) - execution.updated_at.replace(tzinfo=UTC) >= (
                timedelta(seconds=JOB_TIMEOUT_SECONDS) + _RECOVERY_AFTER
                if execution.planner_source == MODEL_DISPATCH_SOURCE else _RECOVERY_AFTER
            )
        )
        if expired:
            data.execution_status = "unconfirmed"

        if step.processing_run_ids:
            run = await session.get(ProcessingRun, UUID(step.processing_run_ids[0]))
            if run is not None and _record_matches(run, locked):
                data.training_run_id = run.id
                if run.status == "succeeded":
                    data.model_id = UUID(run.result["model_id"])
                    data.training_status = "succeeded"
                    if data.manifest_status in {"pending", "unconfirmed"}:
                        try:
                            loaded = await load_model_instance(
                                session,
                                model_id=data.model_id,
                                artifact_root=root,
                                expected_model_type=data.model_type_id,
                            )
                            if loaded.manifest is not None and loaded.training_run_id == run.id:
                                data.manifest_status = "published"
                        except (ValueError, OSError):
                            if expired:
                                data.manifest_status = "unconfirmed"
                elif run.status == "failed":
                    data.training_status = "failed"
                    data.training_error = "PLATFORM_TRAINING_FAILED"
                    data.execution_status = "failed"
                    data.evaluation_status = data.comparison_status = "skipped"
        if expired and data.training_status == "running":
            data.training_status = "unconfirmed"
            data.training_error = "TRAINING_REQUIRES_RECONCILIATION"

        if len(step.processing_run_ids) > 1 and data.training_status == "succeeded":
            evaluation_id = UUID(step.processing_run_ids[1])
            detail = await get_model_evaluation(session, evaluation_id)
            if detail is not None and detail.model_id == data.model_id:
                data.evaluation_run_id = evaluation_id
                if detail.status == "succeeded" and _evaluation_matches(detail.result, data):
                    data.evaluation_status = "succeeded"
                    data.evaluation = detail.result
                    data.evaluation_error = None
                elif detail.status == "failed":
                    data.evaluation_status = "failed"
                    data.evaluation_error = "VALIDATION_EVALUATION_FAILED"
                    data.comparison_status = "skipped"
                else:
                    data.evaluation_status = "unconfirmed" if expired else "running"
        if expired and data.evaluation_status == "running":
            data.evaluation_status = "unconfirmed"
            data.evaluation_error = "VALIDATION_REQUIRES_RECONCILIATION"
        if expired and data.comparison_status == "pending":
            data.comparison_status = "unconfirmed"
        return data


async def _comparison(factory, data, locked, root):
    async with factory() as session:
        ids = [data.evaluation_run_id]
        peers = await session.scalars(
            select(ProcessingRun.id)
            .where(
                ProcessingRun.run_type == EVALUATION_RUN_TYPE,
                ProcessingRun.status == "succeeded",
                ProcessingRun.dataset_id == locked.dataset_id,
                ProcessingRun.source_version_id == locked.dataset_version_id,
                ProcessingRun.parameters["dataset_sha256"].as_string() == locked.csv_sha256,
                ProcessingRun.parameters["partition"].as_string() == "validation",
                ProcessingRun.result["model_id"].as_string() != str(data.model_id),
            )
            .order_by(ProcessingRun.created_at.desc(), ProcessingRun.id.desc())
            .limit(20)
        )
        reason = "NO_OTHER_VALIDATION_RESULT"
        for peer in peers:
            try:
                result = await compare_model_evaluations(
                    session,
                    request=ModelComparisonRequest(evaluation_run_ids=(*ids, peer)),
                    artifact_root=root,
                )
            except ModelComparisonError as error:
                if error.run_id == data.evaluation_run_id:
                    raise
                reason = f"{error.code}:{error.field}"
                continue
            ids.append(peer)
            data.comparison = result
            if len(ids) == 10:
                break
        data.compared_evaluation_run_ids = tuple(ids) if len(ids) > 1 else ()
        data.comparison_status = "succeeded" if len(ids) > 1 else "not_comparable"
        if len(ids) == 1:
            data.comparison_reason = reason


def model_training_execution_id(selection_pk: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"indusopt/confirmed-model-execution/{selection_pk}")


def _execution_identity(request, selection_pk, locked):
    return CopilotModelExecutionData(
        execution_id=model_training_execution_id(selection_pk),
        selection_execution_id=request.selection_execution_id,
        confirmed_selection_step_id=request.confirmed_selection_step_id,
        model_type_id=locked.model_type_id,
        dataset_version_id=locked.dataset_version_id,
        experiment_spec_hash=locked.experiment_spec_hash,
        forecast_spec=locked.forecast_spec,
    )


def reserve_model_training(session, *, execution_id, copilot_run_id, step_id, step_pk, selection):
    """Insert the dispatch intent in the caller's selection transaction."""
    locked = _LockedSelection.model_validate(selection)
    request = CopilotModelExecuteRequest(
        selection_execution_id=execution_id,
        copilot_run_id=copilot_run_id,
        confirmed_selection_step_id=step_id,
    )
    data = _execution_identity(request, step_pk, locked)
    data.execution_status = data.training_status = data.dispatch_status = "pending"
    child = AgentExecutionSession(
        id=data.execution_id,
        copilot_run_id=copilot_run_id,
        dataset_id=locked.dataset_id,
        initial_version_id=locked.dataset_version_id,
        current_version_id=locked.dataset_version_id,
        planner_source=MODEL_DISPATCH_SOURCE,
        workflow_status="PLANNED",
        plan_json=ExecutionPlan(
            goal="Execute the confirmed model selection",
            dataset_id=locked.dataset_id,
            steps=[ExecutionPlanStep(step_id=_TOOL, tool=_TOOL)],
        ).model_dump(mode="json"),
    )
    child.step_runs.append(AgentStepRun(
        step_id=_TOOL,
        sequence=1,
        tool_name=_TOOL,
        status="PENDING",
        source_version_id=locked.dataset_version_id,
        input_payload={
            "selection_step_pk": str(step_pk),
            "selection_execution_id": str(execution_id),
            "selection": selection,
        },
        result_payload=data.model_dump(mode="json"),
    ))
    session.add(child)


async def run_dispatched_model(
    factory: SessionFactory, *, execution_id: UUID, artifact_root: Path
) -> None:
    """Only a worker that changes the durable intent from pending to running may fit."""
    async with factory() as session:
        child = await session.scalar(
            select(AgentExecutionSession)
            .where(AgentExecutionSession.id == execution_id)
            .options(selectinload(AgentExecutionSession.step_runs))
        )
        if (
            child is None or child.planner_source != MODEL_DISPATCH_SOURCE
            or child.workflow_status != "PLANNED" or len(child.step_runs) != 1
        ):
            return
        step = child.step_runs[0]
        if step.status != "PENDING" or step.processing_run_ids:
            return
        step_pk = step.id
        data = CopilotModelExecutionData.model_validate(step.result_payload)
        request = CopilotModelExecuteRequest(
            selection_execution_id=data.selection_execution_id,
            copilot_run_id=child.copilot_run_id,
            confirmed_selection_step_id=data.confirmed_selection_step_id,
        )
        intent = dict(step.input_payload)

    try:
        selection_pk, locked, recommendation_request = await _selection(factory, request)
        identity = _execution_identity(request, selection_pk, locked)
        excluded = {"dispatch_status", "execution_status", "training_status"}
        if (
            identity.execution_id != execution_id
            or data.model_dump(exclude=excluded) != identity.model_dump(exclude=excluded)
            or intent.get("selection_step_pk") != str(selection_pk)
            or intent.get("selection_execution_id") != str(request.selection_execution_id)
            or _LockedSelection.model_validate(intent.get("selection")) != locked
        ):
            raise _conflict()
        spec, params = await _preflight(factory, locked, recommendation_request, artifact_root)
    except (AgentDomainError, ValueError) as error:
        data.execution_status = data.training_status = "failed"
        data.training_error = error.code if isinstance(error, AgentDomainError) else _conflict().code
        data.evaluation_status = data.comparison_status = "skipped"
        await _transition_dispatch(factory, data, step_pk, status="FAILED")
        return

    data.execution_status = data.training_status = "running"
    data.dispatch_status = "started"
    if await _transition_dispatch(factory, data, step_pk, status="RUNNING"):
        await _execute_claim(factory, data, selection_pk, locked, spec, params, step_pk, artifact_root)


async def _transition_dispatch(factory, data, step_pk, *, status):
    now = datetime.now(UTC)
    running = status == "RUNNING"
    async with factory() as session:
        claimed = await session.execute(
            update(AgentExecutionSession)
            .where(
                AgentExecutionSession.id == data.execution_id,
                AgentExecutionSession.planner_source == MODEL_DISPATCH_SOURCE,
                AgentExecutionSession.workflow_status == "PLANNED",
            )
            .values(
                workflow_status=status,
                current_step_id=_TOOL if running else None,
                updated_at=now,
                finished_at=None if running else now,
            )
        )
        if claimed.rowcount != 1:
            return False
        changed = await session.execute(
            update(AgentStepRun)
            .where(
                AgentStepRun.id == step_pk,
                AgentStepRun.status == "PENDING",
                AgentStepRun.processing_run_ids[0].as_string().is_(None),
            )
            .values(
                status=status,
                started_at=now if running else None,
                finished_at=None if running else now,
                attempt_count=int(running),
                result_payload=data.model_dump(mode="json"),
            )
        )
        if changed.rowcount != 1:
            return False
        await session.commit()
        return True


async def read_confirmed_model_execution(
    factory: SessionFactory, *, request: CopilotModelExecuteRequest, artifact_root: Path
) -> CopilotModelExecutionData | None:
    selection_pk, locked, _ = await _selection(factory, request)
    return await _replay(
        factory, _execution_identity(request, selection_pk, locked), selection_pk, locked, artifact_root
    )


async def execute_confirmed_model(
    factory: SessionFactory, *, request: CopilotModelExecuteRequest, artifact_root: Path
) -> CopilotModelExecutionData:
    selection_pk, locked, recommendation_request = await _selection(factory, request)
    data = _execution_identity(request, selection_pk, locked)
    existing = await _replay(factory, data, selection_pk, locked, artifact_root)
    if existing is not None:
        return existing
    spec, params = await _preflight(factory, locked, recommendation_request, artifact_root)
    step_pk = await _claim(factory, data, locked, request.copilot_run_id, selection_pk)
    if step_pk is None:
        existing = await _replay(factory, data, selection_pk, locked, artifact_root)
        if existing is None:
            raise _conflict()
        return existing

    return await _execute_claim(factory, data, selection_pk, locked, spec, params, step_pk, artifact_root)


async def _execute_claim(factory, data, selection_pk, locked, spec, params, step_pk, artifact_root):
    try:
        trained = await _fit(
            _linked_factory(factory, step_pk, locked),
            spec,
            params,
            locked.forecast_spec,
            artifact_root,
        )
        async with factory() as session:
            step = await session.get(AgentStepRun, step_pk)
            run = await session.get(ProcessingRun, trained.training_run_id)
            if (
                step.processing_run_ids != [str(trained.training_run_id)]
                or run is None
                or run.status != "succeeded"
                or not _record_matches(run, locked)
                or run.result.get("model_id") != str(trained.model_id)
            ):
                raise RuntimeError("Training result does not match the linked Run")
        data.model_id = trained.model_id
        data.training_run_id = trained.training_run_id
        data.training_status = "succeeded"
        data.manifest_status = trained.manifest_status
        data.training_error = trained.error_code
    except Exception as error:
        recovered = await _replay(
            factory, data, selection_pk, locked, artifact_root, interrupted=True
        )
        if recovered is None:
            raise
        if isinstance(error, _TRAINING_ERRORS):
            recovered.training_error = f"TRAINING_{error.stage.upper()}_{error.outcome.upper()}"
        elif isinstance(error, ValueError) and recovered.training_run_id is None:
            # All four platform adapters reject invalid preflight inputs before inserting a Run.
            recovered.training_status = recovered.execution_status = "failed"
            recovered.training_error = "PLATFORM_TRAINING_REJECTED"
        if recovered.training_status == "failed":
            recovered.evaluation_status = recovered.comparison_status = "skipped"
        await _checkpoint(factory, step_pk, recovered)
        return recovered

    if data.manifest_status != "published" or "validation" not in spec.evaluation.scopes:
        data.evaluation_status = data.comparison_status = "skipped"
        data.evaluation_error = (
            "MANIFEST_NOT_PUBLISHED"
            if data.manifest_status != "published"
            else "VALIDATION_NOT_DECLARED"
        )
    else:
        data.evaluation_status = "running"
        await _checkpoint(factory, step_pk, data)
        try:
            result = await evaluate_saved_model(
                _linked_factory(
                    factory,
                    step_pk,
                    locked,
                    model_id=data.model_id,
                    training_run_id=data.training_run_id,
                ),
                request=ModelEvaluationRequest(model_id=data.model_id, partition="validation"),
                artifact_root=artifact_root,
            )
            if (
                not _evaluation_matches(result, data)
                or await _linked_evaluation_id(factory, step_pk) != result.evaluation_run_id
            ):
                raise RuntimeError("Evaluation result does not match the linked Run")
            data.evaluation_run_id = result.evaluation_run_id
            data.evaluation_status = "succeeded"
            data.evaluation = result
        except ModelEvaluationError as error:
            data.evaluation_status = "failed" if error.outcome == "failed" else "unconfirmed"
            linked_id = await _linked_evaluation_id(factory, step_pk)
            data.evaluation_run_id = linked_id
            data.evaluation_error = f"VALIDATION_{error.stage.upper()}_{error.outcome.upper()}"
        except Exception:
            data.evaluation_status = "unconfirmed"
            data.evaluation_run_id = await _linked_evaluation_id(factory, step_pk)
            data.evaluation_error = "VALIDATION_REQUIRES_RECONCILIATION"
        if data.evaluation_status == "succeeded":
            await _checkpoint(factory, step_pk, data)
            try:
                await _comparison(factory, data, locked, artifact_root)
            except Exception:
                data.comparison = None
                data.comparison_status = "failed"
                data.comparison_reason = "MODEL_COMPARISON_FAILED"
        else:
            data.comparison_status = "skipped"
    data.execution_status = (
        "unconfirmed" if data.evaluation_status == "unconfirmed" else "succeeded"
    )
    await _checkpoint(factory, step_pk, data)
    return data
