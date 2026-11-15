"""Static, audited model catalogue; no dynamic imports and no fitting."""

from __future__ import annotations

from types import MappingProxyType

from app.schemas.model_catalog import ModelCapabilities, ModelTypeDefinition
from app.schemas.modeling import ArxFitRequest
from app.schemas.pls import PLSParameters
from app.schemas.tcn import TCNParameters
from app.schemas.timexer import TimeXerParameters
from app.schemas.xgboost import XGBoostParameters

_MODELS = MappingProxyType(
    {
        "arx": ModelTypeDefinition(
            model_type_id="arx",
            display_name="ARX",
            description="结合输入及输出历史，辨识动态响应。",
            implementation_id="algorithms.identifiability.estimation.estimate_parameters",
            constraints=("na >= 1", "OLS/Ridge/Huber; stability is diagnosed, not guaranteed"),
        ),
        "fir": ModelTypeDefinition(
            model_type_id="fir",
            display_name="FIR",
            description="从滞后输入估计有限脉冲响应。",
            implementation_id="algorithms.identifiability.estimation.estimate_parameters",
            constraints=("na = 0", "TC kernel requires standardized Ridge with positive alpha"),
        ),
        "oe": ModelTypeDefinition(
            model_type_id="oe",
            display_name="Multihorizon OE",
            description="通过多时域仿真辨识输出误差模型。",
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
            description="通过潜变量预测连续目标，适用于输入共线的场景。",
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
        "xgboost": ModelTypeDefinition(
            model_type_id="xgboost",
            display_name="XGBoost Regression",
            description="用提升树学习输入与连续目标之间的非线性关系。",
            family="tree_ensemble",
            supported_tasks=("supervised_regression",),
            maturity="experimental",
            execution_scope="api",
            implementation_id="app.services.xgboost_modeling_service.fit_xgboost_core",
            implementation_version="xgboost-core-1",
            parameter_schema_id="app.schemas.xgboost.XGBoostParameters",
            capabilities=ModelCapabilities(
                supervised_regression=True,
                independent_run_api=True,
                selected_rows=False,
                soft_weights=False,
                free_run=False,
                one_step_equation=False,
            ),
            constraints=("Static single target, horizon=1, full Train",),
            dependencies=("numpy>=1.26,<3", "scipy>=1.13,<2", "xgboost==3.1.3"),
        ),
        "tcn": ModelTypeDefinition(
            model_type_id="tcn",
            display_name="Temporal Convolutional Network",
            description="用时间卷积对历史窗口建模。",
            family="temporal_convolution",
            supported_tasks=("supervised_regression",),
            maturity="experimental",
            execution_scope="api",
            implementation_id="app.services.tcn_modeling_service.fit_tcn_core",
            implementation_version="tcn-core-1",
            parameter_schema_id="app.schemas.tcn.TCNParameters",
            capabilities=ModelCapabilities(
                supervised_regression=True,
                independent_run_api=True,
                selected_rows=False,
                soft_weights=False,
                free_run=False,
                one_step_equation=False,
            ),
            constraints=("Uniform sampling, fixed history, single target, horizon=1, full Train",),
            dependencies=("numpy>=1.26,<3", "torch==2.9.1"),
        ),
        "timexer": ModelTypeDefinition(
            model_type_id="timexer",
            display_name="TimeXer",
            description="结合目标历史和外生变量进行时序预测。",
            family="time_series_transformer",
            supported_tasks=("supervised_regression",),
            maturity="experimental",
            execution_scope="api",
            implementation_id="app.services.timexer_modeling_service.fit_timexer_core",
            implementation_version="timexer-core-1",
            parameter_schema_id="app.schemas.timexer.TimeXerParameters",
            capabilities=ModelCapabilities(
                supervised_regression=True,
                independent_run_api=True,
                selected_rows=False,
                soft_weights=False,
                free_run=False,
                one_step_equation=False,
            ),
            constraints=(
                "Separate target and exogenous histories; single target",
                "Fixed forecast horizon of 1 to 32 steps; uniform sampling; full Train",
            ),
            dependencies=("numpy>=1.26,<3", "torch==2.9.1"),
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
) -> ArxFitRequest | PLSParameters | XGBoostParameters | TCNParameters | TimeXerParameters:
    model = get_model(model_type_id)
    if model.model_type_id == "pls":
        return PLSParameters.model_validate(parameters)
    if model.model_type_id == "xgboost":
        return XGBoostParameters.model_validate(parameters)
    if model.model_type_id == "tcn":
        return TCNParameters.model_validate(parameters)
    if model.model_type_id == "timexer":
        return TimeXerParameters.model_validate(parameters)
    family = model.model_type_id.upper()
    if parameters.get("model_type", family) != family:
        raise ValueError("model_type_id conflicts with model_type")
    defaults = {"na": 0} if family == "FIR" else {}
    return ArxFitRequest.model_validate({**defaults, **parameters, "model_type": family})


def parameter_json_schema(model_type_id: str) -> dict[str, object]:
    model = get_model(model_type_id)
    if model.model_type_id == "pls":
        return PLSParameters.model_json_schema()
    if model.model_type_id == "xgboost":
        return XGBoostParameters.model_json_schema()
    if model.model_type_id == "tcn":
        return TCNParameters.model_json_schema()
    if model.model_type_id == "timexer":
        return TimeXerParameters.model_json_schema()
    return ArxFitRequest.model_json_schema()
