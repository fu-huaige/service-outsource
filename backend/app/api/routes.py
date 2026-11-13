import json
from typing import Annotated, Any, TypeVar
from uuid import UUID

from algorithms.agent.llm import LlmUnavailableError
from fastapi import APIRouter, Body, Depends, File, Form, Path, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.db import database_is_ready, get_session, get_session_factory, redis_is_ready
from app.core.errors import AppError
from app.schemas.benchmark import BenchmarkData, BenchmarkRequest
from app.schemas.common import ErrorEnvelope, SuccessEnvelope
from app.schemas.copilot import (
    ArxStructureValidationData,
    ArxStructureValidationRequest,
    CopilotChatData,
    CopilotChatRequest,
    CopilotConfirmData,
    CopilotConfirmRequest,
    CopilotEvaluateModelExecuteData,
    CopilotEvaluateModelExecuteRequest,
    CopilotExecutionSnapshotData,
    CopilotModelExecuteRequest,
    CopilotModelExecutionData,
    CopilotOptimizePipelineExecuteData,
    FeatureSelectionValidationData,
    FeatureSelectionValidationRequest,
    LagOverrideValidationData,
    LagOverrideValidationRequest,
    OptimizePipelineExecuteRequest,
)
from app.schemas.dashboard import DashboardLeaderboardData
from app.schemas.datasets import (
    CollinearitySourceVersionsData,
    DatasetConfigData,
    DatasetConfigRequest,
    DatasetDeleteData,
    DatasetDetail,
    DatasetListData,
    DatasetProfile,
    DatasetUploadData,
    DatasetVersionPreviewData,
    DatasetVersionPreviewPageSize,
    DatasetVersionsData,
    DelaySourceVersionsData,
)
from app.schemas.diagnostics import GeneralizationDiagnosticsData
from app.schemas.model_comparison import ModelComparisonRequest, ModelComparisonResult
from app.schemas.model_evaluation import (
    ModelEvaluationDetail,
    ModelEvaluationHistory,
    ModelEvaluationHistoryQuery,
    ModelEvaluationRequest,
    ModelEvaluationSuccess,
)
from app.schemas.modeling import (
    ArxFitData,
    ArxFitRequest,
)
from app.schemas.optimization import (
    OptimizationStartData,
    OptimizationStartRequest,
    OptimizationStatusData,
)
from app.schemas.pls import (
    EvaluationPartition,
    EvaluationStatus,
    ModelDetailsData,
    ModelSourceSummary,
    PLSEvaluationAPIHistory,
    PLSEvaluationRequest,
    PLSEvaluationResult,
    PLSFitRequest,
    PLSFitResponse,
    PLSModelBasics,
    PLSPredictRequest,
    PLSPredictResponse,
)
from app.schemas.preprocessing import (
    CleanData,
    CleaningVersionCompareChannelsData,
    CleaningVersionCompareData,
    CleanRequest,
    CollinearityData,
    CollinearityRequest,
    DelayData,
    DelayRequest,
    FeatureSelectionApplyRequest,
    LagCompensationRequest,
    SegmentData,
    SegmentRequest,
    VersionApplyData,
)
from app.schemas.reporting import (
    DeliveryStudyListData,
    ExportDatasetData,
    ExportDatasetRequest,
    ReportData,
    ReportRequest,
)
from app.schemas.simulation import SimulationGenerateData, SimulationGenerateRequest
from app.schemas.system import (
    AgentLlmConfigData,
    AgentLlmConfigUpdate,
    AgentLlmConnectionData,
    LivenessData,
    ReadinessData,
    SystemInfoData,
)
from app.schemas.tasks import CancelTaskData
from app.schemas.tcn_platform import (
    MAX_PREDICT_BYTES,
    TCNFitRequest,
    TCNFitResponse,
    TCNManifestRetryRequest,
    TCNPredictRequest,
    TCNPredictResponse,
    TCNPublicationData,
)
from app.schemas.timexer_platform import MAX_PREDICT_BYTES as TIMEXER_MAX_PREDICT_BYTES
from app.schemas.timexer_platform import (
    TimeXerFitRequest,
    TimeXerFitResponse,
    TimeXerManifestRetryRequest,
    TimeXerPredictRequest,
    TimeXerPredictResponse,
    TimeXerPublicationData,
)
from app.schemas.xgboost_platform import (
    XGBoostFitRequest,
    XGBoostFitResponse,
    XGBoostManifestRetryRequest,
    XGBoostPredictRequest,
    XGBoostPredictResponse,
    XGBoostPublicationData,
)
from app.services.agent_arx_modeling_service import (
    ArxStructureError,
    approve_and_execute_arx_step,
    is_arx_fit_step,
    validate_arx_structure,
)
from app.services.agent_execution_service import (
    ExecutionStateError,
    approve_step,
    get_execution,
    reject_step,
    to_copilot_execution_snapshot,
)
from app.services.agent_feature_selection_service import (
    FeatureSelectionError,
    approve_and_execute_feature_step,
    is_feature_apply_step,
    validate_feature_selection,
)
from app.services.agent_lag_apply_service import (
    LagOverrideError,
    approve_and_execute_lag_step,
    is_lag_apply_step,
    validate_lag_overrides,
)
from app.services.agent_model_dispatch_service import dispatch_model_training
from app.services.agent_model_execution_service import (
    execute_confirmed_model,
    model_training_execution_id,
    read_confirmed_model_execution,
)
from app.services.agent_service import (
    AgentDomainError,
    confirm_model_selection,
    continue_agent_execution,
    execute_approved_export_step,
    execute_approved_optimization_step,
    execute_pending_evaluation_step,
    provide_model_spec,
    run_copilot,
)
from app.services.agent_tool_adapter import AgentToolAdapterError
from app.services.benchmark_service import BenchmarkDomainError, run_benchmark
from app.services.cleaning_service import CleaningDomainError, clean_dataset_version
from app.services.cleaning_version_compare_service import (
    CleaningVersionCompareError,
    compare_cleaning_versions,
    get_cleaning_version_compare_channels,
)
from app.services.contract_stubs import completed_task, queued_task
from app.services.dashboard_service import get_dashboard_leaderboard
from app.services.dataset_service import (
    DatasetDomainError,
    configure_dataset_columns,
    delete_dataset_asset,
    get_dataset_detail,
    get_dataset_download,
    get_dataset_version_preview,
    list_dataset_summaries,
    register_simulation_dataset,
    upload_csv_dataset,
)
from app.services.dataset_service import (
    get_dataset_profile as get_dataset_profile_service,
)
from app.services.dataset_service import (
    get_dataset_versions as get_dataset_versions_service,
)
from app.services.generalization_diagnostics_service import get_generalization_diagnostics
from app.services.llm_runtime_config_service import (
    get_agent_llm_config_data,
    reset_agent_llm_config,
    test_agent_llm_connection,
    update_agent_llm_config,
)
from app.services.model_artifact_service import (
    LoadedModelInstance,
    ModelArtifactError,
    load_model_instance,
)
from app.services.model_comparison_service import ModelComparisonError, compare_model_evaluations
from app.services.model_evaluation_service import (
    ModelEvaluationError,
    evaluate_saved_model,
    get_model_evaluation,
    list_model_evaluations,
)
from app.services.model_registry import get_model
from app.services.modeling_service import ModelingDomainError, fit_arx_on_version
from app.services.optimization_service import (
    OptimizationDomainError,
    get_optimization_status,
    start_optimization_study,
)
from app.services.pls_evaluation_service import (
    PLSEvaluationError,
    evaluate_saved_pls_model,
    list_pls_evaluations,
)
from app.services.pls_modeling_service import SavedPLSModel
from app.services.pls_training_service import (
    PLSTrainingError,
    SessionFactory,
    fit_pls_with_manifest,
)
from app.services.preprocessing_analysis_service import (
    AnalysisDomainError,
    get_collinearity_source_versions,
    get_delay_source_versions,
    get_latest_collinearity_result,
    get_latest_delay_result,
    run_collinearity_analysis,
    run_delay_estimation,
)
from app.services.report_service import (
    ReportDomainError,
    export_optimised_dataset,
    generate_report,
    get_export_artifact,
    list_delivery_studies,
)
from app.services.segment_service import SegmentDomainError, select_dynamic_segments
from app.services.simulation_service import generate_simulation as generate_simulation_service
from app.services.tcn_modeling_service import TCNModel
from app.services.tcn_platform_adapter import (
    TCNTrainingError,
    fit_tcn_on_version,
    retry_tcn_manifest,
)
from app.services.timexer_modeling_service import TimeXerModel
from app.services.timexer_platform_adapter import (
    TimeXerTrainingError,
    fit_timexer_on_version,
    predict_saved_timexer,
    retry_timexer_manifest,
)
from app.services.version_data import VersionDataError
from app.services.versioned_preprocessing_service import (
    VersionedPreprocessingError,
    apply_feature_selection,
    apply_lag_compensation,
)
from app.services.xgboost_artifact_service import SavedXGBoostModel
from app.services.xgboost_platform_adapter import (
    XGBoostTrainingError,
    fit_xgboost_on_version,
    retry_xgboost_manifest,
)

router = APIRouter()
DataT = TypeVar("DataT")
DatasetId = Annotated[UUID, Path(description="数据集 UUID。")]

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorEnvelope, "description": "请求参数或领域规则无效。"},
    404: {"model": ErrorEnvelope, "description": "目标资源不存在。"},
    422: {"model": ErrorEnvelope, "description": "请求体或路径参数未通过 Pydantic 校验。"},
    500: {"model": ErrorEnvelope, "description": "未预期的服务端错误。"},
}


def success(request: Request, data: DataT) -> SuccessEnvelope[DataT]:
    """Return the only success envelope used by every v1 endpoint."""

    return SuccessEnvelope(data=data, request_id=UUID(request.state.request_id))


