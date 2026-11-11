"""Static samples retain version-local CSV identity through row selection."""

from dataclasses import replace
from uuid import uuid4

import numpy as np
import pytest
from app.schemas.experiment_spec import ExperimentSpec, IndexFile, RowRange, RowSet
from app.services.experiment_spec_service import spec_hash
from app.services.model_data_adapter import BoundSource, ResolvedRows, build_table_samples
from app.services.version_data import VersionSeries


@pytest.fixture
def data():
    spec = ExperimentSpec.model_validate(
        {
            "task_type": "supervised_regression",
            "dataset_id": uuid4(),
            "dataset_version_id": uuid4(),
            "dataset_version_sha256": "a" * 64,
            "row_count": 14,
            "input_columns": ("flow", "pressure"),
            "target_column": "target",
            "continuous_runs": [
                {"start": 0, "stop": 4},
                {"start": 4, "stop": 8},
                {"start": 9, "stop": 14},
            ],
            "feature_spec": {"kind": "tabular", "input_lags": {"flow": [0]}},
            "split": {
                "train": [
                    {"start": 1, "stop": 4},
                    {"start": 4, "stop": 6},
                    {"start": 9, "stop": 10},
                ],
                "validation": [{"start": 10, "stop": 12}],
                "test": [{"start": 12, "stop": 14}],
            },
        }
    )
    rows = np.arange(spec.row_count, dtype=float)
    series = VersionSeries(
        dataset_id=spec.dataset_id,
        version_id=spec.dataset_version_id,
        dataset_name="in-memory",
        origin="dataset",
        timestamps=[],
        values={"pressure": 200 + rows, "target": 300 + rows, "flow": 100 + rows},
        declared_inputs=("pressure", "flow"),
        declared_output="target",
        sample_period_seconds=None,
    )
    return series, spec


def build(data, *, partition="train", **kwargs):
    series, spec = data
    source = BoundSource(
        spec.dataset_id, spec.dataset_version_id, spec.dataset_version_sha256, spec_hash(spec)
    )
    return build_table_samples(series, spec=spec, source=source, partition=partition, **kwargs)


def sparse(*records, count=None):
    return ResolvedRows(
        RowSet(
            index_file=IndexFile(
                uri="rows.txt", sha256="b" * 64, count=count if count is not None else len(records)
            )
        ),
        records,
    )


def assert_samples(batch, records):
    np.testing.assert_array_equal(batch.inputs.x, [(100 + r, 200 + r) for r in records])
    np.testing.assert_array_equal(batch.y, [300 + r for r in records])
    assert batch.inputs.feature_names == ("flow", "pressure")
    assert batch.target_name == "target"
    assert batch.inputs.x.shape[0] == batch.y.shape[0] == batch.evidence.anchor_rows.count
    (horizon,) = batch.evidence.targets_by_horizon
    assert horizon.step == 1
    assert horizon.target_rows == batch.evidence.anchor_rows
    assert batch.evidence.history_lengths == ()
    assert batch.evidence.rule_version == "static_tabular_v1"


@pytest.mark.parametrize(
    ("partition", "records"),
    [("train", (1, 2, 3, 4, 5, 9)), ("validation", (10, 11)), ("test", (12, 13))],
)
def test_default_selection_uses_each_partition_and_preserves_ranges(data, partition, records):
    batch = build(data, partition=partition, requested_rows=None)
    assert_samples(batch, records)
    spec = data[1]
    assert batch.evidence.partition == partition
    assert batch.evidence.anchor_rows.ranges == getattr(spec.split, partition)
    assert batch.evidence.source.experiment_spec_hash == spec_hash(spec)


def test_explicit_ranges_select_exact_records(data):
    selection = ResolvedRows(RowSet(ranges=(RowRange(start=2, stop=4), RowRange(start=9, stop=10))))
    batch = build(data, requested_rows=selection)
    assert_samples(batch, (2, 3, 9))
    assert batch.evidence.anchor_rows == selection.evidence


def test_verified_sparse_selection_uses_original_records_in_reordered_compact_view(data):
    series, spec = data
    positions = (9, 2, 5, 1)
    compact = replace(
        series, values={name: values[list(positions)] for name, values in series.values.items()}
    )
    selection = sparse(1, 5, 9)
    batch = build((compact, spec), requested_rows=selection, record_positions=positions)
    assert_samples(batch, (1, 5, 9))
    assert batch.evidence.anchor_rows == selection.evidence


@pytest.mark.parametrize("records", [(), (1, 1), (5, 1), (True, 2), (-1, 2), (1,)])
def test_empty_duplicate_unsorted_or_inconsistent_sparse_rows_are_rejected(data, records):
    with pytest.raises(ValueError, match="strictly increasing"):
        build(data, requested_rows=sparse(*records, count=2))


