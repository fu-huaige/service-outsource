"""Fixed PLS evaluation, immutable model provenance and isolated run history."""

import hashlib
import json
from dataclasses import replace
from uuid import uuid4

import numpy as np
import pytest
import pytest_asyncio
from app.models.dataset import DatasetVersion, ProcessingRun
from app.schemas.experiment_spec import EvaluationSpec, RowSet
from app.schemas.pls import PLSEvaluationRequest, PLSParameters
from app.services import pls_evaluation_service as evaluation
from app.services import pls_training_service as training
from app.services.model_artifact_service import load_model_instance
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from test_pls_training_service import data as data

pytestmark = pytest.mark.asyncio


async def prepare(data, mutate=None):
    document = data["spec"].model_dump(mode="json")
    document["evaluation"]["scopes"] = ["validation", "test"]
    if mutate:
        mutate(document)
    from app.schemas.experiment_spec import ExperimentSpec

    result = await training.fit_pls_with_manifest(
        data["factory"],
        spec=ExperimentSpec.model_validate(document),
        artifact_root=data["root"],
        parameters=PLSParameters(),
    )
    assert result.manifest_status == "published"
    async with data["factory"]() as session:
        return await load_model_instance(
            session, model_id=result.model_id, artifact_root=data["root"]
        )


@pytest_asyncio.fixture
async def saved(data):
    return await prepare(data)


async def evaluate(data, saved, partition="validation", **assertions):
    return await evaluation.evaluate_saved_pls_model(
        data["factory"],
        artifact_root=data["root"],
        request=PLSEvaluationRequest(model_id=saved.model_id, partition=partition, **assertions),
    )


async def records(data):
    async with data["factory"]() as session:
        return list(
            (
                await session.scalars(
                    select(ProcessingRun).where(ProcessingRun.run_type == "modeling.pls_evaluation")
                )
            ).all()
        )


@pytest.mark.parametrize("partition,start,stop", [("validation", 24, 32), ("test", 32, 40)])
async def test_fixed_model_metrics_identity_and_immutable_inputs(
    data, saved, monkeypatch, partition, start, stop
):
    from app.services import pls_modeling_service as core
    from sklearn.cross_decomposition import PLSRegression

    before = {str(p): p.read_bytes() for p in (data["root"] / "models").rglob("*") if p.is_file()}
    async with data["factory"]() as session:
        original = await session.get(ProcessingRun, saved.training_run_id)
        training_before = json.loads(json.dumps(original.result))
    x, y = data["x"][start:stop, ::-1], data["y"][start:stop]
    prediction = saved.payload.predict(x)

    def forbidden(*args, **kwargs):
        raise AssertionError("Evaluation must never fit or prepare training data")

    monkeypatch.setattr(PLSRegression, "fit", forbidden)
    monkeypatch.setattr(core, "fit_pls_core", forbidden)
    for name in (
        "fit_pls_core",
        "fit_pls_on_version",
        "fit_pls_with_manifest",
        "_prepare_training",
    ):
        monkeypatch.setattr(training, name, forbidden)
    result = await evaluate(data, saved, partition)
    assert result.model_id == saved.model_id and result.training_run_id == saved.training_run_id
    assert result.evaluation_run_id not in (saved.model_id, saved.training_run_id)
    assert result.sample_count == result.evaluation_rows.count == stop - start
    assert result.evaluation_rows.ranges[0].start == start
    assert result.evaluation_rows.ranges[0].stop == stop
    residual = y - prediction
    assert result.metrics.rmse == pytest.approx(np.sqrt(np.mean(residual**2)))
    assert result.metrics.mae == pytest.approx(np.mean(abs(residual)))
    assert result.metrics.r2 == pytest.approx(1 - np.sum(residual**2) / np.sum((y - y.mean()) ** 2))
    assert result.metrics.nrmse == pytest.approx(
        np.sqrt(np.mean(residual**2)) / (np.percentile(y, 95) - np.percentile(y, 5))
    )
    assert set(result.metrics.model_dump()) == {"r2", "rmse", "mae", "nrmse"}
    assert before == {
        str(p): p.read_bytes() for p in (data["root"] / "models").rglob("*") if p.is_file()
    }
    async with data["factory"]() as session:
        assert (await session.get(ProcessingRun, saved.training_run_id)).result == training_before
    run = (await records(data))[0]
    assert run.id == result.evaluation_run_id and run.status == "succeeded"
    assert run.source_version_id == data["spec"].dataset_version_id
    assert run.result["evaluation_rows"] == result.evaluation_rows.model_dump(mode="json")
    assert "y_pred" not in run.result and "y_true" not in run.result
    assert run.result["evaluation_status"] == "succeeded"


