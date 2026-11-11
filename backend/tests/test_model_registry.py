"""Catalogue truthfulness and legacy API contracts; no fitting."""

from uuid import uuid4

import pytest
from app.schemas.model_catalog import ModelTypeDefinition
from app.schemas.modeling import ArxFitRequest
from app.services.model_registry import (
    get_model,
    list_models,
    parameter_json_schema,
    validate_parameters,
)
from pydantic import ValidationError


def parameters(**changes):
    return {
        "version_id": uuid4(),
        "na": 1,
        "nb": {"u": 1},
        "delays": {"u": 0},
        "input_columns": ["u"],
        **changes,
    }


def test_only_real_models_are_available():
    assert [m.model_type_id for m in list_models()] == [
        "arx",
        "fir",
        "oe",
        "pls",
        "xgboost",
        "tcn",
        "timexer",
    ]
    assert all(m.availability == "available" for m in list_models())
    assert [m.model_type_id for m in list_models(task_type="supervised_regression")] == [
        "pls",
        "xgboost",
        "tcn",
        "timexer",
    ]
    assert [m.model_type_id for m in list_models(task_type="dynamic_system_identification")] == [
        "arx",
        "fir",
        "oe",
    ]
    with pytest.raises(ValueError):
        get_model("svr")
    with pytest.raises(ValidationError):
        ModelTypeDefinition(model_type_id="svr", display_name="SVR", implementation_id="missing")


def test_xgboost_registry_uses_standalone_parameters():
    from app.schemas.xgboost import XGBoostParameters

    definition = get_model("xgboost")
    assert definition.execution_scope == "api" and definition.family == "tree_ensemble"
    assert definition.capabilities.supervised_regression and not definition.capabilities.free_run
    assert validate_parameters("xgboost", {"max_depth": 2}) == XGBoostParameters(max_depth=2)
    assert parameter_json_schema("xgboost") == XGBoostParameters.model_json_schema()
    with pytest.raises(ValidationError):
        validate_parameters("xgboost", {"na": 2})


def test_tcn_registry_uses_standalone_parameters():
    from app.schemas.tcn import TCNParameters

    definition = get_model("tcn")
    assert definition.execution_scope == "api" and definition.device == "cpu"
    assert definition.family == "temporal_convolution"
    assert definition.capabilities.single_target and not definition.capabilities.free_run
    assert validate_parameters("tcn", {"window_length": 29}) == TCNParameters(window_length=29)
    assert parameter_json_schema("tcn") == TCNParameters.model_json_schema()
    with pytest.raises(ValidationError):
        validate_parameters("tcn", {"window_length": 28})


def test_timexer_registry_uses_standalone_parameters():
    from app.schemas.timexer import TimeXerParameters

    definition = get_model("timexer")
    assert definition.execution_scope == "api" and definition.device == "cpu"
    assert definition.family == "time_series_transformer"
    assert definition.capabilities.single_target and not definition.capabilities.free_run
    assert validate_parameters("timexer", {"prediction_length": 3}) == TimeXerParameters(
        prediction_length=3
    )
    assert parameter_json_schema("timexer") == TimeXerParameters.model_json_schema()


def test_oe_capabilities_match_formal_service():
    oe = get_model("oe")
    assert oe.implementation_id.endswith("multihorizon.fit_multihorizon")
    assert "fit_output_error" not in oe.implementation_id
    assert oe.maturity == "experimental"
    assert not oe.capabilities.soft_weights
    assert oe.capabilities.continuous_selected_intervals_required
    assert not oe.capabilities.independent_run_api
    assert get_model("fir").capabilities.soft_weights
    with pytest.raises(ValidationError):
        oe.display_name = "changed"


@pytest.mark.parametrize(
    "family,changes",
    [
        ("arx", {}),
        ("fir", {"na": 0}),
        ("oe", {"estimator": "ridge", "ridge_alpha": 0.001}),
    ],
)
def test_parameters_reuse_legacy_schema(family, changes):
    params = parameters(**changes)
    actual = validate_parameters(family, params)
    assert actual == ArxFitRequest.model_validate({**params, "model_type": family.upper()})


