"""Verify sequence windows against version-local source record positions."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import numpy as np
import pytest
from app.schemas.experiment_spec import ExperimentSpec, IndexFile, RowRange, RowSet
from app.schemas.tcn import TCNParameters, receptive_field
from app.schemas.timexer import TimeXerParameters
from app.services.experiment_spec_service import spec_hash
from app.services.model_data_adapter import BoundSource, ResolvedRows
from app.services.sequence_data_adapter import build_tcn_samples, build_timexer_samples
from app.services.version_data import VersionSeries

TCN = TCNParameters(window_length=receptive_field())
TIMEXER = TimeXerParameters(
    target_window_length=8, exogenous_window_length=11, prediction_length=3, patch_length=4
)


@pytest.fixture
def data():
    spec = ExperimentSpec.model_validate(
        {
            "task_type": "supervised_regression",
            "dataset_id": uuid4(),
            "dataset_version_id": uuid4(),
            "dataset_version_sha256": "a" * 64,
            "row_count": 152,
            "input_columns": ["b", "a"],
            "target_column": "y",
            "feature_spec": {"kind": "tabular"},
            "time_axis": {
                "column": "timestamp",
                "sample_period_seconds": 1,
                "sampling_status": "uniform",
            },
            "continuous_runs": [
                {"start": 0, "stop": 35},
                {"start": 35, "stop": 110},
                {"start": 110, "stop": 152},
            ],
            "split": {
                "train": [{"start": 0, "stop": 33}, {"start": 35, "stop": 69}],
                "validation": [{"start": 69, "stop": 110}],
                "test": [{"start": 110, "stop": 152}],
            },
        }
    )
    records = np.arange(spec.row_count, dtype=np.float64)
    epoch = datetime(2026, 1, 1, tzinfo=UTC)
    timestamps = [
        epoch + timedelta(seconds=position - run.start)
        for run in spec.continuous_runs
        for position in range(run.start, run.stop)
    ]
    series = VersionSeries(
        dataset_id=spec.dataset_id,
        version_id=spec.dataset_version_id,
        dataset_name="in-memory",
        origin="dataset",
        timestamps=timestamps,
        values={"a": records + 100, "b": records + 200, "y": records + 300},
        declared_inputs=("a", "b"),
        declared_output="y",
        sample_period_seconds=1,
    )
    return series, spec


def source_for(spec):
    return BoundSource(
        spec.dataset_id, spec.dataset_version_id, spec.dataset_version_sha256, spec_hash(spec)
    )


def tcn(data, *, partition="train", **kwargs):
    series, spec = data
    return build_tcn_samples(
        series, spec=spec, source=source_for(spec), partition=partition, parameters=TCN, **kwargs
    )


def timexer(data, *, partition="train", parameters=TIMEXER, **kwargs):
    series, spec = data
    return build_timexer_samples(
        series,
        spec=spec,
        source=source_for(spec),
        partition=partition,
        parameters=parameters,
        **kwargs,
    )


def sparse(*anchors):
    return ResolvedRows(
        RowSet(index_file=IndexFile(uri="anchors.txt", sha256="b" * 64, count=len(anchors))),
        anchors,
    )


@pytest.mark.parametrize(
    ("partition", "bounds"),
    [("train", ((0, 33), (35, 69))), ("validation", ((69, 110),)), ("test", ((110, 152),))],
)
def test_tcn_values_order_and_partition_evidence(data, partition, bounds):
    batch = tcn(data, partition=partition)
    length = TCN.window_length
    anchors = [r for start, stop in bounds for r in range(start + length, stop)]
    assert batch.x.shape == (len(anchors), length, 2)
    assert batch.y.shape == (len(anchors),)
    assert batch.x.dtype == batch.y.dtype == np.float32
    assert batch.feature_names == ("b", "a") and batch.target_name == "y"
    expected = np.asarray(anchors)[:, None] + np.arange(-length, 0)
    np.testing.assert_array_equal(batch.x[:, :, 0], 200 + expected)
    np.testing.assert_array_equal(batch.x[:, :, 1], 100 + expected)
    np.testing.assert_array_equal(batch.y, 300 + np.asarray(anchors))
    evidence = batch.evidence
    assert evidence.anchor_rows.ranges == tuple(
        RowRange(start=start + length, stop=stop) for start, stop in bounds
    )
    assert evidence.sample_count == len(batch.x) == len(batch.y)
    assert evidence.source == source_for(data[1])
    assert evidence.partition == partition and evidence.history_lengths == (("features", length),)
    assert evidence.prediction_horizon == 1 and evidence.target_offsets == (0,)
    assert not evidence.record_positions_used
    assert evidence.continuous_runs == tuple(
        run for run in data[1].continuous_runs if any(run.start <= r < run.stop for r in anchors)
    )


@pytest.mark.parametrize(("target_length", "exogenous_length"), [(8, 11), (12, 8)])
def test_timexer_unequal_histories_and_multistep_labels(data, target_length, exogenous_length):
    parameters = TIMEXER.model_copy(
        update={"target_window_length": target_length, "exogenous_window_length": exogenous_length}
    )
    batch = timexer(data, partition="validation", parameters=parameters)
    lookback = max(target_length, exogenous_length)
    anchors = np.arange(69 + lookback, 108)
    assert batch.x_target.shape == (len(anchors), target_length, 1)
    assert batch.x_exogenous.shape == (len(anchors), exogenous_length, 2)
    assert batch.y.shape == (len(anchors), 3)
    assert all(array.dtype == np.float32 for array in (batch.x_target, batch.x_exogenous, batch.y))
    assert batch.exogenous_feature_names == ("b", "a") and batch.target_name == "y"
    np.testing.assert_array_equal(
        batch.x_target[:, :, 0], 300 + anchors[:, None] + np.arange(-target_length, 0)
    )
    exogenous = anchors[:, None] + np.arange(-exogenous_length, 0)
    np.testing.assert_array_equal(batch.x_exogenous[:, :, 0], 200 + exogenous)
    np.testing.assert_array_equal(batch.x_exogenous[:, :, 1], 100 + exogenous)
    np.testing.assert_array_equal(batch.y, 300 + anchors[:, None] + np.arange(3))
    evidence = batch.evidence
    assert evidence.sample_count == len(anchors)
    assert evidence.anchor_rows.ranges == (RowRange(start=int(anchors[0]), stop=108),)
    assert evidence.history_lengths == (("target", target_length), ("exogenous", exogenous_length))
    assert evidence.prediction_horizon == 3 and evidence.target_offsets == (0, 1, 2)
    assert evidence.continuous_runs == (data[1].continuous_runs[1],)
    assert batch.y[-1, -1] == 409


@pytest.mark.parametrize(
    ("partition", "anchor"),
    [
        ("train", 10),
        ("train", 31),
        ("train", 35),
        ("validation", 69),
        ("validation", 108),
        ("test", 110),
        ("test", 150),
        ("test", 109),
    ],
)
def test_explicit_invalid_anchors_do_not_cross_boundaries_or_get_dropped(data, partition, anchor):
    with pytest.raises(ValueError, match="outside the effective partition"):
        timexer(data, partition=partition, requested_rows=sparse(anchor))


def test_partitions_without_full_windows_fail_and_single_tcn_train_sample_fails(data):
    series, spec = data
    no_windows = spec.split.model_copy(update={"train": (RowRange(start=0, stop=29),)})
    with pytest.raises(ValueError, match="No complete sequence windows"):
        tcn((series, spec.model_copy(update={"split": no_windows})))
    one_window = spec.split.model_copy(update={"train": (RowRange(start=0, stop=30),)})
    with pytest.raises(ValueError, match="at least two"):
        tcn((series, spec.model_copy(update={"split": one_window})))


def test_sparse_selection_preserves_anchors_across_runs(data):
    selection = sparse(13, 27, 47)
    batch = timexer(data, requested_rows=selection)
    assert batch.evidence.anchor_rows == selection.evidence
    assert batch.evidence.continuous_runs == data[1].continuous_runs[:2]
    np.testing.assert_array_equal(batch.y[:, 0], [313, 327, 347])


@pytest.mark.parametrize("anchors", [(13, 13), (27, 13)])
def test_duplicate_or_unordered_anchors_are_rejected(data, anchors):
    with pytest.raises(ValueError, match="strictly increasing"):
        timexer(data, requested_rows=sparse(*anchors))


def test_reordered_compact_view_uses_original_record_positions(data):
    series, spec = data
    positions = tuple(reversed(range(14, 28)))
    compact = replace(
        series,
        timestamps=[series.timestamps[index] for index in positions],
        values={name: values[list(positions)] for name, values in series.values.items()},
    )
    batch = timexer((compact, spec), requested_rows=sparse(25), record_positions=positions)
    assert batch.evidence.record_positions_used and batch.evidence.sample_count == 1
    np.testing.assert_array_equal(batch.x_target[0, :, 0], np.arange(317, 325))
    np.testing.assert_array_equal(batch.x_exogenous[0, :, 0], np.arange(214, 225))
    np.testing.assert_array_equal(batch.y[0], [325, 326, 327])


@pytest.mark.parametrize(
    ("positions", "reason"),
    [
        ((*range(14, 19), *range(20, 29)), "missing from the array view"),
        ((*range(14, 27), 26), "must be unique"),
    ],
)
def test_mapped_windows_reject_missing_and_duplicate_records(data, positions, reason):
    series, spec = data
    compact = replace(
        series,
        timestamps=[series.timestamps[index] for index in positions],
        values={name: values[list(positions)] for name, values in series.values.items()},
    )
    with pytest.raises(ValueError, match=reason):
        timexer((compact, spec), requested_rows=sparse(25), record_positions=positions)


@pytest.mark.parametrize(
    ("name", "index", "value"), [("b", 14, np.nan), ("y", 17, np.inf), ("y", 27, 1e40)]
)
def test_nonfinite_values_or_float32_overflow_are_rejected_in_used_records(
    data, name, index, value
):
    series, spec = data
    altered = series.values[name].copy()
    altered[index] = value
    invalid = replace(series, values={**series.values, name: altered})
    with pytest.raises(ValueError, match="finite float32"):
        timexer((invalid, spec), requested_rows=sparse(25))


def test_target_column_conflict_and_wrong_source_are_rejected(data):
    series, spec = data
    with pytest.raises(ValueError, match="separate target"):
        timexer((series, spec.model_copy(update={"input_columns": ("b", "y")})))
    with pytest.raises(ValueError, match="identities must agree"):
        build_timexer_samples(
            series,
            spec=spec,
            source=replace(source_for(spec), dataset_sha256="c" * 64),
            partition="train",
            parameters=TIMEXER,
        )


def test_time_axis_rejects_disorder_and_preserves_explicit_irregular_sampling(data):
    series, spec = data
    altered = list(series.timestamps)
    altered[15] = altered[14]
    with pytest.raises(ValueError, match="Time must increase"):
        timexer((replace(series, timestamps=altered), spec), requested_rows=sparse(25))
    altered = [time + timedelta(seconds=index // 2) for index, time in enumerate(series.timestamps)]
    irregular = replace(series, timestamps=altered)
    with pytest.raises(ValueError, match="uniform sample period"):
        timexer((irregular, spec), requested_rows=sparse(25))
    axis = spec.time_axis.model_copy(
        update={"sampling_status": "irregular", "sample_period_seconds": None}
    )
    bound = spec.model_copy(update={"time_axis": axis})
    batch = timexer((irregular, bound), requested_rows=sparse(25))
    assert batch.evidence.sampling_status == "irregular"
    np.testing.assert_array_equal(batch.y[0], [325, 326, 327])
