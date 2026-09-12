"""Report assembly and optimised-dataset export (phase 10).

Agent reports are composed from their persisted step results and explicitly linked
``ProcessingRun`` records. Standalone reports retain dataset/version-scoped run lookup.
Every figure enters through a typed placeholder, so the document is a view over persisted
evidence rather than a retelling of in-memory state. :mod:`algorithms.report.provenance`
enforces that a draft containing a bare numeral is rejected before rendering.

Export writes the rows the closed loop actually selected, plus a manifest recording which
runs produced the selection, so the delivered CSV can be traced back to the decisions that
shaped it.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import numpy as np
from algorithms.agent.llm import LlmProvider
from algorithms.agent.llm_planner import LlmNarrator, NarrationOutcome
from algorithms.report.provenance import (
    RenderResult,
    format_fraction_percent,
    render_template,
    resolve_path,
    validate_draft,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_execution import AgentStepRun
from app.models.dataset import ProcessingRun
from app.models.operation_log import OperationLog
from app.models.optimization import OptimizationStudy
from app.schemas.reporting import (
    ExportDatasetData,
    ExportDatasetRequest,
    ExportSelectionProvenance,
    ReportBinding,
    ReportData,
    ReportRequest,
    ReportSection,
)
from app.services.agent_execution_service import ExecutionStateError, get_execution
from app.services.contract_stubs import completed_task
from app.services.version_data import VersionDataError, load_version_series

# Reports cite recent work, not the whole history; this bounds the scan below.
RUN_SCAN_LIMIT = 500


class ReportDomainError(Exception):
    """A client-safe reporting failure for the standard error envelope."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


@dataclass(frozen=True)
class RunIndex:
    """Persisted runs keyed by short id, as the placeholder resolver sees them."""

    records: dict[str, dict[str, Any]]
    by_type: dict[str, str]
    step_by_tool: dict[str, str]
    execution_id: UUID | None

    def latest(self, run_type: str) -> str | None:
        return self.by_type.get(run_type)


async def build_run_index(
    session: AsyncSession,
    *,
    dataset_id: UUID | None,
    version_id: UUID | None,
) -> RunIndex:
    """Load the runs a report may cite, newest first per type."""

    statement = (
        select(ProcessingRun).order_by(ProcessingRun.created_at.desc()).limit(RUN_SCAN_LIMIT)
    )
    runs = list((await session.scalars(statement)).all())
    runs = [run for run in runs if _matches(run, dataset_id=dataset_id, version_id=version_id)]

    records: dict[str, dict[str, Any]] = {}
    by_type: dict[str, str] = {}
    for run in runs:
        short = _short_id(run.id)
        records[short] = {
            "run_id": str(run.id),
            "run_type": run.run_type,
            "status": run.status,
            "parameters": dict(run.parameters or {}),
            "created_at": run.created_at.isoformat() if run.created_at else "",
            **(run.result or {}),
        }
        by_type.setdefault(run.run_type, short)
    return RunIndex(records=records, by_type=by_type, step_by_tool={}, execution_id=None)


