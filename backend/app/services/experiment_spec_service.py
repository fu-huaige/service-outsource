"""Read-only data binding. No training, index-file generation or DB mutation."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from collections.abc import Iterator
from itertools import zip_longest
from pathlib import Path

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dataset import Dataset, DatasetVersion, ProcessingRun
from app.schemas.experiment_spec import ExperimentSpec, LeakageAssessment, RowRange, RowSet
from app.services.dataset_version_io import artifact_matches_sha256, load_version_csv
from app.services.version_data import load_version_series


def contained_path(root: Path, uri: str) -> Path:
    candidate = Path(uri)
    if candidate.is_absolute() or "\\" in uri or ":" in uri:
        raise ValueError("Artifact URI must be a relative POSIX path")
    resolved = (root / candidate).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("Artifact path escapes its root")
    return resolved


def sha256_file(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def iter_rows(rows: RowSet, artifact_root: Path) -> Iterator[int]:
    """Stream external indexes; callers must exhaust the iterator to verify its digest."""
    if rows.index_file is None:
        for interval in rows.ranges:
            yield from range(interval.start, interval.stop)
        return
    reference = rows.index_file
    digest, count, previous = hashlib.sha256(), 0, -1
    with contained_path(artifact_root, reference.uri).open("rb") as source:
        for line in source:
            digest.update(line)
            if not re.fullmatch(rb"[0-9]+\r?\n?", line):
                raise ValueError("Index file must contain one decimal CSV row ID per line")
            value = int(line)
            if value <= previous:
                raise ValueError("Index file must be strictly increasing")
            previous = value
            count += 1
            yield value
    if count != reference.count or digest.hexdigest() != reference.sha256:
        raise ValueError("Index file count or SHA256 mismatch")


def compact_rows(indices: Iterator[int]) -> RowSet:
    """Compress already ordered row IDs; reject, rather than reorder, bad input."""
    ranges: list[RowRange] = []
    start = previous = None
    for value in indices:
        if type(value) is not int or value < 0 or (previous is not None and value <= previous):
            raise ValueError("Rows must be strictly increasing nonnegative integers")
        if previous is not None and value != previous + 1:
            ranges.append(RowRange(start=start, stop=previous + 1))
            start = value
        if start is None:
            start = value
        previous = value
    if previous is not None:
        ranges.append(RowRange(start=start, stop=previous + 1))
    return RowSet(ranges=tuple(ranges))


def within(row: int, ranges: tuple[RowRange, ...]) -> bool:
    return any(r.start <= row < r.stop for r in ranges)


def spec_hash(spec: ExperimentSpec) -> str:
    payload = json.dumps(
        spec.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _covering_run(spec: ExperimentSpec, interval: RowRange) -> RowRange:
    for run in spec.ordered_record_ranges or spec.continuous_runs:
        if run.start <= interval.start and interval.stop <= run.stop:
            return run
    raise ValueError("Range is not covered by one continuous run/history boundary")


def validate_partition_coverage(spec: ExperimentSpec) -> None:
    """Validate nominal ranges even for full Train and unresolved evaluation.

    Interval operations only: no expansion of the dataset's row positions.
    """
    for partition in ("train", "validation", "test"):
        for interval in getattr(spec.split, partition):
            _covering_run(spec, interval)
        if not effective_ranges(spec, partition):
            raise ValueError("Partition has no effective rows after history/guard exclusion")


def effective_ranges(spec: ExperimentSpec, partition: str) -> tuple[RowRange, ...]:
    """Candidate target rows, before finite-regressor/weight filtering.

    Each range belongs to exactly one run. Train starts after the run's history;
    dynamic guards retain the original service's partition boundary exclusions.
    This validates a contract, not multi-run execution by the legacy trainer.
    """
    if partition not in {"train", "validation", "test"}:
        raise ValueError("Unknown partition")
    history = spec.feature_spec.history_window
    dynamic = spec.task_type == "dynamic_system_identification"
    guard = max(spec.split.history_guard, history) if dynamic else 0
    output = []
    for interval in getattr(spec.split, partition):
        run = _covering_run(spec, interval)
        start = max(interval.start, run.start + history)
        if partition != "train":
            start = max(start, interval.start + guard)
        stop = interval.stop - (guard if dynamic and partition != "test" else 0)
        if start < stop:
            output.append(RowRange(start=start, stop=stop))
    return tuple(output)


def _validate_rows(spec: ExperimentSpec, rows: RowSet, partition: str, root: Path) -> None:
    for interval in rows.ranges:
        _covering_run(spec, interval)
    allowed = effective_ranges(spec, partition)
    # All accepted contracts have horizon=1 and target-row indices.
    lookback = spec.feature_spec.history_window
    for row in iter_rows(rows, root):
        if not within(row, allowed):
            raise ValueError("Row outside its effective partition")
        if not any(
            r.start <= row - lookback and row < r.stop
            for r in spec.ordered_record_ranges or spec.continuous_runs
        ):
            raise ValueError("Feature history crosses a continuous-run boundary")


async def bind_experiment_spec(
    session: AsyncSession,
    *,
    spec: ExperimentSpec,
    artifact_root: Path,
) -> ExperimentSpec:
    """Verify physical records and lineage; never trust caller leakage assertions.

    Multi-range contracts are validated, NOT executed. Current ARX execution
    continues to use its existing single chronological split.
    """
    spec = ExperimentSpec.model_validate(spec.model_dump())
    validate_partition_coverage(spec)
    version = await session.get(DatasetVersion, spec.dataset_version_id)
    dataset = await session.get(Dataset, spec.dataset_id)
    if version is None or dataset is None or version.dataset_id != dataset.id:
        raise ValueError("DatasetVersion ownership mismatch")
    if version.sha256 != spec.dataset_version_sha256 or not artifact_matches_sha256(
        artifact_root=artifact_root,
        relative_path=version.artifact_path,
        expected_sha256=spec.dataset_version_sha256,
    ):
        raise ValueError("DatasetVersion SHA256 mismatch")
    parsed = load_version_csv(
        dataset=dataset, version=version, artifact_root=artifact_root,
        allow_missing_time=spec.row_order is not None,
    )
    if spec.row_order is not None and parsed.timestamp_column is not None:
        raise ValueError("Confirmed row order is only supported for CSVs without timestamps")
    # Existing readers skip blank records. Reject them here so physical record
    # positions and the existing numeric arrays are provably identical.
    with contained_path(artifact_root, version.artifact_path).open(
        encoding=version.parameters.get("csv_encoding") or dataset.encoding,
        newline="",
    ) as source:
        reader = csv.reader(
            source, delimiter=version.parameters.get("csv_delimiter") or dataset.delimiter
        )
        next(reader)
        physical_count = 0
        for record in reader:
            if not record or all(not value.strip() for value in record):
                raise ValueError("Blank CSV records make physical row positions ambiguous")
            physical_count += 1
    if (
        physical_count != spec.row_count
        or len(parsed.rows) != spec.row_count
        or version.row_count != spec.row_count
    ):
        raise ValueError("CSV row count mismatch")
    series = await load_version_series(
        session, version_id=version.id, dataset_id=dataset.id, artifact_root=artifact_root,
        allow_missing_time=spec.row_order is not None,
    )
    series.resolve_columns(input_columns=list(spec.input_columns), output_column=spec.target_column)
    if spec.time_axis.column is not None and spec.time_axis.column != parsed.timestamp_column:
        raise ValueError("Time column mismatch")
    periods = np.array(
        [
            (b - a).total_seconds()
            for a, b in zip(parsed.timestamps, parsed.timestamps[1:], strict=False)
        ]
    )
    for run in spec.continuous_runs:
        local = periods[run.start : run.stop - 1]
        if np.any(local <= 0):
            raise ValueError("Time must increase within each continuous run")
        if spec.task_type == "dynamic_system_identification":
            expected = spec.time_axis.sample_period_seconds
            if (
                expected is None
                or not local.size
                or not np.allclose(local, expected, rtol=1e-8, atol=1e-9)
            ):
                raise ValueError("Dynamic runs require verified uniform sampling")
    if spec.time_axis.sample_period_seconds is not None and not math.isfinite(
        spec.time_axis.sample_period_seconds
    ):
        raise ValueError("Invalid sample period")
    if spec.time_axis.column is not None and spec.time_axis.sampling_status == "uniform":
        expected = spec.time_axis.sample_period_seconds
        if expected is None or any(
            not np.allclose(periods[r.start : r.stop - 1], expected, rtol=1e-8, atol=1e-9)
            for r in spec.continuous_runs
        ):
            raise ValueError("Claimed uniform sampling does not match source timestamps")
    selection = spec.training_selection
    if selection.mode == "selected_rows":
        if selection.source_version_id != version.id:
            raise ValueError("Selection references a different version")
        run = await session.get(ProcessingRun, selection.source_run_id)
        if (
            run is None
            or run.status != "succeeded"
            or run.run_type != "preprocessing.segment"
            or run.dataset_id != dataset.id
            or run.source_version_id != version.id
        ):
            raise ValueError("Selection run provenance mismatch")
        recorded = run.result.get("selected_sample_indices")
        if not isinstance(recorded, list) or any(type(i) is not int for i in recorded):
            raise ValueError("Selection run has no verifiable indices")
        if any(i < 0 for i in recorded) or any(
            a >= b for a, b in zip(recorded, recorded[1:], strict=False)
        ):
            raise ValueError("Persisted selection is not strictly increasing")
        if any(
            a != b
            for a, b in zip_longest(recorded, iter_rows(selection.requested_indices, artifact_root))
        ):
            raise ValueError("Selection differs from its exact ProcessingRun")
        _validate_rows(spec, selection.requested_indices, "train", artifact_root)
    for scope, rows in spec.evaluation.sample_indices.items():
        _validate_rows(spec, rows, scope, artifact_root)
        for row in iter_rows(rows, artifact_root):
            references = [(spec.target_column, 0)]
            references.extend((spec.target_column, lag) for lag in spec.feature_spec.target_lags)
            for column in spec.input_columns:
                references.extend(
                    (column, lag) for lag in spec.feature_spec.input_lags.get(column, (0,))
                )
            if any(not np.isfinite(series.values[column][row - lag]) for column, lag in references):
                raise ValueError("Evaluation rows contain nonfinite targets or features")
    ancestors = {version.id}
    ancestor = version
    while ancestor.parent_version_id is not None:
        if ancestor.parent_version_id in ancestors:
            raise ValueError("DatasetVersion lineage cycle")
        ancestor = await session.get(DatasetVersion, ancestor.parent_version_id)
        if ancestor is None or ancestor.dataset_id != dataset.id:
            raise ValueError("Broken DatasetVersion lineage")
        ancestors.add(ancestor.id)
    for step in spec.preprocessing:
        if step.result_version_id not in ancestors:
            raise ValueError("Preprocessing does not belong to source lineage")
        run = await session.get(ProcessingRun, step.source_run_id)
        result_version = await session.get(DatasetVersion, step.result_version_id)
        if (
            run is None
            or run.status != "succeeded"
            or run.dataset_id != dataset.id
            or run.source_version_id != step.source_version_id
            or run.run_type != step.operation
            or run.parameters != step.parameters
            or result_version is None
            or result_version.dataset_id != dataset.id
            or result_version.parent_version_id != step.source_version_id
            or run.result.get("result_version_id") != str(step.result_version_id)
        ):
            raise ValueError("Preprocessing lineage mismatch")
        if step.fit_indices is not None:
            # Indices belong to the step's source, not necessarily the final version.
            source_version = await session.get(DatasetVersion, step.source_version_id)
            if source_version is None:
                raise ValueError("Preprocessing source is missing")
            if any(
                i >= source_version.row_count for i in iter_rows(step.fit_indices, artifact_root)
            ):
                raise ValueError("Preprocessing fit row out of bounds")
    # No existing persisted preprocessing record has an authoritative Train-only
    # fit-evidence protocol. Declared partitions or JSON copied from clients are
    # insufficient. Verification can be added when that protocol exists.
    leakage = LeakageAssessment(
        status="unknown",
        evidence=("No authoritative preprocessing fit evidence protocol in Stage 1A",),
    )
    return spec.model_copy(update={"leakage": leakage})
