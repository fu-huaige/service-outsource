import { beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import CopilotView from "../../src/views/CopilotView.vue";
import {
  chatWithCopilot,
  confirmCopilotStep,
  executePipelineOptimization,
  executeModelEvaluation,
  getCopilotExecution,
  validateArxStructure,
  validateFeatureSelection,
  validateLagOverrides,
} from "../../src/api/copilot";
import type { CopilotChatResponse, CopilotExecutionSnapshot } from "../../src/types/api";
import { ApiError } from "../../src/api/client";
import {
  COPILOT_ACTIVE_EXECUTION_STORAGE_KEY,
  useCopilotExecutionStore,
} from "../../src/stores/copilotExecution";

vi.mock("../../src/api/copilot", () => ({
  chatWithCopilot: vi.fn(),
  confirmCopilotStep: vi.fn(),
  executePipelineOptimization: vi.fn(),
  executeModelEvaluation: vi.fn(),
  getCopilotExecution: vi.fn(),
  validateArxStructure: vi.fn(),
  validateFeatureSelection: vi.fn(),
  validateLagOverrides: vi.fn(),
}));
const { routeQuery, routerReplace } = vi.hoisted(() => ({
  routeQuery: {} as Record<string, string | undefined>,
  routerReplace: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("vue-router", () => ({
  useRoute: () => ({ query: routeQuery }),
  useRouter: () => ({ replace: routerReplace }),
}));
vi.mock("element-plus", () => ({ ElMessage: { success: vi.fn(), error: vi.fn() } }));

const executionId = "22222222-2222-4222-8222-222222222222";
const copilotRunId = "11111111-1111-4111-8111-111111111111";
const versionId = "33333333-3333-4333-8333-333333333333";

const mockedChat = vi.mocked(chatWithCopilot);
const mockedConfirm = vi.mocked(confirmCopilotStep);
const mockedExecuteOptimization = vi.mocked(executePipelineOptimization);
const mockedExecuteEvaluation = vi.mocked(executeModelEvaluation);
const mockedGetExecution = vi.mocked(getCopilotExecution);
const mockedValidateLag = vi.mocked(validateLagOverrides);
const mockedValidateArx = vi.mocked(validateArxStructure);
const mockedValidateFeature = vi.mocked(validateFeatureSelection);

const stubs = {
  "el-form": { template: "<form><slot /></form>" },
  "el-form-item": { props: ["label"], template: "<label>{{ label }}<slot /></label>" },
  "el-input": {
    props: ["modelValue", "type"],
    emits: ["update:modelValue"],
    template: `<input
      :data-test="type === 'textarea' ? 'copilot-prompt' : 'active-version'"
      :value="modelValue"
      @input="$emit('update:modelValue', $event.target.value)"
    />`,
  },
  "el-button": {
    props: ["disabled", "loading"],
    template: "<button type='button' :disabled='disabled || loading' @click=\"$emit('click')\"><slot /></button>",
  },
  "el-alert": { template: "<div><slot name='title' /><slot /></div>" },
  "el-tag": { template: "<span><slot /></span>" },
  "el-icon": { template: "<span><slot /></span>" },
  "el-steps": { template: "<div><slot /></div>" },
  "el-step": { template: "<section><slot name='title' /><slot name='description' /></section>" },
  "el-table": true,
  "el-table-column": true,
  "el-dialog": {
    props: ["modelValue"],
    template: "<div><slot name='header' /><slot /><slot name='footer' /></div>",
  },
  "el-select": {
    props: ["modelValue", "disabled"],
    emits: ["update:modelValue", "change"],
    template: `<select :disabled="disabled" :value="modelValue" @change="$emit('update:modelValue', $event.target.value); $emit('change', $event.target.value)"><slot /></select>`,
  },
  "el-option": {
    props: ["label", "value", "disabled"],
    template: "<option :value='value' :disabled='disabled'>{{ label }}</option>",
  },
  "el-input-number": {
    props: ["modelValue", "disabled"],
    emits: ["update:modelValue"],
    template: `<input type="number" :disabled="disabled" :value="modelValue" @input="$emit('update:modelValue', Number($event.target.value))" />`,
  },
  ChatDotRound: true,
  CircleCheck: true,
  CircleClose: true,
  Document: true,
  InfoFilled: true,
  Promotion: true,
  Share: true,
};

const waitingResponse = (): CopilotChatResponse => ({
  copilot_run_id: copilotRunId,
  execution_id: executionId,
  workflow_status: "WAITING_CONFIRMATION",
  current_version_id: versionId,
  pending_confirmation_step_id: "s2",
  plan: {
    goal: "确认后继续",
    dataset_id: null,
    steps: [
      {
        step_id: "s1",
        tool: "profile_data",
        depends_on: [],
        parameters: {},
        requires_confirmation: false,
        status: "completed",
      },
      {
        step_id: "s2",
        tool: "export_dataset",
        depends_on: ["s1"],
        parameters: { selected: ["u", "y"] },
        requires_confirmation: true,
        status: "waiting_confirmation",
      },
      {
        step_id: "s3",
        tool: "fit_arx",
        depends_on: ["s2"],
        parameters: {},
        requires_confirmation: false,
        status: "pending",
      },
    ],
    stop_conditions: [],
    assumptions: [],
  },
  task: null,
  compliance: {
    proof_id: "proof-1",
    passed: true,
    checks: [],
    signature: "signature",
    code_version: "test",
    generated_at: "2026-08-25T00:00:00Z",
  },
  step_runs: [
    {
      step_id: "s1",
      tool: "profile_data",
      status: "completed",
      parameters: {},
      summary: "profile complete",
      result: {},
      duration_ms: 1,
      error_code: null,
    },
    {
      step_id: "s2",
      tool: "export_dataset",
      status: "waiting_confirmation",
      parameters: { selected: ["u", "y"] },
      summary: "等待确认",
      result: {},
      duration_ms: 0,
      error_code: null,
    },
  ],
  conclusion: "等待人工确认",
  executed: true,
  plan_source: "rule_based",
  llm_provider: "none",
  llm_model: "none",
  llm_fallback_reason: null,
});

const arxWaitingResponse = (): CopilotChatResponse => {
  const response = waitingResponse();
  response.plan.steps[1] = {
    ...response.plan.steps[1],
    tool: "fit_arx",
    requires_confirmation: true,
    status: "waiting_confirmation",
  };
  response.plan.steps[2] = {
    ...response.plan.steps[2],
    tool: "evaluate_model",
    requires_confirmation: false,
    status: "pending",
  };
  response.step_runs[1] = {
    ...response.step_runs[1],
    tool: "fit_arx",
    result: {
      arx_structure_recommendation: {
        recommended_na: 2,
        recommended_nb: { u1: 2, u2: 3 },
        recommended_delays: { u1: 0, u2: 0 },
        delay_source: "derived_from_lag_compensated_version",
        selection_evidence: { test_partition_used: false },
      },
    },
  };
  return response;
};

const evaluationPendingResponse = (): CopilotChatResponse => {
  const response = arxWaitingResponse();
  response.workflow_status = "RUNNING";
  response.pending_confirmation_step_id = null;
  response.plan.steps[1] = {
    ...response.plan.steps[1],
    status: "completed",
  };
  response.step_runs[1] = {
    ...response.step_runs[1],
    status: "completed",
    result: { model_id: "model-arx-1", source_version_id: versionId },
  };
  response.step_runs.push({
    step_id: "s3",
    tool: "evaluate_model",
    status: "pending",
    parameters: {},
    summary: "等待执行模型评价",
    result: {},
    duration_ms: 0,
    error_code: null,
  });
  return response;
};

const evaluationSuccessResponse = () => ({
  execution_id: executionId,
  workflow_status: "SUCCEEDED" as const,
  current_version_id: versionId,
  step_id: "s3",
  step_status: "SUCCEEDED",
  result_payload: {
    model_id: "model-arx-1",
    source_version_id: versionId,
    processing_run_id: "44444444-4444-4444-8444-444444444444",
    test: {
      one_step: { fit: 88.35, r2: 0.9123, rmse: 0.1234, mae: null, nrmse: 0.0567 },
      free_run: { fit: 82.1, r2: 0.8456, rmse: 0.2345, mae: 0.1111, nrmse: 0.0789 },
    },
  },
  error_code: null,
  error_message: null,
  processing_run_ids: ["44444444-4444-4444-8444-444444444444"],
});
const optimizationWaitingResponse = (): CopilotChatResponse => {
  const response = evaluationPendingResponse();
  response.workflow_status = "WAITING_CONFIRMATION";
  response.pending_confirmation_step_id = "s3";
  response.plan.steps[2] = {
    ...response.plan.steps[2],
    tool: "optimize_pipeline",
    depends_on: ["s2"],
    requires_confirmation: true,
    status: "waiting_confirmation",
  };
  response.step_runs[2] = {
    ...response.step_runs[2],
    tool: "optimize_pipeline",
    status: "waiting_confirmation",
    summary: "等待确认模型优化",
  };
  response.plan.steps.push({
    step_id: "s4",
    tool: "evaluate_model",
    depends_on: ["s3"],
    parameters: {},
    requires_confirmation: false,
    status: "pending",
  });
  response.step_runs.push({
    step_id: "s4",
    tool: "evaluate_model",
    status: "pending",
    parameters: {},
    summary: "等待执行模型评价",
    result: {},
    duration_ms: 0,
    error_code: null,
  });
  return response;
};

const optimizationRunningResponse = (): CopilotChatResponse => {
  const response = optimizationWaitingResponse();
  response.workflow_status = "RUNNING";
  response.pending_confirmation_step_id = null;
  response.plan.steps[2] = { ...response.plan.steps[2], status: "running" };
  response.step_runs[2] = { ...response.step_runs[2], status: "running" };
  return response;
};

const optimizationSuccessResponse = () => ({
  execution_id: executionId,
  workflow_status: "RUNNING" as const,
  current_version_id: versionId,
  step_id: "s3",
  step_status: "SUCCEEDED",
  result_payload: {
    study_id: "55555555-5555-4555-8555-555555555555",
    baseline_model_id: "model-arx-1",
    model_id: "model-optimized-1",
    optimized_model_id: "model-optimized-1",
    source_version_id: versionId,
    best_params: { window_size: 90, nk: 0, estimator: "ridge", ridge_alpha: 0.125 },
    best_value: 0.7314,
  },
  error_code: null,
  error_message: null,
  processing_run_ids: ["55555555-5555-4555-8555-555555555555"],
});
const arxValidation = (overall_status: "VALID" | "INVALID", issues: string[] = []) => ({
  recommended_structure: { na: 2, nb: { u1: 2, u2: 3 }, delays: { u1: 0, u2: 0 } },
  manual_overrides: {},
  final_structure: { na: 2, nb: { u1: 2, u2: 3 }, delays: { u1: 0, u2: 0 } },
  structure_sources: { na: "structure_recommendation", "nb.u1": "structure_recommendation", "nb.u2": "structure_recommendation" } as const,
  selection_evidence: { test_partition_used: false },
  overall_status,
  issues,
});
const mountView = () => {
  const pinia = createPinia();
  setActivePinia(pinia);
  return mount(CopilotView, { global: { plugins: [pinia], stubs } });
};

async function submitChat(wrapper: ReturnType<typeof mountView>) {
  await wrapper.get('[data-test="active-version"]').setValue(versionId);
  await wrapper.get('[data-test="copilot-prompt"]').setValue("执行并等待确认");
  const submit = wrapper.findAll("button").find((button) => button.text().includes("提交给 Agent"));
  expect(submit).toBeTruthy();
  await submit!.trigger("click");
  await flushPromises();
}

beforeEach(() => {
  window.localStorage.clear();
  for (const key of Object.keys(routeQuery)) delete routeQuery[key];
  routerReplace.mockReset();
  routerReplace.mockResolvedValue(undefined);
});
describe("CopilotView persistent confirmation", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mockedChat.mockResolvedValue(waitingResponse());
  });

  it("stores the execution state and places confirmation controls on the pending step", async () => {
    const wrapper = mountView();
    await submitChat(wrapper);

    expect(wrapper.get('[data-test="execution-id"]').text()).toContain(executionId);
    expect(wrapper.get('[data-test="workflow-status"]').text()).toContain("WAITING_CONFIRMATION");
    expect(wrapper.get('[data-test="current-version-id"]').text()).toContain(versionId);
    expect(wrapper.find('[data-test="confirm-actions-s1"]').exists()).toBe(false);
    expect(wrapper.get('[data-test="confirm-actions-s2"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="confirm-actions-s3"]').exists()).toBe(false);
  });

  it("approves with execution_id and step_id, then shows RUNNING/APPROVED semantics", async () => {
    mockedConfirm.mockResolvedValue({
      copilot_run_id: copilotRunId,
      confirmation_id: "s2",
      decision: "approved",
      execution_id: executionId,
      workflow_status: "RUNNING",
      current_step_id: "s2",
      pending_confirmation_step_id: null,
      step_id: "s2",
      step_status: "RUNNING",
      confirmation_status: "APPROVED",
      task: null,
    });
    const wrapper = mountView();
    await submitChat(wrapper);

    await wrapper.get('[data-test="approve-s2"]').trigger("click");
    await flushPromises();

    expect(mockedConfirm).toHaveBeenCalledWith(expect.objectContaining({
      execution_id: executionId,
      step_id: "s2",
      approved: true,
    }));
    expect(wrapper.get('[data-test="workflow-status"]').text()).toContain("RUNNING");
    expect(wrapper.text()).toContain("已批准，等待执行");
    expect(wrapper.text()).not.toContain("该步骤已成功完成");
    const downstreamStep = wrapper.findAll("section").find((step) => step.text().includes("s3 · fit_arx"));
    expect(downstreamStep?.text()).toContain("待执行");
  });

  it("rejects with execution_id and step_id and displays the persisted cancellation", async () => {
    mockedConfirm.mockResolvedValue({
      copilot_run_id: copilotRunId,
      confirmation_id: "s2",
      decision: "rejected",
      execution_id: executionId,
      workflow_status: "CANCELLED",
      current_step_id: "s2",
      pending_confirmation_step_id: null,
      step_id: "s2",
      step_status: "CANCELLED",
      confirmation_status: "REJECTED",
      task: null,
    });
    const wrapper = mountView();
    await submitChat(wrapper);

    await wrapper.get('[data-test="reject-s2"]').trigger("click");
    await flushPromises();

    expect(mockedConfirm).toHaveBeenCalledWith(expect.objectContaining({
      execution_id: executionId,
      step_id: "s2",
      approved: false,
    }));
    expect(wrapper.get('[data-test="workflow-status"]').text()).toContain("CANCELLED");
    expect(wrapper.text()).toContain("已拒绝");
  });

  it("does not expose or send real confirmation for a plan-only response", async () => {
    const planOnly = waitingResponse();
    planOnly.execution_id = null;
    planOnly.workflow_status = null;
    planOnly.current_version_id = null;
    planOnly.pending_confirmation_step_id = null;
    planOnly.executed = false;
    mockedChat.mockResolvedValue(planOnly);
    const wrapper = mountView();

    await submitChat(wrapper);

    expect(wrapper.find('[data-test^="confirm-actions-"]').exists()).toBe(false);
    expect(mockedConfirm).not.toHaveBeenCalled();
  });

  it("validates and executes a confirmed Lag Apply, then displays V2 completion", async () => {
    const lagResponse = waitingResponse();
    lagResponse.plan.steps[1] = {
      ...lagResponse.plan.steps[1],
      tool: "apply_lag_compensation",
    };
    lagResponse.step_runs[1] = {
      ...lagResponse.step_runs[1],
      tool: "apply_lag_compensation",
      result: { recommended_lag_map: { u1: 3, u2: 8 } },
    };
    mockedChat.mockResolvedValue(lagResponse);
    mockedValidateLag.mockResolvedValue({
      recommended_lag_map: { u1: 3, u2: 8 },
      manual_overrides: {},
      final_lag_map: { u1: 3, u2: 8 },
      parameter_sources: { u1: "delay_recommendation", u2: "delay_recommendation" },
      per_parameter_validation: [],
      overall_status: "VALID",
      issues: [],
    });
    mockedConfirm.mockResolvedValue({
      copilot_run_id: copilotRunId,
      confirmation_id: "s2",
      decision: "approved",
      execution_id: executionId,
      workflow_status: "RUNNING",
      current_version_id: "44444444-4444-4444-8444-444444444444",
      current_step_id: null,
      pending_confirmation_step_id: null,
      step_id: "s2",
      step_status: "SUCCEEDED",
      confirmation_status: "APPROVED",
      result_version_id: "44444444-4444-4444-8444-444444444444",
      result_payload: { result_version_id: "44444444-4444-4444-8444-444444444444" },
      lag_override_validation: null,
      task: null,
    });
    const wrapper = mountView();
    await submitChat(wrapper);

    expect(wrapper.find('[data-test="lag-recommendation-s2"]').exists()).toBe(false);
    await wrapper.get('[data-test="approve-s2"]').trigger("click");
    await flushPromises();

    expect(mockedValidateLag).toHaveBeenCalledWith({
      execution_id: executionId,
      step_id: "s2",
      manual_overrides: [],
    });
    expect(mockedConfirm).toHaveBeenCalledWith(expect.objectContaining({
      execution_id: executionId,
      step_id: "s2",
      approved: true,
      warning_acknowledged: false,
    }));
    expect(wrapper.get('[data-test="current-version-id"]').text()).toContain("44444444");
    expect(wrapper.text()).toContain("已批准并执行完成");
  });

  it("requires an explicit warning acknowledgement before submitting Lag Apply", async () => {
    const lagResponse = waitingResponse();
    lagResponse.plan.steps[1] = {
      ...lagResponse.plan.steps[1],
      tool: "apply_lag_compensation",
    };
    lagResponse.step_runs[1] = {
      ...lagResponse.step_runs[1],
      tool: "apply_lag_compensation",
      result: { recommended_lag_map: { u1: 3 } },
    };
    mockedChat.mockResolvedValue(lagResponse);
    mockedValidateLag.mockResolvedValue({
      recommended_lag_map: { u1: 3 },
      manual_overrides: {},
      final_lag_map: { u1: 3 },
      parameter_sources: { u1: "delay_recommendation" },
      per_parameter_validation: [],
      overall_status: "WARNING",
      issues: ["outside analyzed range"],
    });
    mockedConfirm.mockResolvedValue({
      copilot_run_id: copilotRunId,
      confirmation_id: "s2",
      decision: "approved",
      execution_id: executionId,
      workflow_status: "RUNNING",
      current_version_id: versionId,
      current_step_id: null,
      pending_confirmation_step_id: null,
      step_id: "s2",
      step_status: "SUCCEEDED",
      confirmation_status: "APPROVED",
      task: null,
    });
    const wrapper = mountView();
    await submitChat(wrapper);

    await wrapper.get('[data-test="approve-s2"]').trigger("click");
    await flushPromises();
    expect(mockedConfirm).not.toHaveBeenCalled();
    expect(wrapper.get('[data-test="ack-lag-warning-s2"]').exists()).toBe(true);

    await wrapper.get('[data-test="ack-lag-warning-s2"]').trigger("click");
    await flushPromises();
    expect(mockedConfirm).toHaveBeenCalledWith(expect.objectContaining({
      warning_acknowledged: true,
    }));
  });

  it("edits lag overrides in a dialog with dynamic recommendations and isolated drafts", async () => {
    const lagResponse = waitingResponse();
    lagResponse.plan.steps[1] = { ...lagResponse.plan.steps[1], tool: "apply_lag_compensation" };
    lagResponse.step_runs[1] = {
      ...lagResponse.step_runs[1],
      tool: "apply_lag_compensation",
      result: { recommended_lag_map: { u1: 4, u2: 9 } },
    };
    mockedChat.mockResolvedValue(lagResponse);
    mockedValidateLag.mockResolvedValue({
      recommended_lag_map: { u1: 4, u2: 9 },
      manual_overrides: {},
      final_lag_map: { u1: 4, u2: 9 },
      parameter_sources: { u1: "delay_recommendation", u2: "delay_recommendation" },
      per_parameter_validation: [],
      overall_status: "VALID",
      issues: [],
    });
    mockedConfirm.mockResolvedValue({
      copilot_run_id: copilotRunId,
      confirmation_id: "s2",
      decision: "approved",
      execution_id: executionId,
      workflow_status: "RUNNING",
      current_version_id: versionId,
      current_step_id: null,
      pending_confirmation_step_id: null,
      step_id: "s2",
      step_status: "SUCCEEDED",
      confirmation_status: "APPROVED",
      task: null,
    });
    const wrapper = mountView();
    await submitChat(wrapper);

    expect(wrapper.find('[data-test="lag-recommendation-s2"]').exists()).toBe(false);
    expect(wrapper.find('[data-test="lag-variable-0"]').exists()).toBe(false);

    await wrapper.get('[data-test="edit-lag-s2"]').trigger("click");
    const dialog = wrapper.get('[data-test="lag-overrides-s2"]');
    expect(dialog.text()).toContain("修改时滞补偿参数");
    expect(dialog.get('[data-test="lag-recommendation-s2"]').text()).toContain(
      "Delay Analyze 建议： u1:4; u2:9"
    );
    expect(dialog.get('[data-test="lag-recommendation-s2"]').text()).not.toContain('{"u1":4,"u2":9}');
    expect((wrapper.get('[data-test="lag-variable-0"]').element as HTMLSelectElement).value).toBe("u1");
    expect((wrapper.get('[data-test="lag-value-0"]').element as HTMLInputElement).value).toBe("4");

    await wrapper.get('[data-test="lag-variable-0"]').setValue("u2");
    await flushPromises();
    expect((wrapper.get('[data-test="lag-value-0"]').element as HTMLInputElement).value).toBe("9");

    await wrapper.get('[data-test="lag-variable-0"]').setValue("u1");
    await flushPromises();
    expect((wrapper.get('[data-test="lag-value-0"]').element as HTMLInputElement).value).toBe("4");

    await wrapper.get('[data-test="add-lag-override-s2"]').trigger("click");
    expect((wrapper.get('[data-test="lag-variable-1"]').element as HTMLSelectElement).value).toBe("u2");
    expect((wrapper.get('[data-test="lag-value-1"]').element as HTMLInputElement).value).toBe("9");
    expect(
      wrapper.get('[data-test="lag-variable-0"]').get('option[value="u2"]').attributes("disabled")
    ).toBeDefined();

    await wrapper.get('[data-test="cancel-lag-s2"]').trigger("click");
    expect(wrapper.find('[data-test="lag-overrides-s2"]').exists()).toBe(false);
    expect(mockedValidateLag).not.toHaveBeenCalled();

    await wrapper.get('[data-test="approve-s2"]').trigger("click");
    await flushPromises();
    expect(mockedValidateLag).toHaveBeenCalledWith({
      execution_id: executionId,
      step_id: "s2",
      manual_overrides: [],
    });
  });

  it("validates a lag override before, and separately from, approval", async () => {
    const lagResponse = waitingResponse();
    lagResponse.plan.steps[1] = { ...lagResponse.plan.steps[1], tool: "apply_lag_compensation" };
    lagResponse.step_runs[1] = {
      ...lagResponse.step_runs[1],
      tool: "apply_lag_compensation",
      result: { recommended_lag_map: { u1: 4, u2: 9 } },
    };
    mockedChat.mockResolvedValue(lagResponse);
    mockedValidateLag.mockResolvedValue({
      recommended_lag_map: { u1: 4, u2: 9 },
      manual_overrides: { u2: 9 },
      final_lag_map: { u1: 4, u2: 9 },
      parameter_sources: { u1: "delay_recommendation", u2: "manual_override" },
      per_parameter_validation: [],
      overall_status: "VALID",
      issues: [],
    });
    mockedConfirm.mockResolvedValue({
      copilot_run_id: copilotRunId,
      confirmation_id: "s2",
      decision: "approved",
      execution_id: executionId,
      workflow_status: "RUNNING",
      current_version_id: versionId,
      current_step_id: null,
      pending_confirmation_step_id: null,
      step_id: "s2",
      step_status: "SUCCEEDED",
      confirmation_status: "APPROVED",
      task: null,
    });
    const wrapper = mountView();
    await submitChat(wrapper);

    await wrapper.get('[data-test="edit-lag-s2"]').trigger("click");
    await wrapper.get('[data-test="lag-variable-0"]').setValue("u2");
    await wrapper.get('[data-test="validate-lag-s2"]').trigger("click");
    await flushPromises();

    expect(mockedValidateLag).toHaveBeenCalledWith({
      execution_id: executionId,
      step_id: "s2",
      manual_overrides: [{ variable: "u2", value: 9 }],
    });
    expect(mockedConfirm).not.toHaveBeenCalled();
    expect(wrapper.find('[data-test="lag-overrides-s2"]').exists()).toBe(false);

    await wrapper.get('[data-test="approve-s2"]').trigger("click");
    await flushPromises();
    expect(mockedConfirm).toHaveBeenCalledWith(expect.objectContaining({
      manual_overrides: [{ variable: "u2", value: 9 }],
    }));
  });
  it("approves or adjusts a controlled Feature recommendation and displays V3", async () => {
    const featureResponse = waitingResponse();
    featureResponse.plan.steps[1] = { ...featureResponse.plan.steps[1], tool: "select_variables" };
    featureResponse.step_runs[1] = {
      ...featureResponse.step_runs[1],
      tool: "select_variables",
      result: {
        recommended_selection: { u1: "keep", u2: "drop", u3: "keep" },
        recommended_drop_columns: ["u2"],
        recommendation_evidence: {
          u1: { action: "keep", reason: "representative", related_variables: ["u2"] },
          u2: { action: "drop", reason: "redundant", related_variables: ["u1"] },
          u3: { action: "keep", reason: "independent", related_variables: [] },
        },
      },
    };
    mockedChat.mockResolvedValue(featureResponse);
    mockedValidateFeature.mockResolvedValue({
      recommended_selection: { u1: "keep", u2: "drop", u3: "keep" },
      recommended_drop_columns: ["u2"],
      manual_drop_columns: ["u1"],
      final_drop_columns: ["u1"],
      kept_input_columns: ["u2", "u3"],
      selection_sources: { u1: "manual_override", u2: "manual_override", u3: "collinearity_analysis" },
      decisions: [],
      overall_status: "VALID",
      issues: [],
    });
    mockedConfirm.mockResolvedValue({
      copilot_run_id: copilotRunId,
      confirmation_id: "s2",
      decision: "approved",
      execution_id: executionId,
      workflow_status: "RUNNING",
      current_version_id: "55555555-5555-4555-8555-555555555555",
      current_step_id: null,
      pending_confirmation_step_id: null,
      step_id: "s2",
      step_status: "SUCCEEDED",
      confirmation_status: "APPROVED",
      result_version_id: "55555555-5555-4555-8555-555555555555",
      feature_selection_validation: null,
      task: null,
    });
    const wrapper = mountView();
    await submitChat(wrapper);

    expect(wrapper.get('[data-test="feature-recommendation-s2"]').text()).toContain("recommendation");
    expect(wrapper.get('[data-test="feature-variable-u2"]').text()).toContain("drop");
    await wrapper.get('[data-test="edit-feature-s2"]').trigger("click");
    await wrapper.get('[data-test="feature-drop-u2"]').setValue(false);
    await wrapper.get('[data-test="feature-drop-u1"]').setValue(true);
    await wrapper.get('[data-test="approve-s2"]').trigger("click");
    await flushPromises();

    expect(mockedValidateFeature).toHaveBeenCalledWith({ execution_id: executionId, step_id: "s2", drop_columns: ["u1"] });
    expect(mockedConfirm).toHaveBeenCalledWith(expect.objectContaining({ execution_id: executionId, step_id: "s2", approved: true, feature_drop_columns: ["u1"] }));
    expect(wrapper.get('[data-test="current-version-id"]').text()).toContain("55555555");
    expect(wrapper.text()).toContain("已批准并执行完成");
  });
  it("shows a read-only ARX recommendation and adopts it with empty manual overrides", async () => {
    mockedChat.mockResolvedValue(arxWaitingResponse());
    mockedConfirm.mockResolvedValue({
      copilot_run_id: copilotRunId,
      confirmation_id: "s2",
      decision: "approved",
      execution_id: executionId,
      workflow_status: "RUNNING",
      current_version_id: versionId,
      current_step_id: null,
      pending_confirmation_step_id: null,
      step_id: "s2",
      step_status: "SUCCEEDED",
      confirmation_status: "APPROVED",
      result_payload: { model_id: "model-arx-1", version_id: versionId },
      arx_structure_validation: arxValidation("VALID"),
      task: null,
    });
    const wrapper = mountView();
    await submitChat(wrapper);

    expect(wrapper.get("[data-test='arx-recommendation-s2']").text()).toContain("ARX 结构推荐");
    expect(wrapper.get("[data-test='arx-na-s2']").text()).toContain("2");
    expect(wrapper.get("[data-test='arx-nb-u1']").text()).toContain("2");
    expect(wrapper.get("[data-test='arx-delay-u1']").text()).toContain("只读");
    expect(wrapper.get("[data-test='arx-delay-provenance-s2']").text()).toContain("derived_from_lag_compensated_version");
    expect(wrapper.find("[data-test^='arx-delay-input-']").exists()).toBe(false);

    await wrapper.get("[data-test='adopt-arx-s2']").trigger("click");
    await flushPromises();

    expect(mockedValidateArx).not.toHaveBeenCalled();
    expect(mockedConfirm).toHaveBeenCalledWith(expect.objectContaining({
      execution_id: executionId,
      step_id: "s2",
      approved: true,
      arx_structure_overrides: {},
    }));
    expect(wrapper.get("[data-test='arx-model-id-s2']").text()).toContain("model-arx-1");
    expect(wrapper.find("[data-test='adopt-arx-s2']").exists()).toBe(false);
    const evaluation = wrapper.findAll("section").find((step) => step.text().includes("s3 · evaluate_model"));
    expect(evaluation?.text()).toContain("待执行");
  });

  it("validates controlled ARX na/nb overrides before confirming", async () => {
    mockedChat.mockResolvedValue(arxWaitingResponse());
    mockedValidateArx.mockResolvedValue({
      ...arxValidation("VALID"),
      manual_overrides: { na: 3, nb: { u1: 4 } },
      final_structure: { na: 3, nb: { u1: 4, u2: 3 }, delays: { u1: 0, u2: 0 } },
      structure_sources: { na: "manual_override", "nb.u1": "manual_override", "nb.u2": "structure_recommendation" },
    });
    mockedConfirm.mockResolvedValue({
      copilot_run_id: copilotRunId,
      confirmation_id: "s2",
      decision: "approved",
      execution_id: executionId,
      workflow_status: "RUNNING",
      current_version_id: versionId,
      current_step_id: null,
      pending_confirmation_step_id: null,
      step_id: "s2",
      step_status: "SUCCEEDED",
      confirmation_status: "APPROVED",
      result_payload: { model_id: "model-arx-2" },
      arx_structure_validation: arxValidation("VALID"),
      task: null,
    });
    const wrapper = mountView();
    await submitChat(wrapper);

    await wrapper.get("[data-test='edit-arx-s2']").trigger("click");
    await wrapper.get("[data-test='arx-na-input-s2']").setValue("3");
    await wrapper.get("[data-test='arx-nb-input-u1']").setValue("4");
    await wrapper.get("[data-test='validate-arx-s2']").trigger("click");
    await flushPromises();

    expect(mockedValidateArx).toHaveBeenCalledWith({
      execution_id: executionId,
      step_id: "s2",
      manual_overrides: { na: 3, nb: { u1: 4 } },
    });
    expect(wrapper.get("[data-test='arx-validation-s2']").text()).toContain("VALID");
    await wrapper.get("[data-test='confirm-arx-s2']").trigger("click");
    await flushPromises();
    expect(mockedConfirm).toHaveBeenCalledWith(expect.objectContaining({
      arx_structure_overrides: { na: 3, nb: { u1: 4 } },
    }));
  });

  it("shows Backend ARX validation issues and blocks confirm when invalid", async () => {
    mockedChat.mockResolvedValue(arxWaitingResponse());
    mockedValidateArx.mockResolvedValue(arxValidation("INVALID", ["na must be at least 1"]));
    const wrapper = mountView();
    await submitChat(wrapper);

    await wrapper.get("[data-test='edit-arx-s2']").trigger("click");
    await wrapper.get("[data-test='arx-na-input-s2']").setValue("0");
    await wrapper.get("[data-test='validate-arx-s2']").trigger("click");
    await flushPromises();

    expect(wrapper.get("[data-test='arx-validation-s2']").text()).toContain("na must be at least 1");
    expect(wrapper.find("[data-test='confirm-arx-s2']").exists()).toBe(false);
    expect(mockedConfirm).not.toHaveBeenCalled();
  });

  it("cancels a waiting ARX step without submitting ARX overrides", async () => {
    mockedChat.mockResolvedValue(arxWaitingResponse());
    mockedConfirm.mockResolvedValue({
      copilot_run_id: copilotRunId,
      confirmation_id: "s2",
      decision: "rejected",
      execution_id: executionId,
      workflow_status: "CANCELLED",
      current_version_id: versionId,
      current_step_id: "s2",
      pending_confirmation_step_id: null,
      step_id: "s2",
      step_status: "CANCELLED",
      confirmation_status: "REJECTED",
      task: null,
    });
    const wrapper = mountView();
    await submitChat(wrapper);

    await wrapper.get("[data-test='reject-s2']").trigger("click");
    await flushPromises();

    expect(mockedConfirm).toHaveBeenCalledWith(expect.objectContaining({
      execution_id: executionId,
      step_id: "s2",
      approved: false,
    }));
    expect(mockedValidateArx).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("已拒绝");
  });
});
describe("CopilotView explicit model evaluation", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mockedChat.mockResolvedValue(evaluationPendingResponse());
  });

  it("shows the evaluation trigger only after fit_arx succeeds", async () => {
    const wrapper = mountView();
    await submitChat(wrapper);

    expect(wrapper.get("[data-test='execute-evaluation-s3']").text()).toContain("执行模型评价");
  });

  it("does not expose the evaluation trigger before fit succeeds or for plan-only results", async () => {
    const notReady = evaluationPendingResponse();
    notReady.plan.steps[1].status = "pending";
    mockedChat.mockResolvedValue(notReady);
    const notReadyWrapper = mountView();
    await submitChat(notReadyWrapper);
    expect(notReadyWrapper.find("[data-test='execute-evaluation-s3']").exists()).toBe(false);

    const planOnly = evaluationPendingResponse();
    planOnly.execution_id = null;
    planOnly.executed = false;
    mockedChat.mockResolvedValue(planOnly);
    const planOnlyWrapper = mountView();
    await submitChat(planOnlyWrapper);
    expect(planOnlyWrapper.find("[data-test='execute-evaluation-s3']").exists()).toBe(false);
  });

  it("executes once, updates the step, and renders real test metrics", async () => {
    let resolveResponse: (value: ReturnType<typeof evaluationSuccessResponse>) => void;
    mockedExecuteEvaluation.mockReturnValue(new Promise((resolve) => { resolveResponse = resolve; }));
    const wrapper = mountView();
    await submitChat(wrapper);

    const button = wrapper.get("[data-test='execute-evaluation-s3']");
    await button.trigger("click");
    await wrapper.vm.$nextTick();
    expect(mockedExecuteEvaluation).toHaveBeenCalledWith(executionId);
    expect(button.attributes("disabled")).toBeDefined();
    await button.trigger("click");
    expect(mockedExecuteEvaluation).toHaveBeenCalledTimes(1);

    resolveResponse!(evaluationSuccessResponse());
    await flushPromises();
    expect(mockedGetExecution).toHaveBeenCalledWith(executionId);

    expect(wrapper.find("[data-test='execute-evaluation-s3']").exists()).toBe(false);
    expect(wrapper.get("[data-test='evaluation-results-s3']").text()).toContain("模型评价结果");
    expect(wrapper.get("[data-test='evaluation-one-step-s3']").text()).toContain("一步预测");
    expect(wrapper.get("[data-test='evaluation-free-run-s3']").text()).toContain("自由仿真");
    expect(wrapper.text()).toContain("88.35%");
    expect(wrapper.text()).not.toContain("8835%");
    expect(wrapper.get("[data-test='evaluation-one-step-s3']").text()).toContain("—");
    expect(wrapper.text()).toContain("R²");
    expect(wrapper.text()).toContain("RMSE");
    expect(wrapper.text()).toContain("MAE");
    expect(wrapper.text()).toContain("NRMSE");
  });

  it("renders a persisted FAILED evaluation response without metrics", async () => {
    mockedExecuteEvaluation.mockResolvedValue({
      ...evaluationSuccessResponse(),
      workflow_status: "FAILED",
      step_status: "FAILED",
      result_payload: {},
      error_code: "MODEL_SOURCE_VERSION_MISMATCH",
      error_message: "已保存模型的数据版本不匹配。",
      processing_run_ids: [],
    });
    const wrapper = mountView();
    await submitChat(wrapper);

    await wrapper.get("[data-test='execute-evaluation-s3']").trigger("click");
    await flushPromises();

    expect(wrapper.get("[data-test='evaluation-error-s3']").text()).toContain("已保存模型的数据版本不匹配。");
    expect(wrapper.find("[data-test='evaluation-results-s3']").exists()).toBe(false);
    expect(wrapper.find("[data-test='execute-evaluation-s3']").exists()).toBe(false);
  });

  it("surfaces trigger conflicts without fabricating evaluation data", async () => {
    mockedExecuteEvaluation.mockRejectedValue(new Error("当前执行状态不允许模型评价。"));
    const wrapper = mountView();
    await submitChat(wrapper);

    await wrapper.get("[data-test='execute-evaluation-s3']").trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("当前执行状态不允许模型评价。");
    expect(wrapper.find("[data-test='evaluation-results-s3']").exists()).toBe(false);
  });
});