@router.get(
    "/health/live",
    tags=["System"],
    summary="Liveness probe",
    response_model=SuccessEnvelope[LivenessData],
    responses=ERROR_RESPONSES,
)
async def health_live(request: Request) -> SuccessEnvelope[LivenessData]:
    return success(request, LivenessData())


@router.get(
    "/health/ready",
    tags=["System"],
    summary="Readiness probe for PostgreSQL and Redis",
    response_model=SuccessEnvelope[ReadinessData],
    responses={
        **ERROR_RESPONSES,
        503: {"model": ErrorEnvelope, "description": "PostgreSQL 或 Redis 尚不可用。"},
    },
)
async def health_ready(request: Request) -> SuccessEnvelope[ReadinessData]:
    database_ready, redis_ready = await database_is_ready(), await redis_is_ready()
    if not database_ready or not redis_ready:
        raise AppError(
            "SYSTEM_NOT_READY",
            "系统依赖尚未就绪",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            details={"database": database_ready, "redis": redis_ready},
        )
    return success(request, ReadinessData())


@router.get(
    "/system/info",
    tags=["System"],
    summary="Get service and contract metadata",
    response_model=SuccessEnvelope[SystemInfoData],
    responses=ERROR_RESPONSES,
)
async def system_info(request: Request) -> SuccessEnvelope[SystemInfoData]:
    settings = get_settings()
    return success(
        request,
        SystemInfoData(version=settings.app_version, environment=settings.app_env),
    )


@router.get(
    "/system/agent-config",
    tags=["System"],
    summary="Get the effective Agent LLM configuration without exposing its API key",
    response_model=SuccessEnvelope[AgentLlmConfigData],
    responses=ERROR_RESPONSES,
)
async def get_agent_config(request: Request) -> SuccessEnvelope[AgentLlmConfigData]:
    return success(request, get_agent_llm_config_data())


@router.put(
    "/system/agent-config",
    tags=["System"],
    summary="Apply a process-local Agent LLM configuration",
    response_model=SuccessEnvelope[AgentLlmConfigData],
    responses=ERROR_RESPONSES,
)
async def update_agent_config(
    request: Request, payload: AgentLlmConfigUpdate
) -> SuccessEnvelope[AgentLlmConfigData]:
    return success(request, update_agent_llm_config(payload))


@router.delete(
    "/system/agent-config",
    tags=["System"],
    summary="Discard the process-local Agent LLM configuration",
    response_model=SuccessEnvelope[AgentLlmConfigData],
    responses=ERROR_RESPONSES,
)
async def reset_agent_config(request: Request) -> SuccessEnvelope[AgentLlmConfigData]:
    return success(request, reset_agent_llm_config())


@router.post(
    "/system/agent-config/test",
    tags=["System"],
    summary="Send a minimal completion to the effective Agent model service",
    response_model=SuccessEnvelope[AgentLlmConnectionData],
    responses={
        **ERROR_RESPONSES,
        502: {"model": ErrorEnvelope, "description": "模型服务不可用或配置无效。"},
    },
)
async def test_agent_config(request: Request) -> SuccessEnvelope[AgentLlmConnectionData]:
    try:
        result = await run_in_threadpool(test_agent_llm_connection)
    except LlmUnavailableError as error:
        raise AppError(
            "LLM_CONNECTION_FAILED",
            "模型服务连接失败",
            status_code=status.HTTP_502_BAD_GATEWAY,
            details={"reason": str(error)},
        ) from error
    return success(request, result)


