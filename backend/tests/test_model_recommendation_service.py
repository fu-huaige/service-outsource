"""Read-only model recommendation against a version-bound synthetic CSV."""

import csv
import hashlib
import io
from uuid import uuid4

import pytest
import torch
import xgboost
from app.models.dataset import DatasetVersion
from app.schemas.experiment_spec import ExperimentSpec
from app.schemas.model_recommendation import ModelRecommendationRequest
from app.schemas.timexer_platform import TimeXerForecastSpec
from app.services import (
    model_recommendation_service,
    tcn_modeling_service,
    tcn_platform_adapter,
    timexer_modeling_service,
    timexer_platform_adapter,
)
from app.services.model_recommendation_service import recommend_models
from app.services.version_data import VersionDataError
from sklearn.cross_decomposition import PLSRegression

from test_pls_training_service import runs
from test_tcn_platform import data as data

pytestmark = pytest.mark.asyncio
PARAMETERS = {
    "tcn": {"window_length": 29},
    "timexer": {"target_window_length": 8, "exogenous_window_length": 11, "patch_length": 4},
}


def spec_with(spec, **changes):
    return ExperimentSpec.model_validate({**spec.model_dump(), **changes})


async def recommend(data, *, spec=None, parameters=None, **kwargs):
    async with data["factory"]() as session:
        return await recommend_models(
            session,
            request=ModelRecommendationRequest(
                experiment_spec=spec or data["spec"],
                parameters=PARAMETERS if parameters is None else parameters,
                **kwargs,
            ),
            artifact_root=data["root"],
        )


def candidates(result):
    return {item.model_type_id: item for item in result.candidates}


