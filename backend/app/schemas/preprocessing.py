from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.common import Schema, TaskResource


class CleanRequest(Schema):
    version_id: UUID
    dataset_id: UUID | None = None
    target_sample_period_seconds: float | None = Field(default=None, gt=0)
    # Canonical phase-1 names stay available. The aliases below preserve the
    # already-built browser client while it is upgraded in the next handoff.
    resample_period_s: float | None = Field(default=None, gt=0)
    interpolation: Literal["linear", "forward_fill", "backward_fill", "none"] = "linear"
    interpolation_method: (
        Literal["linear", "ffill", "bfill", "forward_fill", "backward_fill", "none"] | None
    ) = None
    anomaly_detector: Literal["iqr", "z_score", "hampel"] = "hampel"
    outlier_method: Literal["iqr", "zscore", "z_score", "hampel"] | None = None
    anomaly_strategy: Literal["keep", "set_null", "local_median", "linear_interpolate", "clip"] = (
        "linear_interpolate"
    )
    hampel_window: int = Field(default=7, ge=3, le=1_001)
    hampel_threshold: float = Field(default=3.0, gt=0)
    hampel_n_sigmas: float | None = Field(default=None, gt=0)
    z_score_threshold: float = Field(default=3.0, gt=0)
    max_consecutive_missing: int | None = Field(default=10, ge=1, le=100_000)
    duplicate_strategy: Literal["first", "mean"] = "mean"
    smoothing: Literal["none", "moving_average", "savitzky_golay"] = "none"
    smoothing_window: int = Field(default=5, ge=3, le=1_001)


class CleanSeries(Schema):
    column: str
    timestamps: list[datetime]
    raw_series: list[float | None]
    cleaned_series: list[float | None]
    replaced_indices: list[int] = Field(default_factory=list)
    interpolation_changed_indices: list[int] = Field(default_factory=list)
    outlier_replacement_indices: list[int] = Field(default_factory=list)
    smoothing_changed_indices: list[int] = Field(default_factory=list)


class CleanData(Schema):
    source_version_id: UUID
    effective_version_id: UUID
    derived_version_id: UUID | None = None
    created_new_version: bool = True
    no_op: bool = False
    converged: bool = False
    reused_existing_version: bool = False
    processing_run_id: UUID | None = None
    task: TaskResource
    series: list[CleanSeries]
    # Additive browser-friendly projection. It describes the configured output
    # column (or the first numeric column when no output role exists).
    dataset_id: UUID | None = None
    new_version_id: UUID | None = None
    primary_column: str
    raw_series: list[float | None] = Field(default_factory=list)
    cleaned_series: list[float | None] = Field(default_factory=list)
    replaced_indices: list[int] = Field(default_factory=list)
    total_cleaned_points: int = Field(default=0, ge=0)
    warnings: list[str] = Field(default_factory=list)
    recommended_downsample_factor: int = Field(default=1, ge=1)
    summary: dict[str, object] = Field(default_factory=dict)


class SegmentRequest(Schema):
    version_id: UUID
    input_columns: list[str] = Field(min_length=1)
    output_column: str = Field(min_length=1)
    window_size: int = Field(default=60, ge=5)
    min_segment_length: int = Field(default=100, ge=1)
    min_snr_db: float = 0.0
    max_segments: int = Field(default=10, ge=1, le=100)
    dataset_id: UUID | None = None
    stride: int | None = Field(default=None, ge=1)
    # Provisional ARX structure used only to build the information matrix. Delays are
    # refined later; selection is not very sensitive to them, but the orders must be
    # large enough that the regressor spans the directions we care about.
    na: int = Field(default=2, ge=1, le=20)
    nb: int = Field(default=2, ge=1, le=20)
    nk: int = Field(default=0, ge=0, le=1_000)
    train_ratio: float = Field(default=0.7, gt=0, lt=1)
    ridge: float = Field(default=1e-6, gt=0)
    max_missing_ratio: float = Field(default=0.20, ge=0, le=1)
    max_anomaly_ratio: float = Field(default=0.10, ge=0, le=1)
    min_input_activity_ratio: float = Field(default=0.05, ge=0)
    min_information_gain_bits: float = Field(default=0.0, ge=0)


class DynamicSegment(Schema):
    segment_id: str
    start_index: int = Field(ge=0)
    end_index: int = Field(ge=0)
    start_time: datetime | None = None
    end_time: datetime | None = None
    snr_db: float
    dynamic_score: float
    recommendation: Literal["strongly_recommended", "recommended", "review", "rejected"]
    rank: int | None = Field(default=None, ge=1)
    information_gain_bits: float | None = None
    cumulative_log_det: float | None = None
    n_rows: int | None = Field(default=None, ge=0)
    missing_ratio: float | None = None
    anomaly_ratio: float | None = None


class GatedWindow(Schema):
    """A candidate window the quality gate scored, accepted or not."""

    window_index: int = Field(ge=0)
    start_index: int = Field(ge=0)
    end_index: int = Field(ge=0)
    missing_ratio: float
    anomaly_ratio: float
    snr_db: float
    input_activity: float
    output_activity: float
    accepted: bool
    rejection_reasons: list[str] = Field(default_factory=list)


