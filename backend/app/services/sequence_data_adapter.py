"""Build strict within-partition windows from a verified in-memory dataset view."""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from app.schemas.experiment_spec import ExperimentSpec, RowRange, RowSet, TimeAxis
from app.schemas.tcn import MAX_FEATURES as TCN_MAX_FEATURES
from app.schemas.tcn import TCNParameters
from app.schemas.timexer import TimeXerParameters, validate_feature_names
from app.services.experiment_spec_service import (
    effective_ranges,
    spec_hash,
    validate_partition_coverage,
)
from app.services.model_data_adapter import (
    BoundSource,
    Partition,
    ResolvedRows,
    _array_offsets,
    _select_rows,
    _validate_static_spec,
)
from app.services.version_data import VersionDataError, VersionSeries

Float32Array = NDArray[np.float32]


@dataclass(frozen=True)
class SequenceSampleEvidence:
    source: BoundSource
    partition: Partition
    target_name: str
    feature_names: tuple[str, ...]
    anchor_rows: RowSet
    history_lengths: tuple[tuple[str, int], ...]
    prediction_horizon: int
    continuous_runs: tuple[RowRange, ...]
    record_positions_used: bool
    sampling_status: Literal["uniform", "irregular", "unknown"]
    rule_version: Literal["within_partition_sequence_v1"] = "within_partition_sequence_v1"

    @property
    def sample_count(self) -> int:
        return self.anchor_rows.count

    @property
    def target_offsets(self) -> tuple[int, ...]:
        """Add each offset to an anchor record to identify its label in horizon order."""
        return tuple(range(self.prediction_horizon))


@dataclass(frozen=True)
class TCNSamples:
    x: Float32Array
    y: Float32Array
    evidence: SequenceSampleEvidence

    @property
    def feature_names(self) -> tuple[str, ...]:
        return self.evidence.feature_names

    @property
    def target_name(self) -> str:
        return self.evidence.target_name


@dataclass(frozen=True)
class TimeXerSamples:
    x_target: Float32Array
    x_exogenous: Float32Array
    y: Float32Array
    evidence: SequenceSampleEvidence

    @property
    def exogenous_feature_names(self) -> tuple[str, ...]:
        return self.evidence.feature_names

    @property
    def target_name(self) -> str:
        return self.evidence.target_name


@dataclass(frozen=True)
class _SequenceView:
    features: tuple[NDArray, ...]
    target: NDArray
    offsets: NDArray[np.intp]
    evidence: SequenceSampleEvidence


def _check_time_axis(series: VersionSeries, time_axis: TimeAxis, offsets: NDArray[np.intp]) -> None:
    uniform = time_axis.sampling_status == "uniform"
    if not series.timestamps:
        if uniform:
            raise ValueError("Uniform sampling requires aligned timestamps")
        return

    # Check each adjacent record pair once. Windows were already isolated by run.
    starts = offsets[:, :-1].ravel()
    _, first = np.unique(starts, return_index=True)
    stops = offsets[:, 1:].ravel()[first]
    periods = np.fromiter(
        (
            (series.timestamps[end] - series.timestamps[start]).total_seconds()
            for start, end in zip(starts[first], stops, strict=True)
        ),
        dtype=np.float64,
        count=len(first),
    )
    if np.any(periods <= 0):
        raise ValueError("Time must increase inside each sequence window")
    expected = time_axis.sample_period_seconds
    if uniform and (expected is None or not np.allclose(periods, expected, rtol=1e-8, atol=1e-9)):
        raise ValueError("Sequence timestamps do not match the declared uniform sample period")


