"""Physical CSV positions, bounded index storage and conservative provenance."""

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.models.dataset import Dataset, DatasetColumn, DatasetVersion, ProcessingRun
from app.schemas.experiment_spec import ExperimentSpec, RowSet
from app.services.experiment_spec_service import (
    bind_experiment_spec,
    compact_rows,
    iter_rows,
    spec_hash,
)
from pydantic import ValidationError


def make_data(tmp_path: Path, *, blank=False):
    dataset_id, version_id = uuid4(), uuid4()
    start = datetime(2026, 1, 1, tzinfo=UTC)
    lines = ["timestamp,u,y"] + [
        f"{(start + timedelta(seconds=i)).isoformat()},{i},{i * 2 + 1}" for i in range(30)
    ]
    if blank:
        lines.insert(8, "")
    raw = ("\n".join(lines) + "\n").encode()
    (tmp_path / "source.csv").write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    dataset = Dataset(id=dataset_id, encoding="utf-8", delimiter=",", name="test")
    version = DatasetVersion(
        id=version_id,
        dataset_id=dataset_id,
        sha256=digest,
        artifact_path="source.csv",
        row_count=30,
        parameters={},
    )
    columns = [DatasetColumn(name="u", role="input"), DatasetColumn(name="y", role="output")]
    objects = {(Dataset, dataset_id): dataset, (DatasetVersion, version_id): version}

    class Session:
        async def get(self, cls, key):
            return objects.get((cls, key))

        async def scalars(self, statement):
            return SimpleNamespace(all=lambda: columns)

    spec = ExperimentSpec.model_validate(
        {
            "task_type": "dynamic_system_identification",
            "dataset_id": dataset_id,
            "dataset_version_id": version_id,
            "dataset_version_sha256": digest,
            "row_count": 30,
            "input_columns": ["u"],
            "target_column": "y",
            "time_axis": {
                "column": "timestamp",
                "sample_period_seconds": 1,
                "sampling_status": "uniform",
            },
            "continuous_runs": [{"start": 0, "stop": 30}],
            "feature_spec": {
                "kind": "dynamic_lags",
                "input_lags": {"u": [0]},
                "target_lags": [1],
                "history_window": 1,
            },
            "split": {
                "train": [{"start": 0, "stop": 18}],
                "validation": [{"start": 18, "stop": 24}],
                "test": [{"start": 24, "stop": 30}],
                "history_guard": 1,
            },
            "evaluation": {
                "sample_indices": {"validation": {"ranges": [{"start": 19, "stop": 23}]}},
                "resolution_status": "resolved",
            },
        }
    )
    return Session(), objects, spec


def bind(session, spec, root):
    return asyncio.run(bind_experiment_spec(session, spec=spec, artifact_root=root))


def test_physical_csv_rows_and_multiple_ranges(tmp_path):
    session, _, spec = make_data(tmp_path)
    data = spec.model_dump()
    data["split"]["train"] = [{"start": 0, "stop": 8}, {"start": 10, "stop": 18}]
    bound = bind(session, ExperimentSpec.model_validate(data), tmp_path)
    assert len(bound.split.train) == 2
    assert list(iter_rows(bound.evaluation.sample_indices["validation"], tmp_path)) == [
        19,
        20,
        21,
        22,
    ]


@pytest.mark.parametrize("start,stop", [(True, 3), (-1, 3), (3, 3), (5, 4)])
def test_invalid_ranges_fail(start, stop):
    with pytest.raises(ValidationError):
        RowSet.model_validate({"ranges": [{"start": start, "stop": stop}]})


def test_ownership_sha_counts_and_partition_failures(tmp_path):
    session, _, spec = make_data(tmp_path)
    for field, value in (
        ("dataset_id", uuid4()),
        ("dataset_version_sha256", "0" * 64),
        ("row_count", 31),
    ):
        with pytest.raises(ValueError):
            bind(
                session, ExperimentSpec.model_validate(spec.model_dump() | {field: value}), tmp_path
            )
    data = spec.model_dump()
    data["split"]["validation"] = [{"start": 17, "stop": 24}]
    with pytest.raises(ValidationError):
        ExperimentSpec.model_validate(data)
    (tmp_path / "source.csv").write_bytes(b"changed")
    with pytest.raises(ValueError, match="SHA256"):
        bind(session, spec, tmp_path)