def forbid_fitting(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Recommendation must not train models or update weights")

    monkeypatch.setattr(xgboost, "train", forbidden)
    monkeypatch.setattr(PLSRegression, "fit", forbidden)
    monkeypatch.setattr(tcn_modeling_service, "fit_tcn_core", forbidden)
    monkeypatch.setattr(tcn_platform_adapter, "fit_tcn_core", forbidden)
    monkeypatch.setattr(tcn_platform_adapter, "fit_tcn_on_version", forbidden)
    monkeypatch.setattr(timexer_modeling_service, "fit_timexer_core", forbidden)
    monkeypatch.setattr(timexer_platform_adapter, "fit_timexer_core", forbidden)
    monkeypatch.setattr(timexer_platform_adapter, "fit_timexer_on_version", forbidden)
    monkeypatch.setattr(torch.optim.Adam, "step", forbidden)


async def rewrite_source(data, change):
    path = data["root"] / "source.csv"
    original = list(csv.reader(io.StringIO(path.read_text(encoding="utf-8"))))
    change(original[1:])
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerows(original)
    raw = buffer.getvalue().encode()
    digest = hashlib.sha256(raw).hexdigest()
    path.write_bytes(raw)
    spec = data["spec"]
    async with data["factory"]() as session:
        version = await session.get(DatasetVersion, spec.dataset_version_id)
        version.sha256 = digest
        await session.commit()
    return spec_with(spec, dataset_version_sha256=digest)


async def test_four_candidates_use_bound_train_and_never_fit(data, monkeypatch):
    forbid_fitting(monkeypatch)
    source_csv = (data["root"] / "source.csv").read_bytes()
    before = {path.name for path in data["root"].iterdir()}
    result = await recommend(data)
    again = await recommend(data, expected_spec_hash=result.source.experiment_spec_hash)
    by_model = candidates(result)
    assert result.model_dump(exclude={"generated_at"}) == again.model_dump(exclude={"generated_at"})
    assert result.source.dataset_version_id == data["spec"].dataset_version_id != data["latest"]
    assert result.profile.profile_scope == result.profile.partition == "train"
    assert result.profile.sample_count == 67 and result.profile.feature_count == 2
    assert result.source.feature_names == ("b", "a") and result.profile.target_type == "float"
    assert [run.train_record_count for run in result.profile.continuous_runs] == [33, 34]
    assert result.profile.sampling_status == "uniform" and result.profile.sample_period_seconds == 1
    assert result.profile.correlated_groups
    assert result.profile.vif_scores is not None
    assert {key: item.training_sample_count for key, item in by_model.items()} == {
        "pls": 67,
        "xgboost": 67,
        "tcn": 9,
        "timexer": 45,
    }
    assert all(item.eligibility_status == "eligible" for item in by_model.values())
    assert len(result.recommended_models) == 3 and result.recommended_models[0] == "pls"
    assert by_model["tcn"].evidence.history_lengths == {"features": 29}
    assert by_model["timexer"].evidence.history_lengths == {"target": 8, "exogenous": 11}
    assert by_model["tcn"].evidence.anchor_rows.count == 9
    assert await runs(data) == []
    assert {path.name for path in data["root"].iterdir()} == before
    assert (data["root"] / "source.csv").read_bytes() == source_csv


@pytest.mark.parametrize("application", [None, "regression", "soft_sensor"])
async def test_pls_application_contract_preserves_other_candidates(data, application):
    baseline = await recommend(data)
    spec = spec_with(data["spec"], application=application)
    result = await recommend(data, spec=spec)
    by_model = candidates(result)
    expected_status = "excluded" if application is None else "eligible"
    assert by_model["pls"].eligibility_status == expected_status
    if application is None:
        assert "application" in result.excluded_models["pls"][0]
        assert result.recommended_models == ("xgboost", "timexer", "tcn")
    else:
        assert result.recommended_models == baseline.recommended_models

    other_models = ("xgboost", "tcn", "timexer")
    baseline_candidates = candidates(baseline)
    for model in other_models:
        assert by_model[model].model_dump(exclude={"recommendation_rank"}) == (
            baseline_candidates[model].model_dump(exclude={"recommendation_rank"})
        )
    assert sorted(other_models, key=lambda model: by_model[model].recommendation_rank) == sorted(
        other_models, key=lambda model: baseline_candidates[model].recommendation_rank
    )


async def test_pls_recommendation_uses_training_prediction_contract(data):
    evaluation = {**data["spec"].evaluation.model_dump(), "prediction_modes": ["one_step"]}
    result = await recommend(data, spec=spec_with(data["spec"], evaluation=evaluation))
    assert candidates(result)["pls"].eligibility_status == "excluded"
    assert "Unsupported PLS experiment" in result.excluded_models["pls"][0]
    assert result.recommended_models == ("xgboost", "timexer", "tcn")


async def test_task_goal_changes_rank_without_changing_eligibility(data):
    nonlinear = await recommend(data, goal="nonlinear_regression")
    temporal = await recommend(data, goal="temporal_forecast")
    assert nonlinear.recommended_models[0] == "xgboost"
    assert temporal.recommended_models[:2] == ("timexer", "tcn")
    assert all(item.eligibility_status == "eligible" for item in temporal.candidates)


async def test_static_sample_feature_and_component_limits(data):
    spec = data["spec"]
    train = spec.split.model_dump()
    train["train"] = [{"start": 0, "stop": 1}]
    limited = candidates(await recommend(data, spec=spec_with(spec, split=train)))
    for model in ("pls", "xgboost"):
        assert limited[model].eligibility_status == "excluded"
        assert limited[model].training_sample_count == 1

    train["train"] = [{"start": 0, "stop": 2}]
    valid = candidates(await recommend(data, spec=spec_with(spec, split=train)))
    assert valid["pls"].eligibility_status == valid["xgboost"].eligibility_status == "eligible"
    single_input = spec_with(spec, input_columns=["a"])
    by_model = candidates(await recommend(data, spec=single_input))
    assert by_model["xgboost"].eligibility_status == "eligible"
    assert by_model["pls"].eligibility_status == "excluded"
    assert by_model["pls"].actual_parameters["n_components"] == 2
    assert "n_components" in by_model["pls"].reasons[0]


@pytest.mark.parametrize(
    "window,status", [(28, "excluded"), (29, "eligible"), (256, "excluded"), (257, "excluded")]
)
async def test_tcn_window_schema_and_real_window_count(data, window, status):
    result = await recommend(data, parameters={**PARAMETERS, "tcn": {"window_length": window}})
    candidate = candidates(result)["tcn"]
    assert candidate.eligibility_status == status
    if window == 256:
        assert candidate.actual_parameters["window_length"] == 256
        assert "No complete sequence windows" in candidate.reasons[0]
    if window == 29:
        assert candidate.training_sample_count == 9


@pytest.mark.parametrize("sampling,expected", [("irregular", "excluded"), ("unknown", "unknown")])
async def test_time_evidence_is_required_for_sequence_models(data, sampling, expected):
    axis = {"column": "timestamp", "sampling_status": sampling}
    spec = spec_with(data["spec"], time_axis=axis)
    result = await recommend(data, spec=spec)
    assert (
        result.profile.sampling_status == sampling and result.profile.sample_period_seconds is None
    )
    for key in ("tcn", "timexer"):
        assert candidates(result)[key].eligibility_status == expected
        assert key not in result.recommended_models


async def test_multistep_uses_separate_forecast_and_preserves_requested_parameters(data):
    forecast = TimeXerForecastSpec(
        target_window_length=8, exogenous_window_length=11, prediction_length=3
    )
    result = await recommend(data, forecast_spec=forecast)
    timexer = candidates(result)["timexer"]
    assert result.recommended_models == ("timexer",)
    assert timexer.forecast_spec == forecast and timexer.training_sample_count == 41
    assert timexer.evidence.horizon_source == "forecast_spec"
    assert timexer.evidence.target_offsets == (0, 1, 2)
    assert data["spec"].feature_spec.prediction_horizon == 1
    conflicting = await recommend(
        data,
        forecast_spec=forecast,
        parameters={"timexer": {"patch_length": 4, "prediction_length": 1}},
    )
    assert conflicting.recommended_models == ()
    assert "No model" in conflicting.summary
    assert candidates(conflicting)["timexer"].actual_parameters["prediction_length"] == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"target_window_length": 7},
        {"exogenous_window_length": 257},
        {"prediction_length": 33},
        {"patch_length": 8},
        {"prediction_length": 3},
    ],
)
async def test_timexer_rejects_invalid_or_unbound_forecast_parameters(data, overrides):
    result = await recommend(
        data, parameters={**PARAMETERS, "timexer": {**PARAMETERS["timexer"], **overrides}}
    )
    assert candidates(result)["timexer"].eligibility_status == "excluded"


