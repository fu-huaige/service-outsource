"""Build the integrated recommendation contract from the current Agent dataset version."""

import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from uuid import UUID

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_execution import AgentExecutionSession
from app.models.dataset import DatasetVersion, ProcessingRun
from app.schemas.experiment_spec import (
    ConfirmedRowOrder,
    ExperimentSpec,
    RowRange,
    SplitSpec,
    TimeAxis,
)
from app.schemas.model_recommendation import ModelRecommendationRequest
from app.services.arx_platform_adapter import build_arx_spec
from app.services.dataset_version_io import artifact_matches_sha256
from app.services.experiment_spec_service import validate_partition_coverage
from app.services.version_data import VersionSeries, load_version_series


class ModelSpecInputRequired(ValueError):
    """The integrated gate needs one additional piece of source evidence."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


async def _applied_inputs(
    session: AsyncSession, execution: AgentExecutionSession, sequence: int
) -> list[str] | None:
    for step in sorted(execution.step_runs, key=lambda item: item.sequence, reverse=True):
        if (
            step.sequence >= sequence
            or step.tool_name != "select_variables"
            or step.status != "SUCCEEDED"
            or step.confirmation_status != "APPROVED"
            or (step.result_version_id or step.source_version_id) != execution.current_version_id
        ):
            continue
        summary = step.result_payload.get("summary")
        if not isinstance(summary, dict) or summary.get("user_confirmed") is not True:
            continue
        if step.result_version_id is not None:
            if len(step.processing_run_ids) != 1:
                continue
            try:
                run_id = UUID(step.processing_run_ids[0])
            except ValueError:
                continue
            run = await session.get(ProcessingRun, run_id)
            if (
                run is None
                or run.run_type != "preprocessing.feature_selection"
                or run.status != "succeeded"
                or run.dataset_id != execution.dataset_id
                or run.source_version_id != step.source_version_id
                or run.result.get("result_version_id") != str(step.result_version_id)
                or run.result.get("kept_input_columns") != summary.get("kept_input_columns")
                or run.result.get("user_confirmed") is not True
            ):
                continue
        elif step.result_payload.get("operation_name") != "feature_selection_noop":
            continue
        names = summary.get("kept_input_columns")
        if isinstance(names, list) and all(isinstance(name, str) for name in names):
            return names
    return None


def resolve_model_spec_target(series: VersionSeries, explicit: str | None) -> str:
    declared = series.declared_output
    if explicit and declared and explicit != declared:
        raise ModelSpecInputRequired(
            "target_column", "指定的目标与最终版本的输出角色冲突，请确认目标变量。"
        )
    target = declared or explicit
    if target is None or target not in series.values or not np.isfinite(series.values[target]).any():
        raise ModelSpecInputRequired("target_column", "请确认最终版本中可用的数值目标变量。")
    return target


def _time_deltas(timestamps: list[datetime]) -> list[float]:
    return [
        (after - before).total_seconds()
        for before, after in zip(timestamps, timestamps[1:], strict=False)
    ]


def _verified_cadence(deltas: list[float]) -> float | None:
    if deltas:
        period, occurrences = Counter(deltas).most_common(1)[0]
        if period > 0 and occurrences >= 2 and occurrences * 2 > len(deltas):
            return period
    return None


def _declared_target(message: str) -> str | None:
    match = re.search(
        r"(?:目标变量|输出变量|target_column)\s*(?:为|是|[:：=])\s*[「“`\x22]?"
        r"([^\s，。,；;、」”`\x22]+)",
        message,
    )
    return match.group(1) if match else None


def has_no_known_model_gaps(series: VersionSeries, runs: tuple[RowRange, ...]) -> bool:
    # Explicit runs can represent separate acquisitions, including a clock restart.
    global_cadence = _verified_cadence(_time_deltas(series.timestamps))
    for run in runs:
        deltas = _time_deltas(series.timestamps[run.start : run.stop])
        cadence = _verified_cadence(deltas) or global_cadence
        if cadence is not None and any(delta > cadence for delta in deltas):
            return False
    return True


def _layout(series: VersionSeries) -> tuple[TimeAxis, tuple[RowRange, ...]]:
    if series.time_column is None or len(series.timestamps) != series.n_samples:
        raise ModelSpecInputRequired(
            "split", "无法证明最终版本的记录顺序具有时间意义，请补充有依据的数据分区。"
        )
    deltas = _time_deltas(series.timestamps)
    if any(delta <= 0 for delta in deltas):
        raise ModelSpecInputRequired(
            "split", "最终版本时间戳未严格递增，请核对记录顺序并提供连续区段和分区。"
        )
    cadence = _verified_cadence(deltas)
    # A median alone cannot prove continuity. With an evidenced cadence, every off-cadence
    # interval is a boundary. Without one, do not claim continuity across any pair of rows.
    boundaries = [0, *(i for i, delta in enumerate(deltas, 1) if delta != cadence), series.n_samples]
    if len(boundaries) > 10001:
        raise ModelSpecInputRequired("split", "无法核验足够的连续区段，请补充连续区段和分区。")
    runs = tuple(
        RowRange(start=start, stop=stop)
        for start, stop in zip(boundaries, boundaries[1:], strict=False)
    )
    return TimeAxis(
        column=series.time_column,
        sampling_status="uniform" if cadence is not None else "unknown",
        sample_period_seconds=cadence,
    ), runs


def _split(size: int, runs: tuple[RowRange, ...]) -> SplitSpec:
    b1, b2 = size * 3 // 5, size * 4 // 5
    partitions = {}
    for name, start, stop in (
        ("train", 0, b1), ("validation", b1, b2), ("test", b2, size)
    ):
        partitions[name] = tuple(
            RowRange(start=max(run.start, start), stop=min(run.stop, stop))
            for run in runs
            if max(run.start, start) < min(run.stop, stop)
        )
        if not partitions[name]:
            raise ModelSpecInputRequired("split", "最终版本无法生成非空的 60/20/20 分区。")
    return SplitSpec.model_validate(partitions)


async def build_agent_recommendation_request(
    session: AsyncSession,
    *,
    execution: AgentExecutionSession,
    sequence: int,
    artifact_root: Path,
    draft: ModelRecommendationRequest | None,
    keep_explicit_split: bool = True,
    row_order_confirmation: ConfirmedRowOrder | None = None,
) -> ModelRecommendationRequest:
    version = await session.get(DatasetVersion, execution.current_version_id, populate_existing=True)
    if version is None or version.dataset_id != execution.dataset_id:
        raise ModelSpecInputRequired("dataset_version_id", "无法核验当前任务的最终数据版本。")
    if not artifact_matches_sha256(
        artifact_root=artifact_root, relative_path=version.artifact_path, expected_sha256=version.sha256
    ):
        raise ModelSpecInputRequired("dataset_version_sha256", "最终版本的 CSV SHA-256 不一致。")

    series = await load_version_series(
        session, dataset_id=execution.dataset_id, version_id=version.id, artifact_root=artifact_root,
        allow_missing_time=True,
    )
    if series.n_samples != version.row_count:
        raise ModelSpecInputRequired("row_count", "最终版本的 CSV 行数与版本记录不一致。")
    supplied = draft.experiment_spec if draft else None
    explicit = _declared_target(str((execution.plan_json or {}).get("goal", "")))
    if explicit and supplied and explicit != supplied.target_column:
        raise ModelSpecInputRequired("target_column", "任务指定的目标与提交的配置冲突，请确认目标变量。")
    target = resolve_model_spec_target(series, explicit or (supplied.target_column if supplied else None))
    applied = await _applied_inputs(session, execution, sequence)

    recommendation_step = next((step for step in execution.step_runs if step.sequence == sequence), None)
    preference = recommendation_step.input_payload.get("requested_model_type_id") if recommendation_step else None
    if supplied is not None and supplied.task_type == "dynamic_system_identification":
        inputs = _valid_inputs(applied if applied is not None else supplied.input_columns, series, target)
        if (
            (supplied.dataset_id, supplied.dataset_version_id, supplied.dataset_version_sha256, supplied.row_count)
            != (version.dataset_id, version.id, version.sha256, version.row_count)
            or inputs != supplied.input_columns or target != supplied.target_column
        ):
            raise ModelSpecInputRequired("experiment_spec", "提交的动态实验契约与当前数据版本或变量不一致。")
        # Restore an explicit draft as stored. Only qualification can authorize it for training.
        return draft.model_copy(update={
            "preferred_dynamic_model": (
                preference if preference in {"arx", "fir", "oe"} else draft.preferred_dynamic_model
            ),
        })
    if preference in {"arx", "fir", "oe"}:
        if supplied is not None and supplied.training_selection.mode != "full_train":
            raise ModelSpecInputRequired("split", "动态辨识当前仅支持明确授权的完整 Train 分区。")
        axis, runs = _layout(series)
        if len(runs) != 1 or axis.sampling_status != "uniform":
            raise ModelSpecInputRequired("split", "动态辨识当前需要单一连续且等间隔的时间区段。")
        inputs = _valid_inputs(applied if applied is not None else (
            supplied.input_columns if supplied else series.declared_inputs
        ), series, target)
        mapping = draft.parameters if draft else {}
        arguments = dict(version=version, inputs=inputs, target=target, axis=axis, runs=runs)
        try:
            spec = await build_arx_spec(session, **arguments, overrides=mapping.get("arx", {}))
        except ValueError:
            spec = await build_arx_spec(session, **arguments, overrides={})
        return ModelRecommendationRequest(
            experiment_spec=spec, parameters=mapping, preferred_dynamic_model=preference,
        )

    untimed = series.time_column is None
    if untimed and row_order_confirmation is None:
        raise ModelSpecInputRequired(
            "row_order", "请确认当前版本的 CSV 行序与原始采集顺序一致。"
        )
    if row_order_confirmation is not None and (
        not untimed
        or row_order_confirmation.dataset_version_id != version.id
        or row_order_confirmation.csv_sha256 != version.sha256
    ):
        raise ModelSpecInputRequired("row_order", "行序确认与当前数据版本或 CSV SHA-256 不一致。")

    evaluation_scopes = ("validation", "test")
    if (
        not untimed
        and keep_explicit_split
        and draft is not None
        and supplied is not None
        and (
            supplied.dataset_id,
            supplied.dataset_version_id,
            supplied.dataset_version_sha256,
            supplied.row_count,
        ) == (version.dataset_id, version.id, version.sha256, version.row_count)
        and has_no_known_model_gaps(series, supplied.continuous_runs)
    ):
        inputs = supplied.input_columns if applied is None else _valid_inputs(applied, series, target)
        application = supplied.application
        if supplied.task_type == "supervised_regression" and application is None:
            application = "regression"
        if (
            inputs == supplied.input_columns
            and application == supplied.application
            and supplied.evaluation.scopes == evaluation_scopes
        ):
            return draft
        document = {**supplied.model_dump(), "input_columns": inputs, "application": application}
        evaluation = document["evaluation"]
        evaluation["scopes"] = evaluation_scopes
        # Preserve explicit rows. A newly authorized scope uses the evaluator's default rows.
        if set(supplied.evaluation.sample_indices) != set(evaluation_scopes):
            evaluation["resolution_status"] = "unresolved"
        return draft.model_copy(
            update={
                "experiment_spec": ExperimentSpec.model_validate(document),
                "expected_spec_hash": None,
            }
        )

    inputs = _valid_inputs(applied if applied is not None else series.declared_inputs, series, target)
    if untimed:
        time_axis, runs = TimeAxis(), ()
        ordered_ranges = (RowRange(start=0, stop=version.row_count),)
    else:
        time_axis, runs = _layout(series)
        ordered_ranges = None
    spec = ExperimentSpec.model_validate(
        {
            "task_type": "supervised_regression",
            "application": (supplied.application if supplied else None) or "regression",
            "dataset_id": version.dataset_id,
            "dataset_version_id": version.id,
            "dataset_version_sha256": version.sha256,
            "row_count": version.row_count,
            "target_column": target,
            "input_columns": inputs,
            "feature_spec": {"kind": "tabular", "prediction_horizon": 1},
            "continuous_runs": runs,
            "ordered_record_ranges": ordered_ranges,
            "row_order": row_order_confirmation,
            "split": _split(version.row_count, ordered_ranges or runs),
            "time_axis": time_axis,
            "evaluation": {"scopes": evaluation_scopes, "prediction_modes": ["prediction"]},
        }
    )
    validate_partition_coverage(spec)
    return ModelRecommendationRequest(
        experiment_spec=spec,
        goal=draft.goal if draft else "auto",
        forecast_spec=draft.forecast_spec if draft else None,
        parameters=draft.parameters if draft else {},
    )


def _valid_inputs(names: list[str] | tuple[str, ...], series: VersionSeries, target: str) -> tuple[str, ...]:
    inputs = tuple(
        name for name in dict.fromkeys(names)
        if name != target and name in series.values and np.isfinite(series.values[name]).any()
    )
    if not inputs:
        raise ModelSpecInputRequired("input_columns", "请补充至少一个有效且不同于目标的输入变量。")
    return inputs