describe("CopilotView explicit pipeline optimization", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("uses the generic confirmation flow and never executes optimization automatically", async () => {
    mockedChat.mockResolvedValue(optimizationWaitingResponse());
    mockedConfirm.mockResolvedValue({
      copilot_run_id: copilotRunId,
      confirmation_id: "s3",
      decision: "approved",
      execution_id: executionId,
      workflow_status: "RUNNING",
      current_step_id: "s3",
      pending_confirmation_step_id: null,
      step_id: "s3",
      step_status: "RUNNING",
      confirmation_status: "APPROVED",
      task: null,
    });
    const wrapper = mountView();
    await submitChat(wrapper);

    expect(wrapper.find("[data-test='confirm-actions-s3']").exists()).toBe(true);
    expect(wrapper.find("[data-test='execute-optimization-s3']").exists()).toBe(false);

    await wrapper.get("[data-test='approve-s3']").trigger("click");
    await flushPromises();

    expect(mockedExecuteOptimization).not.toHaveBeenCalled();
    expect(wrapper.get("[data-test='execute-optimization-s3']").text()).toContain("执行模型优化");
  });

  it("shows the optimization trigger only for a running optimization with its declared completed fit predecessor", async () => {
    mockedChat.mockResolvedValue(optimizationRunningResponse());
    const wrapper = mountView();
    await submitChat(wrapper);
    expect(wrapper.find("[data-test='execute-optimization-s3']").exists()).toBe(true);

    const notReady = optimizationRunningResponse();
    notReady.plan.steps[1].status = "pending";
    mockedChat.mockResolvedValue(notReady);
    const notReadyWrapper = mountView();
    await submitChat(notReadyWrapper);
    expect(notReadyWrapper.find("[data-test='execute-optimization-s3']").exists()).toBe(false);
  });

  it("executes optimization once, renders its result, and then enables the optimization DAG evaluation step", async () => {
    let resolveResponse: (value: ReturnType<typeof optimizationSuccessResponse>) => void;
    mockedChat.mockResolvedValue(optimizationRunningResponse());
    mockedExecuteOptimization.mockReturnValue(new Promise((resolve) => { resolveResponse = resolve; }));
    const wrapper = mountView();
    await submitChat(wrapper);

    const button = wrapper.get("[data-test='execute-optimization-s3']");
    await button.trigger("click");
    await wrapper.vm.$nextTick();
    expect(mockedExecuteOptimization).toHaveBeenCalledWith(executionId);
    expect(button.attributes("disabled")).toBeDefined();
    await button.trigger("click");
    expect(mockedExecuteOptimization).toHaveBeenCalledTimes(1);

    resolveResponse!(optimizationSuccessResponse());
    await flushPromises();
    expect(mockedGetExecution).toHaveBeenCalledWith(executionId);

    const result = wrapper.get("[data-test='optimization-results-s3']").text();
    expect(result).toContain("模型优化结果");
    expect(result).toContain("0.7314");
    expect(result).not.toContain("73.14%");
    expect(result).toContain("model-optimized-1");
    expect(result).toContain("window_size");
    expect(result).toContain("nk");
    expect(wrapper.find("[data-test='execute-optimization-s3']").exists()).toBe(false);
    expect(wrapper.find("[data-test='execute-evaluation-s4']").exists()).toBe(true);
    expect(mockedExecuteEvaluation).not.toHaveBeenCalled();
  });

  it("renders a persisted HTTP 200 optimization failure without result data or evaluation", async () => {
    mockedChat.mockResolvedValue(optimizationRunningResponse());
    mockedExecuteOptimization.mockResolvedValue({
      ...optimizationSuccessResponse(),
      workflow_status: "FAILED",
      step_status: "FAILED",
      result_payload: {},
      error_code: "OPTIMIZATION_STUDY_FAILED",
      error_message: "正式模型寻优失败。",
      processing_run_ids: [],
    });
    const wrapper = mountView();
    await submitChat(wrapper);

    await wrapper.get("[data-test='execute-optimization-s3']").trigger("click");
    await flushPromises();

    expect(wrapper.get("[data-test='optimization-error-s3']").text()).toContain("正式模型寻优失败。");
    expect(wrapper.find("[data-test='optimization-results-s3']").exists()).toBe(false);
    expect(wrapper.find("[data-test='execute-evaluation-s4']").exists()).toBe(false);
  });
});
const waitingSnapshot = (
  runId: string | null = copilotRunId,
  snapshotExecutionId = executionId
): CopilotExecutionSnapshot => ({
  execution_id: snapshotExecutionId,
  copilot_run_id: runId,
  dataset_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  initial_version_id: versionId,
  current_version_id: versionId,
  planner_source: "rule_based",
  workflow_status: "WAITING_CONFIRMATION",
  current_step_id: "s2",
  pending_confirmation_step_id: "s2",
  plan: {
    goal: "恢复持久化 Agent Execution",
    dataset_id: null,
    steps: [
      {
        step_id: "s1",
        tool: "fit_arx",
        depends_on: [],
        parameters: {},
        requires_confirmation: false,
        status: "pending",
      },
      {
        step_id: "s2",
        tool: "export_dataset",
        depends_on: ["s1"],
        parameters: { selected: ["u1", "y"] },
        requires_confirmation: true,
        status: "pending",
      },
    ],
    stop_conditions: [],
    assumptions: ["snapshot is authoritative"],
  },
  artifacts: {},
  error_code: null,
  error_message: null,
  created_at: "2026-08-28T00:00:00Z",
  updated_at: "2026-08-28T00:01:00Z",
  finished_at: null,
  step_runs: [
    {
      step_id: "s1",
      sequence: 1,
      tool: "fit_arx",
      status: "SUCCEEDED",
      requires_confirmation: false,
      confirmation_status: "NOT_REQUIRED",
      attempt_count: 1,
      source_version_id: versionId,
      result_version_id: null,
      input_payload: { depends_on: [], parameters: {} },
      result_payload: { model_id: "model-from-snapshot" },
      processing_run_ids: ["run-fit"],
      error_code: null,
      error_message: null,
      started_at: "2026-08-28T00:00:00Z",
      finished_at: "2026-08-28T00:00:10Z",
    },
    {
      step_id: "s2",
      sequence: 2,
      tool: "export_dataset",
      status: "WAITING_CONFIRMATION",
      requires_confirmation: true,
      confirmation_status: "PENDING",
      attempt_count: 0,
      source_version_id: versionId,
      result_version_id: null,
      input_payload: {
        depends_on: ["s1"],
        parameters: { selected: ["u1", "y"] },
        confirmation_payload: { source: "persisted-step-input" },
      },
      result_payload: {},
      processing_run_ids: [],
      error_code: null,
      error_message: null,
      started_at: null,
      finished_at: null,
    },
  ],
});

