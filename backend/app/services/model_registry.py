"""Static, audited model catalogue; no dynamic imports and no fitting."""

from __future__ import annotations

from types import MappingProxyType

from app.schemas.model_catalog import ModelCapabilities, ModelTypeDefinition
from app.schemas.modeling import ArxFitRequest
from app.schemas.pls import PLSParameters

_MODELS = MappingProxyType(
    {
        "arx": ModelTypeDefinition(
            model_type_id="arx",
            display_name="ARX",
            implementation_id="algorithms.identifiability.estimation.estimate_parameters",
            constraints=("na >= 1", "OLS/Ridge/Huber; stability is diagnosed, not guaranteed"),
        ),
        "fir": ModelTypeDefinition(
            model_type_id="fir",
            display_name="FIR",
            implementation_id="algorithms.identifiability.estimation.estimate_parameters",
            constraints=("na = 0", "TC kernel requires standardized Ridge with positive alpha"),
        ),
        "oe": ModelTypeDefinition(
            model_type_id="oe",
            display_name="Multihorizon OE",
            maturity="experimental",
            implementation_id="algorithms.identifiability.multihorizon.fit_multihorizon",
            capabilities=ModelCapabilities(
                soft_weights=False, continuous_selected_intervals_required=True
            ),
            constraints=(
                "shared denominator stored as na, 1..4",
                "Ridge initialization, intercept and standardization",
                "fixed initialization",
                "binary weights only",
                "continuous selected intervals with original histories",
            ),
        ),
        "pls": ModelTypeDefinition(
            model_type_id="pls",
            display_name="PLS Regression",
            family="linear_latent_regression",
            supported_tasks=("supervised_regression",),
            maturity="experimental",
            execution_scope="api",
            implementation_id="app.services.pls_modeling_service.fit_pls_core",
            implementation_version="pls-core-1",
            parameter_schema_id="app.schemas.pls.PLSParameters",
            capabilities=ModelCapabilities(
                supervised_regression=True,
                independent_run_api=True,
                latent_transform=True,
                selected_rows=False,
                soft_weights=False,
                free_run=False,
                one_step_equation=False,
            ),
            constraints=(
                "Static single target: X[r] -> y[r], horizon=1, no history or guard",
                "Only n_components and scale are configurable; training arrays only",
                "PLS business API, version-bound ProcessingRun and unified Manifest",
                "Dependency readiness is checked by the caller environment",
            ),
            dependencies=("numpy>=1.26,<3", "scipy>=1.13,<2", "scikit-learn==1.7.2"),
        ),
    }
)


def list_models(*, task_type: str | None = None) -> tuple[ModelTypeDefinition, ...]:
    return tuple(m for m in _MODELS.values() if task_type is None or task_type in m.supported_tasks)


def get_model(model_type_id: str) -> ModelTypeDefinition:
    try:
        model = _MODELS[model_type_id]
    except KeyError as error:
        raise ValueError("Unknown model_type_id") from error
    if model.availability != "available":
        raise ValueError("Model is not executable")
    return model


def validate_parameters(
    model_type_id: str, parameters: dict[str, object]
) -> ArxFitRequest | PLSParameters:
    model = get_model(model_type_id)
    if model.model_type_id == "pls":
        return PLSParameters.model_validate(parameters)
    family = model.model_type_id.upper()
    if parameters.get("model_type", family) != family:
        raise ValueError("model_type_id conflicts with model_type")
    return ArxFitRequest.model_validate({**parameters, "model_type": family})


def parameter_json_schema(model_type_id: str) -> dict[str, object]:
    model = get_model(model_type_id)
    if model.model_type_id == "pls":
        return PLSParameters.model_json_schema()
    return ArxFitRequest.model_json_schema()
