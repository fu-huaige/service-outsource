"""Narrow bridge from persisted Agent steps to formal domain services."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_execution import AgentExecutionSession, AgentStepRun
from app.schemas.preprocessing import CleanRequest, DelayRequest, LagCompensationRequest
from app.services.cleaning_service import clean_dataset_version
from app.services.preprocessing_analysis_service import run_delay_estimation
from app.services.version_data import VersionDataError, load_version_series
from app.services.versioned_preprocessing_service import apply_lag_compensation


class AgentToolAdapterError(Exception):
    """A planner payload cannot be mapped to the supported formal tool contract."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class AgentToolResult:
    """Formal service provenance normalized for one persistent Agent step."""

    summary: str
    source_version_id: UUID
    result_version_id: UUID | None
    processing_run_ids: list[str]
    result_payload: dict[str, Any]


_CLEANING_PARAMETER_NAMES = frozenset(CleanRequest.model_fields) - {"version_id", "dataset_id"}
_DELAY_PARAMETER_NAMES = frozenset({"max_lag", "top_k"})
_LAG_PARAMETER_NAMES = frozenset({"lag_map", "user_confirmed", "recommendation_source", "evidence_summary"})


async def execute_agent_tool(
    session: AsyncSession,
    *,
    execution: AgentExecutionSession,
    step: AgentStepRun,
    parameters: dict[str, Any],
    artifact_root: Path,
) -> AgentToolResult:
    """Execute only supported formal tools against the execution's current version."""

    if step.tool_name == "clean_data":
        return await _clean(
            session,
            execution=execution,
            parameters=parameters,
            artifact_root=artifact_root,
        )
    if step.tool_name == "estimate_delays":
        return await _estimate_delays(
            session,
            execution=execution,
            parameters=parameters,
            artifact_root=artifact_root,
        )
    if step.tool_name == "apply_lag_compensation":
        return await _apply_lag_compensation(
            session,
            execution=execution,
            parameters=parameters,
            artifact_root=artifact_root,
        )
    raise AgentToolAdapterError(
        "UNSUPPORTED_AGENT_TOOL",
        f"Agent Tool Adapter 本轮不支持工具：{step.tool_name}",
    )


def _validated_parameters(
    parameters: dict[str, Any], *, allowed: frozenset[str], tool_name: str
) -> dict[str, Any]:
    unexpected = sorted(set(parameters) - allowed)
    if unexpected:
        raise AgentToolAdapterError(
            "INVALID_AGENT_TOOL_PARAMETERS",
            f"{tool_name} 收到未映射的计划参数：{', '.join(unexpected)}",
        )
    return dict(parameters)


async def _clean(
    session: AsyncSession,
    *,
    execution: AgentExecutionSession,
    parameters: dict[str, Any],
    artifact_root: Path,
) -> AgentToolResult:
    try:
        payload = CleanRequest(
            version_id=execution.current_version_id,
            dataset_id=execution.dataset_id,
            **_validated_parameters(
                parameters, allowed=_CLEANING_PARAMETER_NAMES, tool_name="clean_data"
            ),
        )
    except ValidationError as error:
        raise AgentToolAdapterError("INVALID_AGENT_TOOL_PARAMETERS", str(error)) from error

    data = await clean_dataset_version(session, payload=payload, artifact_root=artifact_root)
    return AgentToolResult(
        summary=(
            f"正式清洗服务已生成不可变版本 {data.derived_version_id}，"
            f"共处理 {data.total_cleaned_points} 个数据点。"
        ),
        source_version_id=data.source_version_id,
        result_version_id=data.derived_version_id,
        processing_run_ids=[str(data.processing_run_id)] if data.processing_run_id else [],
        result_payload=data.model_dump(mode="json"),
    )


async def _estimate_delays(
    session: AsyncSession,
    *,
    execution: AgentExecutionSession,
    parameters: dict[str, Any],
    artifact_root: Path,
) -> AgentToolResult:
    try:
        series = await load_version_series(
            session,
            version_id=execution.current_version_id,
            dataset_id=execution.dataset_id,
            artifact_root=artifact_root,
        )
        input_columns, output_column = series.resolve_columns(
            input_columns=None, output_column=None
        )
    except VersionDataError:
        raise

    try:
        payload = DelayRequest(
            version_id=execution.current_version_id,
            dataset_id=execution.dataset_id,
            input_columns=input_columns,
            output_column=output_column,
            **_validated_parameters(
                parameters,
                allowed=_DELAY_PARAMETER_NAMES,
                tool_name="estimate_delays",
            ),
        )
    except ValidationError as error:
        raise AgentToolAdapterError("INVALID_AGENT_TOOL_PARAMETERS", str(error)) from error

    data = await run_delay_estimation(session, payload=payload, artifact_root=artifact_root)
    rendered = ", ".join(f"{column}={delay}" for column, delay in data.best_delays.items())
    return AgentToolResult(
        summary=f"正式时滞分析服务已完成：{rendered}。",
        source_version_id=data.source_version_id,
        result_version_id=None,
        processing_run_ids=[str(data.processing_run_id)] if data.processing_run_id else [],
        result_payload=data.model_dump(mode="json"),
    )

async def _apply_lag_compensation(
    session: AsyncSession,
    *,
    execution: AgentExecutionSession,
    parameters: dict[str, Any],
    artifact_root: Path,
) -> AgentToolResult:
    """Apply the validated, human-confirmed lag map through the formal versioned service."""

    try:
        payload = LagCompensationRequest(
            version_id=execution.current_version_id,
            dataset_id=execution.dataset_id,
            **_validated_parameters(
                parameters,
                allowed=_LAG_PARAMETER_NAMES,
                tool_name="apply_lag_compensation",
            ),
        )
    except ValidationError as error:
        raise AgentToolAdapterError("INVALID_AGENT_TOOL_PARAMETERS", str(error)) from error

    data = await apply_lag_compensation(session, payload=payload, artifact_root=artifact_root)
    return AgentToolResult(
        summary=f"正式时滞补偿服务已生成不可变版本 {data.result_version_id}。",
        source_version_id=data.source_version_id,
        result_version_id=data.result_version_id,
        processing_run_ids=[str(data.processing_run_id)],
        result_payload=data.model_dump(mode="json"),
    )