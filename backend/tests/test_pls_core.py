"""Numerical parity with sklearn and isolation of the core fitting boundary."""

import numpy as np
import pytest
from app.schemas.pls import PLSParameters
from app.services.pls_modeling_service import fit_pls_core
from sklearn.cross_decomposition import PLSRegression


def data():
    rng = np.random.default_rng(17)
    x = rng.normal(size=(90, 4)) * [0.2, 3, 20, 5] + [10, -8, 40, 90]
    y = x @ np.array([3, -0.8, 0.2, 2]) + 11 + rng.normal(0, 0.05, 90)
    return x, y


def fit(x=None, y=None, **kwargs):
    default_x, default_y = data()
    return fit_pls_core(
        default_x if x is None else x,
        default_y if y is None else y,
        feature_names=kwargs.pop("feature_names", ("a", "b", "c", "d")),
        target_name=kwargs.pop("target_name", "quality"),
        parameters=kwargs.pop("parameters", PLSParameters()),
        **kwargs,
    )


@pytest.mark.parametrize("scale", [True, False])
def test_sklearn_parity_and_train_only_statistics(scale, monkeypatch):
    x, y = data()
    x_train, x_test = x[:65].copy(), x[65:].copy() + 100
    reference = PLSRegression(n_components=3, scale=scale).fit(x_train, y[:65])
    original_fit = PLSRegression.fit
    calls = []

    def counted(self, features, target):
        calls.append((features.copy(), target.copy()))
        return original_fit(self, features, target)

    monkeypatch.setattr(PLSRegression, "fit", counted)
    saved = fit(x_train, y[:65], parameters=PLSParameters(n_components=3, scale=scale))
    assert len(calls) == 1
    np.testing.assert_array_equal(calls[0][0], x_train)
    np.testing.assert_array_equal(calls[0][1], y[:65])
    assert saved.metadata.training_rows == 65
    np.testing.assert_allclose(saved.x_mean, x_train.mean(axis=0))
    expected_std = x_train.std(axis=0, ddof=1) if scale else np.ones(4)
    np.testing.assert_allclose(saved.x_std, expected_std)
    np.testing.assert_allclose(
        saved.predict(x_test), reference.predict(x_test), rtol=1e-9, atol=1e-12
    )
    np.testing.assert_allclose(
        saved.transform(x_test), reference.transform(x_test), rtol=1e-9, atol=1e-12
    )
    np.testing.assert_array_equal(x[:65], x_train)

    def forbidden(*args, **kwargs):
        raise AssertionError("Prediction must not fit")

    monkeypatch.setattr(PLSRegression, "fit", forbidden)
    saved.predict(x_test)
    saved.transform(x_test)


@pytest.mark.parametrize(
    "case",
    [
        "multi_target",
        "column_target",
        "one_sample",
        "no_features",
        "row_count",
        "nan_x",
        "inf_y",
        "constant_y",
        "constant_x",
        "complex",
        "string",
        "boolean",
    ],
)
def test_invalid_training_data(case):
    x, y = data()
    if case == "multi_target":
        y = np.column_stack((y, y))
    elif case == "column_target":
        y = y[:, None]
    elif case == "one_sample":
        x, y = x[:1], y[:1]
    elif case == "no_features":
        x = x[:, :0]
    elif case == "row_count":
        y = y[:-1]
    elif case == "nan_x":
        x[0, 0] = np.nan
    elif case == "inf_y":
        y[0] = np.inf
    elif case == "constant_y":
        y[:] = 3
    elif case == "constant_x":
        x[:] = 2
    elif case == "complex":
        x = x.astype(complex)
    elif case == "string":
        x = x.astype(str)
    elif case == "boolean":
        x = x > 0
    with pytest.raises(ValueError):
        fit(x, y)


@pytest.mark.parametrize(
    "names,target",
    [
        (("a", "a", "c", "d"), "y"),
        (("a", "b"), "y"),
        (("a", "b", "c", "d"), "a"),
        (("a", " ", "c", "d"), "y"),
    ],
)
def test_feature_names(names, target):
    with pytest.raises(ValueError):
        fit(feature_names=names, target_name=target)


def test_component_upper_bound_uses_real_training_shape():
    with pytest.raises(ValueError, match="n_components"):
        fit(parameters=PLSParameters(n_components=5))
    x, y = data()
    with pytest.raises(ValueError, match="n_components"):
        fit(x[:2], y[:2], parameters=PLSParameters(n_components=3))


def test_partial_constant_column_is_reported_and_order_preserved():
    x, y = data()
    x[:, 2] = 7
    saved = fit(x, y)
    assert saved.metadata.feature_names == ("a", "b", "c", "d")
    assert any("constant" in warning.lower() for warning in saved.metadata.training_warnings)
    assert saved.x_std[2] == 1


def test_completed_components_are_recorded_instead_of_requested_count():
    x = np.arange(1, 11, dtype=float)[:, None]
    x = np.column_stack((x, 2 * x, 3 * x))
    y = np.arange(1, 11, dtype=float) * 4
    saved = fit(x, y, feature_names=("a", "b", "c"), parameters=PLSParameters(n_components=3))
    assert saved.metadata.effective_n_components < 3
    assert saved.x_rotations.shape == (3, saved.metadata.effective_n_components)
    assert saved.metadata.training_warnings
    with pytest.warns(UserWarning, match="constant"):
        reference = PLSRegression(n_components=3).fit(x, y)
    np.testing.assert_allclose(saved.predict(x), reference.predict(x), rtol=1e-9, atol=1e-12)
    np.testing.assert_allclose(
        saved.transform(x),
        reference.transform(x)[:, : saved.metadata.effective_n_components],
        rtol=1e-9,
        atol=1e-12,
    )


def test_predict_transform_validate_order_shape_and_finiteness():
    saved = fit()
    x, _ = data()
    saved.predict(x, feature_names=("a", "b", "c", "d"))
    for method in (saved.predict, saved.transform):
        with pytest.raises(ValueError, match="order"):
            method(x, feature_names=("b", "a", "c", "d"))
        with pytest.raises(ValueError):
            method(x[:, :2])
        with pytest.raises(ValueError):
            method(x.astype(complex))
        bad = x.copy()
        bad[0, 0] = np.nan
        with pytest.raises(ValueError):
            method(bad)
        huge = np.full((2, 4), np.finfo(float).max)
        with pytest.raises(ValueError, match="finite"):
            method(huge)


@pytest.mark.parametrize("parameters", [False, 0, [], ""])
def test_false_like_parameter_objects_are_not_silently_defaulted(parameters):
    with pytest.raises(ValueError):
        fit(parameters=parameters)


@pytest.mark.parametrize("names", ["abcd", ("a", {}, "c", "d")])
def test_malformed_feature_name_container_rejected(names):
    with pytest.raises(ValueError):
        fit(feature_names=names)


def test_convergence_warning_is_a_training_failure(monkeypatch):
    import warnings

    from sklearn.exceptions import ConvergenceWarning

    original = PLSRegression.fit

    def nonconvergent(self, x, y):
        result = original(self, x, y)
        warnings.warn("Injected nonconvergence", ConvergenceWarning, stacklevel=2)
        return result

    monkeypatch.setattr(PLSRegression, "fit", nonconvergent)
    with pytest.raises(ValueError, match="converge"):
        fit()