async def test_large_window_preflight_is_unknown_without_overallocating(data, monkeypatch):
    monkeypatch.setattr(model_recommendation_service, "_MAX_SEQUENCE_BYTES", 0)
    result = await recommend(data)
    for name in ("tcn", "timexer"):
        candidate = candidates(result)[name]
        assert candidate.eligibility_status == "unknown"
        assert candidate.training_sample_count is None
        assert "memory budget" in candidate.reasons[0]
    assert result.recommended_models == ("pls", "xgboost")


async def test_tcn_rejects_exactly_one_complete_window(data):
    spec = data["spec"]
    split = spec.split.model_dump()
    split["train"] = [{"start": 0, "stop": 30}]
    result = await recommend(data, spec=spec_with(spec, split=split))
    assert candidates(result)["tcn"].eligibility_status == "excluded"
    assert "at least two complete windows" in candidates(result)["tcn"].reasons[0]


async def test_windows_cannot_use_other_partitions_or_continuous_runs(data):
    spec = data["spec"]
    split = spec.split.model_dump()
    split["train"] = [{"start": 28, "stop": 36}, {"start": 36, "stop": 44}]
    result = await recommend(data, spec=spec_with(spec, split=split))
    assert result.profile.sample_count == 16
    for kind in ("tcn", "timexer"):
        candidate = candidates(result)[kind]
        assert candidate.eligibility_status == "excluded"
        assert "No complete sequence windows" in candidate.reasons[0]


async def test_held_out_missing_values_do_not_enter_train_profile(data):
    def alter(rows):
        rows[90][1] = ""
        rows[91][2] = ""
        rows[92][3] = "500000"

    changed = await rewrite_source(data, alter)
    result = await recommend(data, spec=changed)
    assert result.profile.missing_rate == 0
    assert result.profile.anomaly_summary["quality"] == 0
    assert all(item.eligibility_status == "eligible" for item in result.candidates)


async def test_xgboost_rejects_float32_overflow_in_train(data):
    def alter(rows):
        rows[20][1] = "1e40"

    changed = await rewrite_source(data, alter)
    result = await recommend(data, spec=changed)
    xgb = candidates(result)["xgboost"]
    assert xgb.eligibility_status == "excluded"
    assert "float32" in xgb.reasons[0]


@pytest.mark.parametrize(
    "fault", ["version", "sha", "spec_hash", "missing_exogenous", "false_uniform"]
)
async def test_rejects_unverified_source_or_contract(data, fault):
    spec = data["spec"]
    kwargs = {}
    if fault == "version":
        spec = spec_with(spec, dataset_version_id=uuid4())
        message = "ownership"
    elif fault == "sha":
        (data["root"] / "source.csv").write_bytes(b"tampered")
        message = "SHA256"
    elif fault == "spec_hash":
        kwargs["expected_spec_hash"] = "0" * 64
        message = "ExperimentSpec SHA256"
    elif fault == "missing_exogenous":
        spec = spec_with(spec, input_columns=["missing_column"])
        message = "input"
    else:
        spec = spec_with(
            spec, time_axis={**spec.time_axis.model_dump(), "sample_period_seconds": 2}
        )
        message = "uniform"
    if fault == "missing_exogenous":
        with pytest.raises(VersionDataError):
            await recommend(data, spec=spec, **kwargs)
    else:
        with pytest.raises(ValueError, match=message):
            await recommend(data, spec=spec, **kwargs)
    assert await runs(data) == []
