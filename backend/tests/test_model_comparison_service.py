"""Comparison of persisted evaluation evidence in isolated SQLite."""

import hashlib
from statistics import mean
from uuid import uuid4

import pytest
from app.models.dataset import ProcessingRun
from app.schemas.experiment_spec import ExperimentSpec, RowRange, RowSet
from app.schemas.model_comparison import ModelComparisonRequest
from app.services import model_comparison_service as comparison
from app.services.experiment_spec_service import spec_hash

from test_model_evaluation_service import tcn_spec
from test_tcn_platform import data as data
from test_timexer_platform import forecast

pytestmark = pytest.mark.asyncio


def ranges_for(rows):
    spans = []
    for row in sorted(set(rows)):
        if spans and spans[-1]["stop"] == row:
            spans[-1]["stop"] += 1
        else:
            spans.append({"start": row, "stop": row + 1})
    return {"ranges": spans}


def scores(r2=0.4, rmse=1.0, mae=0.8, nrmse=0.2):
    return {"r2": r2, "rmse": rmse, "mae": mae, "nrmse": nrmse}


async def persist(
    data,
    *,
    kind="pls",
    rows=(81, 83),
    partition="validation",
    spec=None,
    horizon=1,
    metrics=None,
    horizon_scores=None,
    index=None,
    change=None,
):
    spec = spec or data["spec"]
    model_id, training_id, evaluation_id = uuid4(), uuid4(), uuid4()
    anchors = (
        RowSet(index_file=index)
        if index
        else RowSet(ranges=tuple(RowRange(**span) for span in ranges_for(rows)["ranges"]))
    ).model_dump(mode="json")
    identity = {
        "model_id": str(model_id),
        "model_type_id": kind,
        "training_run_id": str(training_id),
    }
    source = {
        "dataset_id": str(spec.dataset_id),
        "dataset_version_id": str(spec.dataset_version_id),
        "dataset_sha256": spec.dataset_version_sha256,
        "experiment_spec_hash": spec_hash(spec),
    }
    parameters = {**identity, **source, "partition": partition, "actual_rows": anchors}
    result = {
        **parameters,
        "evaluation_run_id": str(evaluation_id),
        "sample_count": len(rows),
        "metrics": metrics or scores(),
    }
    training_parameters = {
        "experiment_spec": spec.model_dump(mode="json"),
        "experiment_spec_hash": spec_hash(spec),
    }
    training_result = dict(identity)
    if kind in {"tcn", "timexer"}:
        evidence = {
            "source": source,
            "partition": partition,
            "target_name": spec.target_column,
            "feature_names": list(spec.input_columns),
            "anchor_rows": anchors,
            "sample_count": len(rows),
            "prediction_horizon": horizon,
            "target_offsets": list(range(horizon)),
            "continuous_runs": [
                run.model_dump(mode="json")
                for run in spec.continuous_runs
                if any(run.start <= row < run.stop for row in rows)
            ],
        }
        parameters["sequence_evidence"] = result["sequence_evidence"] = evidence
        result["dependency_versions"] = {}
    if kind == "tcn":
        result.update(window_length=29, model_implementation_version="tcn-core-1")
    if kind == "timexer":
        contract = forecast(horizon).model_dump(mode="json")
        for record in (parameters, result, training_parameters, training_result):
            record["forecast_spec"] = contract
        steps = horizon_scores or [scores()] * horizon
        valid = {
            name: [step[name] for step in steps if step[name] is not None] for name in scores()
        }
        result.update(
            target_rows=ranges_for(row + step for step in range(horizon) for row in rows),
            target_rows_by_horizon=[
                ranges_for(row + step for row in rows) for step in range(horizon)
            ],
            horizon_metrics=[
                {"horizon_step": step, **score} for step, score in enumerate(steps, 1)
            ],
            metrics={name: mean(values) if values else None for name, values in valid.items()},
            metric_aggregation={
                "valid_horizon_counts": {name: len(values) for name, values in valid.items()},
                "undefined_horizons": {
                    name: [i for i, step in enumerate(steps, 1) if step[name] is None]
                    for name in scores()
                },
            },
            model_implementation_version="timexer-core-1",
        )
    if change:
        change(result)
    async with data["factory"]() as session:
        session.add_all(
            [
                ProcessingRun(
                    id=training_id,
                    run_type=f"modeling.{kind}",
                    status="succeeded",
                    dataset_id=spec.dataset_id,
                    source_version_id=spec.dataset_version_id,
                    parameters=training_parameters,
                    result=training_result,
                ),
                ProcessingRun(
                    id=evaluation_id,
                    run_type=comparison.RUN_TYPE,
                    status="succeeded",
                    dataset_id=spec.dataset_id,
                    source_version_id=spec.dataset_version_id,
                    parameters=parameters,
                    result={
                        "model_id": str(model_id),
                        "evaluation_run_id": str(evaluation_id),
                        "evaluation": result,
                    },
                ),
            ]
        )
        await session.commit()
    return evaluation_id, model_id


