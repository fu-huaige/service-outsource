"""Contracts for deterministic, read-only model recommendations."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.common import Schema
from app.schemas.experiment_spec import Digest, ExperimentSpec, LeakageAssessment, RowRange, RowSet
from app.schemas.model_catalog import ModelTypeId
from app.schemas.timexer_platform import TimeXerForecastSpec

RecommendationModelType = Literal["arx", "fir", "oe", "pls", "xgboost", "tcn", "timexer"]
RecommendationGoal = Literal[
    "auto", "static_regression", "nonlinear_regression", "temporal_forecast"
]
EligibilityStatus = Literal["eligible", "excluded", "unknown"]


class ModelRecommendationRequest(Schema):
    experiment_spec: ExperimentSpec
    expected_spec_hash: Digest | None = Field(
        default=None, description="Optional digest of the server-bound ExperimentSpec."
    )
    goal: RecommendationGoal = "auto"
    preferred_dynamic_model: Literal["arx", "fir", "oe"] | None = None
    forecast_spec: TimeXerForecastSpec | None = None
    parameters: dict[RecommendationModelType, dict[str, object]] = Field(default_factory=dict)


class RecommendationSource(Schema):
    dataset_id: UUID
    dataset_version_id: UUID
    csv_sha256: Digest
    experiment_spec_hash: Digest
    partition: Literal["train"] = "train"
    train_rows: RowSet
    target_name: str
    feature_names: tuple[str, ...]


class ContinuousRunProfile(Schema):
    rows: RowRange
    train_record_count: int


class DataProfileSummary(RecommendationSource):
    profile_scope: Literal["train"] = "train"
    sample_count: int
    feature_count: int
    target_type: str | None
    missing_rate: float
    missing_rates: dict[str, float]
    anomaly_summary: dict[str, int]
    constant_columns: tuple[str, ...]
    frozen_columns: tuple[str, ...]
    correlated_groups: tuple[tuple[str, ...], ...] | None
    vif_scores: dict[str, float | None] | None
    condition_number: float | None
    collinearity_status: Literal["available", "rank_deficient", "unknown"]
    time_column: str | None
    sampling_status: Literal["uniform", "irregular", "unknown"]
    sample_period_seconds: float | None
    continuous_run_count: int
    continuous_runs: tuple[ContinuousRunProfile, ...]


class CandidateEvidence(Schema):
    parameter_source: Literal["defaults", "overrides", "forecast_spec"]
    horizon_source: Literal["default", "forecast_spec"]
    anchor_rows: RowSet | None = None
    history_lengths: dict[str, int] = Field(default_factory=dict)
    target_offsets: tuple[int, ...] = ()
    sample_rule: str | None = None


class ModelCandidate(Schema):
    experiment_spec: ExperimentSpec | None = None
    experiment_spec_hash: Digest | None = None
    model_type_id: RecommendationModelType
    model_name: str
    eligibility_status: EligibilityStatus
    recommendation_rank: int | None = None
    suitability: Literal["preferred", "compatible", "inapplicable", "unverified"]
    reasons: tuple[str, ...]
    limitations: tuple[str, ...] = ()
    actual_parameters: dict[str, object] | None = None
    fixed_parameters: dict[str, object] = Field(default_factory=dict)
    training_sample_count: int | None = None
    prediction_horizon: int
    forecast_spec: TimeXerForecastSpec | None = None
    evidence: CandidateEvidence


class RecommendationCatalogEntry(Schema):
    model_type_id: ModelTypeId
    model_name: str
    family: str
    category: str
    description: str
    eligibility_status: Literal["eligible", "task_mismatch", "not_integrated", "excluded", "unknown"]
    reasons: tuple[str, ...] = ()


class ModelRecommendationResult(Schema):
    catalog_models: tuple[RecommendationCatalogEntry, ...] = ()
    experiment_spec: ExperimentSpec | None = None
    task_type: Literal["dynamic_system_identification", "supervised_regression"] = "supervised_regression"
    leakage: LeakageAssessment | None = None
    profile: DataProfileSummary
    source: RecommendationSource
    goal: RecommendationGoal
    candidates: tuple[ModelCandidate, ...]
    recommended_models: tuple[RecommendationModelType, ...]
    excluded_models: dict[RecommendationModelType, tuple[str, ...]]
    rule_version: Literal["model-recommendation-1"] = "model-recommendation-1"
    generated_at: datetime
    summary: str