async def build_execution_run_index(
    session: AsyncSession,
    *,
    execution_id: UUID,
    dataset_id: UUID | None,
    version_id: UUID | None,
) -> RunIndex:
    """Index one execution's persisted steps and only their explicitly linked runs."""

    try:
        execution = await get_execution(session, execution_id=execution_id)
    except ExecutionStateError as error:
        raise ReportDomainError(
            "REPORT_EXECUTION_NOT_FOUND",
            "报告绑定的 Agent 执行不存在。",
            status_code=404,
        ) from error
    if dataset_id != execution.dataset_id or version_id != execution.current_version_id:
        raise ReportDomainError(
            "REPORT_EXECUTION_SCOPE_MISMATCH",
            "报告请求的数据集或版本与当前 Agent 执行不一致。",
            status_code=409,
            details={
                "execution_id": str(execution.id),
                "execution_dataset_id": str(execution.dataset_id),
                "execution_version_id": str(execution.current_version_id),
            },
        )

    records: dict[str, dict[str, Any]] = {}
    step_by_tool: dict[str, str] = {}
    referenced_run_ids: list[UUID] = []
    for step in sorted(execution.step_runs, key=lambda item: item.sequence):
        if step.status != "SUCCEEDED":
            continue
        key = f"step{step.sequence}"
        records[key] = _step_record(step)
        step_by_tool.setdefault(step.tool_name, key)
        for raw_run_id in step.processing_run_ids:
            try:
                run_id = UUID(raw_run_id)
            except (TypeError, ValueError):
                continue
            if run_id not in referenced_run_ids:
                referenced_run_ids.append(run_id)

    by_type: dict[str, str] = {}
    for run_id in referenced_run_ids:
        run = await session.get(ProcessingRun, run_id)
        if run is None:
            continue
        short = _short_id(run.id)
        records[short] = {
            "run_id": str(run.id),
            "run_type": run.run_type,
            "status": run.status,
            "parameters": dict(run.parameters or {}),
            "created_at": run.created_at.isoformat() if run.created_at else "",
            **(run.result or {}),
        }
        by_type.setdefault(run.run_type, short)
    return RunIndex(
        records=records,
        by_type=by_type,
        step_by_tool=step_by_tool,
        execution_id=execution.id,
    )


def _step_record(step: AgentStepRun) -> dict[str, Any]:
    payload = dict(step.result_payload or {})
    result = dict(payload["result"]) if isinstance(payload.get("result"), Mapping) else payload
    summary_data = result.get("summary") if isinstance(result.get("summary"), Mapping) else None
    summary = payload.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        task = result.get("task") if isinstance(result.get("task"), Mapping) else {}
        progress = task.get("progress") if isinstance(task.get("progress"), Mapping) else {}
        summary = progress.get("message") if isinstance(progress.get("message"), str) else ""
    record: dict[str, Any] = {
        "step_id": step.step_id,
        "tool_name": step.tool_name,
        "status": step.status,
        "summary": summary,
        "source_version_id": str(step.source_version_id) if step.source_version_id else "",
        "result_version_id": str(step.result_version_id) if step.result_version_id else "",
        "processing_run_ids": list(step.processing_run_ids),
        **result,
    }
    record["summary"] = summary
    if summary_data is not None:
        record["summary_data"] = dict(summary_data)
    return record


