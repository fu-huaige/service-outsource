import { beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia } from "pinia";
import CopilotView from "../../src/views/CopilotView.vue";
import { chatWithCopilot, confirmCopilotStep, validateLagOverrides } from "../../src/api/copilot";
import type { CopilotChatResponse } from "../../src/types/api";

vi.mock("../../src/api/copilot", () => ({
  chatWithCopilot: vi.fn(),
  confirmCopilotStep: vi.fn(),
  validateLagOverrides: vi.fn(),
}));
vi.mock("element-plus", () => ({ ElMessage: { success: vi.fn(), error: vi.fn() } }));

const executionId = "22222222-2222-4222-8222-222222222222";
const copilotRunId = "11111111-1111-4111-8111-111111111111";
const versionId = "33333333-3333-4333-8333-333333333333";

const mockedChat = vi.mocked(chatWithCopilot);
const mockedConfirm = vi.mocked(confirmCopilotStep);
const mockedValidateLag = vi.mocked(validateLagOverrides);

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
        tool: "select_variables",
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
      tool: "select_variables",
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

const mountView = () => mount(CopilotView, { global: { plugins: [createPinia()], stubs } });

async function submitChat(wrapper: ReturnType<typeof mountView>) {
  await wrapper.get('[data-test="active-version"]').setValue(versionId);
  await wrapper.get('[data-test="copilot-prompt"]').setValue("执行并等待确认");
  const submit = wrapper.findAll("button").find((button) => button.text().includes("提交给 Agent"));
  expect(submit).toBeTruthy();
  await submit!.trigger("click");
  await flushPromises();
}

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

    expect(wrapper.get('[data-test="lag-recommendation-s2"]').text()).toContain("u1");
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
  });});