class SelectionSummary(Schema):
    """Information-theoretic outcome of the D-optimal stage."""

    candidate_count: int = Field(ge=0)
    gated_count: int = Field(ge=0)
    selected_count: int = Field(ge=0)
    selected_rows: int = Field(ge=0)
    coverage_ratio: float
    baseline_log_det: float
    selected_log_det: float
    information_retention: float | None = None
    evaluated_candidates: int = Field(ge=0)
    naive_candidate_evaluations: int = Field(ge=0)
    lazy_speedup: float
    stopped_reason: str
    budget_advisory: str | None = Field(
        default=None,
        description="样本预算过小、信息准则无法覆盖全部参数方向时的提示；为 null 表示预算充足。",
    )
    condition_number: float | None = None
    excitation_satisfied: bool = False
    persistent_excitation_order: dict[str, int] = Field(default_factory=dict)
    required_excitation_order: dict[str, int] = Field(default_factory=dict)
    rejection_counts: dict[str, int] = Field(default_factory=dict)
    noise_sigma: float = 0.0


class SegmentData(Schema):
    source_version_id: UUID
    task: TaskResource
    timestamps: list[datetime]
    series: dict[str, list[float | None]]
    segments: list[DynamicSegment]
    dataset_id: UUID | None = None
    derived_version_id: UUID | None = None
    selection: SelectionSummary | None = None
    gated_windows: list[GatedWindow] = Field(default_factory=list)
    selected_indices: list[int] = Field(default_factory=list)


class DelayRequest(Schema):
    version_id: UUID
    input_columns: list[str] = Field(min_length=1)
    output_column: str = Field(min_length=1)
    max_lag: int = Field(default=100, ge=0, le=10_000)
    top_k: int = Field(default=3, ge=1, le=20)
    dataset_id: UUID | None = None


class DelayPeak(Schema):
    lag: int = Field(ge=0)
    correlation: float = Field(ge=-1, le=1)
    confidence: float = Field(ge=0, le=1)


class DelayData(Schema):
    source_version_id: UUID
    processing_run_id: UUID | None = None
    task: TaskResource
    delays: list[int]
    correlations: dict[str, list[float]]
    best_delays: dict[str, int]
    candidate_peaks: dict[str, list[DelayPeak]]
    dataset_id: UUID | None = None
    # Validation free-run FIT achieved by the refined delay set. Cross-correlation only
    # proposes candidates; this is the number that actually chose between them.
    validation_fit: float | None = None
    refinement_rounds: int = Field(default=0, ge=0)
    uncertain_columns: list[str] = Field(default_factory=list)
    prewhitening_orders: dict[str, int] = Field(default_factory=dict)


class LagCompensationRequest(Schema):
    """Apply an explicitly confirmed ARX ``nk`` alignment to input columns.

    For this project ``y(k)`` depends on ``u(k-nk)``.  Applying ``nk=d`` therefore
    writes source ``u(t-d)`` alongside unchanged ``y(t)`` and drops the leading boundary
    rows that cannot be aligned.  The API never infers or applies a lag by itself.
    """

    version_id: UUID
    dataset_id: UUID | None = None
    lag_map: dict[str, int] = Field(min_length=1)
    user_confirmed: bool = False
    recommendation_source: Literal["manual", "delay_analysis"] = "manual"
    evidence_summary: dict[str, str] = Field(default_factory=dict)


class VersionApplyData(Schema):
    source_version_id: UUID
    result_version_id: UUID
    dataset_id: UUID
    processing_run_id: UUID
    operation: str
    summary: dict[str, object] = Field(default_factory=dict)
    task: TaskResource


class CollinearityRequest(Schema):
    version_id: UUID
    input_columns: list[str] = Field(min_length=2)
    correlation_threshold: float = Field(default=0.9, gt=0, le=1)
    vif_threshold: float = Field(default=10.0, gt=1)
    dataset_id: UUID | None = None
    output_column: str | None = None


class VariableRecommendation(Schema):
    variable: str
    action: Literal["keep", "drop", "merge", "review"]
    reason: str
    related_variables: list[str] = Field(default_factory=list)


InputDiagnosticStatus = Literal[
    "analyzable",
    "constant_or_near_constant",
    "non_numeric",
    "missing",
]


class InputDiagnostic(Schema):
    column: str
    status: InputDiagnosticStatus
    reason: str
    variance: float | None = None


class CollinearityData(Schema):
    source_version_id: UUID
    processing_run_id: UUID
    task: TaskResource
    variables: list[str]
    matrix: list[list[float | None]]
    vif_scores: dict[str, float | None]
    condition_number: float | None = None
    recommendations: list[VariableRecommendation]
    dataset_id: UUID | None = None
    spearman_matrix: list[list[float | None]] = Field(default_factory=list)
    correlated_groups: list[list[str]] = Field(default_factory=list)
    input_diagnostics: list[InputDiagnostic] = Field(default_factory=list)


class FeatureSelectionApplyRequest(Schema):
    """Drop only explicitly confirmed redundant input columns."""

    version_id: UUID
    dataset_id: UUID | None = None
    drop_columns: list[str] = Field(min_length=1)
    user_confirmed: bool = False
    recommendation_source: Literal["manual", "collinearity_analysis"] = "manual"
    evidence: dict[str, dict[str, object]] = Field(default_factory=dict)
