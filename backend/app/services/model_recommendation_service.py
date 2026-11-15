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
    RecommendationCatalogEntry,
    RecommendationModelType,
    RecommendationSource,
)
from app.schemas.pls import PLSParameters
from app.schemas.tcn import DILATIONS, KERNEL_SIZE, MAX_FEATURES, TCNParameters
from app.schemas.tcn_platform import MAX_FEATURE_NAME_LENGTH as TCN_NAME_LIMIT
from app.schemas.timexer import TimeXerParameters, validate_feature_names
from app.schemas.timexer_platform import MAX_FEATURE_NAME_LENGTH as TIMEXER_NAME_LIMIT
from app.schemas.timexer_platform import TimeXerForecastSpec
from app.schemas.xgboost import XGBoostParameters
from app.schemas.xgboost_platform import MAX_FEATURE_NAME_LENGTH as XGBOOST_NAME_LIMIT
from app.services.arx_platform_adapter import (
    DYNAMIC_IMPLEMENTATIONS,
    build_dynamic_spec,
    dynamic_parameters,
    validate_dynamic_source,
    validate_lag_reference,
)
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
from app.services.model_registry import get_model, list_models, validate_parameters
from app.services.pls_training_service import validate_pls_experiment_spec
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
                validate_pls_experiment_spec(spec)
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
        fixed_parameters={"kernel_size": KERNEL_SIZE, "dilations": DILATIONS} if kind == "tcn" else {},
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
    dynamic_specs: dict[str, ExperimentSpec | ValueError] | None = None,
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
    if spec.task_type == "dynamic_system_identification":
        return _recommend_dynamic(request, spec, series, profile, source, dynamic_specs or {})
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
        leakage=spec.leakage,
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


def _recommend_dynamic(request, spec, series, profile, source, dynamic_specs) -> ModelRecommendationResult:
    candidates = []
    for definition in list_models(task_type=spec.task_type):
        kind = definition.model_type_id
        if kind not in DYNAMIC_IMPLEMENTATIONS:
            continue
        contract = dynamic_specs[kind]
        params = rows = None
        try:
            if isinstance(contract, ValueError):
                raise contract
            if request.forecast_spec is not None:
                raise ValueError("Dynamic identification does not accept a TimeXer forecast contract")
            params, rows = validate_dynamic_source(contract, series, request.parameters.get(kind))
        except ValueError as error:
            reasons = (str(error),)
        else:
            response = {
                "arx": "使用输出历史和有滞后输入。",
                "fir": "仅使用有滞后输入估计有限脉冲响应。",
                "oe": "已核验正权重连续目标与初始化历史，使用多时域输出误差拟合。",
            }[kind]
            reasons = ("已核验连续采样、滞后结构及有效 Train 样本。", response)
        candidates.append(ModelCandidate(
            model_type_id=kind, model_name=definition.display_name,
            eligibility_status="eligible" if rows is not None else "excluded",
            suitability="compatible" if rows is not None else "inapplicable",
            reasons=reasons, prediction_horizon=1,
            actual_parameters=dynamic_parameters(params) if params else None,
            training_sample_count=rows.count if rows else None,
            experiment_spec=contract if rows else None,
            experiment_spec_hash=spec_hash(contract) if rows else None,
            evidence=CandidateEvidence(
                parameter_source="overrides" if request.parameters.get(kind) else "defaults",
                horizon_source="default", anchor_rows=rows,
            ),
        ))
    preferred = request.preferred_dynamic_model or ("oe" if spec.oe_contract else "fir" if spec.fir_contract else "arx")
    ranked = sorted(
        (candidate for candidate in candidates if candidate.eligibility_status == "eligible"),
        key=lambda candidate: candidate.model_type_id != preferred,
    )
    ranks = {candidate.model_type_id: rank for rank, candidate in enumerate(ranked, 1)}
    return ModelRecommendationResult(
        task_type=spec.task_type, leakage=spec.leakage, profile=profile, source=source, goal=request.goal,
        candidates=tuple(candidate.model_copy(update={
            "recommendation_rank": ranks[candidate.model_type_id],
            "suitability": "preferred" if ranks[candidate.model_type_id] == 1 else "compatible",
        }) if candidate.model_type_id in ranks else candidate for candidate in candidates),
        recommended_models=tuple(ranks),
        excluded_models={
            item.model_type_id: item.reasons for item in candidates if item.eligibility_status == "excluded"
        },
        generated_at=datetime.now(UTC),
        summary=ranked[0].reasons[0] if ranked else "没有通过资格校验的动态模型。",
    )


_CATALOG_CATEGORIES = {
    "linear_dynamic": "动态系统辨识",
    "linear_latent_regression": "静态监督回归",
    "tree_ensemble": "静态监督回归",
    "temporal_convolution": "深度时序预测",
    "time_series_transformer": "深度时序预测",
}