@pytest.mark.parametrize(
    "assertion", ["training_run_id", "dataset_id", "dataset_version_id", "dataset_sha256"]
)
async def test_assertions_cannot_replace_model_source(data, saved, assertion):
    value = "0" * 64 if assertion == "dataset_sha256" else uuid4()
    with pytest.raises(evaluation.PLSEvaluationError):
        await evaluate(data, saved, **{assertion: value})
    run = (await records(data))[0]
    assert run.status == "failed" and run.result["failure_stage"] == "load_model"


async def test_missing_model_is_a_failed_independent_evaluation(data):
    identity = uuid4()
    with pytest.raises(evaluation.PLSEvaluationError) as caught:
        await evaluation.evaluate_saved_pls_model(
            data["factory"],
            artifact_root=data["root"],
            request=PLSEvaluationRequest(model_id=identity, partition="validation"),
        )
    run = (await records(data))[0]
    assert run.id == caught.value.evaluation_run_id and run.status == "failed"
    assert run.result["model_id"] == str(identity)


@pytest.mark.parametrize(
    "kind", ["manifest", "training_status", "sha", "not_pls", "feature_order", "target"]
)
async def test_invalid_model_or_source_is_rejected(data, saved, monkeypatch, kind):
    if kind == "manifest":
        (data["root"] / "models" / f"{saved.model_id}.manifest.json").write_text("{")
    elif kind == "training_status":
        async with data["factory"]() as session:
            run = await session.get(ProcessingRun, saved.training_run_id)
            run.status = "running"
            await session.commit()
    elif kind == "sha":
        path = data["root"] / "source.csv"
        path.write_bytes(path.read_bytes() + b"\n")
    else:
        altered = saved
        if kind == "not_pls":
            altered = replace(saved, model_type_id="arx")
        else:
            changes = (
                {"feature_names": ("a", "b")} if kind == "feature_order" else {"target_name": "a"}
            )
            payload = replace(
                saved.payload, metadata=saved.payload.metadata.model_copy(update=changes)
            )
            altered = replace(saved, payload=payload)

        async def wrong(*args, **kwargs):
            return altered

        monkeypatch.setattr(evaluation, "load_model_instance", wrong)
    with pytest.raises(evaluation.PLSEvaluationError):
        await evaluate(data, saved)
    assert (await records(data))[0].status == "failed"


async def test_test_scope_must_have_been_declared(data):
    saved = await prepare(data, lambda d: d["evaluation"].update(scopes=["validation"]))
    with pytest.raises(evaluation.PLSEvaluationError):
        await evaluate(data, saved, "test")
    assert (await records(data))[0].status == "failed"


async def test_explicit_rows_are_used_exactly(data):
    def mutate(d):
        d["evaluation"]["sample_indices"] = {"validation": {"ranges": [{"start": 25, "stop": 27}]}}

    saved = await prepare(data, mutate)
    result = await evaluate(data, saved)
    assert result.sample_count == 2
    assert result.evaluation_rows.model_dump(mode="json")["ranges"] == [{"start": 25, "stop": 27}]


