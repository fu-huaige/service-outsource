"""Native CPU training and fixed prediction on explicitly supplied arrays only."""

from __future__ import annotations

import json
import platform
from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import ArrayLike, NDArray

from app.schemas.xgboost import XGBoostParameters, XGBoostTrainingMetadata

if TYPE_CHECKING:
    from types import ModuleType

    from xgboost import Booster

TRAINING_ATTRIBUTE = "indusopt_training_metadata"
SUPPORTED_VERSION = "3.1.3"


def xgboost_runtime() -> ModuleType:
    """Import only at an execution boundary; never make older models require XGBoost."""
    import xgboost

    if xgboost.__version__ != SUPPORTED_VERSION:
        raise ValueError("Unsupported XGBoost runtime version; expected 3.1.3")
    return xgboost


def numeric_matrix(value: ArrayLike, *, ndim: int) -> NDArray[np.float32]:
    """Reject coercible strings/bools and check both sides of the float32 boundary."""
    array = np.asarray(value)
    if array.ndim != ndim or array.dtype.kind not in "iuf":
        raise ValueError("Expected real numeric data with the required dimensions")
    if not np.isfinite(array).all():
        raise ValueError("Input contains NaN or infinity")
    with np.errstate(over="ignore", invalid="ignore"):
        converted = np.array(array, dtype=np.float32, order="C", copy=True)
    if not np.isfinite(converted).all():
        raise ValueError("Input overflows the float32 representation")
    return converted


def _validate_booster(booster: Booster, metadata: XGBoostTrainingMetadata) -> None:
    xgb = xgboost_runtime()
    if not isinstance(booster, xgb.Booster):
        raise ValueError("Expected a native XGBoost Booster")
    config = json.loads(booster.save_config())["learner"]
    if (
        config["gradient_booster"]["name"] != "gbtree"
        or config["objective"]["name"] != "reg:squarederror"
        or int(config["learner_model_param"]["num_target"]) != 1
        or config["generic_param"]["device"] != "cpu"
        or int(config["generic_param"]["nthread"]) != 1
        or booster.num_features() != metadata.n_features
        or booster.num_boosted_rounds() != metadata.boosting_rounds
        or booster.feature_names != list(metadata.internal_feature_names)
    ):
        raise ValueError("Native Booster does not match the fixed model contract")


def training_metadata(booster: Booster) -> XGBoostTrainingMetadata:
    xgb = xgboost_runtime()
    if not isinstance(booster, xgb.Booster):
        raise ValueError("Expected a native XGBoost Booster")
    raw = booster.attr(TRAINING_ATTRIBUTE)
    if raw is None or len(raw.encode("utf-8")) > 1_048_576:
        raise ValueError("Missing or oversized XGBoost training metadata")
    metadata = XGBoostTrainingMetadata.model_validate_json(raw)
    _validate_booster(booster, metadata)
    return metadata


def fit_xgboost_core(
    X_train: ArrayLike,
    y_train: ArrayLike,
    *,
    feature_names: tuple[str, ...],
    target_name: str,
    parameters: XGBoostParameters | None = None,
    random_seed: int = 0,
) -> Booster:
    """Return a native Booster after exactly one train call; no splitting or persistence."""
    parameters = XGBoostParameters.model_validate(
        {}
        if parameters is None
        else (parameters.model_dump() if isinstance(parameters, XGBoostParameters) else parameters)
    )
    effective = parameters.booster_parameters(random_seed=random_seed)
    x, y = numeric_matrix(X_train, ndim=2), numeric_matrix(y_train, ndim=1)
    n, p = x.shape
    if n < 2 or p < 1 or y.shape != (n,):
        raise ValueError("Training requires at least two aligned rows and one feature")
    if (
        not isinstance(feature_names, (tuple, list))
        or len(feature_names) != p
        or any(not isinstance(name, str) or not name.strip() for name in feature_names)
        or len(set(feature_names)) != p
        or not isinstance(target_name, str)
        or not target_name.strip()
        or target_name in feature_names
    ):
        raise ValueError("Invalid feature names, feature count or isolated target")
    internal = tuple(f"f{i}" for i in range(p))
    xgb = xgboost_runtime()
    import scipy

    matrix = xgb.DMatrix(x, label=y, feature_names=list(internal), nthread=1)
    booster = xgb.train(
        effective,
        matrix,
        num_boost_round=parameters.num_boost_round,
        evals=(),
        verbose_eval=False,
    )
    metadata = XGBoostTrainingMetadata(
        xgboost_version=xgb.__version__,
        python_version=platform.python_version(),
        numpy_version=np.__version__,
        scipy_version=scipy.__version__,
        parameters=parameters,
        effective_parameters=effective,
        random_seed=random_seed,
        boosting_rounds=booster.num_boosted_rounds(),
        feature_names=tuple(feature_names),
        internal_feature_names=internal,
        n_features=p,
        target_name=target_name,
        training_rows=n,
    )
    booster.set_attr(**{TRAINING_ATTRIBUTE: metadata.model_dump_json()})
    _validate_booster(booster, metadata)
    # Check actual numerical behavior, including failures inside the native learner.
    predict_xgboost(booster, x, feature_names=tuple(feature_names))
    return booster


def predict_xgboost(
    booster: Booster,
    X: ArrayLike,
    *,
    feature_names: tuple[str, ...],
) -> NDArray[np.float64]:
    """Predict with all saved rounds; callers cannot supply training or iteration options."""
    metadata = training_metadata(booster)
    if (
        not isinstance(feature_names, (list, tuple))
        or tuple(feature_names) != metadata.feature_names
    ):
        raise ValueError("Feature order differs from training")
    x = numeric_matrix(X, ndim=2)
    if x.shape[0] == 0 or x.shape[1] != metadata.n_features:
        raise ValueError("Prediction requires nonempty rows with the trained feature count")
    xgb = xgboost_runtime()
    matrix = xgb.DMatrix(x, feature_names=list(metadata.internal_feature_names), nthread=1)
    prediction = np.asarray(booster.predict(matrix, validate_features=True, strict_shape=True))
    if prediction.shape != (x.shape[0], 1) or not np.isfinite(prediction).all():
        raise ValueError("Native prediction has an invalid shape or nonfinite values")
    return prediction[:, 0].astype(np.float64, copy=True)
