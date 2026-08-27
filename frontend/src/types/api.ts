/**
 * IndusOpt API TypeScript Types
 * Generated & Synchronized with backend/openapi.json (OpenAPI 3.1.0, Phase 3)
 */

export interface ErrorDetail {
  code: string;
  message: string;
  details?: Record<string, any> | null;
}

export interface ErrorEnvelope {
  success: false;
  data: null;
  error: ErrorDetail;
  request_id: string;
}

export interface SuccessEnvelope<T> {
  success: true;
  data: T;
  error: null;
  request_id: string;
}

export type ApiResponse<T> = SuccessEnvelope<T> | ErrorEnvelope;

/** Progress descriptor every long-running or completed stage returns. */
export interface TaskResource {
  task_id: string;
  status: string;
  stage: string;
  progress: number;
  message?: string | null;
}

// System API Types
export interface LivenessData {
  status: "ok";
  service: string;
}

export interface ReadinessData {
  status: "ready";
  database: "connected";
  queue: "connected";
}

export interface SystemInfoData {
  name: string;
  version: string;
  api_version: string;
  environment: string;
  docs_url: string;
  openapi_url: string;
}

export interface AgentLlmConfigData {
  source: "environment" | "runtime";
  persistence: "process_memory";
  enabled: boolean;
  provider: string;
  base_url: string;
  model: string;
  has_api_key: boolean;
  timeout_seconds: number;
  updated_at: string | null;
}

export interface AgentLlmConfigUpdate {
  provider: string;
  base_url: string;
  model: string;
  api_key?: string | null;
  clear_api_key?: boolean;
  timeout_seconds: number;
}

export interface AgentLlmConnectionData {
  connected: true;
  provider: string;
  model: string;
  latency_ms: number;
  message: string;
}

// Simulation API Types
export interface SimulationGenerateRequest {
  scenario: "S1" | "S2" | "S3" | "S4" | "S5" | "S6";
  dataset_name: string;
  num_samples?: number;
  noise_level?: number;
  seed?: number;
}

export interface DynamicSegmentGroundTruth {
  start_idx: number;
  end_idx: number;
  segment_type: string;
}

export interface SimulationGroundTruth {
  system_type: string;
  true_na: number;
  true_nb: number[];
  true_delays: number[];
  true_parameters: Record<string, number>;
  dynamic_segments: DynamicSegmentGroundTruth[];
  noise_level: number;
  seed: number;
}

export interface SimulationGenerateResponse {
  dataset_id: string;
  dataset_name: string;
  version_id: string;
  scenario: string;
  file_path: string;
  ground_truth_path: string;
  manifest_path: string;
  download_url: string;
  num_rows: number;
  num_cols: number;
  columns: string[];
  ground_truth: SimulationGroundTruth;
}

export interface DashboardLeaderboardEntry {
  dataset_id: string;
  dataset_name: string;
  version_id: string;
  study_id: string;
  status: string;
  baseline_validation_fit: number | null;
  optimized_validation_fit: number | null;
  optimized_test_fit: number | null;
  optimized_test_one_step_fit: number | null;
  optimized_test_one_step_r2: number | null;
  optimized_test_free_run_r2: number | null;
  improvement: number | null;
  generalization_gap: number | null;
  baseline_available: boolean;
  test_available: boolean;
  generalization_risk: "unavailable" | "normal" | "attention" | "high";
  risk_message: string;
  contribution_summary: string | null;
}

export interface DashboardLeaderboardResponse {
  items: DashboardLeaderboardEntry[];
}

// Dataset API Types (Phase 3 Real Models)
export interface DatasetColumnInfo {
  name: string;
  data_type?: string;
  role: "time" | "input" | "output" | "ignored" | "timestamp" | "ignore";
  missing_count?: number;
  unit?: string | null;
}

export interface DatasetItem {
  id: string;
  name: string;
  version_id: string;
  latest_version_id?: string;
  source?: string;
  status?: string;
  file_size_bytes: number;
  row_count: number;
  col_count: number;
  column_count?: number;
  created_at: string;
  updated_at?: string;
  time_column: string;
  input_columns: string[];
  output_column: string | null;
  columns?: DatasetColumnInfo[];
  preview?: DatasetPreview | null;
}

export interface DatasetPreview {
  columns: string[];
  rows: Array<Record<string, string | number | boolean | null>>;
  truncated: boolean;
  recommended_downsample_factor: number;
}