async def generate_report(
    session: AsyncSession,
    *,
    payload: ReportRequest,
    artifact_root: Path,
    provider: LlmProvider | None = None,
) -> ReportData:
    """Compose, validate and render a provenance-bound report.

    When a model is configured it writes the closing engineering commentary, under the rule
    that it may not emit a single digit. Its draft goes through the same numeral validator
    as everything else, so a model that ignores the rule produces a rejected paragraph and
    the templated conclusion stands instead.
    """

    if payload.execution_id is not None:
        index = await build_execution_run_index(
            session,
            execution_id=payload.execution_id,
            dataset_id=payload.dataset_id,
            version_id=payload.version_id,
        )
    else:
        index = await build_run_index(
            session, dataset_id=payload.dataset_id, version_id=payload.version_id
        )
    if not index.records:
        raise ReportDomainError(
            "REPORT_NO_RUNS",
            "该数据集尚无可引用的处理运行记录，无法生成报告。",
            status_code=404,
        )

    study = None
    if payload.execution_id is None and payload.study_id is not None:
        study = await session.get(OptimizationStudy, payload.study_id)
        if study is None:
            raise ReportDomainError(
                "OPTIMIZATION_STUDY_NOT_FOUND", "寻优任务不存在。", status_code=404
            )
        index.records["study"] = {
            "best_value": study.best_value,
            "best_params": dict(study.best_params or {}),
            "statistics": dict(study.statistics or {}),
            "objective": study.objective,
        }

    sections = _compose(index, payload)
    narration = (
        NarrationOutcome()
        if payload.execution_id is not None
        else _narrate(provider or _resolve_provider(), index=index, sections=sections)
    )
    if narration.text:
        sections.append(
            ReportSection(
                key="expert_commentary", title="专家结论（大模型撰写）", body=narration.text
            )
        )
    sections = _number_sections(sections)
    title = _report_title(index, payload)
    template = "\n\n".join(f"## {section.title}\n\n{section.body}" for section in sections)

    # The draft must contain no bare numerals. This is checked even though the composer is
    # ours, because the same path serves LLM-authored drafts and must not be weaker there.
    violations = validate_draft(template)
    if violations:
        raise ReportDomainError(
            "REPORT_CONTAINS_UNBOUND_NUMERAL",
            "报告草稿包含未溯源的数字字面量，已拒绝渲染。",
            details={"violations": [violation.to_payload() for violation in violations[:20]]},
        )

    rendered = render_template(
        template,
        runs=index.records,
        formatters=_presentation_formatters(index),
    )
    report_id = uuid4()
    artifact_uri = _write_report(
        artifact_root,
        report_id=report_id,
        rendered=rendered,
        payload=payload,
        index=index,
        title=title,
    )
    await _persist(session, report_id=report_id, payload=payload, rendered=rendered)

    return ReportData(
        report_id=report_id,
        execution_id=payload.execution_id,
        dataset_id=payload.dataset_id,
        task=completed_task(stage="generate_report", message="图文报告已生成，全部数值均已溯源。"),
        title=title,
        markdown=rendered.text,
        sections=sections,
        bindings=[ReportBinding(**binding.to_payload()) for binding in rendered.bindings],
        unresolved=list(rendered.unresolved),
        fully_resolved=rendered.fully_resolved,
        artifact_uri=artifact_uri,
        cited_runs=sorted(
            {
                binding.run_id
                for binding in rendered.bindings
                if binding.kind == "run" and binding.resolved
            }
        ),
        narration_source=narration.source,
        llm_provider=narration.provider,
        llm_model=narration.model,
        llm_fallback_reason=narration.fallback_reason,
        llm_rejected_attempts=max(0, narration.attempts - (1 if narration.text else 0)),
    )


def _resolve_provider() -> LlmProvider:
    from app.services.llm_runtime_config_service import build_effective_llm_provider

    return build_effective_llm_provider()


def _narrate(
    provider: LlmProvider,
    *,
    index: RunIndex,
    sections: list[ReportSection],
) -> NarrationOutcome:
    """Ask the model for closing commentary, offering it only real placeholder paths."""

    paths: list[str] = []
    for short, record in index.records.items():
        for path in _leaf_paths(record):
            paths.append(f"{short}.{path}")
    context = "已完成的分析环节：\n" + "\n".join(f"- {section.title}" for section in sections)
    return LlmNarrator(provider).narrate(context=context, available_paths=paths[:60])


def _leaf_paths(record: Mapping[str, Any], prefix: str = "", depth: int = 0) -> list[str]:
    """Enumerate scalar paths a narrative may cite, so the model cannot invent fields."""

    if depth > 3:
        return []
    paths: list[str] = []
    for key, value in record.items():
        path = f"{prefix}{key}"
        if isinstance(value, Mapping):
            paths.extend(_leaf_paths(value, f"{path}.", depth + 1))
        elif isinstance(value, (int, float, bool, str)):
            paths.append(path)
    return paths


def _presentation_formatters(
    index: RunIndex,
) -> dict[tuple[str, str, str], Callable[[Any], str]]:
    """Declare percentage presentation by metric semantics, never by numeric range."""

    formatters: dict[tuple[str, str, str], Callable[[Any], str]] = {}
    profile = index.step_by_tool.get("profile_dataset")
    if profile is not None:
        for path in (
            "fingerprint.values.missing_ratio",
            "fingerprint.values.anomaly_ratio",
            "fingerprint.values.dynamic_ratio",
        ):
            formatters[("step", profile, path)] = format_fraction_percent
    anomaly = index.step_by_tool.get("detect_anomalies")
    if anomaly is not None:
        formatters[("step", anomaly, "anomaly_ratio")] = format_fraction_percent
    segment = index.latest("preprocessing.segment")
    if segment is not None:
        formatters[("run", segment, "selection.coverage_ratio")] = format_fraction_percent
    return formatters