@router.get(
    "/dashboard/leaderboard",
    tags=["Dashboard"],
    summary="List real completed optimisation studies ranked by validation free-run FIT",
    response_model=SuccessEnvelope[DashboardLeaderboardData],
    responses=ERROR_RESPONSES,
)
async def dashboard_leaderboard(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[DashboardLeaderboardData]:
    return success(request, await get_dashboard_leaderboard(session))


@router.post(
    "/simulation/generate",
    tags=["Simulation"],
    summary="Generate and register an S1-S6 benchmark dataset",
    status_code=status.HTTP_201_CREATED,
    response_model=SuccessEnvelope[SimulationGenerateData],
    responses=ERROR_RESPONSES,
)
async def generate_simulation(
    request: Request,
    payload: SimulationGenerateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[SimulationGenerateData]:
    generated = generate_simulation_service(payload, artifact_root=get_settings().artifact_root)
    try:
        registered = await register_simulation_dataset(
            session,
            generated=generated,
            request=payload,
            artifact_root=get_settings().artifact_root,
        )
    except DatasetDomainError as error:
        raise AppError(error.code, error.message, status_code=error.status_code, details=error.details) from error
    return success(request, registered)


@router.post(
    "/datasets/upload",
    tags=["Datasets"],
    summary="Upload a CSV dataset for asynchronous parsing",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SuccessEnvelope[DatasetUploadData],
    responses={**ERROR_RESPONSES, 413: {"model": ErrorEnvelope, "description": "文件超过限制。"}},
)
async def upload_dataset(
    request: Request,
    file: Annotated[UploadFile, File(description="CSV 文件。")],
    session: Annotated[AsyncSession, Depends(get_session)],
    name: Annotated[str | None, Form(max_length=120)] = None,
) -> SuccessEnvelope[DatasetUploadData]:
    """Synchronously validate a CSV while retaining the phase-1 async response envelope."""

    try:
        uploaded = await upload_csv_dataset(
            session,
            upload=file,
            display_name=name,
            artifact_root=get_settings().artifact_root,
        )
    except DatasetDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=413 if error.code == "DATASET_FILE_TOO_LARGE" else error.status_code,
            details=error.details,
        ) from error
    return success(
        request,
        DatasetUploadData(
            dataset=uploaded.summary,
            parse_task=completed_task(
                stage="parse_upload",
                message="CSV 已完成校验、持久化和质量画像计算。",
            ),
            deduplicated=uploaded.deduplicated,
        ),
    )


@router.get(
    "/datasets",
    tags=["Datasets"],
    summary="List datasets",
    response_model=SuccessEnvelope[DatasetListData],
    responses=ERROR_RESPONSES,
)
async def list_datasets(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SuccessEnvelope[DatasetListData]:
    return success(request, await list_dataset_summaries(session, page=page, page_size=page_size))


@router.post(
    "/datasets/{dataset_id}/config",
    tags=["Datasets"],
    summary="Confirm time/input/output column roles and recompute the profile",
    response_model=SuccessEnvelope[DatasetConfigData],
    responses=ERROR_RESPONSES,
)
async def configure_dataset(
    request: Request,
    dataset_id: DatasetId,
    payload: DatasetConfigRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[DatasetConfigData]:
    try:
        data = await configure_dataset_columns(
            session,
            dataset_id=dataset_id,
            payload=payload,
            artifact_root=get_settings().artifact_root,
        )
    except DatasetDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.get(
    "/datasets/{dataset_id}",
    tags=["Datasets"],
    summary="Get a dataset and its parsed column metadata",
    response_model=SuccessEnvelope[DatasetDetail],
    responses=ERROR_RESPONSES,
)
async def get_dataset(
    request: Request,
    dataset_id: DatasetId,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[DatasetDetail]:
    try:
        data = await get_dataset_detail(
            session,
            dataset_id=dataset_id,
            artifact_root=get_settings().artifact_root,
        )
    except DatasetDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.get(
    "/datasets/{dataset_id}/download",
    tags=["Datasets"],
    summary="Download the active or explicitly requested immutable CSV version",
    responses={404: {"model": ErrorEnvelope, "description": "数据集或 CSV 产物不存在。"}},
)
async def download_dataset(
    dataset_id: DatasetId,
    session: Annotated[AsyncSession, Depends(get_session)],
    version_id: Annotated[UUID | None, Query(description="可选的 DatasetVersion UUID。")] = None,
) -> FileResponse:
    try:
        path, filename = await get_dataset_download(
            session, dataset_id=dataset_id, version_id=version_id, artifact_root=get_settings().artifact_root
        )
    except DatasetDomainError as error:
        raise AppError(
            error.code, error.message, status_code=error.status_code, details=error.details
        ) from error
    return FileResponse(path, media_type="text/csv", filename=filename)


@router.delete(
    "/datasets/{dataset_id}",
    tags=["Datasets"],
    summary="Cascade-delete a dataset's database records",
    response_model=SuccessEnvelope[DatasetDeleteData],
    responses=ERROR_RESPONSES,
)
async def delete_dataset(
    request: Request,
    dataset_id: DatasetId,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[DatasetDeleteData]:
    try:
        await delete_dataset_asset(session, dataset_id=dataset_id)
    except DatasetDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, DatasetDeleteData(dataset_id=dataset_id))


@router.get(
    "/datasets/{dataset_id}/profile",
    tags=["Datasets"],
    summary="Get the quality profile for the active dataset version",
    response_model=SuccessEnvelope[DatasetProfile],
    responses=ERROR_RESPONSES,
)
async def get_dataset_profile(
    request: Request,
    dataset_id: DatasetId,
    session: Annotated[AsyncSession, Depends(get_session)],
    version_id: Annotated[UUID | None, Query(description="可选的 DatasetVersion UUID。")] = None,
) -> SuccessEnvelope[DatasetProfile]:
    try:
        data = await get_dataset_profile_service(
            session, dataset_id=dataset_id, version_id=version_id
        )
    except DatasetDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.get(
    "/datasets/{dataset_id}/versions",
    tags=["Datasets"],
    summary="Get the immutable data-version lineage DAG",
    response_model=SuccessEnvelope[DatasetVersionsData],
    responses=ERROR_RESPONSES,
)
async def get_dataset_versions(
    request: Request,
    dataset_id: DatasetId,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[DatasetVersionsData]:
    try:
        data = await get_dataset_versions_service(
            session,
            dataset_id=dataset_id,
            artifact_root=get_settings().artifact_root,
        )
    except DatasetDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.post(
    "/preprocessing/clean",
    tags=["Preprocessing"],
    summary="Queue time alignment, interpolation and anomaly cleaning",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SuccessEnvelope[CleanData],
    responses=ERROR_RESPONSES,
)
async def clean_data(
    request: Request,
    payload: CleanRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[CleanData]:
    """Run the real cleaning pipeline and register an immutable derived version."""

    try:
        data = await clean_dataset_version(
            session,
            payload=payload,
            artifact_root=get_settings().artifact_root,
        )
    except CleaningDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.post(
    "/preprocessing/segment",
    tags=["Preprocessing"],
    summary="Queue dynamic-response segment identification",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SuccessEnvelope[SegmentData],
    responses=ERROR_RESPONSES,
)
async def segment_data(
    request: Request,
    payload: SegmentRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[SegmentData]:
    """Gate candidate windows on quality, then select by D-optimal information gain."""

    try:
        data = await select_dynamic_segments(
            session,
            payload=payload,
            artifact_root=get_settings().artifact_root,
        )
    except SegmentDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.post(
    "/preprocessing/delay",
    tags=["Preprocessing"],
    summary="Queue multi-variable lag-correlation analysis",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SuccessEnvelope[DelayData],
    responses=ERROR_RESPONSES,
)
async def estimate_delay(
    request: Request,
    payload: DelayRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[DelayData]:
    """Prewhitened cross-correlation candidates, refined on the validation split."""

    try:
        data = await run_delay_estimation(
            session,
            payload=payload,
            artifact_root=get_settings().artifact_root,
        )
    except AnalysisDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.get(
    "/datasets/{dataset_id}/delay-sources",
    tags=["Datasets"],
    summary="List Cleaning versions and their persisted delay-analysis states",
    response_model=SuccessEnvelope[DelaySourceVersionsData],
    responses=ERROR_RESPONSES,
)
async def get_delay_sources(
    request: Request,
    dataset_id: DatasetId,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[DelaySourceVersionsData]:
    """Read-only selector data; this endpoint never runs or persists analysis."""

    try:
        data = await get_delay_source_versions(session, dataset_id=dataset_id)
    except AnalysisDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.get(
    "/datasets/{dataset_id}/collinearity-sources",
    tags=["Datasets"],
    summary="List Lag Compensation versions and their persisted collinearity-analysis states",
    response_model=SuccessEnvelope[CollinearitySourceVersionsData],
    responses=ERROR_RESPONSES,
)
async def get_collinearity_sources(
    request: Request,
    dataset_id: DatasetId,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[CollinearitySourceVersionsData]:
    """Read-only selector data; this endpoint never runs or persists analysis."""

    try:
        data = await get_collinearity_source_versions(session, dataset_id=dataset_id)
    except AnalysisDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.get(
    "/preprocessing/delay/latest",
    tags=["Preprocessing"],
    summary="Load the latest complete persisted lag-correlation analysis",
    response_model=SuccessEnvelope[DelayData],
    responses=ERROR_RESPONSES,
)
async def get_latest_delay(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    version_id: Annotated[UUID, Query(description="源 DatasetVersion UUID。")],
    dataset_id: Annotated[UUID | None, Query(description="可选的 Dataset UUID 校验。")] = None,
) -> SuccessEnvelope[DelayData]:
    """Read a persisted delay result; this endpoint never re-runs analysis."""

    try:
        data = await get_latest_delay_result(
            session,
            version_id=version_id,
            dataset_id=dataset_id,
        )
    except AnalysisDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.get(
    "/datasets/{dataset_id}/versions/{version_id}/preview",
    tags=["Datasets"],
    summary="Get a paginated preview of one immutable dataset version",
    response_model=SuccessEnvelope[DatasetVersionPreviewData],
    responses=ERROR_RESPONSES,
)
async def get_dataset_version_preview_page(
    request: Request,
    dataset_id: DatasetId,
    version_id: Annotated[UUID, Path(description="DatasetVersion UUID。")],
    session: Annotated[AsyncSession, Depends(get_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[
        DatasetVersionPreviewPageSize, Query()
    ] = DatasetVersionPreviewPageSize.ROWS_100,
) -> SuccessEnvelope[DatasetVersionPreviewData]:
    try:
        data = await get_dataset_version_preview(
            session,
            dataset_id=dataset_id,
            version_id=version_id,
            page=page,
            page_size=int(page_size),
            artifact_root=get_settings().artifact_root,
        )
    except DatasetDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.get(
    "/datasets/{dataset_id}/cleaning-version-compare/channels",
    tags=["Datasets"],
    summary="List common numeric channels for two Cleaning-eligible versions",
    response_model=SuccessEnvelope[CleaningVersionCompareChannelsData],
    responses={
        **ERROR_RESPONSES,
        409: {"model": ErrorEnvelope, "description": "Artifact integrity conflict。"},
    },
)
async def list_cleaning_version_compare_channels(
    request: Request,
    dataset_id: DatasetId,
    session: Annotated[AsyncSession, Depends(get_session)],
    baseline_version_id: Annotated[UUID, Query(description="Baseline DatasetVersion UUID。")],
    compare_version_id: Annotated[UUID, Query(description="Compare DatasetVersion UUID。")],
) -> SuccessEnvelope[CleaningVersionCompareChannelsData]:
    try:
        data = await get_cleaning_version_compare_channels(
            session,
            dataset_id=dataset_id,
            baseline_version_id=baseline_version_id,
            compare_version_id=compare_version_id,
            artifact_root=get_settings().artifact_root,
        )
    except CleaningVersionCompareError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.get(
    "/datasets/{dataset_id}/cleaning-version-compare",
    tags=["Datasets"],
    summary="Compare two immutable Cleaning-eligible dataset versions",
    response_model=SuccessEnvelope[CleaningVersionCompareData],
    responses={
        **ERROR_RESPONSES,
        409: {"model": ErrorEnvelope, "description": "Artifact integrity or lineage conflict。"},
    },
)
async def get_clean_version_compare(
    request: Request,
    dataset_id: DatasetId,
    session: Annotated[AsyncSession, Depends(get_session)],
    baseline_version_id: Annotated[UUID, Query(description="Baseline DatasetVersion UUID。")],
    compare_version_id: Annotated[UUID, Query(description="Compare DatasetVersion UUID。")],
    channel: Annotated[str, Query(min_length=1, max_length=255)],
    max_points: Annotated[int, Query(ge=2, le=10_000)] = 10_000,
) -> SuccessEnvelope[CleaningVersionCompareData]:
    try:
        data = await compare_cleaning_versions(
            session,
            dataset_id=dataset_id,
            baseline_version_id=baseline_version_id,
            compare_version_id=compare_version_id,
            channel=channel,
            max_points=max_points,
            artifact_root=get_settings().artifact_root,
        )
    except CleaningVersionCompareError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.post(
    "/preprocessing/delay/apply",
    tags=["Preprocessing"],
    summary="Apply confirmed lag compensation and create an immutable DatasetVersion",
    status_code=status.HTTP_201_CREATED,
    response_model=SuccessEnvelope[VersionApplyData],
    responses=ERROR_RESPONSES,
)
async def apply_delay_compensation(
    request: Request,
    payload: LagCompensationRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[VersionApplyData]:
    try:
        data = await apply_lag_compensation(
            session, payload=payload, artifact_root=get_settings().artifact_root
        )
    except VersionedPreprocessingError as error:
        raise AppError(error.code, error.message, status_code=error.status_code, details=error.details) from error
    return success(request, data)


@router.get(
    "/preprocessing/collinearity/latest",
    tags=["Preprocessing"],
    summary="Load the latest complete persisted collinearity analysis",
    response_model=SuccessEnvelope[CollinearityData],
    responses=ERROR_RESPONSES,
)
async def get_latest_collinearity(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    version_id: Annotated[UUID, Query(description="源 DatasetVersion UUID。")],
    dataset_id: Annotated[UUID | None, Query(description="可选的 Dataset UUID 校验。")] = None,
) -> SuccessEnvelope[CollinearityData]:
    """Read a persisted collinearity result; this endpoint never recomputes it."""

    try:
        data = await get_latest_collinearity_result(
            session,
            version_id=version_id,
            dataset_id=dataset_id,
        )
    except AnalysisDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.post(
    "/preprocessing/collinearity",
    tags=["Preprocessing"],
    summary="Queue Pearson and VIF collinearity diagnostics",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SuccessEnvelope[CollinearityData],
    responses=ERROR_RESPONSES,
)
async def analyze_collinearity(
    request: Request,
    payload: CollinearityRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[CollinearityData]:
    """Pearson, Spearman, VIF and condition number with advisory recommendations."""

    try:
        data = await run_collinearity_analysis(
            session,
            payload=payload,
            artifact_root=get_settings().artifact_root,
        )
    except AnalysisDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.post(
    "/preprocessing/features/apply",
    tags=["Preprocessing"],
    summary="Drop confirmed redundant inputs and create an immutable DatasetVersion",
    status_code=status.HTTP_201_CREATED,
    response_model=SuccessEnvelope[VersionApplyData],
    responses=ERROR_RESPONSES,
)
async def apply_features(
    request: Request,
    payload: FeatureSelectionApplyRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[VersionApplyData]:
    try:
        data = await apply_feature_selection(
            session, payload=payload, artifact_root=get_settings().artifact_root
        )
    except VersionedPreprocessingError as error:
        raise AppError(error.code, error.message, status_code=error.status_code, details=error.details) from error
    return success(request, data)


@router.post(
    "/modeling/arx/fit",
    tags=["Modeling"],
    summary="Run MISO ARX identification and chronological partitioned evaluation",
    response_model=SuccessEnvelope[ArxFitData],
    responses=ERROR_RESPONSES,
)
async def fit_arx(
    request: Request,
    payload: ArxFitRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[ArxFitData]:
    """Identify ARX only on trusted Lag lineage and apply the formal model checks."""

    try:
        data = await fit_arx_on_version(
            session,
            payload=payload,
            artifact_root=get_settings().artifact_root,
            require_lag_provenance=True,
        )
    except ModelingDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.post(
    "/optimization/optuna/start",
    tags=["Optimization"],
    summary="Start a cancellable Optuna pipeline-optimization study",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SuccessEnvelope[OptimizationStartData],
    responses=ERROR_RESPONSES,
)
async def start_optimization(
    request: Request,
    payload: OptimizationStartRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[OptimizationStartData]:
    """Run the closed loop: gate, select, identify, score on free-run FIT, repeat."""

    try:
        data = await start_optimization_study(
            session,
            payload=payload,
            artifact_root=get_settings().artifact_root,
        )
    except OptimizationDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.get(
    "/optimization/optuna/{study_id}/status",
    tags=["Optimization"],
    summary="Get Optuna trial progress, convergence curve and parameter importance",
    response_model=SuccessEnvelope[OptimizationStatusData],
    responses=ERROR_RESPONSES,
)
async def optimization_status(
    request: Request,
    study_id: Annotated[UUID, Path(description="Optuna study UUID。")],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[OptimizationStatusData]:
    try:
        data = await get_optimization_status(session, study_id=study_id)
    except OptimizationDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.get(
    "/optimization/optuna/{study_id}/diagnostics",
    tags=["Optimization"],
    summary="Replay the validation-selected winner for read-only generalization diagnostics",
    response_model=SuccessEnvelope[GeneralizationDiagnosticsData],
    responses=ERROR_RESPONSES,
)
async def optimization_diagnostics(
    request: Request,
    study_id: Annotated[UUID, Path(description="Optuna study UUID。")],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[GeneralizationDiagnosticsData]:
    """Inspect the fixed winner without running a new Optuna trial or changing the study."""

    try:
        data = await get_generalization_diagnostics(
            session, study_id=study_id, artifact_root=get_settings().artifact_root
        )
    except OptimizationDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.post(
    "/tasks/{task_id}/cancel",
    tags=["Tasks"],
    summary="Request cooperative cancellation of an asynchronous task",
    response_model=SuccessEnvelope[CancelTaskData],
    responses=ERROR_RESPONSES,
)
async def cancel_task(
    request: Request, task_id: Annotated[UUID, Path(description="后台任务 UUID。")]
) -> SuccessEnvelope[CancelTaskData]:
    return success(
        request,
        CancelTaskData(task_id=task_id, task=queued_task(status="cancelled", stage="cancelled")),
    )


@router.post(
    "/copilot/chat",
    tags=["Copilot"],
    summary="Create a validated, whitelisted copilot execution-plan DAG",
    response_model=SuccessEnvelope[CopilotChatData],
    responses=ERROR_RESPONSES,
)
async def copilot_chat(
    request: Request,
    payload: CopilotChatRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[CopilotChatData]:
    """Plan from natural language, verify statically, then execute whitelisted tools."""

    try:
        data = await run_copilot(
            session,
            payload=payload,
            artifact_root=get_settings().artifact_root,
        )
    except AgentDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.get(
    "/copilot/executions/{execution_id}",
    tags=["Copilot"],
    summary="Read one persisted copilot execution snapshot",
    response_model=SuccessEnvelope[CopilotExecutionSnapshotData],
    responses=ERROR_RESPONSES,
)
async def get_copilot_execution(
    request: Request,
    execution_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[CopilotExecutionSnapshotData]:
    """Return durable execution state without dispatching a tool or mutating workflow state."""

    try:
        execution = await get_execution(session, execution_id=execution_id)
    except ExecutionStateError as error:
        raise AppError(
            "AGENT_EXECUTION_NOT_FOUND",
            "未找到指定的 Agent 执行记录。",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"execution_id": str(execution_id)},
        ) from error
    return success(request, to_copilot_execution_snapshot(execution))

@router.post(
    "/copilot/arx-structure/validate",
    tags=["Copilot"],
    summary="Validate controlled ARX na/nb overrides without persisting a model",
    response_model=SuccessEnvelope[ArxStructureValidationData],
    responses={**ERROR_RESPONSES, 409: {"model": ErrorEnvelope}},
)
async def validate_copilot_arx_structure(
    request: Request,
    payload: ArxStructureValidationRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[ArxStructureValidationData]:
    try:
        data = await validate_arx_structure(
            session,
            execution_id=payload.execution_id,
            step_id=payload.step_id,
            manual_overrides=payload.manual_overrides,
            artifact_root=get_settings().artifact_root,
        )
    except ExecutionStateError as error:
        raise AppError(
            "AGENT_EXECUTION_STATE_CONFLICT",
            "当前执行步骤不可校验 ARX 结构。",
            status_code=status.HTTP_409_CONFLICT,
            details={"reason": str(error)},
        ) from error
    except ArxStructureError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)

@router.post(
    "/copilot/feature-selection/validate",
    tags=["Copilot"],
    summary="Validate a controlled Feature Selection without executing a tool",
    response_model=SuccessEnvelope[FeatureSelectionValidationData],
    responses={**ERROR_RESPONSES, 409: {"model": ErrorEnvelope}},
)
async def validate_copilot_feature_selection(
    request: Request,
    payload: FeatureSelectionValidationRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[FeatureSelectionValidationData]:
    try:
        data = await validate_feature_selection(
            session,
            execution_id=payload.execution_id,
            step_id=payload.step_id,
            drop_columns=payload.drop_columns,
        )
    except ExecutionStateError as error:
        raise AppError(
            "AGENT_EXECUTION_STATE_CONFLICT",
            "当前执行步骤不可校验变量选择。",
            status_code=status.HTTP_409_CONFLICT,
            details={"reason": str(error)},
        ) from error
    except FeatureSelectionError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.post(
    "/copilot/lag-overrides/validate",
    tags=["Copilot"],
    summary="Validate controlled manual lag overrides without executing a tool",
    response_model=SuccessEnvelope[LagOverrideValidationData],
    responses={**ERROR_RESPONSES, 409: {"model": ErrorEnvelope}},
)
async def validate_copilot_lag_overrides(
    request: Request,
    payload: LagOverrideValidationRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[LagOverrideValidationData]:
    try:
        data = await validate_lag_overrides(
            session,
            execution_id=payload.execution_id,
            step_id=payload.step_id,
            manual_overrides=payload.manual_overrides,
        )
    except ExecutionStateError as error:
        raise AppError(
            "AGENT_EXECUTION_STATE_CONFLICT",
            "当前执行步骤不可校验时滞覆盖。",
            status_code=status.HTTP_409_CONFLICT,
            details={"reason": str(error)},
        ) from error
    except LagOverrideError as error:
        raise AppError(error.code, error.message, status_code=error.status_code, details=error.details) from error
    return success(request, data)


@router.post(
    "/copilot/confirm",
    tags=["Copilot"],
    summary="Persist a human confirmation decision for an Agent execution step",
    response_model=SuccessEnvelope[CopilotConfirmData],
    responses={
        **ERROR_RESPONSES,
        409: {"model": ErrorEnvelope, "description": "执行状态不允许该确认操作。"},
    },
)
async def copilot_confirm(
    request: Request,
    payload: CopilotConfirmRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> SuccessEnvelope[CopilotConfirmData]:
    if payload.execution_id is None or payload.step_id is None:
        raise AppError(
            "AGENT_EXECUTION_REFERENCE_REQUIRED",
            "持久确认需要 execution_id 和 step_id。",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    validation: LagOverrideValidationData | None = None
    feature_validation: FeatureSelectionValidationData | None = None
    arx_validation: ArxStructureValidationData | None = None
    resume_after_confirmation = False
    try:
        current = await get_execution(session, execution_id=payload.execution_id)
        is_model_selection = any(
            step.step_id == payload.step_id and step.tool_name == "confirm_model_selection"
            for step in current.step_runs
        )
        is_spec_gate = any(
            step.step_id == payload.step_id
            and step.tool_name == "recommend_models"
            and step.requires_confirmation
            for step in current.step_runs
        )
        if payload.dispatch_training and (not is_model_selection or not payload.approved):
            raise AgentDomainError(
                "MODEL_TRAINING_AUTHORIZATION_INVALID", "训练授权仅用于批准模型选择。", status_code=422
            )
        if is_spec_gate and payload.approved:
            execution = await provide_model_spec(
                session, payload=payload, execution=current, artifact_root=get_settings().artifact_root
            )
        elif payload.recommendation_request is not None or payload.row_order_confirmation is not None:
            raise AgentDomainError(
                "MODEL_SPEC_STEP_REQUIRED", "实验契约必须提交到对应推荐步骤。", status_code=422
            )
        elif is_model_selection:
            execution = await confirm_model_selection(
                session,
                payload=payload,
                execution=current,
                artifact_root=get_settings().artifact_root,
            )
            if payload.dispatch_training:
                selection_pk = next(step.id for step in execution.step_runs if step.step_id == payload.step_id)
                async with factory() as dispatch_session:
                    await dispatch_model_training(
                        dispatch_session, execution_id=model_training_execution_id(selection_pk)
                    )
        elif payload.model_selection is not None:
            raise AgentDomainError(
                "MODEL_SELECTION_STEP_REQUIRED", "模型选择必须提交到对应确认步骤。", status_code=422
            )
        elif not payload.approved:
            execution = await reject_step(
                session, execution_id=payload.execution_id, step_id=payload.step_id
            )
        elif await is_lag_apply_step(
            session, execution_id=payload.execution_id, step_id=payload.step_id
        ):
            outcome = await approve_and_execute_lag_step(
                session,
                execution_id=payload.execution_id,
                step_id=payload.step_id,
                manual_overrides=payload.manual_overrides,
                warning_acknowledged=payload.warning_acknowledged,
                artifact_root=get_settings().artifact_root,
            )
            execution, validation = outcome.execution, outcome.validation
            resume_after_confirmation = True
        elif await is_feature_apply_step(
            session, execution_id=payload.execution_id, step_id=payload.step_id
        ):
            feature_outcome = await approve_and_execute_feature_step(
                session,
                execution_id=payload.execution_id,
                step_id=payload.step_id,
                drop_columns=payload.feature_drop_columns,
                artifact_root=get_settings().artifact_root,
            )
            execution = feature_outcome.execution
            feature_validation = feature_outcome.validation
            resume_after_confirmation = True
        elif await is_arx_fit_step(
            session, execution_id=payload.execution_id, step_id=payload.step_id
        ):
            arx_outcome = await approve_and_execute_arx_step(
                session,
                execution_id=payload.execution_id,
                step_id=payload.step_id,
                manual_overrides=payload.arx_structure_overrides,
                artifact_root=get_settings().artifact_root,
            )
            execution = arx_outcome.execution
            arx_validation = arx_outcome.validation
            resume_after_confirmation = True
        else:
            execution = await approve_step(
                session, execution_id=payload.execution_id, step_id=payload.step_id
            )
            approved_step = next(
                item for item in execution.step_runs if item.step_id == payload.step_id
            )
            if approved_step.tool_name == "optimize_pipeline":
                execution = await execute_approved_optimization_step(
                    session,
                    execution_id=execution.id,
                    artifact_root=get_settings().artifact_root,
                )
                resume_after_confirmation = True
            elif approved_step.tool_name == "export_dataset":
                execution = await execute_approved_export_step(
                    session,
                    execution_id=execution.id,
                    step_id=approved_step.step_id,
                    artifact_root=get_settings().artifact_root,
                )
                resume_after_confirmation = True
        if resume_after_confirmation:
            execution = await continue_agent_execution(
                session,
                execution_id=execution.id,
                artifact_root=get_settings().artifact_root,
            )
    except ExecutionStateError as error:
        raise AppError(
            "AGENT_EXECUTION_STATE_CONFLICT",
            "当前执行状态不允许该确认操作。",
            status_code=status.HTTP_409_CONFLICT,
            details={"reason": str(error)},
        ) from error
    except (LagOverrideError, FeatureSelectionError, ArxStructureError, AgentDomainError) as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    except (AgentToolAdapterError, VersionDataError, VersionedPreprocessingError) as error:
        raise AppError(
            getattr(error, "code", "AGENT_CONFIRMED_TOOL_FAILED"),
            getattr(error, "message", str(error)),
            status_code=getattr(error, "status_code", status.HTTP_400_BAD_REQUEST),
            details=getattr(error, "details", {}),
        ) from error

    step = next(item for item in execution.step_runs if item.step_id == payload.step_id)
    return success(
        request,
        CopilotConfirmData(
            copilot_run_id=payload.copilot_run_id,
            confirmation_id=payload.confirmation_id,
            decision="approved" if payload.approved else "rejected",
            execution_id=execution.id,
            workflow_status=execution.workflow_status,
            current_version_id=execution.current_version_id,
            current_step_id=execution.current_step_id,
            pending_confirmation_step_id=execution.pending_confirmation_step_id,
            step_id=step.step_id,
            step_status=step.status,
            confirmation_status=step.confirmation_status,
            result_version_id=step.result_version_id,
            result_payload=step.result_payload,
            lag_override_validation=validation,
            feature_selection_validation=feature_validation,
            arx_structure_validation=arx_validation,
        ),
    )
@router.post(
    "/copilot/modeling/execute",
    tags=["Copilot"],
    response_model=SuccessEnvelope[CopilotModelExecutionData],
    responses={**ERROR_RESPONSES, 409: {"model": ErrorEnvelope}},
)
async def execute_copilot_modeling(
    request: Request,
    payload: CopilotModelExecuteRequest,
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> SuccessEnvelope[CopilotModelExecutionData]:
    try:
        result = await execute_confirmed_model(
            factory, request=payload, artifact_root=get_settings().artifact_root
        )
    except AgentDomainError as error:
        raise AppError(
            error.code, error.message, status_code=error.status_code, details=error.details
        ) from error
    return success(request, result)


@router.get(
    "/copilot/modeling/execution",
    tags=["Copilot"],
    response_model=SuccessEnvelope[CopilotModelExecutionData | None],
    responses={**ERROR_RESPONSES, 409: {"model": ErrorEnvelope}},
)
async def get_copilot_modeling_execution(
    request: Request,
    query: Annotated[CopilotModelExecuteRequest, Query()],
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> SuccessEnvelope[CopilotModelExecutionData | None]:
    try:
        result = await read_confirmed_model_execution(
            factory, request=query, artifact_root=get_settings().artifact_root
        )
    except AgentDomainError as error:
        raise AppError(
            error.code, error.message, status_code=error.status_code, details=error.details
        ) from error
    return success(request, result)


@router.post(
    "/copilot/optimize-pipeline/execute",
    tags=["Copilot"],
    summary="Execute the approved agent optimization step",
    response_model=SuccessEnvelope[CopilotOptimizePipelineExecuteData],
    responses={
        **ERROR_RESPONSES,
        409: {"model": ErrorEnvelope, "description": "执行状态不允许模型寻优。"},
    },
)
async def execute_copilot_optimize_pipeline(
    request: Request,
    payload: OptimizePipelineExecuteRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[CopilotOptimizePipelineExecuteData]:
    """Execute exactly one already-approved optimize_pipeline step synchronously."""

    try:
        execution = await execute_approved_optimization_step(
            session,
            execution_id=payload.execution_id,
            artifact_root=get_settings().artifact_root,
        )
        if execution.workflow_status == "RUNNING":
            execution = await continue_agent_execution(
                session,
                execution_id=execution.id,
                artifact_root=get_settings().artifact_root,
            )
    except ExecutionStateError as error:
        raise AppError(
            "AGENT_EXECUTION_STATE_CONFLICT",
            "当前执行状态不允许模型寻优。",
            status_code=status.HTTP_409_CONFLICT,
            details={"reason": str(error)},
        ) from error
    except AgentDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error

    step = next(item for item in execution.step_runs if item.tool_name == "optimize_pipeline")
    return success(
        request,
        CopilotOptimizePipelineExecuteData(
            execution_id=execution.id,
            workflow_status=execution.workflow_status,
            current_version_id=execution.current_version_id,
            step_id=step.step_id,
            step_status=step.status,
            result_payload=step.result_payload,
            error_code=step.error_code,
            error_message=step.error_message,
            processing_run_ids=step.processing_run_ids,
        ),
    )

@router.post(
    "/copilot/evaluate-model/execute",
    tags=["Copilot"],
    summary="Execute the pending saved-model evaluation step",
    response_model=SuccessEnvelope[CopilotEvaluateModelExecuteData],
    responses={
        **ERROR_RESPONSES,
        409: {"model": ErrorEnvelope, "description": "执行状态不允许模型评价。"},
    },
)
async def execute_copilot_evaluate_model(
    request: Request,
    payload: CopilotEvaluateModelExecuteRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[CopilotEvaluateModelExecuteData]:
    try:
        execution = await execute_pending_evaluation_step(session, execution_id=payload.execution_id, artifact_root=get_settings().artifact_root)
        if execution.workflow_status == "RUNNING":
            execution = await continue_agent_execution(
                session,
                execution_id=execution.id,
                artifact_root=get_settings().artifact_root,
            )
    except ExecutionStateError as error:
        raise AppError("AGENT_EXECUTION_STATE_CONFLICT", "当前执行状态不允许模型评价。", status_code=status.HTTP_409_CONFLICT, details={"reason": str(error)}) from error
    except AgentDomainError as error:
        raise AppError(error.code, error.message, status_code=error.status_code, details=error.details) from error

    step = next(item for item in execution.step_runs if item.tool_name == "evaluate_model")
    return success(request, CopilotEvaluateModelExecuteData(
        execution_id=execution.id,
        workflow_status=execution.workflow_status,
        current_version_id=execution.current_version_id,
        step_id=step.step_id,
        step_status=step.status,
        result_payload=step.result_payload,
        error_code=step.error_code,
        error_message=step.error_message,
        processing_run_ids=step.processing_run_ids,
    ))

@router.post(
    "/reports/generate",
    tags=["Delivery"],
    summary="Generate a provenance-bound report where every number cites its run",
    response_model=SuccessEnvelope[ReportData],
    responses=ERROR_RESPONSES,
)
async def generate_report_route(
    request: Request,
    payload: ReportRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[ReportData]:
    """Compose from persisted runs; a draft with a bare numeral is rejected, not rendered."""

    try:
        data = await generate_report(
            session,
            payload=payload,
            artifact_root=get_settings().artifact_root,
        )
    except ReportDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.get(
    "/delivery/studies",
    tags=["Delivery"],
    summary="List successful Studies with a strictly verifiable Best result",
    response_model=SuccessEnvelope[DeliveryStudyListData],
    responses=ERROR_RESPONSES,
)
async def delivery_studies_route(
    request: Request,
    dataset_id: Annotated[UUID, Query()],
    version_id: Annotated[UUID, Query()],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[DeliveryStudyListData]:
    data = await list_delivery_studies(
        session,
        dataset_id=dataset_id,
        version_id=version_id,
        artifact_root=get_settings().artifact_root,
    )
    return success(request, data)


@router.post(
    "/delivery/export",
    tags=["Delivery"],
    summary="Export the closed-loop selected rows as CSV plus a provenance manifest",
    response_model=SuccessEnvelope[ExportDatasetData],
    responses=ERROR_RESPONSES,
)
async def export_dataset_route(
    request: Request,
    payload: ExportDatasetRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[ExportDatasetData]:
    try:
        data = await export_optimised_dataset(
            session,
            payload=payload,
            artifact_root=get_settings().artifact_root,
        )
    except ReportDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.get(
    "/delivery/exports/{export_id}/csv",
    tags=["Delivery"],
    summary="Download a persisted optimised dataset CSV",
    responses={404: {"model": ErrorEnvelope, "description": "导出记录或 CSV 不存在。"}},
)
async def download_export_csv(
    export_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FileResponse:
    try:
        path, filename, media_type = await get_export_artifact(
            session,
            export_id=export_id,
            artifact_root=get_settings().artifact_root,
            kind="csv",
        )
    except ReportDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return FileResponse(path, media_type=media_type, filename=filename)


@router.get(
    "/delivery/exports/{export_id}/manifest",
    tags=["Delivery"],
    summary="Download a persisted optimised dataset provenance manifest",
    responses={404: {"model": ErrorEnvelope, "description": "导出记录或 Manifest 不存在。"}},
)
async def download_export_manifest(
    export_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FileResponse:
    try:
        path, filename, media_type = await get_export_artifact(
            session,
            export_id=export_id,
            artifact_root=get_settings().artifact_root,
            kind="manifest",
        )
    except ReportDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return FileResponse(path, media_type=media_type, filename=filename)


@router.post(
    "/benchmark/run",
    tags=["Delivery"],
    summary="Run the built-in ablation suite and return freshly measured results",
    response_model=SuccessEnvelope[BenchmarkData],
    responses=ERROR_RESPONSES,
)
async def run_benchmark_route(
    request: Request,
    payload: BenchmarkRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[BenchmarkData]:
    """Every number is computed during this request; nothing is cached or hard-coded."""

    try:
        data = await run_benchmark(
            session,
            payload=payload,
            artifact_root=get_settings().artifact_root,
        )
    except BenchmarkDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


# PLS endpoints reuse the existing router, envelopes and domain services.
def _pls_http_error(error: Exception, *, operation: str) -> AppError:
    details = {}
    root = error
    seen = set()
    while root.__cause__ is not None and id(root) not in seen:
        seen.add(id(root))
        root = root.__cause__
    if isinstance(error, (PLSTrainingError, PLSEvaluationError)):
        details = {"model_id": str(error.model_id), "stage": error.stage, "outcome": error.outcome}
        key = "training_run_id" if isinstance(error, PLSTrainingError) else "evaluation_run_id"
        details[key] = str(getattr(error, key))
        if error.outcome != "failed":
            return AppError(
                "PLS_OPERATION_UNCONFIRMED",
                "操作结果需要核对，请使用原运行 ID 查询。",
                status_code=503,
                details=details,
            )
    # Preserve typed artifact distinctions rather than treating corruption as absence.
    candidate = error if isinstance(error, ModelArtifactError) else error.__cause__
    if isinstance(candidate, ModelArtifactError):
        code = candidate.code
        http = (
            404
            if code in ("PAYLOAD_MISSING", "TRAINING_RUN_MISSING")
            else (
                409
                if code
                in (
                    "MANIFEST_NOT_PUBLISHED",
                    "TRAINING_RUN_NOT_SUCCEEDED",
                    "TRAINING_RUN_ID_MISMATCH",
                    "MODEL_ID_MISMATCH",
                    "MODEL_TYPE_MISMATCH",
                    "DATASET_VERSION_MISMATCH",
                    "MANIFEST_CONFLICT",
                )
                else 422
            )
        )
        return AppError(code, "模型清单或训练来源校验失败。", status_code=http, details=details)
    if isinstance(error, ModelingDomainError):
        return AppError(error.code, error.message, status_code=error.status_code, details=details)
    if isinstance(error, VersionDataError):
        return AppError(error.code, error.message, status_code=error.status_code, details=details)
    text = str(root) if isinstance(root, ValueError) else ""
    if "Model payload is missing" in text or "MODEL_ARTIFACT_NOT_FOUND" in text:
        return AppError("MODEL_NOT_FOUND", "指定模型不存在。", status_code=404, details=details)
    if "partition was not declared" in text:
        return AppError(
            "PLS_EVALUATION_SCOPE_NOT_ALLOWED",
            "训练契约未声明该评价分区。",
            status_code=409,
            details=details,
        )
    if "assertion mismatch" in text:
        return AppError(
            "PLS_SOURCE_MISMATCH", "评价来源与原模型不一致。", status_code=409, details=details
        )
    if isinstance(error, (PLSTrainingError, PLSEvaluationError)):
        client_error = isinstance(root, ValueError)
        return AppError(
            "PLS_OPERATION_REJECTED" if client_error else "PLS_OPERATION_FAILED",
            "PLS 操作未完成，请根据运行 ID 核对记录。",
            status_code=400 if client_error else 500,
            details=details,
        )
    if isinstance(error, ValueError):
        return AppError(
            "PLS_INPUT_INVALID" if operation in ("predict", "fit") else "MODEL_ARTIFACT_INVALID",
            "输入不符合模型要求。" if operation in ("predict", "fit") else "模型数据无法通过校验。",
            status_code=400 if operation in ("predict", "fit") else 422,
            details=details,
        )
    return AppError("PLS_OPERATION_FAILED", "PLS 操作失败。", status_code=500, details=details)


async def _api_load_model(
    session: AsyncSession, model_id: UUID, *, expected_model_type: str | None = None
) -> LoadedModelInstance:
    try:
        return await load_model_instance(
            session,
            model_id=model_id,
            artifact_root=get_settings().artifact_root,
            expected_model_type=expected_model_type,
        )
    except (ValueError, ModelingDomainError, VersionDataError) as error:
        raise _pls_http_error(error, operation="load") from error


def _model_details(instance: LoadedModelInstance) -> ModelDetailsData:
    manifest = instance.manifest
    definition = get_model(instance.model_type_id)
    if isinstance(instance.payload, SavedPLSModel):
        metadata = instance.payload.metadata
        spec = metadata.provenance.experiment_spec
        dataset_id, version_id = spec.dataset_id, spec.dataset_version_id
        names, target = metadata.feature_names, metadata.target_name
        additional = {
            "artifact_version": metadata.artifact_version,
            "parameters": metadata.parameters,
            "requested_n_components": metadata.requested_n_components,
            "effective_n_components": metadata.effective_n_components,
            "training_rows": metadata.training_rows,
        }
    elif isinstance(instance.payload, TimeXerModel):
        if manifest is None:
            raise AppError("MANIFEST_NOT_PUBLISHED", "模型清单尚未发布。", status_code=409)
        metadata_timexer = instance.payload.metadata
        spec = manifest.experiment_spec
        dataset_id, version_id = spec.dataset_id, spec.dataset_version_id
        names = metadata_timexer.exogenous_feature_names
        target = metadata_timexer.target_name
        additional = {
            "artifact_version": 1,
            "training_rows": metadata_timexer.training_samples,
            "parameters": metadata_timexer.parameters,
        }
    elif isinstance(instance.payload, TCNModel):
        if manifest is None:
            raise AppError("MANIFEST_NOT_PUBLISHED", "模型清单尚未发布。", status_code=409)
        metadata_tcn = instance.payload.metadata
        spec = manifest.experiment_spec
        dataset_id, version_id = spec.dataset_id, spec.dataset_version_id
        names, target = metadata_tcn.feature_names, metadata_tcn.target_name
        additional = {"artifact_version": 1, "training_rows": metadata_tcn.training_samples}
    elif isinstance(instance.payload, SavedXGBoostModel):
        if manifest is None:
            raise AppError("MANIFEST_NOT_PUBLISHED", "模型清单尚未发布。", status_code=409)
        metadata_xgboost = instance.payload.metadata
        spec = manifest.experiment_spec
        dataset_id, version_id = spec.dataset_id, spec.dataset_version_id
        names, target = metadata_xgboost.feature_names, metadata_xgboost.target_name
        additional = {
            "artifact_version": metadata_xgboost.artifact_version,
            "training_rows": metadata_xgboost.training_rows,
        }
    else:
        saved = instance.payload
        dataset_id, version_id = saved.dataset_id, saved.source_version_id
        names, target = tuple(saved.payload.input_columns), saved.payload.output_column
        additional = {}
    return ModelDetailsData(
        model_id=instance.model_id,
        model_type=instance.model_type_id,
        training_run_id=instance.training_run_id,
        source=ModelSourceSummary(
            dataset_id=dataset_id,
            dataset_version_id=version_id,
            dataset_sha256=manifest.experiment_spec.dataset_version_sha256 if manifest else None,
            experiment_spec_hash=manifest.experiment_spec_hash if manifest else None,
        ),
        feature_names=names,
        target_name=target,
        implementation_id=manifest.implementation_id if manifest else None,
        implementation_version=manifest.implementation_version if manifest else None,
        execution_scope=definition.execution_scope,
        manifest_version=manifest.manifest_version if manifest else None,
        training_status="succeeded" if instance.training_run_id else "unknown",
        provenance_status="incomplete" if instance.missing_provenance else "verified",
        missing_provenance=instance.missing_provenance,
        **additional,
    )


async def _parse_pls_predict(body: Annotated[Any, Body()]) -> PLSPredictRequest:
    # Local validation avoids reflecting non-JSON NaN/Inf in the global error envelope.
    try:
        return PLSPredictRequest.model_validate(body)
    except ValidationError as error:
        issues = [
            {"loc": list(e["loc"]), "type": e["type"], "msg": e["msg"]} for e in error.errors()
        ]
        raise AppError(
            "REQUEST_VALIDATION_FAILED",
            "预测请求参数校验失败。",
            status_code=422,
            details={"issues": issues},
        ) from error


@router.post(
    "/modeling/pls/fit",
    tags=["Modeling"],
    response_model=SuccessEnvelope[PLSFitResponse],
    responses=ERROR_RESPONSES,
)
async def fit_pls_api(
    request: Request,
    payload: PLSFitRequest,
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
):
    try:
        outcome = await fit_pls_with_manifest(
            factory,
            spec=payload.experiment_spec,
            parameters=payload.parameters,
            artifact_root=get_settings().artifact_root,
        )
    except (ValueError, VersionDataError) as error:
        raise _pls_http_error(error, operation="fit") from error
    failed = outcome.manifest_status == "failed"
    spec = payload.experiment_spec
    return success(
        request,
        PLSFitResponse(
            model_id=outcome.model_id,
            training_run_id=outcome.training_run_id,
            training_status=outcome.training_status,
            manifest_status=outcome.manifest_status,
            model_info=PLSModelBasics(
                dataset_id=spec.dataset_id,
                dataset_version_id=spec.dataset_version_id,
                feature_names=spec.input_columns,
                target_name=spec.target_column,
                parameters=payload.parameters,
            ),
            manifest_retryable=failed,
            retry_model_id=outcome.model_id if failed else None,
            retry_action="publish_existing_model_manifest" if failed else None,
            error_code=outcome.error_code,
            error_message="训练已成功，清单发布失败；请使用原 model_id 重试清单发布，勿重新训练。"
            if failed
            else None,
        ),
    )


@router.get(
    "/models/{model_id}",
    tags=["Modeling"],
    response_model=SuccessEnvelope[ModelDetailsData],
    responses=ERROR_RESPONSES,
)
async def model_details_api(
    request: Request, model_id: UUID, session: Annotated[AsyncSession, Depends(get_session)]
):
    instance = await _api_load_model(session, model_id)
    return success(request, _model_details(instance))


@router.post(
    "/modeling/pls/predict",
    tags=["Modeling"],
    response_model=SuccessEnvelope[PLSPredictResponse],
    responses=ERROR_RESPONSES,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": PLSPredictRequest.model_json_schema()}},
        }
    },
)
async def predict_pls_api(
    request: Request,
    payload: Annotated[PLSPredictRequest, Depends(_parse_pls_predict)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    instance = await _api_load_model(session, payload.model_id)
    if instance.model_type_id != "pls" or not isinstance(instance.payload, SavedPLSModel):
        raise AppError("MODEL_TYPE_MISMATCH", "固定 PLS 预测仅接受 PLS 模型。", status_code=409)
    try:
        predicted = await run_in_threadpool(
            instance.payload.predict, payload.X, feature_names=payload.feature_names
        )
    except ValueError as error:
        raise _pls_http_error(error, operation="predict") from error
    return success(
        request,
        PLSPredictResponse(
            model_id=instance.model_id,
            predictions=tuple(predicted.tolist()),
            sample_count=len(predicted),
        ),
    )


@router.post(
    "/modeling/pls/evaluate",
    tags=["Modeling"],
    response_model=SuccessEnvelope[PLSEvaluationResult],
    responses=ERROR_RESPONSES,
)
async def evaluate_pls_api(
    request: Request,
    payload: PLSEvaluationRequest,
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
):
    try:
        result = await evaluate_saved_pls_model(
            factory, request=payload, artifact_root=get_settings().artifact_root
        )
    except (ValueError, VersionDataError) as error:
        raise _pls_http_error(error, operation="evaluate") from error
    return success(request, result)


@router.get(
    "/modeling/pls/evaluations",
    tags=["Modeling"],
    response_model=SuccessEnvelope[PLSEvaluationAPIHistory],
    responses=ERROR_RESPONSES,
)
async def pls_evaluation_history_api(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    model_id: UUID,
    partition: Annotated[EvaluationPartition | None, Query()] = None,
    evaluation_status: Annotated[EvaluationStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    result = await list_pls_evaluations(
        session,
        model_id=model_id,
        partition=partition,
        status=evaluation_status,
        limit=limit,
        offset=offset,
    )
    return success(request, PLSEvaluationAPIHistory.model_validate(result.model_dump()))


def _model_evaluation_http_error(error: ModelEvaluationError) -> AppError | None:
    details = {
        "model_id": str(error.model_id),
        "evaluation_run_id": str(error.evaluation_run_id),
        "stage": error.stage,
        "outcome": error.outcome,
    }
    if error.outcome == "unconfirmed":
        return AppError(
            "MODEL_EVALUATION_UNCONFIRMED",
            "评价结果需要核对，请使用原评价运行 ID 查询。",
            status_code=503,
            details=details,
        )
    cause = error.__cause__
    if isinstance(cause, (ModelArtifactError, VersionDataError, ModelingDomainError)) or (
        error.stage == "load_model" and isinstance(cause, ValueError)
    ):
        mapped = _pls_http_error(cause, operation="load")
        mapped.details.update(details)
        return mapped
    if isinstance(cause, ValueError):
        if error.stage == "read_data":
            return AppError(
                "DATASET_VERSION_MISMATCH",
                "评价数据版本无法通过校验。",
                status_code=409,
                details=details,
            )
        if error.stage == "resolve_rows" and str(cause) == (
            "Evaluation partition was not declared in the training Spec"
        ):
            return AppError(
                "MODEL_EVALUATION_SCOPE_NOT_ALLOWED",
                "训练契约未声明该评价分区。",
                status_code=409,
                details=details,
            )
        return AppError(
            "MODEL_EVALUATION_REJECTED",
            "评价数据或模型预测无法通过校验。",
            status_code=422,
            details=details,
        )
    return None


@router.post(
    "/modeling/evaluate",
    tags=["Modeling"],
    response_model=SuccessEnvelope[ModelEvaluationSuccess],
    responses={**ERROR_RESPONSES, 409: {"model": ErrorEnvelope}, 503: {"model": ErrorEnvelope}},
)
async def evaluate_model_api(
    request: Request,
    payload: ModelEvaluationRequest,
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
):
    try:
        result = await evaluate_saved_model(
            factory, request=payload, artifact_root=get_settings().artifact_root
        )
    except ModelEvaluationError as error:
        mapped = _model_evaluation_http_error(error)
        if mapped is None:
            raise
        raise mapped from error
    return success(request, result)


@router.get(
    "/modeling/evaluations",
    tags=["Modeling"],
    response_model=SuccessEnvelope[ModelEvaluationHistory],
    responses=ERROR_RESPONSES,
)
async def model_evaluation_history_api(
    request: Request,
    query: Annotated[ModelEvaluationHistoryQuery, Query()],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    return success(request, await list_model_evaluations(session, query))


@router.get(
    "/modeling/evaluations/{evaluation_run_id}",
    tags=["Modeling"],
    response_model=SuccessEnvelope[ModelEvaluationDetail],
    responses=ERROR_RESPONSES,
)
async def model_evaluation_detail_api(
    request: Request,
    evaluation_run_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
):
    result = await get_model_evaluation(session, evaluation_run_id)
    if result is None:
        raise AppError("MODEL_EVALUATION_NOT_FOUND", "指定评价记录不存在。", status_code=404)
    return success(request, result)


@router.post(
    "/modeling/compare",
    tags=["Modeling"],
    response_model=SuccessEnvelope[ModelComparisonResult],
    responses={**ERROR_RESPONSES, 409: {"model": ErrorEnvelope}},
)
async def compare_models_api(
    request: Request,
    payload: ModelComparisonRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
):
    try:
        result = await compare_model_evaluations(
            session, request=payload, artifact_root=get_settings().artifact_root
        )
    except ModelComparisonError as error:
        message = (
            "指定评价记录不存在。"
            if error.status_code == 404
            else f"评价记录无法比较，请核对字段 {error.field}。"
        )
        raise AppError(
            error.code,
            message,
            status_code=error.status_code,
            details={"evaluation_run_id": str(error.run_id), "field": error.field},
        ) from error
    return success(request, result)


def _xgboost_http_error(error: Exception) -> AppError:
    if isinstance(error, XGBoostTrainingError):
        details = {
            "model_id": str(error.model_id),
            "training_run_id": str(error.training_run_id),
            "stage": error.stage,
            "outcome": error.outcome,
        }
        if error.outcome == "unconfirmed":
            return AppError(
                "XGBOOST_OPERATION_UNCONFIRMED",
                "请使用原训练运行 ID 核对结果。",
                status_code=503,
                details=details,
            )
        return AppError(
            "XGBOOST_TRAINING_FAILED",
            "XGBoost 训练失败。",
            status_code=422 if isinstance(error.__cause__, ValueError) else 500,
            details=details,
        )
    if isinstance(error, ModelArtifactError):
        return _pls_http_error(error, operation="load")
    if isinstance(error, (OSError, SQLAlchemyError)):
        return AppError("XGBOOST_SERVICE_UNAVAILABLE", "XGBoost 服务暂不可用。", status_code=503)
    return AppError("XGBOOST_INPUT_INVALID", "输入不符合 XGBoost 模型要求。", status_code=422)


@router.post(
    "/modeling/xgboost/fit",
    tags=["Modeling"],
    response_model=SuccessEnvelope[XGBoostFitResponse],
    responses=ERROR_RESPONSES,
)
async def fit_xgboost_api(
    request: Request,
    payload: XGBoostFitRequest,
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
):
    try:
        outcome = await fit_xgboost_on_version(
            factory,
            spec=payload.experiment_spec,
            parameters=payload.parameters,
            artifact_root=get_settings().artifact_root,
        )
    except (ValueError, VersionDataError, OSError, SQLAlchemyError) as error:
        raise _xgboost_http_error(error) from error
    return success(request, outcome)


async def _parse_xgboost_predict(body: Annotated[Any, Body()]) -> XGBoostPredictRequest:
    try:
        return XGBoostPredictRequest.model_validate(body)
    except ValidationError as error:
        issues = [
            {"loc": list(item["loc"]), "type": item["type"], "msg": item["msg"]}
            for item in error.errors()
        ]
        raise AppError(
            "REQUEST_VALIDATION_FAILED",
            "预测请求参数校验失败。",
            status_code=422,
            details={"issues": issues},
        ) from error


@router.post(
    "/modeling/xgboost/predict",
    tags=["Modeling"],
    response_model=SuccessEnvelope[XGBoostPredictResponse],
    responses=ERROR_RESPONSES,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": XGBoostPredictRequest.model_json_schema()}},
        }
    },
)
async def predict_xgboost_api(
    request: Request,
    payload: Annotated[XGBoostPredictRequest, Depends(_parse_xgboost_predict)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    instance = await _api_load_model(session, payload.model_id, expected_model_type="xgboost")
    if not isinstance(instance.payload, SavedXGBoostModel):
        raise AppError("MODEL_TYPE_MISMATCH", "固定预测需要 XGBoost 模型。", status_code=409)
    try:
        predicted = await run_in_threadpool(
            instance.payload.predict, payload.X, feature_names=payload.feature_names
        )
    except ValueError as error:
        raise _xgboost_http_error(error) from error
    return success(
        request,
        XGBoostPredictResponse(
            model_id=instance.model_id,
            predictions=tuple(predicted.tolist()),
            sample_count=len(predicted),
        ),
    )


@router.post(
    "/modeling/xgboost/{model_id}/manifest/retry",
    tags=["Modeling"],
    response_model=SuccessEnvelope[XGBoostPublicationData],
    responses=ERROR_RESPONSES,
)
async def retry_xgboost_manifest_api(
    request: Request,
    model_id: UUID,
    payload: XGBoostManifestRetryRequest,
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
):
    try:
        outcome = await retry_xgboost_manifest(
            factory,
            model_id=model_id,
            training_run_id=payload.training_run_id,
            artifact_root=get_settings().artifact_root,
        )
    except (ValueError, VersionDataError, OSError, SQLAlchemyError) as error:
        raise _xgboost_http_error(error) from error
    return success(request, outcome)


def _tcn_http_error(error: Exception) -> AppError:
    if isinstance(error, TCNTrainingError):
        details = {
            "model_id": str(error.model_id),
            "training_run_id": str(error.training_run_id),
            "stage": error.stage,
            "outcome": error.outcome,
        }
        if error.outcome == "unconfirmed":
            return AppError(
                "TCN_OPERATION_UNCONFIRMED",
                "请使用原训练运行 ID 核对结果。",
                status_code=503,
                details=details,
            )
        return AppError(
            "TCN_TRAINING_FAILED",
            "TCN 训练失败。",
            status_code=422 if isinstance(error.__cause__, ValueError) else 500,
            details=details,
        )
    if isinstance(error, ModelArtifactError):
        return _pls_http_error(error, operation="load")
    if isinstance(error, (OSError, SQLAlchemyError)):
        return AppError("TCN_SERVICE_UNAVAILABLE", "TCN 服务暂不可用。", status_code=503)
    return AppError("TCN_INPUT_INVALID", "输入不符合 TCN 模型要求。", status_code=422)


@router.post(
    "/modeling/tcn/fit",
    tags=["Modeling"],
    response_model=SuccessEnvelope[TCNFitResponse],
    responses=ERROR_RESPONSES,
)
async def fit_tcn_api(
    request: Request,
    payload: TCNFitRequest,
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
):
    try:
        outcome = await fit_tcn_on_version(
            factory,
            spec=payload.experiment_spec,
            parameters=payload.parameters,
            artifact_root=get_settings().artifact_root,
        )
    except (ValueError, VersionDataError, OSError, SQLAlchemyError) as error:
        raise _tcn_http_error(error) from error
    return success(request, outcome)


async def _parse_tcn_predict(request: Request) -> TCNPredictRequest:
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_PREDICT_BYTES:
            raise AppError("TCN_PREDICT_BODY_TOO_LARGE", "TCN 预测请求体过大。", status_code=413)
        body.extend(chunk)
    try:
        return TCNPredictRequest.model_validate(json.loads(body))
    except (ValueError, RecursionError) as error:
        raise AppError(
            "REQUEST_VALIDATION_FAILED", "TCN 预测请求参数校验失败。", status_code=422
        ) from error


@router.post(
    "/modeling/tcn/predict",
    tags=["Modeling"],
    response_model=SuccessEnvelope[TCNPredictResponse],
    responses=ERROR_RESPONSES,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": TCNPredictRequest.model_json_schema()}},
        }
    },
)
async def predict_tcn_api(
    request: Request,
    payload: Annotated[TCNPredictRequest, Depends(_parse_tcn_predict)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    instance = await _api_load_model(session, payload.model_id, expected_model_type="tcn")
    if not isinstance(instance.payload, TCNModel):
        raise AppError("MODEL_TYPE_MISMATCH", "固定预测需要 TCN 模型。", status_code=409)
    try:
        predicted = await run_in_threadpool(
            instance.payload.predict, payload.X, feature_names=payload.feature_names
        )
    except ValueError as error:
        raise _tcn_http_error(error) from error
    return success(
        request,
        TCNPredictResponse(
            model_id=instance.model_id,
            predictions=tuple(predicted.tolist()),
            sample_count=len(predicted),
        ),
    )


@router.post(
    "/modeling/tcn/{model_id}/manifest/retry",
    tags=["Modeling"],
    response_model=SuccessEnvelope[TCNPublicationData],
    responses=ERROR_RESPONSES,
)
async def retry_tcn_manifest_api(
    request: Request,
    model_id: UUID,
    payload: TCNManifestRetryRequest,
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
):
    try:
        outcome = await retry_tcn_manifest(
            factory,
            model_id=model_id,
            training_run_id=payload.training_run_id,
            artifact_root=get_settings().artifact_root,
        )
    except (ValueError, VersionDataError, OSError, SQLAlchemyError) as error:
        raise _tcn_http_error(error) from error
    return success(request, outcome)


def _timexer_http_error(error: Exception) -> AppError:
    if isinstance(error, TimeXerTrainingError):
        details = {
            "model_id": str(error.model_id),
            "training_run_id": str(error.training_run_id),
            "stage": error.stage,
            "outcome": error.outcome,
        }
        if error.outcome == "unconfirmed":
            return AppError(
                "TIMEXER_OPERATION_UNCONFIRMED",
                "请使用原训练运行 ID 核对结果。",
                status_code=503,
                details=details,
            )
        return AppError(
            "TIMEXER_TRAINING_FAILED",
            "TimeXer 训练失败。",
            status_code=422 if isinstance(error.__cause__, ValueError) else 500,
            details=details,
        )
    if isinstance(error, ModelArtifactError):
        return _pls_http_error(error, operation="load")
    if isinstance(error, (OSError, SQLAlchemyError)):
        return AppError("TIMEXER_SERVICE_UNAVAILABLE", "TimeXer 服务暂不可用。", status_code=503)
    return AppError("TIMEXER_INPUT_INVALID", "输入不符合 TimeXer 模型要求。", status_code=422)


@router.post(
    "/modeling/timexer/fit",
    tags=["Modeling"],
    response_model=SuccessEnvelope[TimeXerFitResponse],
    responses=ERROR_RESPONSES,
)
async def fit_timexer_api(
    request: Request,
    payload: TimeXerFitRequest,
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
):
    try:
        outcome = await fit_timexer_on_version(
            factory,
            spec=payload.experiment_spec,
            parameters=payload.parameters,
            forecast_spec=payload.forecast_spec,
            artifact_root=get_settings().artifact_root,
        )
    except (ValueError, VersionDataError, OSError, SQLAlchemyError) as error:
        raise _timexer_http_error(error) from error
    return success(request, outcome)


async def _parse_timexer_predict(request: Request) -> TimeXerPredictRequest:
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > TIMEXER_MAX_PREDICT_BYTES:
            raise AppError(
                "TIMEXER_PREDICT_BODY_TOO_LARGE", "TimeXer 预测请求体过大。", status_code=413
            )
        body.extend(chunk)
    try:
        return TimeXerPredictRequest.model_validate(json.loads(body))
    except (ValueError, RecursionError) as error:
        raise AppError(
            "REQUEST_VALIDATION_FAILED", "TimeXer 预测请求参数校验失败。", status_code=422
        ) from error


@router.post(
    "/modeling/timexer/predict",
    tags=["Modeling"],
    response_model=SuccessEnvelope[TimeXerPredictResponse],
    responses=ERROR_RESPONSES,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": TimeXerPredictRequest.model_json_schema()}},
        }
    },
)
async def predict_timexer_api(
    request: Request,
    payload: Annotated[TimeXerPredictRequest, Depends(_parse_timexer_predict)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    instance = await _api_load_model(session, payload.model_id, expected_model_type="timexer")
    if not isinstance(instance.payload, TimeXerModel):
        raise AppError("MODEL_TYPE_MISMATCH", "固定预测需要 TimeXer 模型。", status_code=409)
    try:
        predicted = await run_in_threadpool(
            predict_saved_timexer,
            instance.payload,
            payload.X_target,
            payload.X_exogenous,
            target_name=payload.target_name,
            exogenous_names=payload.exogenous_names,
        )
    except ValueError as error:
        raise _timexer_http_error(error) from error
    return success(
        request,
        TimeXerPredictResponse(
            model_id=instance.model_id,
            predictions=tuple(tuple(row) for row in predicted.tolist()),
            sample_count=len(predicted),
        ),
    )


@router.post(
    "/modeling/timexer/{model_id}/manifest/retry",
    tags=["Modeling"],
    response_model=SuccessEnvelope[TimeXerPublicationData],
    responses=ERROR_RESPONSES,
)
async def retry_timexer_manifest_api(
    request: Request,
    model_id: UUID,
    payload: TimeXerManifestRetryRequest,
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
):
    try:
        outcome = await retry_timexer_manifest(
            factory,
            model_id=model_id,
            training_run_id=payload.training_run_id,
            artifact_root=get_settings().artifact_root,
        )
    except (ValueError, VersionDataError, OSError, SQLAlchemyError) as error:
        raise _timexer_http_error(error) from error
    return success(request, outcome)
