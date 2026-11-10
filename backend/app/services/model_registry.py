"""Static, audited model catalogue; no dynamic imports and no fitting."""

from __future__ import annotations

from types import MappingProxyType

from app.schemas.model_catalog import ModelCapabilities, ModelTypeDefinition
from app.schemas.modeling import ArxFitRequest

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


def validate_parameters(model_type_id: str, parameters: dict[str, object]) -> ArxFitRequest:
    model = get_model(model_type_id)
    family = model.model_type_id.upper()
    if parameters.get("model_type", family) != family:
        raise ValueError("model_type_id conflicts with model_type")
    return ArxFitRequest.model_validate({**parameters, "model_type": family})


def parameter_json_schema(model_type_id: str) -> dict[str, object]:
    get_model(model_type_id)
    return ArxFitRequest.model_json_schema()
