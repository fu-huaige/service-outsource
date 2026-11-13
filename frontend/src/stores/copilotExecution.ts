import { defineStore } from "pinia";
import { ref } from "vue";
import type { AgentComposerSubmission } from "../types/api";

export const COPILOT_ACTIVE_EXECUTION_STORAGE_KEY = "indusopt.copilot.activeExecutionId";

const readStoredExecutionId = (): string | null => {
  if (typeof window === "undefined") return null;
  const value = window.localStorage.getItem(COPILOT_ACTIVE_EXECUTION_STORAGE_KEY)?.trim();
  return value || null;
};

export const useCopilotExecutionStore = defineStore("copilotExecution", () => {
  const activeExecutionId = ref<string | null>(readStoredExecutionId());

  function setActiveExecutionId(executionId: string) {
    const value = executionId.trim();
    activeExecutionId.value = value || null;
    if (typeof window === "undefined") return;
    if (value) {
      window.localStorage.setItem(COPILOT_ACTIVE_EXECUTION_STORAGE_KEY, value);
    } else {
      window.localStorage.removeItem(COPILOT_ACTIVE_EXECUTION_STORAGE_KEY);
    }
  }

  function clearActiveExecutionId() {
    activeExecutionId.value = null;
    if (typeof window !== "undefined") {
      window.localStorage.removeItem(COPILOT_ACTIVE_EXECUTION_STORAGE_KEY);
    }
  }

  // The home handoff belongs to this app instance and is consumed before any request.
  let pendingHomeTask: { id: string; payload: AgentComposerSubmission } | undefined;

  function stageHomeTask(payload: AgentComposerSubmission): string {
    const id = crypto.getRandomValues(new Uint32Array(4)).join("-");
    pendingHomeTask = { id, payload };
    return id;
  }

  function takeHomeTask(id: string): AgentComposerSubmission | undefined {
    if (pendingHomeTask?.id !== id) return undefined;
    const { payload } = pendingHomeTask;
    pendingHomeTask = undefined;
    return payload;
  }

  return { activeExecutionId, setActiveExecutionId, clearActiveExecutionId, stageHomeTask, takeHomeTask };
});