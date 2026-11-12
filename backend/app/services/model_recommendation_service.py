"""Screen model contracts against verified training data without fitting."""

import asyncio
from datetime import UTC, datetime
from itertools import groupby
from math import isfinite
from pathlib import Path

import numpy as np
from algorithms.cleaning.quality import _frozen_segments, build_quality_profile
from algorithms.identifiability.collinearity import analyze_collinearity
from algorithms.identifiability.regressor import IdentifiabilityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dataset import Dataset, DatasetVersion
from app.schemas.experiment_spec import ExperimentSpec, RowSet
from app.schemas.model_recommendation import (
    CandidateEvidence,
    ContinuousRunProfile,
    DataProfileSummary,
    ModelCandidate,
    ModelRecommendationRequest,
    ModelRecommendationResult,
    RecommendationModelType,
    RecommendationSource,
)
from app.schemas.pls import PLSParameters
from app.schemas.tcn import MAX_FEATURES, TCNParameters
from app.schemas.tcn_platform import MAX_FEATURE_NAME_LENGTH as TCN_NAME_LIMIT
from app.schemas.timexer import TimeXerParameters, validate_feature_names
from app.schemas.timexer_platform import MAX_FEATURE_NAME_LENGTH as TIMEXER_NAME_LIMIT
from app.schemas.timexer_platform import TimeXerForecastSpec
from app.schemas.xgboost import XGBoostParameters
from app.schemas.xgboost_platform import MAX_FEATURE_NAME_LENGTH as XGBOOST_NAME_LIMIT
from app.services.dataset_csv import ParsedCsv
from app.services.dataset_version_io import artifact_matches_sha256, load_version_csv
from app.services.experiment_spec_service import (
    bind_experiment_spec,
    effective_ranges,
    iter_rows,
    spec_hash,
)
from app.services.model_data_adapter import (
    BoundSource,
    PreparedBatch,
    _validate_static_spec,
    build_table_samples,
)
from app.services.model_registry import get_model, validate_parameters
from app.services.sequence_data_adapter import build_tcn_samples, build_timexer_samples
from app.services.version_data import VersionSeries, load_version_series
from app.services.xgboost_modeling_service import numeric_matrix

_MODELS: tuple[RecommendationModelType, ...] = ("pls", "xgboost", "tcn", "timexer")
_MAX_SEQUENCE_BYTES = 128 * 1024**2
_MAX_DIAGNOSTIC_FEATURES = 64
_NAME_LIMITS = {"xgboost": XGBOOST_NAME_LIMIT, "tcn": TCN_NAME_LIMIT, "timexer": TIMEXER_NAME_LIMIT}


class _Unverified(ValueError):
    """A candidate lacks evidence for a required check."""


def _finite(value: float) -> float | None:
    return float(value) if isfinite(value) else None


def _profile(
    parsed: ParsedCsv,
    series: VersionSeries,
    spec: ExperimentSpec,
    source: RecommendationSource,
    positions: tuple[int, ...],
) -> DataProfileSummary:
    columns = (*source.feature_names, source.target_name)
    rows = [parsed.rows[row] for row in positions]
    types = {name: parsed.inferred_types[name] for name in columns}
    quality = build_quality_profile(
        dataset_id=str(source.dataset_id),
        version_id=str(source.dataset_version_id),
        headers=columns,
        rows=rows,
        inferred_types=types,
        timestamps=(),
    ).payload
    runs = []
    frozen = set()
    offset = 0
    for run in spec.continuous_runs:
        start = offset
        while offset < len(positions) and positions[offset] < run.stop:
            offset += 1
        runs.append(ContinuousRunProfile(rows=run, train_record_count=offset - start))
        # Frozen stretches cannot bridge a split, a sparse gap or a clock restart.
        for _, group in groupby(range(start, offset), key=lambda index: positions[index] - index):
            group_rows = [rows[index] for index in group]
            for name in columns:
                if types[name] in {"float", "integer"} and _frozen_segments(
                    name, [row[name] for row in group_rows]
                ):
                    frozen.add(name)

    diagnostic = None
    if 2 <= len(source.feature_names) <= _MAX_DIAGNOSTIC_FEATURES and len(positions) >= 2:
        indices = np.asarray(positions, dtype=np.intp)
        inputs = {name: series.values[name][indices] for name in source.feature_names}
        if all(np.isfinite(column).all() for column in inputs.values()):
            try:
                with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
                    diagnostic = analyze_collinearity(inputs=inputs)
            except (IdentifiabilityError, np.linalg.LinAlgError, FloatingPointError):
                pass

    axis = spec.time_axis
    verified_uniform = axis.column is not None and axis.sampling_status == "uniform"
    sampling = axis.sampling_status if axis.column is not None else "unknown"
    return DataProfileSummary(
        **source.model_dump(),
        sample_count=len(positions),
        feature_count=len(source.feature_names),
        target_type=types[source.target_name],
        missing_rate=quality["missing_rate"],
        missing_rates=quality["missing_rates"],
        anomaly_summary=quality["anomaly_counts"],
        constant_columns=tuple(quality["constant_columns"]),
        frozen_columns=tuple(name for name in columns if name in frozen),
        correlated_groups=diagnostic.groups if diagnostic else None,
        vif_scores={name: _finite(value) for name, value in diagnostic.vif.items()}
        if diagnostic
        else None,
        condition_number=_finite(diagnostic.condition_number) if diagnostic else None,
        collinearity_status=(
            "unknown"
            if diagnostic is None
            else "available"
            if isfinite(diagnostic.condition_number)
            else "rank_deficient"
        ),
        time_column=parsed.timestamp_column,
        sampling_status=sampling,
        sample_period_seconds=axis.sample_period_seconds if verified_uniform else None,
        continuous_run_count=len(runs),
        continuous_runs=tuple(runs),
    )


