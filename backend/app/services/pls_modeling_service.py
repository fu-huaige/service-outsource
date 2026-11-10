"""PLS fitting on training arrays only; restored models need no sklearn object."""

from __future__ import annotations

import platform
import warnings
from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray

from app.schemas.pls import PLSParameters, PLSTrainingMetadata

FloatArray = NDArray[np.float64]
ARRAY_NAMES = (
    "coefficients",
    "intercept",
    "x_mean",
    "x_std",
    "y_mean",
    "y_std",
    "x_rotations",
    "x_loadings",
    "y_loadings",
)


def _numeric_array(value: ArrayLike, *, ndim: int) -> FloatArray:
    array = np.asarray(value)
    if array.ndim != ndim or array.dtype.kind not in "iuf":
        raise ValueError("Expected a real numeric array with the required shape")
    with np.errstate(over="ignore", invalid="ignore"):
        array = np.array(array, dtype=np.float64, order="C", copy=True)
    if not np.isfinite(array).all():
        raise ValueError("Input must contain only finite values")
    return array


@dataclass(frozen=True)
class SavedPLSModel:
    metadata: PLSTrainingMetadata
    coefficients: FloatArray
    intercept: FloatArray
    x_mean: FloatArray
    x_std: FloatArray
    y_mean: FloatArray
    y_std: FloatArray
    x_rotations: FloatArray
    x_loadings: FloatArray
    y_loadings: FloatArray

    def __post_init__(self) -> None:
        p, k = self.metadata.n_features, self.metadata.effective_n_components
        shapes = {
            "coefficients": (1, p),
            "intercept": (1,),
            "x_mean": (p,),
            "x_std": (p,),
            "y_mean": (1,),
            "y_std": (1,),
            "x_rotations": (p, k),
            "x_loadings": (p, k),
            "y_loadings": (1, k),
        }
        for name, shape in shapes.items():
            array = np.asarray(getattr(self, name))
            if array.dtype != np.dtype("float64") or array.shape != shape:
                raise ValueError(f"Invalid {name} shape or dtype")
            if not np.isfinite(array).all():
                raise ValueError(f"Nonfinite {name}")
            array = np.array(array, copy=True, order="C")
            array.setflags(write=False)
            object.__setattr__(self, name, array)
        if np.any(np.all(self.x_rotations == 0, axis=0)) or np.any(
            np.all(self.x_loadings == 0, axis=0)
        ):
            raise ValueError("Effective components must have nonzero latent state")
        if np.any(self.x_std <= 0) or np.any(self.y_std <= 0):
            raise ValueError("Standardization scales must be positive")
        if not self.metadata.scale and (
            not np.array_equal(self.x_std, np.ones(p)) or not np.array_equal(self.y_std, np.ones(1))
        ):
            raise ValueError("scale=False requires unit scales")
        if not np.array_equal(self.intercept, self.y_mean):
            raise ValueError("Intercept and training target mean mismatch")
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            expected = (self.x_rotations @ self.y_loadings.T * self.y_std).T / self.x_std
        if not np.isfinite(expected).all() or not np.allclose(
            self.coefficients, expected, rtol=1e-9, atol=1e-12
        ):
            raise ValueError("PLS coefficient and latent state mismatch")

    def arrays(self) -> dict[str, FloatArray]:
        return {name: getattr(self, name) for name in ARRAY_NAMES}

    def _features(self, X: ArrayLike, feature_names: tuple[str, ...] | None) -> FloatArray:
        if feature_names is not None and (
            not isinstance(feature_names, (list, tuple))
            or tuple(feature_names) != self.metadata.feature_names
        ):
            raise ValueError("Feature order differs from training")
        array = _numeric_array(X, ndim=2)
        if array.shape[1] != self.metadata.n_features:
            raise ValueError("Feature count differs from training")
        return array

    def predict(self, X: ArrayLike, *, feature_names: tuple[str, ...] | None = None) -> FloatArray:
        array = self._features(X, feature_names)
        # sklearn 1.7.2 coef_ already includes the X/Y scale conversion.
        with np.errstate(over="ignore", invalid="ignore"):
            prediction = ((array - self.x_mean) @ self.coefficients.T + self.intercept).ravel()
        if not np.isfinite(prediction).all():
            raise ValueError("Prediction must be finite")
        return prediction

    def transform(
        self, X: ArrayLike, *, feature_names: tuple[str, ...] | None = None
    ) -> FloatArray:
        array = self._features(X, feature_names)
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            scores = ((array - self.x_mean) / self.x_std) @ self.x_rotations
        if not np.isfinite(scores).all():
            raise ValueError("Latent scores must be finite")
        return scores