def test_blank_records_rejected_instead_of_reindexing(tmp_path):
    session, _, spec = make_data(tmp_path, blank=True)
    with pytest.raises(ValueError, match="Blank CSV"):
        bind(session, spec, tmp_path)


def test_forged_train_only_claim_is_downgraded(tmp_path):
    session, _, spec = make_data(tmp_path)
    data = spec.model_dump()
    data["leakage"] = {"status": "verified_train_only", "evidence": ["user says so"]}
    bound = bind(session, ExperimentSpec.model_validate(data), tmp_path)
    assert bound.leakage.status == "unknown"
    assert "user says so" not in bound.leakage.evidence


def test_evaluation_history_and_guard_boundaries(tmp_path):
    session, _, spec = make_data(tmp_path)
    for index in (18, 23, 24, 30):
        data = spec.model_dump()
        data["evaluation"]["sample_indices"]["validation"] = {
            "ranges": [{"start": index, "stop": index + 1}]
        }
        with pytest.raises(ValueError):
            bind(session, ExperimentSpec.model_validate(data), tmp_path)
    data = spec.model_dump()
    data["continuous_runs"] = [{"start": 0, "stop": 20}, {"start": 20, "stop": 30}]
    with pytest.raises(ValueError, match="history"):
        bind(session, ExperimentSpec.model_validate(data), tmp_path)


def test_external_indices_stream_and_validate(tmp_path):
    path = tmp_path / "rows.txt"
    raw = b"19\n20\n22\n"
    path.write_bytes(raw)
    rows = RowSet.model_validate(
        {"index_file": {"uri": "rows.txt", "sha256": hashlib.sha256(raw).hexdigest(), "count": 3}}
    )
    assert list(iter_rows(rows, tmp_path)) == [19, 20, 22]
    for updates in ({"sha256": "0" * 64}, {"count": 2}, {"uri": "../rows.txt"}):
        data = rows.model_dump()
        data["index_file"].update(updates)
        with pytest.raises(ValueError):
            list(iter_rows(RowSet.model_validate(data), tmp_path))
    path.write_bytes(b"20\n19\n")
    with pytest.raises(ValueError):
        list(iter_rows(rows, tmp_path))


def test_selected_rows_bind_exact_processing_run(tmp_path):
    session, objects, spec = make_data(tmp_path)
    run_id = uuid4()
    objects[ProcessingRun, run_id] = ProcessingRun(
        id=run_id,
        dataset_id=spec.dataset_id,
        source_version_id=spec.dataset_version_id,
        run_type="preprocessing.segment",
        status="succeeded",
        result={"selected_sample_indices": [3, 4, 5]},
    )
    data = spec.model_dump()
    data["training_selection"] = {
        "mode": "selected_rows",
        "source_run_id": run_id,
        "source_version_id": spec.dataset_version_id,
        "requested_indices": {"ranges": [{"start": 3, "stop": 6}]},
    }
    assert (
        bind(
            session, ExperimentSpec.model_validate(data), tmp_path
        ).training_selection.requested_indices.count
        == 3
    )
    objects[ProcessingRun, run_id].result = {"selected_sample_indices": [5, 6, 7]}
    with pytest.raises(ValueError):
        bind(session, ExperimentSpec.model_validate(data), tmp_path)


def test_large_contiguous_selection_is_compact():
    rows = compact_rows(iter(range(100000)))
    assert len(rows.ranges) == 1 and rows.count == 100000
    assert len(rows.model_dump_json()) < 100
    with pytest.raises(ValueError):
        compact_rows(iter([2, 2]))