export interface DatasetListResponse {
  items: DatasetItem[];
  page?: {
    current_page: number;
    page_size: number;
    total_items: number;
    total_pages: number;
  };
}

export interface DatasetUploadResponse {
  dataset: DatasetItem;
  parse_task: {
    task_id: string;
    status: string;
    progress: number;
  };
  deduplicated: boolean;
}

export interface ColumnStatInfo {
  count: number;
  mean: number | null;
  std: number | null;
  min: number | null;
  max: number | null;
  q25: number | null;
  q50: number | null;
  q75: number | null;
}

export interface DatasetProfile {
  dataset_id: string;
  version_id: string;
  total_rows: number;
  total_cols: number;
  missing_rate: number;
  missing_rates: Record<string, number>;
  max_consecutive_missing?: number;
  anomaly_counts: Record<string, number>;
  interval_histogram: Array<{ bin: number; count: number }>;
  duplicate_timestamp_count?: number;
  irregular_sampling_rate?: number;
  frozen_segments?: FrozenSegment[];
  candidate_frozen_segments?: FrozenSegment[];
  freeze_detection_summary?: FreezeDetectionSummary | null;
  constant_columns?: string[];
  time_range_start?: string | null;
  time_range_end?: string | null;
  sample_period_seconds?: number | null;
  column_statistics?: Record<string, ColumnStatInfo>;
  quality_score: number;
  recommendations: string[];
  quality_issues?: string[];
}

export interface FrozenSegment {
  column: string;
  start_index: number;
  end_index: number;
  length: number;
}

export interface FreezeDetectionSummary {
  candidate_count: number;
  affected_column_count: number;
  longest_segment: FrozenSegment | null;
}

export interface DatasetVersionNode {
  id: string;
  name: string;
  tool: string;
  parent_version_id?: string | null;
  parameters?: Record<string, any>;
  created_at: string;
  row_count: number;
  column_count: number;
  artifact_path: string;
  processing_run_id?: string | null;
  audit_summary?: {
    freeze?: {
      historical_constant_value_segment_count?: number;
      constant_value_segment_count?: number;
      candidate_frozen_segment_count?: number;
      candidate_frozen_segments?: FrozenSegment[];
    };
    processing?: CleaningChangeSummary | Record<string, unknown>;
    warnings?: string[];
  };
  provenance?: {
    user_request?: Record<string, unknown>;
    resolved_scenario_parameters?: Record<string, unknown>;
    evidence_source?: string;
  };
}

export interface DatasetVersionsResponse {
  dataset_id: string;
  active_version_id: string;
  nodes: DatasetVersionNode[];
  edges?: Array<{ source: string; target: string }>;
}

export interface DatasetDeleteResponse {
  dataset_id: string;
  status: string;
}

export interface DatasetColumnConfig {
  name: string;
  role: "time" | "input" | "output" | "ignored" | "timestamp" | "ignore";
  unit?: string | null;
}

export interface DatasetConfigRequest {
  columns?: DatasetColumnConfig[];
  time_column?: string;
  input_columns?: string[];
  output_column?: string | null;
  ignored_columns?: string[];
}

// Preprocessing API Types
export interface CleanRequest {
  dataset_id?: string;
  version_id: string;
  target_sample_period_seconds?: number;
  interpolation?: "linear" | "forward_fill" | "backward_fill" | "none";
  anomaly_detector?: "hampel" | "iqr" | "z_score";
  resample_period_s?: number;
  interpolation_method?: "linear" | "ffill" | "bfill";
  outlier_method?: "hampel" | "iqr" | "zscore";
  hampel_window?: number;
  hampel_n_sigmas?: number;
}

export interface CleanResponse {
  dataset_id: string;
  new_version_id: string;
  source_version_id?: string;
  derived_version_id?: string;
  processing_run_id?: string | null;
  raw_series: number[];
  cleaned_series: number[];
  replaced_indices: number[];
  total_cleaned_points: number;
  warnings?: string[];
  summary?: {
    changes?: CleaningChangeSummary;
    [key: string]: unknown;
  };
}