async def compare(data, *ids):
    async with data["factory"]() as session:
        return await comparison.compare_model_evaluations(
            session,
            request=ModelComparisonRequest(evaluation_run_ids=ids),
            artifact_root=data["root"],
        )


async def test_metric_directions_competition_ties_and_nulls_are_stable(data):
    first, second, third = [
        await persist(data, metrics=metrics)
        for metrics in (
            scores(0.6, 2, 1, None),
            scores(0.6, 1, 0.5, 0.2),
            scores(None, 1, 0.8, 0.1),
        )
    ]
    result = await compare(data, first[0], second[0], third[0])
    reversed_result = await compare(data, third[0], second[0], first[0])
    assert result.rankings == reversed_result.rankings
    assert [entry.model_id for entry in result.rankings["r2"]] == sorted([first[1], second[1]])
    assert [entry.rank for entry in result.rankings["r2"]] == [1, 1]
    assert [entry.rank for entry in result.rankings["rmse"]] == [1, 1, 3]
    assert [entry.model_id for entry in result.rankings["mae"]] == [second[1], third[1], first[1]]
    assert [entry.model_id for entry in result.rankings["nrmse"]] == [third[1], second[1]]
    assert result.candidates[0].ranks["nrmse"] is None
    assert result.candidates[2].ranks["r2"] is None


async def test_multistep_rankings_keep_the_saved_macro_and_step_metrics(data):
    one = [scores(0.8, 2), scores(0.2, 1), scores(None, 3, nrmse=None)]
    two = [scores(0.4, 1), scores(0.9, 2), scores(0.3, 2)]
    first = await persist(data, kind="timexer", horizon=3, horizon_scores=one)
    second = await persist(data, kind="timexer", horizon=3, horizon_scores=two)
    result = await compare(data, first[0], second[0])
    assert result.scope.prediction_length == 3
    assert result.scope.sample_counts_by_horizon == (2, 2, 2)
    assert result.aggregation_method == "macro_average"
    assert result.rankings["r2"][0].model_id == second[1]
    assert result.candidates[0].metrics.r2 == 0.5
    assert result.candidates[0].metrics.rmse == 2
    assert [h.rankings["r2"][0].model_id for h in result.horizon_rankings] == [
        first[1],
        second[1],
        second[1],
    ]
    assert [h.rankings["rmse"][0].model_id for h in result.horizon_rankings] == [
        second[1],
        first[1],
        second[1],
    ]
    assert result.candidates[0].horizons[2].ranks["r2"] is None
    assert result.candidates[0].metric_aggregation.undefined_horizons["r2"] == (3,)
    assert result.candidates[0].metric_aggregation.valid_horizon_counts["r2"] == 2
    assert result.candidates[0].horizons[0].metrics.model_dump() == one[0]