def _compose(index: RunIndex, payload: ReportRequest) -> list[ReportSection]:
    """Build only sections supported by evidence in the selected report scope."""

    if index.execution_id is not None:
        return _compose_execution(index)
    return _compose_standalone(index, payload)


def _report_title(index: RunIndex, payload: ReportRequest) -> str:
    if index.execution_id is None:
        return payload.title
    tools = set(index.step_by_tool)
    if "optimize_pipeline" in tools:
        return "IndusOpt 动态建模与闭环寻优报告"
    if tools.intersection({"fit_arx", "evaluate_model"}):
        return "IndusOpt 动态建模与系统辨识报告"
    if tools.intersection(
        {
            "detect_dynamic_segments",
            "estimate_delays",
            "apply_lag_compensation",
            "analyze_collinearity",
            "select_variables",
        }
    ):
        return "IndusOpt 建模数据预处理与优选报告"
    if tools.intersection({"profile_dataset", "detect_anomalies", "clean_data"}):
        return "IndusOpt 数据质量分析与清洗报告"
    return "IndusOpt 数据分析报告"


def _compose_execution(index: RunIndex) -> list[ReportSection]:
    sections = [
        ReportSection(
            key="overview",
            title="分析概述",
            body=(
                "本报告仅汇总当前 Agent 任务中已完成并持久化的执行步骤。"
                "未在本次任务中执行的分析阶段及同一数据资源的历史处理记录，均不进入本次结论。"
            ),
        )
    ]
    definitions = [
        ("profile_dataset", "profile", "数据画像", _profile_body),
        ("detect_anomalies", "anomaly", "异常检测", _anomaly_body),
        ("clean_data", "cleaning", "数据清洗与规整", _cleaning_body),
        ("detect_dynamic_segments", "selection", "动态区间与数据优选", _summary_body),
        ("estimate_delays", "delay", "时滞估计", _summary_body),
        ("apply_lag_compensation", "lag", "时滞补偿", _summary_body),
        ("analyze_collinearity", "collinearity", "共线性诊断", _summary_body),
        ("select_variables", "feature_selection", "变量优选", _summary_body),
        ("fit_arx", "model", "动态模型辨识", _summary_body),
        ("evaluate_model", "evaluation", "模型评价", _summary_body),
        ("optimize_pipeline", "optimization", "闭环寻优", _summary_body),
        ("export_dataset", "export", "数据导出", _summary_body),
    ]
    for tool, section_key, title, body_builder in definitions:
        record_key = index.step_by_tool.get(tool)
        if record_key is None:
            continue
        sections.append(
            ReportSection(
                key=section_key,
                title=title,
                body=body_builder(record_key, index.records[record_key]),
            )
        )
    limitations = _execution_limitations(set(index.step_by_tool))
    if limitations:
        sections.append(
            ReportSection(key="limitations", title="局限与风险提示", body=limitations)
        )
    return sections


def _summary_body(record_key: str, record: Mapping[str, Any]) -> str:
    if isinstance(record.get("summary"), str) and record["summary"].strip():
        return f"本阶段执行摘要：{{{{step:{record_key}.summary}}}}"
    return "本阶段已在当前 Agent 任务中完成，详细结果保存在对应步骤证据中。"


def _profile_body(record_key: str, record: Mapping[str, Any]) -> str:
    clauses = _step_metric_clauses(
        record_key,
        record,
        [
            ("n_samples", "本次数据画像覆盖样本", "个"),
            ("fingerprint.values.missing_ratio", "缺失比例", ""),
            ("fingerprint.values.anomaly_ratio", "画像离群比例", ""),
        ],
    )
    return _body_with_summary(record_key, record, clauses)


def _anomaly_body(record_key: str, record: Mapping[str, Any]) -> str:
    clauses = _step_metric_clauses(
        record_key,
        record,
        [("anomaly_count", "检出疑似异常点", "个"), ("anomaly_ratio", "疑似异常比例", "")],
    )
    return _body_with_summary(record_key, record, clauses)


