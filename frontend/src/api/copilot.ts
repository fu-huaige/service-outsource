import apiClient from "./client";
import type {
  ArxStructureValidationRequest,
  ArxStructureValidationResponse,
  CopilotChatRequest,
  CopilotChatResponse,
  CopilotConfirmRequest,
  CopilotConfirmResponse,
  CopilotEvaluateModelExecuteResponse,
  CopilotExecutionSnapshot,
  CopilotModelExecuteRequest,
  CopilotModelExecutionData,
  CopilotOptimizePipelineExecuteResponse,
  FeatureSelectionValidationRequest,
  FeatureSelectionValidationResponse,
  LagOverrideValidationRequest,
  LagOverrideValidationResponse,
} from "../types/api";

const COPILOT_PLAN_TIMEOUT_MS = 120_000;
const COPILOT_OPTIMIZATION_TIMEOUT_MS = 600_000;

export const chatWithCopilot = (req: CopilotChatRequest): Promise<CopilotChatResponse> =>
  apiClient.post("/copilot/chat", req, { timeout: COPILOT_PLAN_TIMEOUT_MS });

export const getCopilotExecution = (executionId: string): Promise<CopilotExecutionSnapshot> =>
  apiClient.get(`/copilot/executions/${encodeURIComponent(executionId)}`);

export const confirmCopilotStep = (
  req: CopilotConfirmRequest
): Promise<CopilotConfirmResponse> =>
  apiClient.post("/copilot/confirm", req);

export const executeConfirmedModel = (req: CopilotModelExecuteRequest): Promise<CopilotModelExecutionData> =>
  apiClient.post("/copilot/modeling/execute", req, { timeout: 600_000 });

export const getConfirmedModelExecution = (req: CopilotModelExecuteRequest): Promise<CopilotModelExecutionData | null> =>
  apiClient.get("/copilot/modeling/execution", { params: req });

export const validateLagOverrides = (
  req: LagOverrideValidationRequest
): Promise<LagOverrideValidationResponse> =>
  apiClient.post("/copilot/lag-overrides/validate", req);

export const validateFeatureSelection = (
  req: FeatureSelectionValidationRequest
): Promise<FeatureSelectionValidationResponse> =>
  apiClient.post("/copilot/feature-selection/validate", req);

export const validateArxStructure = (
  req: ArxStructureValidationRequest
): Promise<ArxStructureValidationResponse> =>
  apiClient.post("/copilot/arx-structure/validate", req);

export const executeModelEvaluation = (
  executionId: string
): Promise<CopilotEvaluateModelExecuteResponse> =>
  apiClient.post("/copilot/evaluate-model/execute", { execution_id: executionId });

export const executePipelineOptimization = (
  executionId: string
): Promise<CopilotOptimizePipelineExecuteResponse> =>
  apiClient.post(
    "/copilot/optimize-pipeline/execute",
    { execution_id: executionId },
    { timeout: COPILOT_OPTIMIZATION_TIMEOUT_MS }
  );