export interface CleaningChangeSummary {
  count_unit: "cell";
  unique_changed_cells: number | null;
  missing_value_fills?: number;
  outlier_replacements?: number;
  smoothing_changes?: number;
  overlapping_changed_cells?: number;
  category_counts_may_overlap?: boolean;
  duplicate_timestamps_processed?: number;
  resampling_empty_rows_created?: number;
  source_missing_cells?: number;
  aligned_missing_cells_before_interpolation?: number;
  breakdown_status?: "not_recorded";
}

export interface SegmentItem {
  segment_id: string;
  start_index: number;
  end_index: number;
  start_time?: string | null;
  end_time?: string | null;
  snr_db: number;
  dynamic_score: number;
  recommendation: string;
  /** Rank in the greedy selection order; 1 is the most informative segment. */
  rank?: number | null;
  /** Marginal Fisher-information gain contributed by this segment, in bits. */
  information_gain_bits?: number | null;
  cumulative_log_det?: number | null;
  n_rows?: number | null;
  missing_ratio?: number | null;
  anomaly_ratio?: number | null;
}

/** One candidate window the quality gate scored, whether or not it survived. */
export interface GatedWindow {
  window_index: number;
  start_index: number;
  end_index: number;
  missing_ratio: number;
  anomaly_ratio: number;
  snr_db: number;
  input_activity: number;
  output_activity: number;
  accepted: boolean;
  rejection_reasons: string[];
}

/** Information-theoretic outcome of the D-optimal stage. */
export interface SelectionSummary {
  candidate_count: number;
  gated_count: number;
  selected_count: number;
  selected_rows: number;
  coverage_ratio: number;
  baseline_log_det: number;
  selected_log_det: number;
  information_retention: number | null;
  evaluated_candidates: number;
  naive_candidate_evaluations: number;
  lazy_speedup: number;
  stopped_reason: string;
  budget_advisory: string | null;
  condition_number: number | null;
  excitation_satisfied: boolean;
  persistent_excitation_order: Record<string, number>;
  required_excitation_order: Record<string, number>;
  rejection_counts: Record<string, number>;
  noise_sigma: number;
}

export interface SegmentRequest {
  version_id: string;
  input_columns: string[];
  output_column: string;
  dataset_id?: string | null;
  window_size?: number;
  stride?: number;
  max_segments?: number;
  min_snr_db?: number;
  na?: number;
  nb?: number;
  nk?: number;
  train_ratio?: number;
  max_missing_ratio?: number;
  max_anomaly_ratio?: number;
  min_input_activity_ratio?: number;
  min_information_gain_bits?: number;
}

export interface SegmentResponse {
  source_version_id: string;
  dataset_id: string | null;
  task: TaskResource;
  timestamps: string[];
  series: Record<string, (number | null)[]>;
  segments: SegmentItem[];
  selection: SelectionSummary | null;
  gated_windows: GatedWindow[];
  selected_indices: number[];
}

export interface DelayPeak {
  lag: number;
  correlation: number;
  confidence: number;
}

export interface DelayRequest {
  version_id: string;
  input_columns: string[];
  output_column: string;
  dataset_id?: string | null;
  max_lag?: number;
  top_k?: number;
}

export interface DelayResponse {
  source_version_id: string;
  dataset_id: string | null;
  task: TaskResource;
  delays: number[];
  /** Prewhitened cross-correlation curve per input, indexed by lag. */
  correlations: Record<string, number[]>;
  best_delays: Record<string, number>;
  candidate_peaks: Record<string, DelayPeak[]>;
  /** Validation free-run FIT achieved by the refined delay set. */
  validation_fit: number | null;
  refinement_rounds: number;
  /** Inputs whose top two candidates were too close to separate confidently. */
  uncertain_columns: string[];
  prewhitening_orders: Record<string, number>;
}

export interface VersionApplyResponse {
  source_version_id: string;
  result_version_id: string;
  dataset_id: string;
  processing_run_id: string;
  operation: string;
  summary: Record<string, any>;
}

export interface LagCompensationRequest {
  version_id: string;
  dataset_id?: string;
  lag_map: Record<string, number>;
  user_confirmed: boolean;
  recommendation_source: "manual" | "delay_analysis";
  evidence_summary?: Record<string, string>;
}

export interface VariableRecommendation {
  variable: string;
  action: "keep" | "drop" | "merge" | "review";
  reason: string;
  related_variables: string[];
}

export interface CollinearityRequest {
  version_id: string;
  input_columns: string[];
  dataset_id?: string | null;
  output_column?: string | null;
  correlation_threshold?: number;
  vif_threshold?: number;
}