@pytest.mark.parametrize("start,stop", [(0, 4), (30, 35), (32, 35)])
async def test_disallowed_rows_fail_without_relabelling_partitions(data, start, stop):
    spec = data["spec"].model_copy(
        update={
            "evaluation": EvaluationSpec(
                scopes=("validation", "test"),
                prediction_modes=("prediction",),
                sample_indices={
                    "validation": RowSet.model_validate(
                        {"ranges": [{"start": start, "stop": stop}]}
                    )
                },
            )
        }
    )
    with pytest.raises(ValueError):
        evaluation._evaluation_rows(
            spec, RowSet(ranges=spec.split.train), "validation", data["root"]
        )


async def test_adjacent_evaluation_runs_keep_separate_boundaries(data):
    def mutate(d):
        d["continuous_runs"] = [
            {"start": 0, "stop": 12},
            {"start": 12, "stop": 28},
            {"start": 28, "stop": 40},
        ]
        d["split"]["validation"] = [{"start": 24, "stop": 28}, {"start": 28, "stop": 32}]

    saved = await prepare(data, mutate)
    result = await evaluate(data, saved)
    assert [(r.start, r.stop) for r in result.evaluation_rows.ranges] == [(24, 28), (28, 32)]


@pytest.mark.parametrize("value", [np.nan, np.inf])
async def test_nonfinite_evaluation_rows_are_not_filtered(data, saved, monkeypatch, value):
    original = evaluation.load_version_series

    async def invalid(*args, **kwargs):
        series = await original(*args, **kwargs)
        values = {name: array.copy() for name, array in series.values.items()}
        values["b"][25] = value
        return replace(series, values=values)

    monkeypatch.setattr(evaluation, "load_version_series", invalid)
    with pytest.raises(evaluation.PLSEvaluationError):
        await evaluate(data, saved)
    assert (await records(data))[0].result["failure_stage"] == "read_data"


async def test_file_digest_is_rechecked_after_data_read(data, saved, monkeypatch):
    original = evaluation.load_version_series

    async def changed(*args, **kwargs):
        series = await original(*args, **kwargs)
        path = data["root"] / "source.csv"
        path.write_bytes(path.read_bytes() + b"\n")
        return series

    monkeypatch.setattr(evaluation, "load_version_series", changed)
    with pytest.raises(evaluation.PLSEvaluationError):
        await evaluate(data, saved)
    assert (await records(data))[0].status == "failed"


@pytest.mark.parametrize("stage", ["predict", "metrics"])
async def test_stage_failures_never_mark_success(data, saved, monkeypatch, stage):
    if stage == "predict":

        def fail(*args, **kwargs):
            raise RuntimeError("Injected predict failure")

        monkeypatch.setattr(type(saved.payload), "predict", fail)
    else:
        monkeypatch.setattr(
            evaluation,
            "_scores",
            lambda *a, **k: {"r2": np.nan, "rmse": 1.0, "mae": 1.0, "nrmse": 1.0},
        )
    with pytest.raises(evaluation.PLSEvaluationError):
        await evaluate(data, saved)
    run = (await records(data))[0]
    assert run.status == "failed" and run.result["failure_stage"] == stage


@pytest.mark.parametrize("committed", [False, True])
async def test_final_commit_is_reconciled_independently(data, saved, monkeypatch, committed):
    original = AsyncSession.commit

    async def failed(self):
        if any(
            isinstance(r, ProcessingRun)
            and r.run_type == "modeling.pls_evaluation"
            and r.status == "succeeded"
            for r in self.dirty
        ):
            if committed:
                await original(self)
            raise OSError("Injected final commit acknowledgement failure")
        return await original(self)

    monkeypatch.setattr(AsyncSession, "commit", failed)
    with pytest.raises(evaluation.PLSEvaluationError) as caught:
        await evaluate(data, saved)
    run = (await records(data))[0]
    assert run.status == ("succeeded" if committed else "failed")
    assert caught.value.outcome == ("succeeded_confirmed" if committed else "failed")