def _sequence_budget(
    spec: ExperimentSpec, *, lookback: int, horizon: int, feature_count: int
) -> None:
    anchors = sum(
        max(0, span.stop - span.start - lookback - horizon + 1)
        for span in effective_ranges(spec, "train")
    )
    # Upper bound for major window buffers, including offsets and timestamp checks.
    if anchors * (lookback + horizon) * (8 * 8 + 4 * (feature_count + 1)) > _MAX_SEQUENCE_BYTES:
        raise _Unverified("Sequence preflight exceeds the window memory budget")


def _candidate(
    kind: RecommendationModelType,
    *,
    request: ModelRecommendationRequest,
    profile: DataProfileSummary,
    spec: ExperimentSpec,
    source: BoundSource,
    series: VersionSeries,
    table: PreparedBatch | None,
    table_error: str | None,
    common_error: str | None,
) -> ModelCandidate:
    model = get_model(kind)
    overrides = dict(request.parameters.get(kind, {}))
    forecast = request.forecast_spec if kind == "timexer" else None
    horizon = request.forecast_spec.prediction_length if request.forecast_spec else 1
    evidence = CandidateEvidence(
        parameter_source="forecast_spec" if forecast else "overrides" if overrides else "defaults",
        horizon_source="forecast_spec" if request.forecast_spec else "default",
    )
    actual_parameters = None
    count = None
    status = "eligible"
    limitations = []
    try:
        if forecast:
            overrides = {**forecast.model_dump(), **overrides}
        params = validate_parameters(kind, overrides)
        actual_parameters = params.model_dump(mode="json")
        if isinstance(params, TimeXerParameters):
            if forecast is None and params.prediction_length != horizon:
                raise ValueError("Supply forecast_spec to request a multistep prediction horizon")
            if forecast is None:
                forecast = TimeXerForecastSpec(
                    target_window_length=params.target_window_length,
                    exogenous_window_length=params.exogenous_window_length,
                    prediction_length=params.prediction_length,
                )
            forecast.validate_parameters(params)
        elif horizon != 1:
            raise ValueError("This model only supports prediction horizon 1")
        if common_error:
            raise ValueError(common_error)
        if kind in _NAME_LIMITS:
            names = (
                (*profile.feature_names, profile.target_name)
                if kind == "timexer"
                else profile.feature_names
            )
            if any(len(name) > _NAME_LIMITS[kind] for name in names):
                raise ValueError("Column name exceeds the model platform limit")

        if isinstance(params, (PLSParameters, XGBoostParameters)):
            if table is None:
                raise ValueError(table_error)
            count = table.evidence.anchor_rows.count
            evidence = evidence.model_copy(
                update={
                    "anchor_rows": table.evidence.anchor_rows,
                    "sample_rule": table.evidence.rule_version,
                    "target_offsets": (0,),
                }
            )
            if count < 2:
                raise ValueError("At least two training samples are required")
            if isinstance(params, PLSParameters):
                if params.n_components > min(count, profile.feature_count):
                    raise ValueError("n_components exceeds min(N_train, F)")
                if np.all(table.y == table.y[0]):
                    raise ValueError("PLS requires a nonconstant training target")
                if all(np.all(col == col[0]) for col in table.inputs.x.T):
                    raise ValueError("PLS requires at least one nonconstant training feature")
            else:
                params.booster_parameters(
                    random_seed=0 if spec.random_seed is None else spec.random_seed
                )
                numeric_matrix(table.inputs.x, ndim=2)
                numeric_matrix(table.y, ndim=1)
            if request.goal == "temporal_forecast":
                limitations.append("Same-row inputs must be available at prediction time.")
        elif isinstance(params, (TCNParameters, TimeXerParameters)):
            if isinstance(params, TCNParameters):
                histories = {"features": params.window_length}
                if profile.feature_count > MAX_FEATURES:
                    raise ValueError("Too many TCN input features")
            else:
                validate_feature_names(profile.target_name, profile.feature_names)
                histories = {
                    "target": params.target_window_length,
                    "exogenous": params.exogenous_window_length,
                }
            evidence = evidence.model_copy(update={"history_lengths": histories})
            if spec.random_seed is not None and not 0 <= spec.random_seed < 2**32:
                raise ValueError("Sequence model seed must be in [0, 2**32)")
            if profile.sampling_status == "irregular":
                raise ValueError("This model requires uniform sampling")
            if profile.sampling_status != "uniform" or profile.sample_period_seconds is None:
                raise _Unverified("A bound time column and verified uniform sampling are required")
            _sequence_budget(
                spec,
                lookback=max(histories.values()),
                horizon=horizon,
                feature_count=profile.feature_count,
            )
            if isinstance(params, TCNParameters):
                samples = build_tcn_samples(
                    series, spec=spec, source=source, partition="train", parameters=params
                )
            else:
                samples = build_timexer_samples(
                    series, spec=spec, source=source, partition="train", parameters=params
                )
            count = samples.evidence.sample_count
            evidence = evidence.model_copy(
                update={
                    "anchor_rows": samples.evidence.anchor_rows,
                    "target_offsets": samples.evidence.target_offsets,
                    "sample_rule": samples.evidence.rule_version,
                }
            )
        else:
            raise _Unverified("No recommendation preflight for this parameter contract")
    except _Unverified as error:
        status, reasons = "unknown", (str(error),)
    except ValueError as error:
        status, reasons = "excluded", (str(error),)
    else:
        reasons = ("Verified Train inputs and sample structure satisfy the model contract.",)
        if any(profile.anomaly_summary.values()):
            limitations.append("Train contains potential outliers flagged by the quality profile.")
        if profile.frozen_columns:
            limitations.append("Train contains constant-value stretches that warrant review.")
    return ModelCandidate(
        model_type_id=kind,
        model_name=model.display_name,
        eligibility_status=status,
        suitability={"eligible": "compatible", "excluded": "inapplicable", "unknown": "unverified"}[
            status
        ],
        reasons=reasons,
        limitations=tuple(limitations),
        actual_parameters=actual_parameters,
        training_sample_count=count,
        prediction_horizon=horizon if kind == "timexer" else 1,
        forecast_spec=forecast,
        evidence=evidence,
    )