def _catalog_entries(
    result: ModelRecommendationResult, spec: ExperimentSpec,
) -> tuple[RecommendationCatalogEntry, ...]:
    candidates = {item.model_type_id: item for item in result.candidates}
    entries = []
    for definition in list_models():
        kind = definition.model_type_id
        candidate = candidates.get(kind)
        if spec.task_type not in definition.supported_tasks:
            status, reasons = "task_mismatch", ("当前任务类型不适用。",)
        elif definition.availability != "available" or kind not in (*_MODELS, *DYNAMIC_IMPLEMENTATIONS):
            status, reasons = "not_integrated", ("尚未接入统一训练流程。",)
        elif candidate is None or (
            candidate.eligibility_status == "eligible" and candidate.actual_parameters is None
        ):
            status, reasons = "unknown", ("本次任务没有该模型的完整资格记录。",)
        else:
            status, reasons = candidate.eligibility_status, candidate.reasons
        entries.append(RecommendationCatalogEntry(
            model_type_id=kind, model_name=definition.display_name, family=definition.family,
            category=_CATALOG_CATEGORIES.get(definition.family, definition.family),
            description=definition.description, eligibility_status=status, reasons=reasons,
        ))
    return tuple(entries)


def recommendation_for_display(result_payload: dict, input_payload: dict) -> dict:
    """Add display context to historical snapshots without rewriting stored JSON."""
    raw = result_payload.get("recommendation")
    if not isinstance(raw, dict) or raw.get("catalog_models"):
        return dict(result_payload)
    try:
        result = ModelRecommendationResult.model_validate(raw)
        request = ModelRecommendationRequest.model_validate(input_payload.get("recommendation_request"))
    except ValueError:
        return dict(result_payload)
    spec = request.experiment_spec
    return {**result_payload, "recommendation": {
        **raw, "task_type": spec.task_type,
        "catalog_models": [entry.model_dump(mode="json") for entry in _catalog_entries(result, spec)],
        "experiment_spec": spec.model_dump(mode="json"),
    }}


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
            allow_missing_time=spec.row_order is not None,
        )
        parsed = load_version_csv(
            dataset=dataset, version=version, artifact_root=artifact_root,
            allow_missing_time=spec.row_order is not None,
        )
        if version.sha256 != spec.dataset_version_sha256 or not artifact_matches_sha256(
            artifact_root=artifact_root,
            relative_path=version.artifact_path,
            expected_sha256=spec.dataset_version_sha256,
        ):
            raise ValueError("DatasetVersion SHA256 changed while reading")
        dynamic_specs = None
        if spec.task_type == "dynamic_system_identification":
            dynamic_specs = {}
            primary = "oe" if spec.oe_contract else "fir" if spec.fir_contract else "arx"
            for kind in DYNAMIC_IMPLEMENTATIONS:
                try:
                    base = spec.arx_contract or spec.fir_contract or spec.oe_contract
                    if (
                        base is None or spec.training_selection.mode != "full_train"
                        or spec.evaluation.scopes != ("validation",)
                    ):
                        raise ValueError("Dynamic recommendations require a fixed full-Train and Validation contract")
                    if kind == primary:
                        candidate_spec = spec
                    else:
                        candidate_spec = await build_dynamic_spec(
                            session, kind=kind, version=version, inputs=spec.input_columns,
                            target=spec.target_column, axis=spec.time_axis, runs=spec.continuous_runs, series=series,
                            overrides={
                                **request.parameters.get(kind, {}),
                                "train_ratio": base.parameters.get("train_ratio", 0.6),
                                "validation_ratio": base.parameters.get("validation_ratio", 0.2),
                            },
                        )
                        if any(
                            getattr(candidate_spec.split, partition) != getattr(spec.split, partition)
                            for partition in ("train", "validation", "test")
                        ):
                            raise ValueError("Dynamic candidates must use the same partition boundaries")
                        candidate_spec = candidate_spec.model_copy(update={"preprocessing": spec.preprocessing})
                        candidate_spec = await bind_experiment_spec(
                            session, spec=candidate_spec, artifact_root=artifact_root,
                        )
                    await validate_lag_reference(session, candidate_spec)
                    dynamic_specs[kind] = candidate_spec
                except ValueError as error:
                    dynamic_specs[kind] = error
        ranges = effective_ranges(spec, "train")
        if dynamic_specs is not None and not ranges:
            ranges = spec.split.train
        rows = spec.training_selection.requested_indices or RowSet(ranges=ranges)
        positions = tuple(iter_rows(rows, artifact_root))
    result = await asyncio.to_thread(_recommend, request, spec, series, parsed, rows, positions, dynamic_specs)
    return result.model_copy(update={"catalog_models": _catalog_entries(result, spec), "experiment_spec": spec})
