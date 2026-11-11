"""Fixed evaluation against synthetic version-bound models in isolated SQLite."""

import hashlib
from dataclasses import replace
from uuid import uuid4

import numpy as np
import pytest
from app.models.dataset import ProcessingRun
from app.schemas.experiment_spec import ExperimentSpec, RowRange, RowSet
from app.schemas.model_evaluation import ModelEvaluationRequest, RegressionMetrics
from app.schemas.xgboost import XGBoostParameters
from app.services import model_evaluation_service as evaluation
from app.services import (
    pls_training_service,
    tcn_modeling_service,
    tcn_platform_adapter,
    xgboost_platform_adapter,
)
from app.services.model_data_adapter import ResolvedRows
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from test_pls_evaluation_service import prepare
from test_pls_training_service import data as data
from test_pls_training_service import runs
from test_tcn_platform import data as tcn_platform_data
from test_tcn_platform import fit as fit_tcn
from test_tcn_platform import no_training

pytestmark = pytest.mark.asyncio
tcn_data = tcn_platform_data


def forbid_fit(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Fixed evaluation must not fit or publish a model")

    monkeypatch.setattr(pls_training_service, "fit_pls_core", forbidden)
    monkeypatch.setattr(xgboost_platform_adapter, "fit_xgboost_core", forbidden)
    monkeypatch.setattr(pls_training_service, "retry_pls_manifest", forbidden)
    monkeypatch.setattr(xgboost_platform_adapter, "retry_xgboost_manifest", forbidden)


async def evaluate(data, model_id, partition="validation", *, factory=None):
    return await evaluation.evaluate_saved_model(
        factory or data["factory"],
        request=ModelEvaluationRequest(model_id=model_id, partition=partition),
        artifact_root=data["root"],
    )


async def evaluation_runs(data):
    return [run for run in await runs(data) if run.run_type == evaluation.RUN_TYPE]


def snapshot_files(root):
    return {path: path.read_bytes() for path in (root / "models").rglob("*") if path.is_file()}


@pytest.mark.parametrize(("model_type", "partition"), [("pls", "validation"), ("xgboost", "test")])
async def test_fixed_models_use_bound_rows_and_keep_training_immutable(
    data, monkeypatch, model_type, partition
):
    if model_type == "pls":
        instance = await prepare(data)
    else:
        spec = data["spec"]
        spec = spec.model_copy(
            update={
                "evaluation": spec.evaluation.model_copy(
                    update={
                        "scopes": ("validation", "test"),
                        "prediction_modes": ("one_step", "free_run"),
                    }
                )
            }
        )
        fit = await xgboost_platform_adapter.fit_xgboost_on_version(
            data["factory"],
            spec=spec,
            parameters=XGBoostParameters(num_boost_round=5),
            artifact_root=data["root"],
        )
        assert fit.manifest_status == "published"
        async with data["factory"]() as session:
            instance = await evaluation.load_model_instance(
                session, model_id=fit.model_id, artifact_root=data["root"]
            )

    (training,) = await runs(data)
    before = snapshot_files(data["root"])
    forbid_fit(monkeypatch)
    load = evaluation.load_model_instance

    async def check_running(*args, **kwargs):
        records = await evaluation_runs(data)
        assert sum(run.status == "running" for run in records) == 1
        return await load(*args, **kwargs)

    monkeypatch.setattr(evaluation, "load_model_instance", check_running)
    result = await evaluate(data, instance.model_id, partition)
    repeated = await evaluate(data, instance.model_id, partition)

    assert result.model_type_id == model_type and result.training_run_id == training.id
    assert result.dataset_version_id == data["spec"].dataset_version_id != data["latest"]
    assert result.evaluation_run_id != repeated.evaluation_run_id
    assert result.metrics == repeated.metrics
    start, stop = (24, 32) if partition == "validation" else (32, 40)
    assert result.actual_rows == RowSet(ranges=(RowRange(start=start, stop=stop),))
    assert result.sample_count == stop - start
    assert not set(range(start, stop)).intersection(range(24))
    predicted = instance.payload.predict(data["x"][start:stop, ::-1], feature_names=("b", "a"))
    actual = data["y"][start:stop]
    residual = actual - predicted
    rmse = np.sqrt(np.mean(residual**2))
    p5, p95 = np.percentile(actual, [5, 95])
    assert result.metrics.rmse == pytest.approx(rmse)
    assert result.metrics.mae == pytest.approx(np.mean(np.abs(residual)))
    assert result.metrics.r2 == pytest.approx(
        1 - np.sum(residual**2) / np.sum((actual - actual.mean()) ** 2)
    )
    assert result.metrics.nrmse == pytest.approx(rmse / (p95 - p5))
    all_runs = await runs(data)
    saved = next(run for run in all_runs if run.id == result.evaluation_run_id)
    old = next(run for run in all_runs if run.id == training.id)
    assert saved.status == "succeeded"
    assert saved.result == {
        "model_id": str(result.model_id),
        "evaluation_run_id": str(result.evaluation_run_id),
        "evaluation": result.model_dump(mode="json"),
    }
    assert saved.source_version_id == result.dataset_version_id
    assert old.parameters == training.parameters and old.result == training.result
    assert old.status == training.status and old.finished_at == training.finished_at
    assert snapshot_files(data["root"]) == before


@pytest.mark.parametrize("tamper", [False, True])
async def test_sparse_rows_are_fully_verified_after_loading(data, monkeypatch, tamper):
    path = data["root"] / "eval-rows.txt"
    raw = b"25\n27\n31\n"
    path.write_bytes(raw)

    def configure(document):
        document["evaluation"]["sample_indices"] = {
            "validation": {
                "index_file": {
                    "uri": path.name,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "count": 3,
                }
            },
        }

    instance = await prepare(data, configure)
    forbid_fit(monkeypatch)
    if not tamper:
        result = await evaluate(data, instance.model_id)
        assert result.sample_count == 3 and result.actual_rows.index_file is not None
        assert result.actual_rows.index_file.sha256 == hashlib.sha256(raw).hexdigest()
        prediction = instance.payload.predict(
            data["x"][[25, 27, 31], ::-1], feature_names=("b", "a")
        )
        assert result.metrics.mae == pytest.approx(
            np.mean(np.abs(data["y"][[25, 27, 31]] - prediction))
        )
        return

    load = evaluation.load_model_instance

    async def tamper_after_load(*args, **kwargs):
        loaded = await load(*args, **kwargs)
        path.write_bytes(b"25\n27\n30\n")
        return loaded

    monkeypatch.setattr(evaluation, "load_model_instance", tamper_after_load)
    with pytest.raises(evaluation.ModelEvaluationError) as error:
        await evaluate(data, instance.model_id)
    assert error.value.stage == "resolve_rows" and "SHA256" in str(error.value.__cause__)


async def test_undeclared_test_scope_records_failure(data):
    def configure(document):
        document["evaluation"]["scopes"] = ["validation"]

    instance = await prepare(data, configure)
    with pytest.raises(evaluation.ModelEvaluationError) as error:
        await evaluate(data, instance.model_id, "test")
    (run,) = await evaluation_runs(data)
    assert run.status == error.value.outcome == "failed" and run.id == error.value.evaluation_run_id
    assert run.result["evaluation"]["failure_stage"] == "resolve_rows"
    assert run.result["evaluation"]["training_run_id"] == str(instance.training_run_id)


async def test_overlap_uses_actual_training_evidence_even_with_disjoint_declared_train(
    data, monkeypatch
):
    instance = await prepare(data)
    actual_train = RowSet(ranges=(RowRange(start=0, stop=12), RowRange(start=13, stop=25)))
    manifest = instance.manifest.model_copy(update={"effective_training_rows": actual_train})
    async with data["factory"]() as session:
        run = await session.get(ProcessingRun, instance.training_run_id)
        run.result = {**run.result, "effective_training_rows": actual_train.model_dump(mode="json")}
        await session.commit()

    async def load_with_conflicting_verified_rows(*args, **kwargs):
        # Inject conflicting evidence at the loader boundary to exercise the separate overlap check.
        return replace(instance, manifest=manifest)

    monkeypatch.setattr(evaluation, "load_model_instance", load_with_conflicting_verified_rows)
    with pytest.raises(evaluation.ModelEvaluationError) as error:
        await evaluate(data, instance.model_id)
    assert error.value.stage == "build_samples" and "overlaps actual Train" in str(
        error.value.__cause__
    )


@pytest.mark.parametrize(
    ("fault", "stage", "message"),
    [
        ("version", "build_samples", "identities"),
        ("sha", "read_data", "SHA256"),
        ("feature_order", "build_samples", "feature order"),
        ("nan", "build_samples", "finite"),
        ("inf", "build_samples", "finite"),
        ("empty", "build_samples", "nonempty ranges"),
    ],
)
async def test_invalid_evaluation_input_is_rejected(data, monkeypatch, fault, stage, message):
    instance = await prepare(data)
    read = evaluation.load_version_series
    build = evaluation.build_table_samples

    async def alter_read(*args, **kwargs):
        series = await read(*args, **kwargs)
        if fault == "version":
            return replace(series, version_id=data["latest"])
        if fault == "sha":
            (data["root"] / "source.csv").write_bytes(b"changed after reading")
        if fault in ("nan", "inf"):
            values = series.values["a"].copy()
            values[24] = np.nan if fault == "nan" else np.inf
            return replace(series, values={**series.values, "a": values})
        return series

    def change_order(*args, **kwargs):
        batch = build(*args, **kwargs)
        return replace(batch, inputs=replace(batch.inputs, feature_names=("a", "b")))

    if fault == "empty":
        monkeypatch.setattr(
            evaluation,
            "_resolve_requested_rows",
            lambda *args: ResolvedRows(RowSet.model_construct()),
        )
    elif fault == "feature_order":
        monkeypatch.setattr(evaluation, "build_table_samples", change_order)
    else:
        monkeypatch.setattr(evaluation, "load_version_series", alter_read)
    with pytest.raises(evaluation.ModelEvaluationError) as error:
        await evaluate(data, instance.model_id)
    assert error.value.stage == stage and message in str(error.value.__cause__)
    assert (await evaluation_runs(data))[0].status == "failed"


def tcn_spec(data, *, partition=None, index_rows=None):
    document = data["spec"].model_dump()
    document["split"].update(
        train=[{"start": 0, "stop": 33}],
        validation=[{"start": 33, "stop": 36}, {"start": 36, "stop": 69}],
        test=[{"start": 69, "stop": 102}],
    )
    document["evaluation"]["scopes"] = ("validation", "test")
    if index_rows is not None:
        raw = "".join(f"{row}\n" for row in index_rows).encode()
        path = data["root"] / "tcn-evaluation-rows.txt"
        path.write_bytes(raw)
        document["evaluation"]["sample_indices"] = {
            partition: {
                "index_file": {
                    "uri": path.name,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "count": len(index_rows),
                },
            },
        }
    return ExperimentSpec.model_validate(document)


def forbid_tcn_training(monkeypatch):
    forbid_fit(monkeypatch)
    monkeypatch.setattr(tcn_platform_adapter, "fit_tcn_on_version", no_training)
    monkeypatch.setattr(tcn_platform_adapter, "fit_tcn_core", no_training)
    monkeypatch.setattr(tcn_platform_adapter, "retry_tcn_manifest", no_training)
    monkeypatch.setattr(tcn_modeling_service, "fit_tcn_core", no_training)
    monkeypatch.setattr(tcn_modeling_service.torch_runtime().optim.Adam, "step", no_training)


async def test_tcn_evaluates_saved_model_with_verified_windows(tcn_data, monkeypatch):
    data = tcn_data
    fit = await fit_tcn(data, tcn_spec(data, partition="validation", index_rows=(65, 68)))
    assert fit.manifest_status == "published"
    (training,) = await runs(data)
    before = snapshot_files(data["root"])
    forbid_tcn_training(monkeypatch)
    load = evaluation.load_model_instance
    predict = tcn_modeling_service.TCNModel.predict
    loaded_models, calls = [], []

    async def check_loading(*args, **kwargs):
        (running,) = [run for run in await evaluation_runs(data) if run.status == "running"]
        assert running.parameters["model_id"] == str(fit.model_id)
        instance = await load(*args, **kwargs)
        loaded_models.append(instance.payload)
        return instance

    def record(model, x, *, feature_names):
        assert model is loaded_models[-1]
        predicted = predict(model, x, feature_names=feature_names)
        calls.append((x.copy(), feature_names, predicted.copy(), model.metadata))
        return predicted

    monkeypatch.setattr(evaluation, "load_model_instance", check_loading)
    monkeypatch.setattr(tcn_modeling_service.TCNModel, "predict", record)

    validation = await evaluate(data, fit.model_id)
    test = await evaluate(data, fit.model_id, "test")
    assert validation.evaluation_run_id != test.evaluation_run_id
    assert len(calls) == 2
    for result, anchors, call in zip(
        (validation, test), ([65, 68], [98, 99, 100, 101]), calls, strict=True
    ):
        x, names, predicted, metadata = call
        length = metadata.window_length
        assert result.model_type_id == "tcn" and result.training_run_id == training.id
        assert result.dataset_version_id == data["spec"].dataset_version_id != data["latest"]
        assert result.window_length == length == 29
        assert result.sample_count == len(anchors) and predicted.shape == (len(anchors),)
        assert names == ("b", "a")
        np.testing.assert_array_equal(x, [data["x"][r - length : r, ::-1] for r in anchors])
        actual = data["y"][anchors].astype(np.float64)
        residual = actual - predicted
        rmse = np.sqrt(np.mean(residual**2))
        p5, p95 = np.percentile(actual, [5, 95])
        assert result.metrics.rmse == pytest.approx(rmse)
        assert result.metrics.mae == pytest.approx(np.mean(np.abs(residual)))
        assert result.metrics.r2 == pytest.approx(
            1 - np.sum(residual**2) / np.sum((actual - actual.mean()) ** 2)
        )
        assert result.metrics.nrmse == pytest.approx(rmse / (p95 - p5))
        evidence = result.sequence_evidence
        assert evidence["partition"] == result.partition
        assert evidence["anchor_rows"] == result.actual_rows.model_dump(mode="json")
        assert evidence["sample_count"] == result.sample_count
        assert evidence["history_lengths"] == [["features", length]]
        assert evidence["history_offsets"] == [-length, 0] and evidence["target_offsets"] == [0]
        assert evidence["continuous_runs"] == [{"start": 36, "stop": 102}]
        assert evidence["feature_names"] == ["b", "a"] and evidence["target_name"] == "quality"
        assert evidence["source"] == {
            "dataset_id": str(result.dataset_id),
            "dataset_version_id": str(result.dataset_version_id),
            "dataset_sha256": result.dataset_sha256,
            "experiment_spec_hash": result.experiment_spec_hash,
        }
        assert result.model_implementation_version == metadata.implementation_version
        assert result.dependency_versions["torch"] == metadata.torch_version

    assert validation.actual_rows.index_file is not None
    assert test.actual_rows.ranges == (RowRange(start=98, stop=102),)
    persisted = {run.id: run for run in await runs(data)}
    for result in (validation, test):
        saved = persisted[result.evaluation_run_id]
        assert saved.run_type == evaluation.RUN_TYPE and saved.status == "succeeded"
        assert saved.result["evaluation"] == result.model_dump(mode="json")
        assert saved.parameters["sequence_evidence"] == result.sequence_evidence
    old = persisted[training.id]
    assert old.parameters == training.parameters and old.result == training.result
    assert old.status == training.status and old.finished_at == training.finished_at
    assert snapshot_files(data["root"]) == before


@pytest.mark.parametrize(
    ("fault", "partition", "rows", "message"),
    [
        ("partition", "test", (70,), "outside the effective partition"),
        ("continuous_run", "validation", (64,), "outside the effective partition"),
        ("history", "validation", None, "No complete sequence windows"),
    ],
)
async def test_tcn_rejects_incomplete_or_cross_boundary_windows(
    tcn_data, monkeypatch, fault, partition, rows, message
):
    # r=70 crosses the partition inside one run. r=64 crosses runs within Validation.
    spec = (
        tcn_data["spec"]
        if fault == "history"
        else tcn_spec(tcn_data, partition=partition, index_rows=rows)
    )
    fit = await fit_tcn(tcn_data, spec)
    forbid_tcn_training(monkeypatch)
    monkeypatch.setattr(tcn_modeling_service.TCNModel, "predict", no_training)
    with pytest.raises(evaluation.ModelEvaluationError) as error:
        await evaluate(tcn_data, fit.model_id, partition)
    assert error.value.stage == "build_samples" and message in str(error.value.__cause__)
    assert (await evaluation_runs(tcn_data))[0].status == "failed"


async def test_tcn_rejects_overlap_with_actual_training_anchors(tcn_data, monkeypatch):
    fit = await fit_tcn(tcn_data, tcn_spec(tcn_data))
    forbid_tcn_training(monkeypatch)
    load = evaluation._load_source

    async def conflicting_training_rows(*args, **kwargs):
        source = await load(*args, **kwargs)
        # Inject a conflict after verification to exercise the independent overlap check.
        return replace(source, training_rows=RowSet(ranges=(RowRange(start=65, stop=69),)))

    monkeypatch.setattr(evaluation, "_load_source", conflicting_training_rows)
    monkeypatch.setattr(tcn_modeling_service.TCNModel, "predict", no_training)
    with pytest.raises(evaluation.ModelEvaluationError) as error:
        await evaluate(tcn_data, fit.model_id)
    assert error.value.stage == "build_samples" and "overlaps actual Train" in str(
        error.value.__cause__
    )
    assert (await evaluation_runs(tcn_data))[0].status == "failed"


async def test_tcn_rejects_invalid_evaluation_arrays(tcn_data, monkeypatch):
    fit = await fit_tcn(tcn_data, tcn_spec(tcn_data))
    forbid_tcn_training(monkeypatch)
    build = evaluation.build_tcn_samples

    def wrong_features(*args, **kwargs):
        samples = build(*args, **kwargs)
        return replace(samples, evidence=replace(samples.evidence, feature_names=("a", "b")))

    with monkeypatch.context() as patch:
        patch.setattr(evaluation, "build_tcn_samples", wrong_features)
        patch.setattr(tcn_modeling_service.TCNModel, "predict", no_training)
        with pytest.raises(evaluation.ModelEvaluationError) as error:
            await evaluate(tcn_data, fit.model_id)
        assert error.value.stage == "build_samples"
        assert "feature order" in str(error.value.__cause__)

    def wrong_feature_count(*args, **kwargs):
        samples = build(*args, **kwargs)
        return replace(samples, x=samples.x[:, :, :1])

    with monkeypatch.context() as patch:
        patch.setattr(evaluation, "build_tcn_samples", wrong_feature_count)
        patch.setattr(tcn_modeling_service.TCNModel, "predict", no_training)
        with pytest.raises(evaluation.ModelEvaluationError) as error:
            await evaluate(tcn_data, fit.model_id)
        assert error.value.stage == "build_samples"
        assert "row or target evidence" in str(error.value.__cause__)

    read = evaluation.load_version_series
    for invalid in (np.nan, np.inf):
        with monkeypatch.context() as patch:

            async def nonfinite_history(*args, _invalid=invalid, **kwargs):
                series = await read(*args, **kwargs)
                values = series.values["a"].copy()
                values[36] = _invalid
                return replace(series, values={**series.values, "a": values})

            patch.setattr(evaluation, "load_version_series", nonfinite_history)
            patch.setattr(tcn_modeling_service.TCNModel, "predict", no_training)
            with pytest.raises(evaluation.ModelEvaluationError) as error:
                await evaluate(tcn_data, fit.model_id)
            assert error.value.stage == "build_samples" and "finite" in str(error.value.__cause__)

    for bad_prediction in (
        np.empty(0),
        np.ones(3),
        np.ones((4, 1)),
        np.full(4, np.nan),
        np.full(4, np.inf),
    ):
        monkeypatch.setattr(
            tcn_modeling_service.TCNModel,
            "predict",
            lambda *args, _prediction=bad_prediction, **kwargs: _prediction,
        )
        with pytest.raises(evaluation.ModelEvaluationError) as error:
            await evaluate(tcn_data, fit.model_id)
        assert error.value.stage == "metrics" and "aligned, nonempty, finite" in str(
            error.value.__cause__
        )
    assert all(run.status == "failed" for run in await evaluation_runs(tcn_data))


@pytest.mark.parametrize(
    ("applied", "database_unavailable"), [(True, False), (False, False), (False, True)]
)
async def test_final_commit_reconciles_in_an_independent_session(
    data, applied, database_unavailable
):
    instance = await prepare(data)
    await assert_final_commit_reconciliation(data, instance.model_id, applied, database_unavailable)


@pytest.mark.parametrize(
    ("applied", "database_unavailable"), [(True, False), (False, False), (False, True)]
)
async def test_tcn_final_commit_reconciles_in_an_independent_session(
    tcn_data, monkeypatch, applied, database_unavailable
):
    fit = await fit_tcn(tcn_data, tcn_spec(tcn_data))
    forbid_tcn_training(monkeypatch)
    await assert_final_commit_reconciliation(tcn_data, fit.model_id, applied, database_unavailable)


async def assert_final_commit_reconciliation(data, model_id, applied, database_unavailable):
    final_commit_failed = False

    class InterruptedCommit(AsyncSession):
        async def commit(self):
            nonlocal final_commit_failed
            final = any(
                isinstance(run, ProcessingRun)
                and run.run_type == evaluation.RUN_TYPE
                and run.status == "succeeded"
                for run in self.dirty
            )
            if not final or applied:
                await super().commit()
            if final:
                final_commit_failed = True
                raise OSError("lost evaluation commit acknowledgement")

    session_factory = async_sessionmaker(
        data["factory"].kw["bind"], class_=InterruptedCommit, expire_on_commit=False
    )

    def factory():
        if database_unavailable and final_commit_failed:
            raise OSError("database unavailable during reconciliation")
        return session_factory()

    if applied:
        result = await evaluate(data, model_id, factory=factory)
        (run,) = await evaluation_runs(data)
        assert run.id == result.evaluation_run_id and run.status == "succeeded"
        assert run.result["evaluation"] == result.model_dump(mode="json")
    else:
        with pytest.raises(evaluation.ModelEvaluationError) as error:
            await evaluate(data, model_id, factory=factory)
        (run,) = await evaluation_runs(data)
        assert run.id == error.value.evaluation_run_id and error.value.stage == "final_commit"
        assert error.value.outcome == ("unconfirmed" if database_unavailable else "failed")
        assert run.status == ("running" if database_unavailable else "failed")


async def test_duplicate_run_id_does_not_update_the_existing_evaluation(data, monkeypatch):
    model_id, run_id = uuid4(), uuid4()
    parameters = {
        "model_id": str(model_id),
        "partition": "validation",
        "prediction_mode": "prediction",
    }
    result = {"model_id": str(model_id), "evaluation_run_id": str(run_id)}
    async with data["factory"]() as session:
        session.add(
            ProcessingRun(
                id=run_id,
                run_type=evaluation.RUN_TYPE,
                status="running",
                parameters=parameters,
                result=result,
            )
        )
        await session.commit()

    async def unexpected(*args, **kwargs):
        pytest.fail("Model loading must wait for the running record to be committed")

    monkeypatch.setattr(evaluation, "uuid4", lambda: run_id)
    monkeypatch.setattr(evaluation, "load_model_instance", unexpected)
    with pytest.raises(evaluation.ModelEvaluationError) as error:
        await evaluate(data, model_id)
    (run,) = await evaluation_runs(data)
    assert error.value.stage == "create_run" and error.value.outcome == "unconfirmed"
    assert run.status == "running" and run.parameters == parameters and run.result == result


async def test_metric_degeneracy_and_strict_validation(monkeypatch):
    actual = np.array([5.0, 5.0])
    predicted = np.array([4.0, 6.0])
    score = evaluation.calculate_regression_metrics(actual, predicted)
    assert score.r2 is None and score.nrmse is None and score.rmse == score.mae == 1.0

    def unexpected(*args):
        pytest.fail("Invalid inputs must be rejected before _scores")

    monkeypatch.setattr(evaluation, "_scores", unexpected)
    for invalid in (
        np.array([np.nan, 0.0]),
        np.array([0.0, np.inf]),
        np.ones((2, 1)),
        np.array([]),
    ):
        with pytest.raises(ValueError, match="aligned, nonempty, finite"):
            evaluation.calculate_regression_metrics(actual, invalid)
    with pytest.raises(ValidationError):
        RegressionMetrics(r2=2.0, rmse=np.inf, mae=-1.0, nrmse=None)
    with pytest.raises(ValidationError):
        ModelEvaluationRequest.model_validate(
            {
                "model_id": str(uuid4()),
                "partition": "validation",
                "dataset_version_id": str(uuid4()),
            }
        )