@pytest.mark.parametrize(
    "changes",
    [
        {"na": 5},
        {"estimator": "ols"},
        {"initialization_policy": "past_residual"},
        {"sample_weights": {2: 0.5}},
    ],
)
def test_oe_invalid_options_are_rejected(changes):
    with pytest.raises(ValidationError):
        validate_parameters("oe", parameters(estimator="ridge") | changes)


def test_conflicting_family_and_unmapped_fields_fail():
    with pytest.raises(ValueError):
        validate_parameters("arx", parameters(model_type="OE"))
    with pytest.raises(ValidationError):
        validate_parameters("arx", parameters(manifest_version=1))
    with pytest.raises(ValidationError):
        validate_parameters("fir", parameters(na=0, regularization_kernel="tc", estimator="ols"))


def test_old_api_contract_and_schema_are_unchanged():
    from app.main import create_app

    operation = create_app().openapi()["paths"]["/api/v1/modeling/arx/fit"]["post"]
    assert operation["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/ArxFitRequest"
    )
    assert "200" in operation["responses"]
    parsed = ArxFitRequest.model_validate(parameters(estimation_method="ridge", nb=[1], delays=[0]))
    assert parsed.resolved_estimator() == "ridge"
    assert parsed.training_sample_indices == []
    schema = parameter_json_schema("arx")
    schema["properties"].clear()
    assert parameter_json_schema("fir")["properties"]


def test_planned_model_cannot_be_resolved_for_execution(monkeypatch):
    from app.services import model_registry

    monkeypatch.setattr(
        model_registry,
        "_MODELS",
        {"arx": get_model("arx").model_copy(update={"availability": "planned"})},
    )
    with pytest.raises(ValueError, match="not executable"):
        get_model("arx")


def test_pls_uses_separate_schema_and_has_no_dynamic_executor(monkeypatch):
    from app.schemas.pls import PLSParameters

    def forbidden(*args, **kwargs):
        raise AssertionError("PLS must not use the dynamic model parameter path")

    monkeypatch.setattr(ArxFitRequest, "model_validate", forbidden)
    monkeypatch.setattr(ArxFitRequest, "model_json_schema", forbidden)
    assert isinstance(validate_parameters("pls", {"n_components": 3}), PLSParameters)
    assert set(parameter_json_schema("pls")["properties"]) == {"n_components", "scale"}
    pls = get_model("pls")
    assert pls.family == "linear_latent_regression"
    assert pls.execution_scope == "api"
    assert pls.maturity == "experimental"
    assert pls.implementation_id == "app.services.pls_modeling_service.fit_pls_core"
    assert pls.capabilities.single_target
    assert pls.capabilities.supervised_regression
    assert pls.capabilities.prediction and pls.capabilities.latent_transform
    assert not pls.capabilities.multi_output
    assert not pls.capabilities.free_run
    assert not pls.capabilities.one_step_equation
    assert pls.capabilities.independent_run_api
    assert not pls.capabilities.selected_rows
    assert not pls.capabilities.soft_weights
    with pytest.raises(ValidationError):
        validate_parameters("pls", {"model_type": "ARX"})


def test_catalogue_cannot_be_changed_through_external_references():
    from app.services import model_registry

    pls = get_model("pls")
    with pytest.raises(TypeError):
        model_registry._MODELS["pls"] = get_model("arx")
    with pytest.raises(ValidationError):
        pls.capabilities.free_run = True
    with pytest.raises(ValidationError):
        pls.constraints += ("mutated",)
    document = pls.model_dump()
    document["capabilities"]["free_run"] = True
    assert not get_model("pls").capabilities.free_run
    schema = parameter_json_schema("pls")
    schema["properties"].clear()
    assert parameter_json_schema("pls")["properties"]


def test_dynamic_manifest_does_not_claim_pls_support():
    from app.schemas.model_catalog import ModelArtifactManifest

    assert set(
        ModelArtifactManifest.model_json_schema()["properties"]["model_type_id"]["enum"]
    ) == {
        "arx",
        "fir",
        "oe",
    }