async def test_history_pagination_filters_and_model_isolation(data, saved):
    first = await evaluate(data, saved)
    second = await evaluate(data, saved, "test")
    with pytest.raises(evaluation.PLSEvaluationError):
        await evaluate(data, saved, "test", training_run_id=uuid4())
    other = await prepare(data)
    await evaluate(data, other)
    async with data["factory"]() as session:
        history = await evaluation.list_pls_evaluations(session, model_id=saved.model_id, limit=1)
        assert history.total == 3 and len(history.items) == 1
        assert history.items[0].model_id == saved.model_id
        page = await evaluation.list_pls_evaluations(
            session, model_id=saved.model_id, offset=1, limit=1
        )
        assert page.items[0].evaluation_run_id != history.items[0].evaluation_run_id
        good = await evaluation.list_pls_evaluations(
            session, model_id=saved.model_id, partition="test", status="succeeded"
        )
        assert good.total == 1 and good.items[0].evaluation_run_id == second.evaluation_run_id
    assert first.evaluation_run_id != second.evaluation_run_id


async def test_request_schema_cannot_override_experiment_or_rows():
    for extra in ({"experiment_spec": {}}, {"evaluation_rows": {}}, {"partition": "train"}):
        with pytest.raises(ValidationError):
            PLSEvaluationRequest.model_validate(
                {"model_id": uuid4(), "partition": "validation", **extra}
            )


async def rewrite_targets(data, values):
    path = data["root"] / "source.csv"
    lines = path.read_text().splitlines()
    for row, value in values.items():
        cells = lines[row + 1].split(",")
        cells[-1] = str(value)
        lines[row + 1] = ",".join(cells)
    raw = ("\n".join(lines) + "\n").encode()
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    async with data["factory"]() as session:
        version = await session.get(DatasetVersion, data["spec"].dataset_version_id)
        version.sha256 = digest
        await session.commit()
    data["spec"] = data["spec"].model_copy(update={"dataset_version_sha256": digest})


@pytest.mark.parametrize("near_constant", [False, True])
async def test_constant_and_numerically_degenerate_targets_keep_existing_metric_semantics(
    data, near_constant
):
    values = {row: (1e9 + (row - 24) * 1e-8 if near_constant else 5.0) for row in range(24, 32)}
    await rewrite_targets(data, values)
    saved = await prepare(data)
    result = await evaluate(data, saved)
    assert result.metrics.r2 is None and result.metrics.nrmse is None
    assert result.metrics.rmse is not None and result.metrics.mae is not None
    assert result.sample_count == 8


async def test_sparse_index_rows_are_fully_bound_and_persisted(data):
    raw = b"25\n27\n31\n"
    (data["root"] / "eval-rows.txt").write_bytes(raw)

    def mutate(d):
        d["evaluation"]["sample_indices"] = {
            "validation": {
                "index_file": {
                    "uri": "eval-rows.txt",
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "count": 3,
                }
            }
        }

    saved = await prepare(data, mutate)
    result = await evaluate(data, saved)
    assert result.sample_count == 3 and result.evaluation_rows.index_file.count == 3
    assert result.evaluation_rows.index_file.sha256 == hashlib.sha256(raw).hexdigest()


async def test_cross_run_and_empty_evaluation_rows_are_rejected(data):
    document = data["spec"].model_dump(mode="json")
    document["continuous_runs"] = [
        {"start": 0, "stop": 12},
        {"start": 12, "stop": 28},
        {"start": 28, "stop": 40},
    ]
    document["split"]["validation"] = [{"start": 24, "stop": 28}, {"start": 28, "stop": 32}]
    document["evaluation"]["sample_indices"] = {
        "validation": {"ranges": [{"start": 24, "stop": 32}]}
    }
    from app.schemas.experiment_spec import ExperimentSpec

    spec = ExperimentSpec.model_validate(document)
    with pytest.raises(ValueError, match="continuous run"):
        evaluation._evaluation_rows(
            spec, RowSet(ranges=spec.split.train), "validation", data["root"]
        )
    spec.evaluation.sample_indices["validation"] = RowSet.model_construct(
        ranges=(), index_file=None
    )
    with pytest.raises(ValueError):
        evaluation._evaluation_rows(
            spec, RowSet(ranges=spec.split.train), "validation", data["root"]
        )


