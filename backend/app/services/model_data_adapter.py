"""Build static model batches from an already verified version view."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

import numpy as np
from numpy.typing import NDArray

from app.schemas.experiment_spec import ExperimentSpec, RowRange, RowSet
from app.services.experiment_spec_service import (
    effective_ranges,
    spec_hash,
    validate_partition_coverage,
)
from app.services.version_data import FloatArray, VersionDataError, VersionSeries

Partition = Literal["train", "validation", "test"]


@dataclass(frozen=True)
class TableInput:
    x: FloatArray
    feature_names: tuple[str, ...]


@dataclass(frozen=True)
class BoundSource:
    dataset_id: UUID
    dataset_version_id: UUID
    dataset_sha256: str
    experiment_spec_hash: str


@dataclass(frozen=True)
class HorizonRows:
    step: int
    target_rows: RowSet


@dataclass(frozen=True)
class SampleEvidence:
    source: BoundSource
    partition: Partition
    anchor_rows: RowSet
    targets_by_horizon: tuple[HorizonRows, ...]
    history_lengths: tuple[tuple[str, int], ...]
    rule_version: str


@dataclass(frozen=True)
class PreparedBatch:
    inputs: TableInput
    y: FloatArray
    target_name: str
    evidence: SampleEvidence


@dataclass(frozen=True)
class ResolvedRows:
    """A range RowSet or an external RowSet and its verified record positions.

    For an external index, the caller must fully consume iter_rows before passing
    its output here. The adapter checks the in-memory selection and never opens it.
    """

    evidence: RowSet
    indices: tuple[int, ...] | None = None


def _validate_static_spec(spec: ExperimentSpec) -> None:
    feature = spec.feature_spec
    if (
        spec.task_type != "supervised_regression"
        or feature.kind != "tabular"
        or any(lags != (0,) for lags in feature.input_lags.values())
        or feature.target_lags
        or feature.history_window != 0
        or feature.prediction_horizon != 1
        or feature.initialization_policy != "fixed"
        or spec.split.history_guard != 0
    ):
        raise ValueError("Static tabular regression requires same-row features and horizon 1")


def _select_rows(
    spec: ExperimentSpec,
    allowed: tuple[RowRange, ...],
    requested_rows: ResolvedRows | None,
    available_count: int,
) -> tuple[RowSet, tuple[int, ...]]:
    if requested_rows is None:
        rows = RowSet(ranges=allowed)
        if rows.count > available_count:
            raise ValueError("The array view cannot contain every effective partition record")
        return rows, tuple(i for interval in allowed for i in range(interval.start, interval.stop))
    if not isinstance(requested_rows, ResolvedRows):
        raise ValueError("An explicit selection must be a nonempty ResolvedRows")

    rows = RowSet.model_validate(requested_rows.evidence.model_dump())
    if rows.count > available_count:
        raise ValueError("The array view cannot contain every selected CSV record")
    indices = requested_rows.indices
    if rows.index_file is None:
        if indices is not None:
            raise ValueError("Range selection must use its declared ranges")
        for interval in rows.ranges:
            if not any(
                run.start <= interval.start and interval.stop <= run.stop
                for run in spec.ordered_record_ranges or spec.continuous_runs
            ):
                raise ValueError("A requested range crosses a continuous-run boundary or an ordered record range")
        indices = tuple(i for interval in rows.ranges for i in range(interval.start, interval.stop))
    if (
        not indices
        or len(indices) != rows.count
        or any(type(index) is not int or index < 0 for index in indices)
        or any(left >= right for left, right in zip(indices, indices[1:], strict=False))
    ):
        raise ValueError("Selected records must be nonempty, strictly increasing and match RowSet")

    ranges = iter(allowed)
    current = next(ranges, None)
    for index in indices:
        while current is not None and index >= current.stop:
            current = next(ranges, None)
        if current is None or index < current.start:
            raise ValueError("Selected record lies outside the effective partition")
    return rows, indices


def _array_offsets(
    records: tuple[int, ...],
    record_positions: tuple[int, ...] | None,
    row_count: int,
) -> NDArray[np.intp]:
    if record_positions is None:
        # A full VersionSeries from the verified reader retains CSV record order.
        return np.asarray(records, dtype=np.intp)

    if any(type(record) is not int or not 0 <= record < row_count for record in record_positions):
        raise ValueError("Array record positions must belong to the bound CSV version")
    offsets = {record: offset for offset, record in enumerate(record_positions)}
    if len(offsets) != len(record_positions):
        raise ValueError("Array record positions must be unique")
    try:
        return np.asarray([offsets[record] for record in records], dtype=np.intp)
    except KeyError as error:
        raise ValueError("A selected CSV record is missing from the array view") from error


def build_table_samples(
    series: VersionSeries,
    *,
    spec: ExperimentSpec,
    source: BoundSource,
    partition: Partition,
    requested_rows: ResolvedRows | None = None,
    record_positions: tuple[int, ...] | None = None,
) -> PreparedBatch:
    """Select a partition using zero-based, version-local CSV data record positions.

    The default view must be complete and in the verified CSV reader's order.
    Supply record_positions (array offset -> CSV record) for compact or reordered
    views. A resolved sparse selection contains CSV records, not array offsets.
    """
    spec = ExperimentSpec.model_validate(spec.model_dump())
    _validate_static_spec(spec)
    expected_source = BoundSource(
        spec.dataset_id, spec.dataset_version_id, spec.dataset_version_sha256, spec_hash(spec)
    )
    if source != expected_source or (series.dataset_id, series.version_id) != (
        spec.dataset_id,
        spec.dataset_version_id,
    ):
        raise ValueError("VersionSeries, bound source and ExperimentSpec identities must agree")

    target = spec.target_column
    if target is None or any(
        not name.strip() or name != name.strip() or "\x00" in name
        for name in (*spec.input_columns, target)
    ):
        raise ValueError("Invalid feature or target column name")
    try:
        names, resolved_target = series.resolve_columns(
            input_columns=list(spec.input_columns), output_column=target
        )
    except VersionDataError as error:
        raise ValueError("A requested feature or target is not a numeric column") from error
    if tuple(names) != spec.input_columns or resolved_target != target:
        raise ValueError("Resolved feature order or target differs from ExperimentSpec")

    expected_count = spec.row_count if record_positions is None else len(record_positions)
    columns = tuple(series.values[name] for name in (*names, target))
    if (series.timestamps and len(series.timestamps) != expected_count) or any(
        not isinstance(column, np.ndarray) or column.shape != (expected_count,)
        for column in columns
    ):
        raise ValueError("Each feature and target must be a one-dimensional aligned column")
    if any(column.dtype.kind not in "iuf" for column in columns):
        raise ValueError("Features and target must contain real numeric values")

    validate_partition_coverage(spec)
    rows, records = _select_rows(
        spec, effective_ranges(spec, partition), requested_rows, expected_count
    )
    offsets = _array_offsets(records, record_positions, spec.row_count)
    with np.errstate(over="ignore", invalid="ignore"):
        selected = [np.asarray(column[offsets], dtype=np.float64) for column in columns]
    if any(not np.isfinite(column).all() for column in selected):
        raise ValueError("Selected features and target must be finite")
    return PreparedBatch(
        inputs=TableInput(np.column_stack(selected[:-1]), tuple(names)),
        y=selected[-1],
        target_name=target,
        evidence=SampleEvidence(
            source=source,
            partition=partition,
            anchor_rows=rows,
            targets_by_horizon=(HorizonRows(step=1, target_rows=rows),),
            history_lengths=(),
            rule_version="static_tabular_v1",
        ),
    )