export interface CollinearityResponse {
  source_version_id: string;
  dataset_id: string | null;
  task: TaskResource;
  variables: string[];
  matrix: number[][];
  spearman_matrix: number[][];
  vif_scores: Record<string, number>;
  condition_number: number | null;
  correlated_groups: string[][];
  recommendations: VariableRecommendation[];
}

export interface FeatureSelectionApplyRequest {
  version_id: string;
  dataset_id?: string;
  drop_columns: string[];
  user_confirmed: boolean;
  recommendation_source: "manual" | "collinearity_analysis";
  evidence?: Record<string, Record<string, any>>;
}

// Modeling & Optimization API Types
export interface ARXFitRequest {
  dataset_id: string;
  version_id: string;
  na: number;
  nb: number[];
  delays: number[];
  estimation_method?: "ols" | "ridge";
  ridge_alpha?: number;
}

export interface ArxMetrics {
  train_r2: number | null;
  train_fit: number | null;
  train_rmse: number | null;
  val_r2: number | null;
  val_fit: number | null;
  val_rmse: number | null;
  test_r2: number | null;
  test_fit: number | null;
  test_rmse: number | null;
  rmse: number | null;
  mae: number | null;
  nrmse: number | null;
  /** Free-run (infinite-step) simulation FIT — the primary acceptance metric. */
  train_free_run_fit: number | null;
  val_free_run_fit: number | null;
  test_free_run_fit: number | null;
  aic: number | null;
  bic: number | null;
}

export interface ModelValidationData {
  one_step_fit: number | null;
  free_run_fit: number | null;
  free_run_rmse: number | null;
  /** one_step_fit - free_run_fit. A large gap means the model is coasting on persistence. */
  fit_gap: number | null;
  stable: boolean;
  max_pole_modulus: number | null;
  steady_state_gains: Record<string, number>;
  residual_whiteness_ratio: number | null;
  n_samples: number;
  partition: string;
}

export interface PriorViolation {
  variable: string;
  kind: "gain_sign" | "gain_bounds" | "stability";
  expected: string;
  actual: number | null;
}

export interface SplitIndices {
  train_end: number;
  val_end: number;
  test_end: number;
}

export interface ARXFitResponse {
  model_id: string;
  task: TaskResource;
  estimator: "ols" | "ridge";
  dataset_id: string | null;
  version_id: string | null;
  coefficients: Record<string, number>;
  a_coefficients: number[];
  b_coefficients: Record<string, number[]>;
  metrics: ArxMetrics;
  plot_data: {
    indices: number[];
    y_true: number[];
    y_pred: number[];
    residuals: number[];
    splits: SplitIndices;
    split_indices: SplitIndices | null;
  };
  residual_diagnostics: {
    acf_values: number[];
    confidence_interval: number | null;
  };
  artifact_uri: string | null;
  validation: ModelValidationData | null;
  prior_violations: PriorViolation[];
  training_rows: number;
  /** Model output driven by inputs alone, aligned with plot_data.indices. */
  free_run_series: number[];
}

export interface OptunaStartRequest {
  version_id: string;
  input_columns: string[];
  output_column: string;
  max_trials?: number;
  timeout_seconds?: number | null;
  search_space?: Record<string, any>;
  random_seed?: number;
}

export interface OptunaTrialItem {
  trial_id: number;
  /** Failed and pruned trials are returned too; they are never hidden. */
  state: "queued" | "running" | "complete" | "pruned" | "failed";
  value: number | null;
  params: Record<string, any>;
  created_at: string;
  finished_at: string | null;
  error_code: string | null;
}

export interface OptunaStatistics {
  hits: number;
  misses: number;
  lookups: number;
  hit_rate: number;
  entries: number;
  total_trials: number;
  completed_trials: number;
  failed_trials: number;
  pruned_trials: number;
  mean_trial_ms: number;
  warm_start_trials: number;
  /** Model fits performed across all trials. */
  structure_evaluations: number;
  /** Distinct segment selections actually computed. */
  selection_computations: number;
  /** structure_evaluations / selection_computations — the amortisation factor. */
  evaluations_per_selection: number;
}

