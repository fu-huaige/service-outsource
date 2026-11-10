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
    assert [m.model_type_id for m in list_models()] == ["arx", "fir", "oe"]
    assert all(m.availability == "available" for m in list_models())
    assert list_models(task_type="supervised_regression") == ()
    with pytest.raises(ValueError):
        get_model("pls")
    with pytest.raises(ValidationError):
        ModelTypeDefinition(model_type_id="pls", display_name="PLS", implementation_id="missing")


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