def test_targetless_future_tasks_not_accidentally_enabled(tmp_path):
    _, _, spec = make_data(tmp_path)
    with pytest.raises(ValidationError):
        ExperimentSpec.model_validate(spec.model_dump() | {"target_column": None})
    data = spec.model_dump()
    data.update(task_type="supervised_regression", application="soft_sensor")
    data["feature_spec"] = {"kind": "tabular"}
    data["split"]["history_guard"] = 0
    assert ExperimentSpec.model_validate(data).application == "soft_sensor"
    assert spec_hash(spec) == spec_hash(ExperimentSpec.model_validate(spec.model_dump(mode="json")))
    assert spec_hash(spec) != spec_hash(spec.model_copy(update={"random_seed": 1}))


def test_each_continuous_run_can_restart_its_clock(tmp_path):
    session, objects, spec = make_data(tmp_path)
    raw = (tmp_path / "source.csv").read_text().splitlines()
    for i in range(15, 30):
        fields = raw[i + 1].split(",")
        fields[0] = (datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=i - 15)).isoformat()
        raw[i + 1] = ",".join(fields)
    payload = ("\n".join(raw) + "\n").encode()
    (tmp_path / "source.csv").write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    objects[DatasetVersion, spec.dataset_version_id].sha256 = digest
    data = spec.model_dump()
    data["dataset_version_sha256"] = digest
    data["continuous_runs"] = [{"start": 0, "stop": 15}, {"start": 15, "stop": 30}]
    data["split"]["train"] = [{"start": 0, "stop": 15}, {"start": 15, "stop": 18}]
    assert len(bind(session, ExperimentSpec.model_validate(data), tmp_path).continuous_runs) == 2


def test_preprocessing_claim_even_in_a_real_run_is_not_fit_evidence(tmp_path):
    session, objects, spec = make_data(tmp_path)
    parent_id, run_id = uuid4(), uuid4()
    parent = DatasetVersion(id=parent_id, dataset_id=spec.dataset_id, row_count=30)
    objects[DatasetVersion, parent_id] = parent
    objects[DatasetVersion, spec.dataset_version_id].parent_version_id = parent_id
    run = ProcessingRun(
        id=run_id,
        dataset_id=spec.dataset_id,
        source_version_id=parent_id,
        run_type="preprocessing.clean",
        status="succeeded",
        result={"result_version_id": str(spec.dataset_version_id)},
        parameters={"fit_partition": "train"},
    )
    objects[ProcessingRun, run_id] = run
    data = spec.model_dump()
    data["preprocessing"] = [
        {
            "operation": "preprocessing.clean",
            "parameters": {"fit_partition": "train"},
            "source_version_id": parent_id,
            "result_version_id": spec.dataset_version_id,
            "source_run_id": run_id,
            "fit_partition": "train",
        }
    ]
    data["leakage"] = {"status": "verified_train_only", "evidence": [str(run_id)]}
    assert bind(session, ExperimentSpec.model_validate(data), tmp_path).leakage.status == "unknown"
    run.result = {"result_version_id": str(parent_id)}
    with pytest.raises(ValueError, match="lineage"):
        bind(session, ExperimentSpec.model_validate(data), tmp_path)


def test_index_file_and_ranges_cannot_be_combined():
    with pytest.raises(ValidationError):
        RowSet.model_validate(
            {
                "ranges": [{"start": 0, "stop": 2}],
                "index_file": {"uri": "rows.txt", "sha256": "0" * 64, "count": 2},
            }
        )


@pytest.mark.parametrize("partition", ["train", "validation", "test"])
def test_qa_unresolved_partitions_must_be_covered(tmp_path, partition):
    session, _, spec = make_data(tmp_path)
    data = spec.model_dump()
    data["evaluation"] = {"resolution_status": "unresolved"}
    data["continuous_runs"] = [
        {"start": 0, "stop": 18},
        {"start": 18, "stop": 24},
        {"start": 24, "stop": 30},
    ]
    index = ["train", "validation", "test"].index(partition)
    data["continuous_runs"][index]["start"] += 1
    with pytest.raises(ValueError, match="continuous"):
        bind(session, ExperimentSpec.model_validate(data), tmp_path)


