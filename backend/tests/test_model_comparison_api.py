"""Compare four real saved models over a common synthetic evaluation set."""

from itertools import pairwise
from uuid import uuid4

import pytest
from app.api import routes
from app.schemas.experiment_spec import ExperimentSpec
from app.services import model_artifact_service, model_evaluation_service, pls_modeling_service
from sklearn.cross_decomposition import PLSRegression

from test_model_comparison_service import persist
from test_model_evaluation_api import (
    BASE,
    forbid_evaluation_execution,
    post_evaluation,
    response_data,
)
from test_model_evaluation_service import (
    forbid_tcn_training,
    forbid_timexer_training,
    snapshot_files,
    tcn_spec,
)
from test_pls_api import api as api
from test_pls_api import error, trained
from test_pls_training_service import runs
from test_tcn_platform import data as data
from test_tcn_platform import fit as fit_tcn
from test_tcn_platform import no_training
from test_timexer_platform import fit as fit_timexer
from test_xgboost_api import fit as fit_xgboost

pytestmark = pytest.mark.asyncio


def post_comparison(api, *ids, **extras):
    return api.post(
        f"{BASE}/compare",
        json={"evaluation_run_ids": [str(identity) for identity in ids], **extras},
    )


async def run_snapshot(data):
    return {
        run.id: (
            run.run_type,
            run.status,
            run.dataset_id,
            run.source_version_id,
            run.created_at,
            run.finished_at,
            run.parameters,
            run.result,
        )
        for run in await runs(data)
    }


async def test_pairwise_and_four_model_comparisons_are_read_only(api, data, monkeypatch):
    spec = tcn_spec(data, partition="validation", index_rows=(65, 68))
    xgboost_spec = ExperimentSpec.model_validate({**spec.model_dump(), "input_columns": ["a"]})
    pls = trained(api, {**data, "spec": spec})
    xgboost = fit_xgboost(api, {**data, "spec": xgboost_spec})
    tcn = await fit_tcn(data, spec)
    timexer = await fit_timexer(data, horizon=1, spec=spec)
    model_ids = (pls["model_id"], xgboost["model_id"], tcn.model_id, timexer.model_id)
    evaluations = [response_data(post_evaluation(api, model_id)) for model_id in model_ids]
    ids = [item["evaluation_run_id"] for item in evaluations]
    duplicate_model_run = response_data(post_evaluation(api, model_ids[0]))
    before = await run_snapshot(data)
    artifacts_before = snapshot_files(data["root"])

    forbid_evaluation_execution(monkeypatch)
    forbid_tcn_training(monkeypatch)
    forbid_timexer_training(monkeypatch)
    monkeypatch.setattr(model_artifact_service, "load_model_instance", no_training)
    monkeypatch.setattr(model_evaluation_service, "evaluate_saved_model", no_training)
    monkeypatch.setattr(PLSRegression, "fit", no_training)
    monkeypatch.setattr(pls_modeling_service, "fit_pls_core", no_training)
    for name in (
        "fit_pls_with_manifest",
        "fit_xgboost_on_version",
        "fit_tcn_on_version",
        "fit_timexer_on_version",
    ):
        monkeypatch.setattr(routes, name, no_training)

    for pair in pairwise(ids):
        result = response_data(post_comparison(api, *pair))
        assert [entry["evaluation_run_id"] for entry in result["candidates"]] == list(pair)
        assert result["scope"]["prediction_length"] == 1
        assert result["scope"]["sample_counts_by_horizon"] == [2]

    result = response_data(post_comparison(api, *ids))
    assert result["scope"]["evaluation_count"] == 4
    assert result["scope"]["dataset_id"] == str(spec.dataset_id)
    assert result["scope"]["dataset_version_id"] == str(spec.dataset_version_id)
    assert result["scope"]["dataset_sha256"] == spec.dataset_version_sha256
    assert result["scope"]["target_column"] == "quality"
    assert result["scope"]["partition"] == "validation"
    assert [entry["model_type"] for entry in result["candidates"]] == [
        "pls",
        "xgboost",
        "tcn",
        "timexer",
    ]
    assert result["horizon_rankings"] == [] and result["aggregation_method"] is None
    for candidate, original in zip(result["candidates"], evaluations, strict=True):
        assert candidate["model_id"] == original["model_id"]
        assert candidate["metrics"] == original["metrics"]
        assert candidate["sample_count"] == 2 and candidate["model_name"]
        assert candidate["feature_names"] == (
            ["a"] if candidate["model_type"] == "xgboost" else ["b", "a"]
        )
    assert "target_rows_by_horizon" in result["compatibility"]
    assert (
        error(post_comparison(api, ids[0], duplicate_model_run["evaluation_run_id"]), 409)["code"]
        == "MODEL_COMPARISON_DUPLICATE_MODEL"
    )
    assert response_data(api.get(f"{BASE}/evaluations"))["total"] == 5
    assert response_data(api.get(f"{BASE}/evaluations/{ids[3]}"))["result"] == evaluations[3]
    assert await run_snapshot(data) == before
    assert snapshot_files(data["root"]) == artifacts_before


async def test_compare_rejects_invalid_requests_and_incompatible_runs(api, data):
    first, _ = await persist(data)
    different, _ = await persist(data, rows=(80, 82))
    with_missing_status, _ = await persist(data)
    async with data["factory"]() as session:
        from app.models.dataset import ProcessingRun

        run = await session.get(ProcessingRun, with_missing_status)
        training_id = run.result["evaluation"]["training_run_id"]
        run.status = "running"
        await session.commit()
    for ids in ((), (first,), (first, first), tuple(uuid4() for _ in range(11))):
        assert error(post_comparison(api, *ids), 422)["code"] == "REQUEST_VALIDATION_FAILED"
    assert (
        error(post_comparison(api, first, different, model_type="timexer"), 422)["code"]
        == "REQUEST_VALIDATION_FAILED"
    )
    for invalid in (uuid4(), training_id):
        assert (
            error(post_comparison(api, first, invalid), 404)["code"]
            == "MODEL_COMPARISON_EVALUATION_NOT_FOUND"
        )
    assert (
        error(post_comparison(api, first, with_missing_status), 409)["details"]["field"] == "status"
    )
    incompatible = error(post_comparison(api, first, different), 409)
    assert incompatible["code"] == "MODEL_COMPARISON_INCOMPATIBLE"
    assert incompatible["details"] == {
        "evaluation_run_id": str(different),
        "field": "target_rows_by_horizon",
    }