def _recommend(
    request: ModelRecommendationRequest,
    spec: ExperimentSpec,
    series: VersionSeries,
    parsed: ParsedCsv,
    rows: RowSet,
    positions: tuple[int, ...],
) -> ModelRecommendationResult:
    source = RecommendationSource(
        dataset_id=spec.dataset_id,
        dataset_version_id=spec.dataset_version_id,
        csv_sha256=spec.dataset_version_sha256,
        experiment_spec_hash=spec_hash(spec),
        train_rows=rows,
        target_name=spec.target_column,
        feature_names=spec.input_columns,
    )
    bound_source = BoundSource(
        source.dataset_id, source.dataset_version_id, source.csv_sha256, source.experiment_spec_hash
    )
    profile = _profile(parsed, series, spec, source, positions)
    common_error = None
    table_error = None
    table = None
    try:
        _validate_static_spec(spec)
        if spec.training_selection.mode != "full_train":
            raise ValueError("The four platform models require full Train")
    except ValueError as error:
        common_error = str(error)
    horizon = request.forecast_spec.prediction_length if request.forecast_spec else 1
    if common_error is None and horizon == 1:
        try:
            table = build_table_samples(series, spec=spec, source=bound_source, partition="train")
        except ValueError as error:
            table_error = str(error)
    candidates = [
        _candidate(
            kind,
            request=request,
            profile=profile,
            spec=spec,
            source=bound_source,
            series=series,
            table=table,
            table_error=table_error,
            common_error=common_error,
        )
        for kind in _MODELS
    ]
    collinear = bool(profile.correlated_groups) or profile.collinearity_status == "rank_deficient"
    if horizon > 1:
        preferred, rationale = ("timexer",), "Matches the requested multistep horizon."
    elif request.goal == "temporal_forecast":
        preferred, rationale = (
            ("tcn", "timexer"),
            "Uses historical windows for the requested forecast.",
        )
    elif request.goal == "nonlinear_regression":
        preferred, rationale = ("xgboost",), "Matches the requested nonlinear regression objective."
    elif collinear:
        preferred, rationale = (
            ("pls",),
            "Latent components are suitable for the observed input collinearity.",
        )
    else:
        preferred, rationale = ("pls", "xgboost"), "Matches the same-row regression task."
    ranked = sorted(
        (item for item in candidates if item.eligibility_status == "eligible"),
        key=lambda item: (
            item.model_type_id not in preferred,
            -(item.training_sample_count or 0),
            _MODELS.index(item.model_type_id),
        ),
    )
    ranks = {item.model_type_id: index for index, item in enumerate(ranked, start=1)}
    return ModelRecommendationResult(
        profile=profile,
        source=source,
        goal=request.goal,
        candidates=tuple(
            item.model_copy(
                update={
                    "recommendation_rank": ranks[item.model_type_id],
                    "suitability": "preferred" if item.model_type_id in preferred else "compatible",
                    "reasons": (*item.reasons, rationale)
                    if item.model_type_id in preferred
                    else item.reasons,
                }
            )
            if item.model_type_id in ranks
            else item
            for item in candidates
        ),
        recommended_models=tuple(item.model_type_id for item in ranked[:3]),
        excluded_models={
            item.model_type_id: item.reasons
            for item in candidates
            if item.eligibility_status == "excluded"
        },
        generated_at=datetime.now(UTC),
        summary="Eligible candidates ranked by task fit and verified sample availability."
        if ranked
        else "No model has verified eligibility. Review each candidate's exclusion or evidence gap.",
    )