const completedSnapshot = (): CopilotExecutionSnapshot => {
  const snapshot = waitingSnapshot();
  snapshot.workflow_status = "SUCCEEDED";
  snapshot.current_step_id = null;
  snapshot.pending_confirmation_step_id = null;
  snapshot.finished_at = "2026-08-28T00:02:00Z";
  snapshot.step_runs[1] = {
    ...snapshot.step_runs[1],
    status: "SUCCEEDED",
    confirmation_status: "APPROVED",
    result_payload: { export_id: "export-from-snapshot" },
    processing_run_ids: ["run-export"],
    finished_at: "2026-08-28T00:02:00Z",
  };
  return snapshot;
};

describe("CopilotView execution resume", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    window.localStorage.clear();
    for (const key of Object.keys(routeQuery)) delete routeQuery[key];
    routerReplace.mockResolvedValue(undefined);
  });

  it("persists only the execution UUID and replaces the URL after chat", async () => {
    routeQuery.dataset_id = "preserved-dataset";
    mockedChat.mockResolvedValue(waitingResponse());
    const wrapper = mountView();

    await submitChat(wrapper);

    expect(useCopilotExecutionStore().activeExecutionId).toBe(executionId);
    expect(window.localStorage.getItem(COPILOT_ACTIVE_EXECUTION_STORAGE_KEY)).toBe(executionId);
    expect(window.localStorage.length).toBe(1);
    expect(routerReplace).toHaveBeenCalledWith({
      query: { dataset_id: "preserved-dataset", execution_id: executionId },
    });
  });

  it("uses URL execution_id before a stored execution and hydrates persisted plan and steps", async () => {
    const storedExecutionId = "99999999-9999-4999-8999-999999999999";
    window.localStorage.setItem(COPILOT_ACTIVE_EXECUTION_STORAGE_KEY, storedExecutionId);
    routeQuery.execution_id = executionId;
    mockedGetExecution.mockResolvedValue(waitingSnapshot());

    const wrapper = mountView();
    await flushPromises();

    expect(mockedGetExecution).toHaveBeenCalledTimes(1);
    expect(mockedGetExecution).toHaveBeenCalledWith(executionId);
    expect(useCopilotExecutionStore().activeExecutionId).toBe(executionId);
    expect(window.localStorage.getItem(COPILOT_ACTIVE_EXECUTION_STORAGE_KEY)).toBe(executionId);
    expect(wrapper.get('[data-test="workflow-status"]').text()).toContain("WAITING_CONFIRMATION");
    expect(wrapper.get('[data-test="arx-model-id-s1"]').text()).toContain("model-from-snapshot");
    expect(wrapper.get('[data-test="confirm-actions-s2"]').exists()).toBe(true);
  });

  it("restores lag recommendations from a waiting confirmation snapshot", async () => {
    routeQuery.execution_id = executionId;
    const snapshot = waitingSnapshot();
    snapshot.plan.steps[1] = {
      ...snapshot.plan.steps[1],
      tool: "apply_lag_compensation",
      requires_confirmation: true,
    };
    snapshot.step_runs[1] = {
      ...snapshot.step_runs[1],
      tool: "apply_lag_compensation",
      result_payload: { recommended_lag_map: { u1: 4, u2: 9 } },
    };
    mockedGetExecution.mockResolvedValue(snapshot);

    const wrapper = mountView();
    await flushPromises();
    await wrapper.get('[data-test="edit-lag-s2"]').trigger("click");

    expect(wrapper.get('[data-test="lag-recommendation-s2"]').text()).toContain(
      "Delay Analyze 建议： u1:4; u2:9"
    );
    expect((wrapper.get('[data-test="lag-variable-0"]').element as HTMLSelectElement).value).toBe("u1");
    expect((wrapper.get('[data-test="lag-value-0"]').element as HTMLInputElement).value).toBe("4");
  });
  it("falls back to the UUID-only store when the URL has no execution_id", async () => {
    window.localStorage.setItem(COPILOT_ACTIVE_EXECUTION_STORAGE_KEY, executionId);
    mockedGetExecution.mockResolvedValue(waitingSnapshot());

    const wrapper = mountView();
    await flushPromises();

    expect(mockedGetExecution).toHaveBeenCalledWith(executionId);
    expect(routerReplace).toHaveBeenCalledWith({ query: { execution_id: executionId } });
    expect(wrapper.get('[data-test="execution-id"]').text()).toContain(executionId);
  });

  it("continues the existing confirmation contract after restoring a linked execution", async () => {
    routeQuery.execution_id = executionId;
    mockedGetExecution
      .mockResolvedValueOnce(waitingSnapshot())
      .mockResolvedValueOnce(completedSnapshot());
    mockedConfirm.mockResolvedValue({
      copilot_run_id: copilotRunId,
      confirmation_id: "s2",
      decision: "approved",
      execution_id: executionId,
      workflow_status: "SUCCEEDED",
      current_version_id: versionId,
      current_step_id: null,
      pending_confirmation_step_id: null,
      step_id: "s2",
      step_status: "SUCCEEDED",
      confirmation_status: "APPROVED",
      task: null,
    });
    const wrapper = mountView();
    await flushPromises();

    await wrapper.get('[data-test="approve-s2"]').trigger("click");
    await flushPromises();

    expect(mockedConfirm).toHaveBeenCalledWith(expect.objectContaining({
      copilot_run_id: copilotRunId,
      execution_id: executionId,
      step_id: "s2",
    }));
    expect(mockedGetExecution).toHaveBeenCalledTimes(2);
    expect(wrapper.get('[data-test="workflow-status"]').text()).toContain("SUCCEEDED");
  });

  it("shows historical waiting executions but disables confirmation when run linkage is null", async () => {
    routeQuery.execution_id = executionId;
    mockedGetExecution.mockResolvedValue(waitingSnapshot(null));

    const wrapper = mountView();
    await flushPromises();

    expect(wrapper.get('[data-test="historical-confirmation-unavailable"]').text()).toContain(
      "缺少继续确认所需的 Copilot run 关联"
    );
    expect(wrapper.find('[data-test="confirm-actions-s2"]').exists()).toBe(false);
    expect(wrapper.get('[data-test="historical-confirmation-disabled"]').attributes("disabled")).toBeDefined();
    expect(mockedConfirm).not.toHaveBeenCalled();
  });

  it("clears a missing execution UUID and returns to a usable new-task state", async () => {
    routeQuery.execution_id = executionId;
    routeQuery.dataset_id = "preserved-dataset";
    window.localStorage.setItem(COPILOT_ACTIVE_EXECUTION_STORAGE_KEY, executionId);
    mockedGetExecution.mockRejectedValue(
      new ApiError("AGENT_EXECUTION_NOT_FOUND", "未找到指定的 Agent 执行记录。", "request-1")
    );

    const wrapper = mountView();
    await flushPromises();

    expect(wrapper.get('[data-test="resume-notice"]').text()).toContain("已清除失效的恢复标识");
    expect(useCopilotExecutionStore().activeExecutionId).toBeNull();
    expect(window.localStorage.getItem(COPILOT_ACTIVE_EXECUTION_STORAGE_KEY)).toBeNull();
    expect(routerReplace).toHaveBeenCalledWith({ query: { dataset_id: "preserved-dataset" } });
    expect(wrapper.find('[data-test="execution-id"]').exists()).toBe(false);
    expect(wrapper.get('[data-test="copilot-prompt"]').exists()).toBe(true);
  });

  it("rehydrates after unmount without relying on the previous component instance", async () => {
    routeQuery.execution_id = executionId;
    mockedGetExecution.mockResolvedValue(waitingSnapshot());
    const first = mountView();
    await flushPromises();
    first.unmount();

    delete routeQuery.execution_id;
    const second = mountView();
    await flushPromises();

    expect(mockedGetExecution).toHaveBeenCalledTimes(2);
    expect(routerReplace).toHaveBeenCalledWith({ query: { execution_id: executionId } });
    expect(second.get('[data-test="workflow-status"]').text()).toContain("WAITING_CONFIRMATION");
  });
});