import apiClient from "./client";
import type {
  CopilotChatRequest,
  CopilotChatResponse,
  CopilotConfirmRequest,
  CopilotConfirmResponse,
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