def test_qa_no_partition_may_span_adjacent_runs(tmp_path):
    session, _, spec = make_data(tmp_path)
    data = spec.model_dump()
    data["evaluation"] = {"resolution_status": "unresolved"}
    data["continuous_runs"] = [{"start": 0, "stop": 10}, {"start": 10, "stop": 30}]
    with pytest.raises(ValueError, match="continuous"):
        bind(session, ExperimentSpec.model_validate(data), tmp_path)


def test_qa_multiple_train_ranges_have_explicit_history_exclusion(tmp_path):
    from app.services.experiment_spec_service import effective_ranges

    session, _, spec = make_data(tmp_path)
    data = spec.model_dump()
    data["continuous_runs"] = [{"start": 0, "stop": 10}, {"start": 10, "stop": 30}]
    data["split"]["train"] = [{"start": 0, "stop": 10}, {"start": 10, "stop": 18}]
    bound = bind(session, ExperimentSpec.model_validate(data), tmp_path)
    assert [(r.start, r.stop) for r in effective_ranges(bound, "train")] == [(1, 9), (11, 17)]


def test_qa_continuous_run_overlap_is_rejected(tmp_path):
    _, _, spec = make_data(tmp_path)
    data = spec.model_dump()
    data["continuous_runs"] = [{"start": 0, "stop": 20}, {"start": 19, "stop": 30}]
    with pytest.raises(ValidationError):
        ExperimentSpec.model_validate(data)


@pytest.mark.parametrize("horizon", [2, 5])
def test_qa_unimplemented_horizons_are_rejected(tmp_path, horizon):
    _, _, spec = make_data(tmp_path)
    data = spec.model_dump()
    data["feature_spec"]["prediction_horizon"] = horizon
    with pytest.raises(ValidationError, match="prediction_horizon"):
        ExperimentSpec.model_validate(data)


def test_qa_regression_guard_cannot_be_silently_ignored(tmp_path):
    session, _, spec = make_data(tmp_path)
    data = spec.model_dump()
    data.update(task_type="supervised_regression", application="soft_sensor")
    data["feature_spec"] = {"kind": "tabular"}
    data["split"]["history_guard"] = 0
    assert bind(session, ExperimentSpec.model_validate(data), tmp_path).split.history_guard == 0
    data["split"]["history_guard"] = 1
    with pytest.raises(ValidationError, match="guard"):
        ExperimentSpec.model_validate(data)


@pytest.mark.parametrize("column", ["u", "y"])
def test_qa_nonfinite_lagged_features_are_rejected(tmp_path, column):
    session, objects, spec = make_data(tmp_path)
    lines = (tmp_path / "source.csv").read_text().splitlines()
    fields = lines[19].split(",")  # data row 18, used by prediction target row 19
    fields[1 if column == "u" else 2] = ""
    lines[19] = ",".join(fields)
    raw = ("\n".join(lines) + "\n").encode()
    (tmp_path / "source.csv").write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    objects[DatasetVersion, spec.dataset_version_id].sha256 = digest
    data = spec.model_dump()
    data["dataset_version_sha256"] = digest
    data["feature_spec"]["input_lags"] = {"u": [1]}
    with pytest.raises(ValueError, match="nonfinite"):
        bind(session, ExperimentSpec.model_validate(data), tmp_path)


def test_qa_feature_history_can_start_exactly_at_run_start(tmp_path):
    session, _, spec = make_data(tmp_path)
    data = spec.model_dump()
    data["continuous_runs"] = [
        {"start": 0, "stop": 18},
        {"start": 18, "stop": 24},
        {"start": 24, "stop": 30},
    ]
    data["feature_spec"]["input_lags"] = {"u": [1]}
    bound = bind(session, ExperimentSpec.model_validate(data), tmp_path)
    assert bound.evaluation.sample_indices["validation"].ranges[0].start == 19
    data["evaluation"]["sample_indices"]["validation"] = {"ranges": [{"start": 18, "stop": 19}]}
    with pytest.raises(ValueError, match="partition|boundary"):
        bind(session, ExperimentSpec.model_validate(data), tmp_path)