def _prepare(
    series: VersionSeries,
    *,
    spec: ExperimentSpec,
    source: BoundSource,
    partition: Partition,
    requested_rows: ResolvedRows | None,
    record_positions: tuple[int, ...] | None,
    history_lengths: tuple[tuple[str, int], ...],
    horizon: int,
) -> _SequenceView:
    spec = ExperimentSpec.model_validate(spec.model_dump())
    # v1 describes the base data/split. Model parameters define the sequence windows.
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
    columns = tuple(series.values[name] for name in (*names, target))
    view_size = spec.row_count if record_positions is None else len(record_positions)
    if (series.timestamps and len(series.timestamps) != view_size) or any(
        not isinstance(column, np.ndarray) or column.shape != (view_size,) for column in columns
    ):
        raise ValueError("Expected one-dimensional columns aligned to the array view")
    if any(column.dtype.kind not in "iuf" for column in columns):
        raise ValueError("Features and target must contain real numeric values")

    if spec.row_order is not None:
        raise ValueError('Sequence models require continuous timestamp evidence')
    validate_partition_coverage(spec)
    lookback = max(length for _, length in history_lengths)
    allowed = tuple(
        RowRange(start=interval.start + lookback, stop=interval.stop - horizon + 1)
        for interval in effective_ranges(spec, partition)
        if interval.stop - interval.start >= lookback + horizon
    )
    if not allowed:
        raise ValueError("No complete sequence windows in the requested partition")
    rows, anchors = _select_rows(spec, allowed, requested_rows, view_size)
    records = np.asarray(anchors, dtype=np.intp)[:, None] + np.arange(
        -lookback, horizon, dtype=np.intp
    )
    offsets = records
    if record_positions is not None:
        # Reconstruct original record order even when the numeric view is reordered.
        unique, inverse = np.unique(records.ravel(), return_inverse=True)
        mapped = _array_offsets(tuple(unique.tolist()), record_positions, spec.row_count)
        offsets = mapped[inverse].reshape(records.shape)
    _check_time_axis(series, spec.time_axis, offsets)
    used_runs = []
    for run in spec.continuous_runs:
        first = bisect_left(anchors, run.start)
        if first < len(anchors) and anchors[first] < run.stop:
            used_runs.append(run)
    return _SequenceView(
        features=columns[:-1],
        target=columns[-1],
        offsets=offsets,
        evidence=SequenceSampleEvidence(
            source=source,
            partition=partition,
            target_name=target,
            feature_names=tuple(names),
            anchor_rows=rows,
            history_lengths=history_lengths,
            prediction_horizon=horizon,
            continuous_runs=tuple(used_runs),
            record_positions_used=record_positions is not None,
            sampling_status=spec.time_axis.sampling_status,
        ),
    )


def _gather(column: NDArray, offsets: NDArray[np.intp]) -> Float32Array:
    with np.errstate(over="ignore", invalid="ignore"):
        values = np.ascontiguousarray(column[offsets], dtype=np.float32)
    if not np.isfinite(values).all():
        raise ValueError("Sequence inputs and labels must be finite float32 values")
    return values


def _gather_features(columns: tuple[NDArray, ...], offsets: NDArray[np.intp]) -> Float32Array:
    result = np.empty((*offsets.shape, len(columns)), dtype=np.float32)
    for index, column in enumerate(columns):
        result[..., index] = _gather(column, offsets)
    return result


def build_tcn_samples(
    series: VersionSeries,
    *,
    spec: ExperimentSpec,
    source: BoundSource,
    partition: Partition,
    parameters: TCNParameters | None = None,
    requested_rows: ResolvedRows | None = None,
    record_positions: tuple[int, ...] | None = None,
) -> TCNSamples:
    """Build X[r-L:r] and y[r] from windows wholly inside the partition and run."""
    config = TCNParameters.model_validate({} if parameters is None else parameters.model_dump())
    if len(spec.input_columns) > TCN_MAX_FEATURES:
        raise ValueError("Too many TCN input features")
    view = _prepare(
        series,
        spec=spec,
        source=source,
        partition=partition,
        requested_rows=requested_rows,
        record_positions=record_positions,
        history_lengths=(("features", config.window_length),),
        horizon=1,
    )
    if partition == "train" and view.evidence.sample_count < 2:
        raise ValueError("TCN training requires at least two complete windows")
    return TCNSamples(
        x=_gather_features(view.features, view.offsets[:, :-1]),
        y=_gather(view.target, view.offsets[:, -1]),
        evidence=view.evidence,
    )


def build_timexer_samples(
    series: VersionSeries,
    *,
    spec: ExperimentSpec,
    source: BoundSource,
    partition: Partition,
    parameters: TimeXerParameters | None = None,
    requested_rows: ResolvedRows | None = None,
    record_positions: tuple[int, ...] | None = None,
) -> TimeXerSamples:
    """Build both histories before r and the H labels starting at r."""
    config = TimeXerParameters.model_validate({} if parameters is None else parameters.model_dump())
    target_length = config.target_window_length
    exogenous_length = config.exogenous_window_length
    horizon = config.prediction_length
    view = _prepare(
        series,
        spec=spec,
        source=source,
        partition=partition,
        requested_rows=requested_rows,
        record_positions=record_positions,
        history_lengths=(("target", target_length), ("exogenous", exogenous_length)),
        horizon=horizon,
    )
    validate_feature_names(view.evidence.target_name, view.evidence.feature_names)
    history = view.offsets[:, :-horizon]
    return TimeXerSamples(
        x_target=_gather(view.target, history[:, -target_length:])[:, :, None],
        x_exogenous=_gather_features(view.features, history[:, -exogenous_length:]),
        y=_gather(view.target, view.offsets[:, -horizon:]),
        evidence=view.evidence,
    )
