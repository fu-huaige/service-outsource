import apiClient from "./client";
import type {
  ArxStructureValidationRequest,
  ArxStructureValidationResponse,
  CopilotChatRequest,
  CopilotChatResponse,
  CopilotConfirmRequest,
  CopilotConfirmResponse,
  FeatureSelectionValidationRequest,
  FeatureSelectionValidationResponse,
  LagOverrideValidationRequest,
  LagOverrideValidationResponse,
} from "../types/api";

const COPILOT_PLAN_TIMEOUT_MS = 120_000;

export const chatWithCopilot = (req: CopilotChatRequest): Promise<CopilotChatResponse> =>
  apiClient.post("/copilot/chat", req, { timeout: COPILOT_PLAN_TIMEOUT_MS });

export const confirmCopilotStep = (
  req: CopilotConfirmRequest
): Promise<CopilotConfirmResponse> =>
  apiClient.post("/copilot/confirm", req);

export const validateLagOverrides = (
  req: LagOverrideValidationRequest
): Promise<LagOverrideValidationResponse> => apiClient.post("/copilot/lag-overrides/validate", req);
export const validateFeatureSelection = (
  req: FeatureSelectionValidationRequest
): Promise<FeatureSelectionValidationResponse> =>
  apiClient.post("/copilot/feature-selection/validate", req);
export const validateArxStructure = (
  req: ArxStructureValidationRequest
): Promise<ArxStructureValidationResponse> =>
  apiClient.post("/copilot/arx-structure/validate", req);
