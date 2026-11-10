"""Strict PLS core contracts, without business API schemas."""

import pytest
from app.schemas.pls import PLSParameters, PLSTrainingMetadata
from pydantic import ValidationError


def test_defaults_and_fixed_solver_options():
    params = PLSParameters()
    assert params.model_dump() == {"n_components": 2, "scale": True}
    assert (params.max_iter, params.tol, params.copy) == (500, 1e-6, True)


@pytest.mark.parametrize(
    "changes",
    [
        {"n_components": 0},
        {"n_components": -1},
        {"n_components": True},
        {"n_components": 2.0},
        {"n_components": "2"},
        {"scale": 1},
        {"scale": "false"},
        {"max_iter": 500},
        {"tol": float("nan")},
        {"tol": float("inf")},
        {"tol": 1e-6},
        {"copy": True},
        {"history_guard": 1},
        {"prediction_horizon": 2},
    ],
)
def test_invalid_or_unexposed_parameters_are_rejected(changes):
    with pytest.raises(ValidationError):
        PLSParameters(**changes)


def test_parameter_schema_is_small_and_strict():
    schema = PLSParameters.model_json_schema()
    assert set(schema["properties"]) == {"n_components", "scale"}
    assert schema["additionalProperties"] is False
    assert PLSParameters(n_components=3, scale=False).n_components == 3


def test_training_metadata_rejects_inconsistent_dimensions():
    with pytest.raises(ValidationError):
        PLSTrainingMetadata(
            sklearn_version="1.7.2",
            numpy_version="2.4.6",
            scipy_version="1.17.1",
            python_version="3.11.3",
            feature_names=("x",),
            target_name="y",
            n_features=2,
            requested_n_components=1,
            effective_n_components=1,
            scale=True,
            training_rows=5,
            parameters=PLSParameters(n_components=1),
            n_iter=(1,),
        )


def test_bound_artifact_requires_complete_source_and_version_separation():
    from uuid import uuid4

    from app.schemas.pls import PLSArtifactProvenance, PLSBoundArtifactMetadata

    with pytest.raises(ValidationError):
        PLSArtifactProvenance(training_run_id=uuid4())
    with pytest.raises(ValidationError):
        PLSBoundArtifactMetadata.model_validate({"artifact_version": 2})
    # The old contract remains v1 and cannot accept new provenance silently.
    from app.schemas.pls import PLSArtifactMetadata

    assert PLSArtifactMetadata.model_fields["artifact_version"].default == 1
    assert "provenance" not in PLSArtifactMetadata.model_fields
    assert PLSBoundArtifactMetadata.model_fields["artifact_version"].default == 2