async def test_evaluation_cannot_overlap_actual_training_evidence(data):
    actual_train = RowSet.model_validate({"ranges": [{"start": 25, "stop": 27}]})
    with pytest.raises(ValueError, match="overlaps"):
        evaluation._evaluation_rows(data["spec"], actual_train, "validation", data["root"])


async def test_running_evaluation_is_durable_before_loading_model(data, saved, monkeypatch):
    original = evaluation.load_model_instance
    seen = []

    async def checked(*args, **kwargs):
        visible = await records(data)
        seen.extend((r.status, r.run_type) for r in visible)
        return await original(*args, **kwargs)

    monkeypatch.setattr(evaluation, "load_model_instance", checked)
    await evaluate(data, saved)
    assert seen == [("running", "modeling.pls_evaluation")]


@pytest.mark.parametrize("committed", [False, True])
async def test_initial_commit_failure_never_evaluates(data, saved, monkeypatch, committed):
    original = AsyncSession.commit

    async def failed(self):
        creating = any(
            isinstance(r, ProcessingRun) and r.run_type == "modeling.pls_evaluation"
            for r in self.new
        )
        if creating:
            if committed:
                await original(self)
            raise OSError("Injected initial commit failure")
        return await original(self)

    monkeypatch.setattr(AsyncSession, "commit", failed)

    async def forbidden(*args, **kwargs):
        raise AssertionError("No load after failed creation")

    monkeypatch.setattr(evaluation, "load_model_instance", forbidden)
    with pytest.raises(evaluation.PLSEvaluationError) as caught:
        await evaluate(data, saved)
    assert caught.value.stage == "create_run"
    visible = await records(data)
    assert (len(visible) == 1 and visible[0].status == "failed") if committed else visible == []


async def test_unavailable_database_does_not_turn_uncertain_commit_into_success(
    data, saved, monkeypatch
):
    original = AsyncSession.commit

    async def failed(self):
        if any(
            isinstance(r, ProcessingRun)
            and r.run_type == "modeling.pls_evaluation"
            and r.status == "succeeded"
            for r in self.dirty
        ):
            raise OSError("Commit unavailable")
        return await original(self)

    monkeypatch.setattr(AsyncSession, "commit", failed)
    calls = []

    def factory():
        calls.append(len(calls) + 1)
        if len(calls) == 4:
            raise OSError("Reconciliation unavailable")
        return data["factory"]()

    with pytest.raises(evaluation.PLSEvaluationError) as caught:
        await evaluation.evaluate_saved_pls_model(
            factory,
            request=PLSEvaluationRequest(model_id=saved.model_id, partition="validation"),
            artifact_root=data["root"],
        )
    assert caught.value.outcome == "unconfirmed" and len(calls) == 4
    assert (await records(data))[0].status == "running"


@pytest.mark.parametrize("kind", ["shape", "nan", "inf"])
async def test_invalid_prediction_is_rejected_before_metrics(data, saved, monkeypatch, kind):
    def wrong(self, x, **kwargs):
        if kind == "shape":
            return np.zeros((x.shape[0], 1))
        return np.full(x.shape[0], np.nan if kind == "nan" else np.inf)

    monkeypatch.setattr(type(saved.payload), "predict", wrong)
    with pytest.raises(evaluation.PLSEvaluationError):
        await evaluate(data, saved)
    assert (await records(data))[0].result["failure_stage"] == "predict"


@pytest.mark.parametrize(
    "query",
    [
        {"offset": -1},
        {"limit": 0},
        {"limit": 101},
        {"offset": True},
        {"partition": "train"},
        {"status": "unknown"},
    ],
)
async def test_history_query_has_bounded_strict_pagination(data, query):
    async with data["factory"]() as session:
        with pytest.raises(ValidationError):
            await evaluation.list_pls_evaluations(session, model_id=uuid4(), **query)