async def test_same_family_models_can_use_different_windows_and_core_versions(data):
    spec = tcn_spec(data)
    first, _ = await persist(data, kind="tcn", rows=(66, 68), spec=spec)

    def different_config(result):
        result.update(window_length=30, model_implementation_version="tcn-core-2")

    second, _ = await persist(data, kind="tcn", rows=(66, 68), spec=spec, change=different_config)
    result = await compare(data, first, second)
    assert result.scope.prediction_length == 1
    assert result.scope.sample_counts_by_horizon == (2,)
    assert [item.model_type for item in result.candidates] == ["tcn", "tcn"]


async def test_multistep_comparison_rejects_partially_overlapping_label_sets(data):
    first, _ = await persist(data, kind="timexer", horizon=3, rows=(81, 83))
    second, _ = await persist(data, kind="timexer", horizon=3, rows=(81, 82))
    with pytest.raises(comparison.ModelComparisonError) as error:
        await compare(data, first, second)
    assert error.value.code == "MODEL_COMPARISON_INCOMPATIBLE"
    assert error.value.field == "target_rows_by_horizon"


@pytest.mark.parametrize(
    "field",
    [
        "dataset_id",
        "dataset_version_id",
        "dataset_sha256",
        "partition",
        "target_column",
        "prediction_length",
        "target_rows_by_horizon",
        "continuous_runs",
    ],
)
async def test_incompatible_evaluations_are_rejected(data, field):
    document = data["spec"].model_dump()
    document["evaluation"]["scopes"] = ["validation", "test"]
    baseline = ExperimentSpec.model_validate(document)
    first, _ = await persist(data, spec=baseline)
    kwargs = {}
    if field in {"dataset_id", "dataset_version_id"}:
        document[field] = uuid4()
    elif field == "dataset_sha256":
        document["dataset_version_sha256"] = "a" * 64
    elif field == "partition":
        kwargs.update(partition="test", rows=(98, 99))
    elif field == "target_column":
        document[field] = "other_target"
    elif field == "prediction_length":
        kwargs.update(kind="timexer", horizon=3)
    elif field == "target_rows_by_horizon":
        kwargs["rows"] = (80, 82)
    else:
        document["continuous_runs"] = [{"start": 0, "stop": 86}, {"start": 86, "stop": 102}]
    second, _ = await persist(data, spec=ExperimentSpec.model_validate(document), **kwargs)
    with pytest.raises(comparison.ModelComparisonError) as error:
        await compare(data, first, second)
    assert error.value.code == "MODEL_COMPARISON_INCOMPATIBLE"
    assert error.value.field == field


@pytest.mark.parametrize("field", ["actual_rows", "target_rows_by_horizon", "target_rows"])
async def test_missing_or_inconsistent_label_evidence_is_rejected(data, field):
    def tamper(result):
        if field == "actual_rows":
            del result[field]
        elif field == "target_rows_by_horizon":
            result[field][1] = ranges_for((81, 83))
        else:
            result[field] = ranges_for((81, 83))

    first, _ = await persist(data, kind="timexer", horizon=3)
    second, _ = await persist(data, kind="timexer", horizon=3, change=tamper)
    with pytest.raises(comparison.ModelComparisonError) as error:
        await compare(data, first, second)
    assert error.value.code == "MODEL_COMPARISON_EVIDENCE_INVALID" and error.value.field == field


async def test_index_and_inline_rows_compare_by_content_and_require_verified_index(data):
    path = data["root"] / "comparison-rows.txt"
    raw = b"81\n83\n"
    path.write_bytes(raw)
    inline, _ = await persist(data)
    external, _ = await persist(
        data,
        kind="xgboost",
        index={"uri": path.name, "count": 2, "sha256": hashlib.sha256(raw).hexdigest()},
    )
    assert (await compare(data, inline, external)).scope.sample_counts_by_horizon == (2,)
    path.write_bytes(b"81\n82\n")
    with pytest.raises(comparison.ModelComparisonError) as error:
        await compare(data, inline, external)
    assert error.value.field == "actual_rows"