def _cleaning_body(record_key: str, record: Mapping[str, Any]) -> str:
    clauses = _step_metric_clauses(
        record_key,
        record,
        [
            ("total_cleaned_points", "清洗修改单元格", "个"),
            ("summary_data.rows_before", "清洗前样本", "条"),
            ("summary_data.rows_after", "清洗后样本", "条"),
            ("summary_data.changes.unique_changed_cells", "实际修改单元格", "个"),
            ("summary_data.changes.missing_value_fills", "缺失填补", "个"),
            ("summary_data.changes.outlier_replacements", "异常替换", "个"),
            ("summary_data.changes.duplicate_timestamps_processed", "重复时间戳处理", "个"),
            ("summary_data.changes.resampling_empty_rows_created", "重采样空行", "条"),
            ("summary_data.changes.smoothing_changes", "平滑修改", "个"),
        ],
    )
    return _body_with_summary(record_key, record, clauses)


def _body_with_summary(
    record_key: str, record: Mapping[str, Any], clauses: list[str]
) -> str:
    paragraphs: list[str] = []
    if clauses:
        paragraphs.append("，".join(clauses) + "。")
    if isinstance(record.get("summary"), str) and record["summary"].strip():
        paragraphs.append(f"执行摘要：{{{{step:{record_key}.summary}}}}")
    return "\n\n".join(paragraphs) or "本阶段已完成，未产生可量化的结构化摘要。"


def _step_metric_clauses(
    record_key: str,
    record: Mapping[str, Any],
    definitions: list[tuple[str, str, str]],
) -> list[str]:
    return [
        f"{label} {{{{step:{record_key}.{path}}}}}{suffix}"
        for path, label, suffix in definitions
        if resolve_path(record, path) is not None
    ]


def _execution_limitations(tools: set[str]) -> str:
    limitations: list[str] = []
    if "detect_anomalies" in tools:
        limitations.append("疑似异常点由当前检测方法识别，结果用于提示复核，不等同于过程故障诊断。")
    if "clean_data" in tools:
        limitations.append("清洗结果受当前插值、异常处理和时间规整参数约束，仍需结合工艺语义复核。")
    if "detect_dynamic_segments" in tools:
        limitations.append("D-最优区间优选依赖候选窗口与质量门控结果，不能替代对工况覆盖性的工程判断。")
    if tools.intersection({"estimate_delays", "apply_lag_compensation"}):
        limitations.append("时滞结论受采样周期、信号激励与相关结构影响，补偿前应确认工艺因果方向。")
    if tools.intersection({"fit_arx", "evaluate_model"}):
        limitations.append("ARX 模型建立在线性与时不变近似上，外推至未覆盖工况时应重新验证。")
    if "optimize_pipeline" in tools:
        limitations.append("闭环寻优结果受搜索空间、目标函数和试验预算约束，不代表全局最优保证。")
    return "\n\n".join(limitations)