export interface OptunaStatusResponse {
  study_id: string;
  task: TaskResource;
  trials: OptunaTrialItem[];
  best_trial_id: number | null;
  best_value: number | null;
  /** Best-so-far objective after each trial; monotone non-decreasing by construction. */
  best_curve: (number | null)[];
  param_importances: Record<string, number>;
  statistics: Partial<OptunaStatistics>;
  best_params: Record<string, any>;
  /** Set when this study reused parameters learned from a different dataset. */
  warm_started_from: string | null;
}

// Copilot API Types
export type AgentStepStatus =
  | "pending"
  | "running"
  | "waiting_confirmation"
  | "completed"
  | "failed"
  | "cancelled";

export type AgentWorkflowStatus =
  | "PLANNED"
  | "RUNNING"
  | "WAITING_CONFIRMATION"
  | "WAITING_ASYNC_TASK"
  | "SUCCEEDED"
  | "FAILED"
  | "CANCELLED";

export type AgentConfirmationStatus = "NOT_REQUIRED" | "PENDING" | "APPROVED" | "REJECTED";

export interface ExecutionPlanStep {
  step_id: string;
  tool: string;
  depends_on: string[];
  parameters: Record<string, any>;
  requires_confirmation: boolean;
  status: AgentStepStatus;
}

export interface ExecutionPlan {
  goal: string;
  dataset_id: string | null;
  steps: ExecutionPlanStep[];
  stop_conditions: string[];
  assumptions: string[];
}

export interface ProofCheckData {
  name: string;
  passed: boolean;
  detail: string;
}

/** Machine-checked evidence that the plan obeys the frozen safety rules. */
export interface ComplianceProofData {
  proof_id: string;
  passed: boolean;
  checks: ProofCheckData[];
  signature: string;
  code_version: string;
  generated_at: string;
}

/** One executed step, carrying the real tool output rather than the agent's prose. */
export interface AgentStepRun {
  step_id: string;
  tool: string;
  status: AgentStepStatus;
  parameters: Record<string, any>;
  summary: string;
  result: Record<string, any>;
  duration_ms: number;
  error_code: string | null;
  error_message?: string | null;
  processing_run_ids?: string[];
}

export interface CopilotChatRequest {
  message: string;
  dataset_id?: string | null;
  active_version_id?: string | null;
  context?: Record<string, any>;
}

export interface CopilotChatResponse {
  copilot_run_id: string;
  execution_id: string | null;
  workflow_status: AgentWorkflowStatus | null;
  current_version_id: string | null;
  pending_confirmation_step_id: string | null;
  plan: ExecutionPlan;
  task: TaskResource | null;
  compliance: ComplianceProofData | null;
  step_runs: AgentStepRun[];
  conclusion: string;
  executed: boolean;
  /** "llm" means a model authored the plan and it then passed the same safety checks. */
  plan_source: "llm" | "rule_based";
  llm_provider: string;
  llm_model: string;
  /** Why the LLM plan was not used, when it was not. */
  llm_fallback_reason: string | null;
}

export interface LagManualOverride {
  variable: string;
  value: number | string;
}

export type LagOverrideStatus = "VALID" | "WARNING" | "INVALID";

export interface LagOverrideParameterValidation {
  variable: string;
  recommended_value: number | null;
  manual_value: number | string | null;
  final_value: number | null;
  status: LagOverrideStatus;
  issues: string[];
}

export interface LagOverrideValidationRequest {
  execution_id: string;
  step_id: string;
  manual_overrides: LagManualOverride[];
}

export interface LagOverrideValidationResponse {
  recommended_lag_map: Record<string, number>;
  manual_overrides: Record<string, number | string>;
  final_lag_map: Record<string, number>;
  parameter_sources: Record<string, "delay_recommendation" | "manual_override">;
  per_parameter_validation: LagOverrideParameterValidation[];
  overall_status: LagOverrideStatus;
  issues: string[];
}
export type FeatureSelectionAction = "keep" | "drop" | "merge" | "review";

export interface FeatureSelectionDecision {
  variable: string;
  recommended_action: FeatureSelectionAction;
  final_action: "keep" | "drop";
  source: "collinearity_analysis" | "manual_override";
}

export interface FeatureSelectionValidationRequest {
  execution_id: string;
  step_id: string;
  drop_columns?: string[] | null;
}