async def recommend_models(
    session: AsyncSession, *, request: ModelRecommendationRequest, artifact_root: Path
) -> ModelRecommendationResult:
    """Verify the exact CSV and contract, then profile and preflight Train only."""
    request = ModelRecommendationRequest.model_validate(request.model_dump())
    with session.no_autoflush:
        spec = await bind_experiment_spec(
            session, spec=request.experiment_spec, artifact_root=artifact_root
        )
        if request.expected_spec_hash is not None and request.expected_spec_hash != spec_hash(spec):
            raise ValueError("Bound ExperimentSpec SHA256 mismatch")
        dataset = await session.get(Dataset, spec.dataset_id)
        version = await session.get(DatasetVersion, spec.dataset_version_id, populate_existing=True)
        if dataset is None or version is None or version.dataset_id != dataset.id:
            raise ValueError("DatasetVersion ownership mismatch")
        series = await load_version_series(
            session,
            dataset_id=spec.dataset_id,
            version_id=spec.dataset_version_id,
            artifact_root=artifact_root,
        )
        parsed = load_version_csv(dataset=dataset, version=version, artifact_root=artifact_root)
        if version.sha256 != spec.dataset_version_sha256 or not artifact_matches_sha256(
            artifact_root=artifact_root,
            relative_path=version.artifact_path,
            expected_sha256=spec.dataset_version_sha256,
        ):
            raise ValueError("DatasetVersion SHA256 changed while reading")
        rows = spec.training_selection.requested_indices or RowSet(
            ranges=effective_ranges(spec, "train")
        )
        positions = tuple(iter_rows(rows, artifact_root))
    return await asyncio.to_thread(_recommend, request, spec, series, parsed, rows, positions)