def test_explicit_empty_range_selection_does_not_fall_back(data):
    selection = ResolvedRows(RowSet.model_construct())
    with pytest.raises(ValueError, match="Specify nonempty ranges"):
        build(data, requested_rows=selection)


@pytest.mark.parametrize("record", [0, 8, 10, 12, 14])
def test_rows_outside_train_are_rejected(data, record):
    with pytest.raises(ValueError, match="outside the effective partition"):
        build(data, requested_rows=sparse(record))


def test_requested_range_cannot_cross_adjacent_runs(data):
    selection = ResolvedRows(RowSet(ranges=(RowRange(start=3, stop=5),)))
    with pytest.raises(ValueError, match="continuous-run boundary"):
        build(data, requested_rows=selection)


def test_nominal_partition_cannot_cross_adjacent_runs(data):
    series, spec = data
    split = spec.split.model_copy(update={"train": (RowRange(start=1, stop=5),)})
    with pytest.raises(ValueError, match="continuous run"):
        build((series, spec.model_copy(update={"split": split})))


@pytest.mark.parametrize("positions", [(1, 1), (1, 14), (1, 2)])
def test_invalid_record_mapping_is_rejected(data, positions):
    series, spec = data
    compact = replace(series, values={name: values[:2] for name, values in series.values.items()})
    with pytest.raises(ValueError, match="record positions|selected CSV record"):
        build((compact, spec), requested_rows=sparse(1, 5), record_positions=positions)


def test_compact_data_requires_an_explicit_record_mapping(data):
    series, spec = data
    compact = replace(series, values={name: values[:2] for name, values in series.values.items()})
    with pytest.raises(ValueError, match="aligned column"):
        build((compact, spec), requested_rows=sparse(1))


@pytest.mark.parametrize("names", [("flow", "flow"), ("target", "flow"), (" ",), ("missing",)])
def test_invalid_feature_names_are_rejected(data, names):
    series, spec = data
    with pytest.raises(ValueError):
        build((series, spec.model_copy(update={"input_columns": names})))


def test_resolved_feature_order_must_match_spec(data, monkeypatch):
    monkeypatch.setattr(
        VersionSeries, "resolve_columns", lambda *args, **kwargs: (["pressure", "flow"], "target")
    )
    with pytest.raises(ValueError, match="feature order"):
        build(data)


@pytest.mark.parametrize(
    ("column", "change", "message"),
    [
        ("flow", lambda x: np.full_like(x, np.nan), "finite"),
        ("target", lambda x: np.full_like(x, np.inf), "finite"),
        ("flow", lambda x: x.astype(str), "numeric"),
        ("flow", lambda x: x.astype(bool), "numeric"),
        ("pressure", lambda x: x[:, None], "aligned column"),
        ("target", lambda x: x[:-1], "aligned column"),
        ("target", lambda x: x[:0], "aligned column"),
    ],
)
def test_invalid_columns_are_rejected_without_filtering(data, column, change, message):
    series, spec = data
    changed = replace(series, values={**series.values, column: change(series.values[column])})
    with pytest.raises(ValueError, match=message):
        build((changed, spec))


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": "dynamic_lags"},
        {"history_window": 1, "input_lags": {"flow": (1,)}},
        {"initialization_policy": "past_residual"},
    ],
)
def test_dynamic_or_history_features_are_rejected(data, changes):
    series, spec = data
    updated = spec.feature_spec.model_copy(update=changes)
    with pytest.raises(ValueError, match="Static tabular regression"):
        build((series, spec.model_copy(update={"feature_spec": updated})))


def test_mismatched_version_identity_is_rejected(data):
    series, spec = data
    with pytest.raises(ValueError, match="identities must agree"):
        build((replace(series, version_id=uuid4()), spec))


@pytest.mark.parametrize("field", ["dataset_sha256", "experiment_spec_hash"])
def test_mismatched_source_digest_is_rejected(data, field):
    series, spec = data
    source = BoundSource(
        spec.dataset_id, spec.dataset_version_id, spec.dataset_version_sha256, spec_hash(spec)
    )
    with pytest.raises(ValueError, match="identities must agree"):
        build_table_samples(
            series, spec=spec, source=replace(source, **{field: "c" * 64}), partition="train"
        )


def test_invalid_held_out_value_is_never_consumed_by_train(data):
    series, spec = data
    flow = series.values["flow"].copy()
    flow[10] = np.nan
    changed = replace(series, values={**series.values, "flow": flow})
    assert_samples(build((changed, spec)), (1, 2, 3, 4, 5, 9))
    with pytest.raises(ValueError, match="finite"):
        build((changed, spec), partition="validation")