def _compose_standalone(index: RunIndex, payload: ReportRequest) -> list[ReportSection]:
    sections = [
        ReportSection(
            key="overview",
            title="分析概述",
            body=(
                f"本报告由 IndusOpt 自动生成，引用了 "
                f"{{{{run:{next(iter(index.records))}.run_type}}}} 等当前数据资源范围内的处理记录。"
                "报告数值均通过持久化证据占位符解析。"
            ),
        )
    ]
    clean = index.latest("preprocessing.clean")
    segment = index.latest("preprocessing.segment")
    delay = index.latest("preprocessing.delay")
    collinearity = index.latest("preprocessing.collinearity")
    modeling = index.latest("modeling.arx")
    standalone_sections = [
        (clean, "cleaning", "数据清洗与规整", [("total_cleaned_points", "清洗修改数据点", "个")]),
        (
            segment,
            "selection",
            "动态区间与数据优选",
            [
                ("selection.candidate_count", "候选窗口", "个"),
                ("selection.gated_count", "通过质量门控", "个"),
                ("selection.selected_count", "最终选中区间", "个"),
                ("selection.coverage_ratio", "采样占比", ""),
            ],
        ),
        (delay, "delay", "时滞估计", [("refined_delays", "最终时滞", ""), ("validation_fit", "验证结果", "")]),
        (collinearity, "collinearity", "共线性诊断", [("condition_number", "设计矩阵条件数", ""), ("groups", "高相关变量组", "")]),
        (
            modeling,
            "model",
            "模型辨识与评价",
            [
                ("validation.free_run_fit", "验证集自由仿真 FIT", ""),
                ("validation.one_step_fit", "一步预测 FIT", ""),
                ("validation.stable", "模型稳定性", ""),
                ("training_rows", "训练样本", "条"),
            ],
        ),
    ]
    for record_key, section_key, title, metrics in standalone_sections:
        if record_key:
            sections.append(
                ReportSection(
                    key=section_key,
                    title=title,
                    body=_run_body(record_key, index.records[record_key], metrics),
                )
            )
    if "study" in index.records:
        sections.append(
            ReportSection(
                key="optimization",
                title="闭环寻优",
                body=_run_body(
                    "study",
                    index.records["study"],
                    [("objective", "寻优目标", ""), ("best_value", "最优目标值", "")],
                ),
            )
        )
    limitations = _standalone_limitations(index)
    if limitations:
        sections.append(ReportSection(key="limitations", title="局限与风险提示", body=limitations))
    _ = payload
    return sections


def _run_body(
    record_key: str,
    record: Mapping[str, Any],
    definitions: list[tuple[str, str, str]],
) -> str:
    clauses = [
        f"{label} {{{{run:{record_key}.{path}}}}}{suffix}"
        for path, label, suffix in definitions
        if resolve_path(record, path) is not None
    ]
    return "，".join(clauses) + "。" if clauses else "该处理记录已完成，但未提供可量化摘要。"


def _standalone_limitations(index: RunIndex) -> str:
    limitations: list[str] = []
    if index.latest("preprocessing.clean"):
        limitations.append("清洗结论受当前处理参数约束，仍需结合工艺语义复核。")
    if index.latest("preprocessing.segment"):
        limitations.append("D-最优区间优选依赖候选窗口与质量门控结果。")
    if index.latest("preprocessing.delay"):
        limitations.append("时滞估计受采样周期、信号激励与相关结构影响。")
    if index.latest("modeling.arx"):
        limitations.append("ARX 模型建立在线性与时不变近似上，外推时应重新验证。")
    if "study" in index.records:
        limitations.append("闭环寻优受搜索空间、目标函数和试验预算约束。")
    return "\n\n".join(limitations)


_SECTION_NUMERALS = ("零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十")


def _section_numeral(value: int) -> str:
    if value <= 10:
        return _SECTION_NUMERALS[value]
    if value < 20:
        return f"十{_SECTION_NUMERALS[value - 10]}"
    return str(value)


def _number_sections(sections: list[ReportSection]) -> list[ReportSection]:
    return [
        section.model_copy(update={"title": f"{_section_numeral(index)}、{section.title}"})
        for index, section in enumerate(sections, start=1)
    ]


def _write_report(
    artifact_root: Path,
    *,
    report_id: UUID,
    rendered: RenderResult,
    payload: ReportRequest,
    index: RunIndex,
    title: str,
) -> str:
    root = artifact_root / "reports"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{report_id}.md"
    header = (
        f"# {title}\n\n"
        f"生成时间：{datetime.now(UTC).isoformat()}\n\n"
        f"引用运行记录：{', '.join(sorted(index.records))}\n\n"
        f"数值绑定数：{len(rendered.bindings)}，未解析：{len(rendered.unresolved)}\n\n"
        "---\n\n"
    )
    path.write_text(header + rendered.text + "\n", encoding="utf-8")
    return path.relative_to(artifact_root).as_posix()