def _extract_sklearn_172(
    model: object,
    *,
    feature_names: tuple[str, ...],
    target_name: str,
    parameters: PLSParameters,
    training_rows: int,
    training_warnings: tuple[str, ...],
) -> SavedPLSModel:
    """The only adapter that reads sklearn private fitted attributes."""
    import scipy
    import sklearn

    if sklearn.__version__ != "1.7.2":
        raise ValueError("Unsupported sklearn adapter version")
    # n_iter_ is appended only after a component has actually been extracted.
    iterations = tuple(int(i) for i in model.n_iter_)
    k = len(iterations)
    if not 1 <= k <= parameters.n_components:
        raise ValueError("PLS did not extract any usable components")
    rotations = np.asarray(model.x_rotations_, dtype=np.float64)
    loadings = np.asarray(model.x_loadings_, dtype=np.float64)
    y_loadings = np.asarray(model.y_loadings_, dtype=np.float64)
    if (
        rotations.shape != (len(feature_names), parameters.n_components)
        or loadings.shape != rotations.shape
        or y_loadings.shape != (1, parameters.n_components)
        or np.any(np.linalg.norm(rotations[:, :k], axis=0) == 0)
        or np.any(np.linalg.norm(loadings[:, :k], axis=0) == 0)
        or np.any(rotations[:, k:] != 0)
        or np.any(y_loadings[:, k:] != 0)
    ):
        raise ValueError("Invalid extracted component state")
    if k != parameters.n_components:
        training_warnings += (
            f"Effective components reduced from {parameters.n_components} to {k}",
        )
    metadata = PLSTrainingMetadata(
        sklearn_version=sklearn.__version__,
        numpy_version=np.__version__,
        scipy_version=scipy.__version__,
        python_version=platform.python_version(),
        feature_names=feature_names,
        target_name=target_name,
        n_features=len(feature_names),
        requested_n_components=parameters.n_components,
        effective_n_components=k,
        scale=parameters.scale,
        training_rows=training_rows,
        parameters=parameters,
        n_iter=iterations,
        training_warnings=training_warnings,
    )
    return SavedPLSModel(
        metadata=metadata,
        coefficients=np.asarray(model.coef_, dtype=np.float64),
        intercept=np.asarray(model.intercept_, dtype=np.float64),
        x_mean=np.asarray(model._x_mean, dtype=np.float64),
        x_std=np.asarray(model._x_std, dtype=np.float64),
        y_mean=np.asarray(model._y_mean, dtype=np.float64),
        y_std=np.asarray(model._y_std, dtype=np.float64),
        x_rotations=rotations[:, :k],
        x_loadings=loadings[:, :k],
        y_loadings=y_loadings[:, :k],
    )


def fit_pls_core(
    X_train: ArrayLike,
    y_train: ArrayLike,
    *,
    feature_names: tuple[str, ...],
    target_name: str,
    parameters: PLSParameters | None = None,
) -> SavedPLSModel:
    """Fit once on exactly these training arrays. No splitting or dataset access."""
    from sklearn.cross_decomposition import PLSRegression
    from sklearn.exceptions import ConvergenceWarning

    parameters = (
        PLSParameters()
        if parameters is None
        else PLSParameters.model_validate(
            parameters.model_dump() if isinstance(parameters, PLSParameters) else parameters
        )
    )
    X, y = _numeric_array(X_train, ndim=2), _numeric_array(y_train, ndim=1)
    if not isinstance(feature_names, (list, tuple)):
        raise ValueError("Feature names must be an ordered sequence of names")
    feature_names = tuple(feature_names)
    n, p = X.shape
    if n < 2 or p == 0 or y.shape != (n,):
        raise ValueError("Training requires at least two aligned rows and one feature")
    if (
        len(feature_names) != p
        or any(not isinstance(name, str) or not name.strip() for name in feature_names)
        or len(set(feature_names)) != p
        or not isinstance(target_name, str)
        or not target_name.strip()
        or target_name in feature_names
    ):
        raise ValueError("Invalid feature names or target")
    if parameters.n_components > min(n, p):
        raise ValueError("n_components exceeds min(n_train, n_features)")
    if np.all(y == y[0]):
        raise ValueError("Constant training target is not supported")
    constant = np.all(X[0] == X, axis=0)
    if constant.all():
        raise ValueError("All training features are constant")
    notes = tuple(f"Constant input: {feature_names[i]}" for i in np.flatnonzero(constant))
    model = PLSRegression(
        n_components=parameters.n_components,
        scale=parameters.scale,
        max_iter=parameters.max_iter,
        tol=parameters.tol,
        copy=parameters.copy,
    )
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        model.fit(X, y)
    if any(issubclass(w.category, ConvergenceWarning) for w in captured):
        raise ValueError("PLS did not converge")
    notes += tuple(f"{w.category.__name__}: {w.message}" for w in captured)
    return _extract_sklearn_172(
        model,
        feature_names=feature_names,
        target_name=target_name,
        parameters=parameters,
        training_rows=n,
        training_warnings=notes,
    )