export interface FeatureSelectionValidationResponse {
  recommended_selection: Record<string, FeatureSelectionAction>;
  recommended_drop_columns: string[];
  manual_drop_columns: string[] | null;
  final_drop_columns: string[];
  kept_input_columns: string[];
  selection_sources: Record<string, "collinearity_analysis" | "manual_override">;
  decisions: FeatureSelectionDecision[];
  overall_status: "VALID" | "INVALID";
  issues: string[];
}
export interface ArxStructureManualOverrides {
  na?: number | null;
  nb?: Record<string, number>;
}

export interface ArxStructureValidationRequest {
  execution_id: string;
  step_id: string;
  manual_overrides: ArxStructureManualOverrides;
}

export interface ArxStructureValidationResponse {
  recommended_structure: Record<string, any>;
  manual_overrides: Record<string, any>;
  final_structure: Record<string, any>;
  structure_sources: Record<string, "structure_recommendation" | "manual_override">;
  selection_evidence: Record<string, any>;
  overall_status: "VALID" | "INVALID";
  issues: string[];
}
export interface CopilotConfirmRequest {
  copilot_run_id: string;
  confirmation_id: string;
  approved: boolean;
  execution_id?: string | null;
  step_id?: string | null;
  parameter_overrides?: Record<string, any>;
  manual_overrides?: LagManualOverride[];
  warning_acknowledged?: boolean;
  feature_drop_columns?: string[] | null;
  arx_structure_overrides?: ArxStructureManualOverrides;
  comment?: string | null;
}

export interface CopilotConfirmResponse {
  copilot_run_id: string;
  confirmation_id: string;
  decision: "approved" | "rejected";
  execution_id: string;
  workflow_status: AgentWorkflowStatus;
  current_version_id?: string | null;
  current_step_id: string | null;
  pending_confirmation_step_id: string | null;
  step_id: string;
  step_status: string;
  confirmation_status: AgentConfirmationStatus;
  result_version_id?: string | null;
  result_payload?: Record<string, any>;
  lag_override_validation?: LagOverrideValidationResponse | null;
  feature_selection_validation?: FeatureSelectionValidationResponse | null;
  arx_structure_validation?: ArxStructureValidationResponse | null;
  task: TaskResource | null;
}


export interface PredictionMetrics {
  mae: number | null;
  rmse: number | null;
  r2: number | null;
  fit: number | null;
  nrmse: number | null;
}

export interface SavedArxEvaluationTest {
  one_step: PredictionMetrics;
  free_run: PredictionMetrics;
}

export interface SavedArxEvaluationResult {
  model_id: string;
  source_version_id: string;
  processing_run_id: string;
  test: SavedArxEvaluationTest;
}

export interface CopilotEvaluateModelExecuteResponse {
  execution_id: string;
  workflow_status: AgentWorkflowStatus;
  current_version_id: string | null;
  step_id: string;
  step_status: string;
  result_payload: Record<string, unknown>;
  error_code: string | null;
  error_message: string | null;
  processing_run_ids: string[];
}// Delivery API Types (Phase 10)
export interface ReportRequest {
  dataset_id?: string | null;
  version_id?: string | null;
  study_id?: string | null;
  title?: string;
}

export interface ReportSection {
  key: string;
  title: string;
  body: string;
}

/** One number in the report, and the run record it was read from. */
export interface ReportBinding {
  placeholder: string;
  kind: string;
  run_id: string;
  path: string;
  value: string;
  resolved: boolean;
}

export interface ReportResponse {
  report_id: string;
  dataset_id: string | null;
  task: TaskResource;
  title: string;
  markdown: string;
  sections: ReportSection[];
  bindings: ReportBinding[];
  unresolved: string[];
  fully_resolved: boolean;
  artifact_uri: string | null;
  cited_runs: string[];
  /** "llm" means a model wrote the commentary and it passed the numeral check. */
  narration_source: string;
  llm_provider: string;
  llm_model: string;
  llm_fallback_reason: string | null;
  /** Drafts rejected for containing unbound digits before one was accepted. */
  llm_rejected_attempts: number;
}

export interface ExportDatasetRequest {
  version_id: string;
  dataset_id?: string | null;
  input_columns?: string[];
  output_column?: string | null;
  sample_indices?: number[];
}

export interface ExportDatasetResponse {
  export_id: string;
  dataset_id: string | null;
  version_id: string;
  task: TaskResource;
  csv_uri: string;
  manifest_uri: string;
  exported_rows: number;
  source_rows: number;
  coverage_ratio: number;
  columns: string[];
}