async def _persist(
    session: AsyncSession,
    *,
    report_id: UUID,
    payload: ReportRequest,
    rendered: RenderResult,
) -> None:
    now = datetime.now(UTC)
    session.add(
        ProcessingRun(
            id=report_id,
            dataset_id=payload.dataset_id,
            source_version_id=payload.version_id,
            run_type="reporting.generate",
            status="succeeded",
            parameters=payload.model_dump(mode="json"),
            result=rendered.to_payload(),
            created_at=now,
            finished_at=now,
        )
    )
    session.add(
        OperationLog(
            id=uuid4(),
            event_type="reporting.generate.completed",
            subject_id=str(payload.dataset_id) if payload.dataset_id else str(report_id),
            payload_json=json.dumps(
                {
                    "report_id": str(report_id),
                    "bindings": len(rendered.bindings),
                    "unresolved": list(rendered.unresolved),
                    "executed_at": now.isoformat(),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            created_at=now,
        )
    )
    await session.commit()


async def export_optimised_dataset(
    session: AsyncSession,
    *,
    payload: ExportDatasetRequest,
    artifact_root: Path,
    selection_provenance: ExportSelectionProvenance | None = None,
) -> ExportDatasetData:
    """Write the selected rows to CSV alongside a manifest naming their provenance."""

    try:
        series = await load_version_series(
            session,
            version_id=payload.version_id,
            artifact_root=artifact_root,
            dataset_id=payload.dataset_id,
        )
        input_columns, output_column = series.resolve_columns(
            input_columns=payload.input_columns or None,
            output_column=payload.output_column,
        )
    except VersionDataError as error:
        raise ReportDomainError(
            error.code, error.message, status_code=error.status_code, details=error.details
        ) from error

    indices = sorted(set(payload.sample_indices)) if payload.sample_indices else None
    selection_metadata: dict[str, object] = (
        selection_provenance.model_dump(mode="json")
        if selection_provenance is not None
        else {"selection_source": "explicit_sample_indices"}
        if indices is not None
        else {}
    )
    if indices is None:
        statement = (
            select(ProcessingRun)
            .where(ProcessingRun.run_type == "preprocessing.segment")
            .order_by(ProcessingRun.created_at.desc())
            .limit(RUN_SCAN_LIMIT)
        )
        candidates = list((await session.scalars(statement)).all())
        run = next(
            (
                candidate
                for candidate in candidates
                if _matches(
                    candidate,
                    dataset_id=payload.dataset_id,
                    version_id=payload.version_id,
                )
            ),
            None,
        )
        if run is not None:
            indices = sorted(
                set(int(v) for v in (run.result or {}).get("selected_sample_indices", []))
            )
            selection_metadata = {
                "selection_source": "preprocessing_segment",
                "selection_processing_run_id": str(run.id),
            }
    if not indices:
        raise ReportDomainError(
            "EXPORT_NO_SELECTION",
            "没有可导出的优选样本，请先执行动态区间优选或显式提供样本下标。",
            status_code=404,
        )

    n_samples = series.n_samples
    invalid_indices = [index for index in indices if not 0 <= index < n_samples]
    if selection_provenance is not None and invalid_indices:
        raise ReportDomainError(
            "OPTIMIZATION_BEST_SELECTION_INVALID",
            "Optuna Best Trial 的优选样本下标超出来源数据范围。",
            status_code=409,
            details={"invalid_indices": invalid_indices[:20], "source_rows": n_samples},
        )
    indices = [index for index in indices if 0 <= index < n_samples]
    if not indices:
        raise ReportDomainError("EXPORT_NO_SELECTION", "优选样本下标全部越界。", status_code=400)

    export_id = uuid4()
    root = artifact_root / "exports"
    root.mkdir(parents=True, exist_ok=True)
    csv_path = root / f"{export_id}.csv"
    columns = [*input_columns, output_column]
    has_timestamps = len(series.timestamps) == n_samples

    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow((["timestamp"] if has_timestamps else ["sample_index"]) + columns)
        for index in indices:
            first = series.timestamps[index].isoformat() if has_timestamps else str(index)
            row = [first]
            for column in columns:
                value = series.values[column][index]
                row.append("" if not np.isfinite(value) else format(float(value), ".12g"))
            writer.writerow(row)

    manifest_path = root / f"{export_id}.manifest.json"
    manifest = {
        "export_id": str(export_id),
        "dataset_id": str(series.dataset_id),
        "version_id": str(series.version_id),
        "source_version_id": str(series.version_id),
        "origin": series.origin,
        "input_columns": list(input_columns),
        "output_column": output_column,
        "exported_rows": len(indices),
        "selected_row_count": len(indices),
        "source_rows": n_samples,
        "coverage_ratio": len(indices) / n_samples if n_samples else 0.0,
        **selection_metadata,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    now = datetime.now(UTC)
    session.add(
        ProcessingRun(
            id=export_id,
            dataset_id=series.dataset_id if series.origin == "dataset" else None,
            source_version_id=series.version_id if series.origin == "dataset" else None,
            run_type="delivery.export",
            status="succeeded",
            parameters=payload.model_dump(mode="json"),
            result=manifest,
            created_at=now,
            finished_at=now,
        )
    )
    await session.commit()

    return ExportDatasetData(
        export_id=export_id,
        dataset_id=series.dataset_id,
        version_id=series.version_id,
        task=completed_task(stage="export_dataset", message="优选数据集已导出。"),
        csv_uri=csv_path.relative_to(artifact_root).as_posix(),
        manifest_uri=manifest_path.relative_to(artifact_root).as_posix(),
        exported_rows=len(indices),
        source_rows=n_samples,
        coverage_ratio=manifest["coverage_ratio"],
        columns=["timestamp" if has_timestamps else "sample_index", *columns],
    )


async def get_export_artifact(
    session: AsyncSession,
    *,
    export_id: UUID,
    artifact_root: Path,
    kind: str,
) -> tuple[Path, str, str]:
    """Resolve a persisted delivery artifact without trusting a client-provided path."""

    run = await session.get(ProcessingRun, export_id)
    if run is None or run.run_type != "delivery.export" or run.status != "succeeded":
        raise ReportDomainError(
            "EXPORT_NOT_FOUND",
            "优选数据导出记录不存在。",
            status_code=404,
        )
    if kind == "csv":
        path = artifact_root / "exports" / f"{export_id}.csv"
        filename = f"optimised-dataset-{export_id}.csv"
        media_type = "text/csv"
    elif kind == "manifest":
        path = artifact_root / "exports" / f"{export_id}.manifest.json"
        filename = f"optimised-dataset-{export_id}.manifest.json"
        media_type = "application/json"
    else:
        raise ReportDomainError("EXPORT_ARTIFACT_KIND_INVALID", "不支持的导出产物类型。")
    if not path.is_file():
        raise ReportDomainError(
            "EXPORT_ARTIFACT_MISSING",
            "优选数据导出文件不存在。",
            status_code=404,
        )
    return path, filename, media_type


def _matches(
    run: ProcessingRun,
    *,
    dataset_id: UUID | None,
    version_id: UUID | None,
) -> bool:
    """Decide whether a run belongs to the requested dataset or version.

    The foreign keys alone are not enough. Runs on S1-S6 benchmark artifacts have no row in
    ``dataset_versions`` to point at, so their FKs are deliberately null and the identity
    lives in the run's own recorded parameters. Matching on both keeps benchmark runs — the
    ones every demonstration uses — citable in a report.
    """

    parameters = run.parameters or {}
    result = run.result or {}
    dataset_matches = dataset_id is None or (
        run.dataset_id == dataset_id
        or str(parameters.get("dataset_id") or "") == str(dataset_id)
    )
    version_matches = version_id is None or (
        run.source_version_id == version_id
        or str(parameters.get("version_id") or "") == str(version_id)
        or str(parameters.get("active_version_id") or "") == str(version_id)
        or any(
            str(result.get(key) or "") == str(version_id)
            for key in ("derived_version_id", "effective_version_id", "result_version_id")
        )
    )
    return dataset_matches and version_matches


def _short_id(value: UUID) -> str:
    """Placeholders read better with a short handle than a full UUID."""

    return f"r{str(value).replace('-', '')[:8]}"
