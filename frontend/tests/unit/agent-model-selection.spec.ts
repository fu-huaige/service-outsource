import { DOMWrapper, flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { createPinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ApprovalCard from "../../src/components/workspace/ApprovalCard.vue";
import ModelSelectionFields from "../../src/components/workspace/ModelSelectionFields.vue";
import WorkspaceView from "../../src/views/WorkspaceView.vue";
import type {
  CopilotExecutionSnapshot, CopilotExecutionStepSnapshot, CopilotModelExecutionData, ModelCandidate, ModelRecommendationRequest,
  ModelRecommendationResult, RecommendationModelType,
} from "../../src/types/api";

const api = vi.hoisted(() => ({
  chatWithCopilot: vi.fn(),
  getCopilotExecution: vi.fn(),
  confirmCopilotStep: vi.fn(),
  executeModelEvaluation: vi.fn(),
  executePipelineOptimization: vi.fn(),
  executeConfirmedModel: vi.fn(),
  getConfirmedModelExecution: vi.fn(),
}));
const route = vi.hoisted(() => ({ params: { executionId: "selection-run" }, query: {} }));
const messages = vi.hoisted(() => ({ warning: vi.fn(), error: vi.fn() }));
const getDatasetVersions = vi.hoisted(() => vi.fn());
vi.mock("../../src/api/copilot", () => api);
vi.mock("../../src/api/datasets", () => ({ listDatasets: vi.fn(async () => ({ items: [] })), getDatasetVersions }));
vi.mock("vue-router", () => ({ useRoute: () => route, useRouter: () => ({ push: vi.fn() }) }));
vi.mock("element-plus", async importOriginal => ({
  ...await importOriginal<typeof import("element-plus")>(), ElMessage: messages,
}));

const forecast = { target_window_length: 32, exogenous_window_length: 24, prediction_length: 3 };
const source: ModelRecommendationResult["source"] = {
  dataset_id: "data", dataset_version_id: "version", csv_sha256: "a".repeat(64),
  experiment_spec_hash: "b".repeat(64), partition: "train",
  train_rows: { ranges: [{ start: 0, stop: 60 }] }, target_name: "y", feature_names: ["u1", "u2"],
};

function candidate(model: RecommendationModelType, rank: number | null, parameters: Record<string, unknown>): ModelCandidate {
  return {
    model_type_id: model, model_name: model === "timexer" ? "TimeXer" : model.toUpperCase(),
    recommendation_rank: rank, eligibility_status: "eligible", suitability: "compatible",
    reasons: ["后端推荐理由", "额外证据"], limitations: ["后端限制"],
    actual_parameters: parameters, training_sample_count: 60,
    prediction_horizon: model === "timexer" ? 3 : 1,
    forecast_spec: model === "timexer" ? forecast : null,
    evidence: { parameter_source: "defaults", horizon_source: "default", anchor_rows: null, history_lengths: {}, target_offsets: [], sample_rule: null },
  };
}

function recommendation(): ModelRecommendationResult {
  return {
    source,
    profile: { ...source, sample_count: 60, feature_count: 2, sampling_status: "uniform", continuous_run_count: 1 },
    candidates: [
      candidate("pls", 3, { n_components: 2, scale: true }),
      candidate("tcn", 2, { window_length: 32, epochs: 30, hidden_channels: 32 }),
      candidate("xgboost", 1, { max_depth: 4, learning_rate: 0.05, num_boost_round: 200 }),
      candidate("timexer", null, { ...forecast, prediction_length: 1, patch_length: 8, embedding_dim: 32 }),
    ].map(item => item.model_type_id === "timexer"
      ? { ...item, prediction_horizon: 1, forecast_spec: { ...forecast, prediction_length: 1 } } : item),
    recommended_models: ["xgboost", "tcn", "pls"],
    excluded_models: {},
    rule_version: "model-recommendation-1",
    summary: "推荐已生成",
  };
}

function panel(result = recommendation()) {
  return mount(ModelSelectionFields, { attachTo: document.body, props: { recommendation: result, recommendationStepId: "recommend" } });
}

const selection = (wrapper: ReturnType<typeof panel>) => wrapper.emitted("change")?.at(-1)?.[0];
const modelSelect = '[data-test="model-select"]';
const recommended = '[data-test="recommended-model"]';

async function openModelMenu(wrapper: VueWrapper) {
  const trigger = wrapper.get(modelSelect);
  if (trigger.attributes("aria-expanded") !== "true") {
    await trigger.trigger("keydown", { key: "ArrowDown" });
    await flushPromises();
  }
  const listbox = document.getElementById(trigger.attributes("aria-controls") ?? "");
  expect(listbox).not.toBeNull();
  return new DOMWrapper(listbox!);
}

async function chooseModel(wrapper: VueWrapper, model: RecommendationModelType) {
  const menu = await openModelMenu(wrapper);
  await menu.get('[data-model="' + model + '"]').trigger("keydown", { key: "Enter" });
  await flushPromises();
}

describe("Agent model selection fields", () => {
  it("defaults to the backend first choice and switches without altering the snapshot", async () => {
    const result = recommendation();
    const saved = structuredClone(result);
    const wrapper = panel(result);
    const trigger = wrapper.get(modelSelect);
    expect(trigger.text()).toBe("XGBOOST");
    expect(trigger.attributes("role")).toBe("combobox");
    expect(wrapper.find("select").exists()).toBe(false);
    const menu = await openModelMenu(wrapper);
    expect(menu.findAll('[role="option"]').map(option => option.attributes("data-model")))
      .toEqual(["xgboost", "tcn", "pls", "timexer"]);
    expect(menu.get('[data-model="xgboost"]').attributes("data-state")).toBe("checked");
    expect(wrapper.get(recommended).text()).toContain("Agent 推荐 XGBOOST");
    expect(wrapper.get(recommended).text()).toContain("后端推荐理由");
    expect(selection(wrapper)).toMatchObject({
      selected_model_type_id: "xgboost", selection_source: "agent_recommendation",
    });

    const first = menu.get<HTMLElement>('[data-model="xgboost"]');
    first.element.focus();
    await first.trigger("keydown", { key: "ArrowDown" });
    const tcn = menu.get('[data-model="tcn"]');
    await vi.waitFor(() => expect(document.activeElement).toBe(tcn.element));
    await tcn.trigger("keydown", { key: "Enter" });
    await flushPromises();
    expect(selection(wrapper)).toMatchObject({
      selected_model_type_id: "tcn", selection_source: "manual",
      selected_parameters: { window_length: 32, epochs: 30, hidden_channels: 32 },
      experiment_spec_hash: source.experiment_spec_hash,
    });
    expect(wrapper.get(recommended).text()).toContain("XGBOOST");
    await chooseModel(wrapper, "timexer");
    expect(selection(wrapper)).toMatchObject({ selected_model_type_id: "timexer", selection_source: "manual" });
    expect(result).toEqual(saved);
    expect(wrapper.find('input[type="number"]').exists()).toBe(false);
    await chooseModel(wrapper, "xgboost");
    expect(selection(wrapper)).toMatchObject({ selection_source: "agent_recommendation" });
    await wrapper.setProps({ disabled: true });
    expect(wrapper.get(modelSelect).attributes("disabled")).toBeDefined();
    wrapper.unmount();
  });

  it("excludes unavailable models from the dropdown and displays their backend reasons", async () => {
    const result = recommendation();
    result.candidates[1] = { ...result.candidates[1]!, eligibility_status: "excluded", reasons: ["不满足窗口约束"] };
    result.candidates[3] = { ...result.candidates[3]!, eligibility_status: "unknown", reasons: ["采样尚未核实"] };
    const wrapper = panel(result);
    const menu = await openModelMenu(wrapper);
    expect(menu.findAll('[role="option"]').map(option => option.attributes("data-model")))
      .toEqual(["xgboost", "pls"]);
    expect(wrapper.text()).toContain("不满足窗口约束");
    expect(wrapper.text()).toContain("采样尚未核实");
    await menu.get('[data-model="xgboost"]').trigger("keydown", { key: "Escape" });
    await flushPromises();
    expect(wrapper.get(modelSelect).attributes("aria-expanded")).toBe("false");
    expect(selection(wrapper)).toMatchObject({ selected_model_type_id: "xgboost" });
    wrapper.unmount();
  });

  it("passes through TimeXer parameters and forecast without an editable form", () => {
    const result = recommendation();
    result.candidates = [candidate("timexer", 1, { ...forecast, patch_length: 8 })];
    result.recommended_models = ["timexer"];
    const wrapper = panel(result);
    expect(wrapper.get(modelSelect).text()).toBe("TimeXer");
    expect(wrapper.get('[data-test="selected-model-fit"]').text()).toContain("预测 3 步");
    expect(selection(wrapper)).toMatchObject({
      selection_source: "agent_recommendation", forecast_spec: forecast,
      selected_parameters: { ...forecast, patch_length: 8 },
    });
    wrapper.unmount();
  });

  it("discards a draft selection when the Spec identity changes", async () => {
    const wrapper = panel();
    await chooseModel(wrapper, "pls");
    const result = recommendation();
    result.source = { ...result.source, experiment_spec_hash: "c".repeat(64) };
    await wrapper.setProps({ recommendation: result });
    expect(wrapper.get(modelSelect).text()).toBe("XGBOOST");
    expect(selection(wrapper)).toMatchObject({ experiment_spec_hash: result.source.experiment_spec_hash });
    wrapper.unmount();
  });
});
function step(stepId: string, tool: string, fields: Partial<CopilotExecutionStepSnapshot>): CopilotExecutionStepSnapshot {
  return {
    step_id: stepId, sequence: 1, tool, status: "SUCCEEDED",
    requires_confirmation: false, confirmation_status: "NOT_REQUIRED", attempt_count: 1,
    input_payload: {}, result_payload: {}, processing_run_ids: [], ...fields,
  };
}

function snapshot(state: "pending" | "locked" | "rejected"): CopilotExecutionSnapshot {
  const review = state === "pending";
  const locked = state === "locked";
  return {
    execution_id: "selection-run", copilot_run_id: "copilot-run", dataset_id: source.dataset_id,
    initial_version_id: "version", current_version_id: "version", planner_source: "rule_based",
    workflow_status: review ? "WAITING_CONFIRMATION" : locked ? "SUCCEEDED" : "CANCELLED",
    current_step_id: review ? "choose" : null, pending_confirmation_step_id: review ? "choose" : null,
    plan: {
      goal: "推荐模型", dataset_id: source.dataset_id, stop_conditions: [], assumptions: [],
      steps: [
        { step_id: "recommend", tool: "recommend_models", depends_on: [], parameters: {}, requires_confirmation: false, status: "completed" },
        { step_id: "choose", tool: "confirm_model_selection", depends_on: ["recommend"], parameters: {}, requires_confirmation: true,
          status: review ? "waiting_confirmation" : locked ? "completed" : "cancelled" },
      ],
    },
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:01Z",
    artifacts: {},
    step_runs: [
      step("recommend", "recommend_models", { result_payload: { recommendation: recommendation() } }),
      step("choose", "confirm_model_selection", {
        sequence: 2, requires_confirmation: true,
        status: review ? "WAITING_CONFIRMATION" : locked ? "SUCCEEDED" : "CANCELLED",
        confirmation_status: review ? "PENDING" : locked ? "APPROVED" : "REJECTED",
        input_payload: { recommendation_step_id: "recommend" },
        result_payload: locked ? { model_selection: {
          model_type_id: "pls", parameters: { n_components: 1, scale: true }, dataset_version_id: "version",
          selection_source: "manual", forecast_spec: null, confirmation_status: "APPROVED",
        } } : {},
      }),
    ],
  };
}

const trainingRefs = {
  selection_execution_id: "selection-run", copilot_run_id: "copilot-run", confirmed_selection_step_id: "choose",
};

function trainingStatus(overrides: Partial<CopilotModelExecutionData> = {}): CopilotModelExecutionData {
  return {
    execution_id: "child", execution_status: "pending", training_status: "pending",
    dispatch_status: "pending", manifest_status: "pending", model_id: null, training_run_id: null,
    evaluation_run_id: null, evaluation_status: "pending", comparison_status: "pending",
    training_error: null, evaluation_error: null, comparison_reason: null, ...overrides,
  };
}

function workspace() {
  return mount(WorkspaceView, {
    attachTo: document.body,
    global: {
      plugins: [createPinia()],
      stubs: { AgentComposer: true, ArtifactWorkbench: true, RouterLink: true },
    },
  });
}

it("keeps the original ARX override request in the existing approval card", async () => {
  const wrapper = mount(ApprovalCard, { props: {
    executionId: "arx-execution", copilotRunId: "arx-copilot",
    stepRun: step("fit", "fit_arx", {
      requires_confirmation: true, confirmation_status: "PENDING",
      input_payload: { arx_structure_recommendation: { recommended_na: 2, recommended_nb: { u1: 3 } } },
    }),
  } });
  const inputs = wrapper.findAll('input[type="number"]');
  await inputs[0]!.setValue("4");
  await inputs[1]!.setValue("5");
  await wrapper.get('[data-test="approve-fit"]').trigger("click");
  expect(wrapper.emitted("confirm")?.[0]).toEqual([{
    execution_id: "arx-execution", copilot_run_id: "arx-copilot", confirmation_id: "fit", step_id: "fit",
    approved: true, arx_structure_overrides: { na: 4, nb: { u1: 5 } },
  }]);
  wrapper.unmount();
});

describe("Agent model approval through WorkspaceView", () => {
  beforeEach(() => {
    route.params.executionId = "selection-run";
    localStorage.clear();
    sessionStorage.clear();
    vi.clearAllMocks();
    api.getConfirmedModelExecution.mockResolvedValue(null);
    api.getCopilotExecution.mockResolvedValue(snapshot("pending"));
  });

  it("sends the structured Chat request and reads the rule-based response using its step reference", async () => {
    route.params.executionId = "";
    const result = recommendation();
    const persisted = snapshot("pending");
    persisted.step_runs[0]!.result_payload = {};
    api.getCopilotExecution.mockResolvedValueOnce(persisted);
    api.chatWithCopilot.mockResolvedValueOnce({
      execution_id: "selection-run", plan_source: "rule_based", llm_fallback_reason: "unavailable",
      step_runs: [{ step_id: "recommend", tool: "recommend_models", result: { recommendation: result } }],
    });
    const body: ModelRecommendationRequest = {
      goal: "auto",
      experiment_spec: {
        spec_version: 1, task_type: "supervised_regression", dataset_id: "data",
        dataset_version_id: "version", dataset_version_sha256: source.csv_sha256,
        row_count: 100, target_column: "y", input_columns: ["u1", "u2"],
        time_axis: { column: null, sample_period_seconds: null, sampling_status: "unknown", timestamp_policy: "preserve_source" },
        feature_spec: { kind: "tabular", prediction_horizon: 1 },
        continuous_runs: [{ start: 0, stop: 100 }],
        split: {
          train: [{ start: 0, stop: 60 }], validation: [{ start: 60, stop: 80 }], test: [{ start: 80, stop: 100 }],
        },
        training_selection: { mode: "full_train" },
        evaluation: { scopes: ["validation"], prediction_modes: ["prediction"] },
      },
    };
    const wrapper = workspace();
    wrapper.getComponent({ name: "AgentComposer" }).vm.$emit("submit", {
      message: "推荐模型", datasetId: "data", versionId: "version", recommendationRequest: body,
    });
    await flushPromises();

    expect(api.chatWithCopilot).toHaveBeenCalledWith({
      message: "推荐模型", dataset_id: "data", active_version_id: "version", recommendation_request: body,
    });
    expect(wrapper.get(modelSelect).text()).toBe("XGBOOST");
    expect(wrapper.get('[data-test="approve-choose"]').attributes("disabled")).toBeUndefined();
    wrapper.unmount();
  });

  it("confirms the chosen model with automatic dispatch and blocks duplicate clicks", async () => {
    const wrapper = workspace();
    await flushPromises();
    const confirm = wrapper.get('[data-test="approve-choose"]');
    expect(confirm.attributes("disabled")).toBeUndefined();
    expect(confirm.text()).toBe("确认并开始训练");
    await chooseModel(wrapper, "pls");
    let resolveConfirm!: () => void;
    api.confirmCopilotStep.mockReturnValueOnce(new Promise<void>(resolve => { resolveConfirm = resolve; }));
    await confirm.trigger("click");
    await confirm.trigger("click");
    expect(api.confirmCopilotStep).toHaveBeenCalledTimes(1);
    expect(api.confirmCopilotStep).toHaveBeenCalledWith({
      execution_id: "selection-run", copilot_run_id: "copilot-run", step_id: "choose", confirmation_id: "choose", approved: true,
      dispatch_training: true,
      model_selection: {
        recommendation_step_id: "recommend", selected_model_type_id: "pls",
        selected_parameters: { n_components: 2, scale: true }, selection_source: "manual",
        dataset_id: source.dataset_id, dataset_version_id: source.dataset_version_id,
        csv_sha256: source.csv_sha256, experiment_spec_hash: source.experiment_spec_hash, forecast_spec: null,
      },
    });
    api.getCopilotExecution.mockResolvedValue(snapshot("locked"));
    api.getConfirmedModelExecution.mockResolvedValue(trainingStatus());
    resolveConfirm();
    await flushPromises();
    expect(wrapper.get('[data-test="locked-model-name"]').text()).toBe("PLS");
    expect(wrapper.text()).toContain("模型已锁定");
    const panel = wrapper.get('[data-test="agent-model-training"]');
    expect(panel.text()).toContain("等待派发");
    expect(panel.find("button").exists()).toBe(false);
    expect(api.getConfirmedModelExecution).toHaveBeenCalledWith(trainingRefs);
    expect(api.executeConfirmedModel).not.toHaveBeenCalled();
    expect(api.executeModelEvaluation).not.toHaveBeenCalled();
    expect(api.executePipelineOptimization).not.toHaveBeenCalled();
    wrapper.unmount();

    const restored = workspace();
    await flushPromises();
    expect(restored.text()).toContain("n_components = 1");
    expect(restored.text()).toContain("等待派发");
    expect(restored.find('[data-test="approve-choose"]').exists()).toBe(false);
    restored.unmount();
  });

  it("submits the final-version Spec within the original execution", async () => {
    const paused = snapshot("pending");
    paused.initial_version_id = "before-preprocessing";
    paused.pending_confirmation_step_id = "recommend";
    paused.current_step_id = "recommend";
    paused.step_runs.unshift(step("profile", "profile_dataset", { source_version_id: "before-preprocessing" }));
    paused.step_runs[1] = step("recommend", "recommend_models", {
      status: "WAITING_CONFIRMATION", confirmation_status: "PENDING", requires_confirmation: true,
    });
    paused.step_runs[2] = { ...paused.step_runs[2]!, status: "PENDING" };
    getDatasetVersions.mockResolvedValueOnce({ dataset_id: "data", nodes: [{
      id: "version", name: "处理后版本", row_count: 100, input_columns: ["u1", "u2"],
      output_column: "y", sha256: source.csv_sha256,
    }] });
    api.getCopilotExecution.mockResolvedValueOnce(paused);
    const wrapper = workspace();
    await flushPromises();
    expect(wrapper.text()).toContain("数据画像");
    const spec = wrapper.get('[data-test="agent-model-spec"]');
    const fallback = spec.get<HTMLDetailsElement>('[data-test="model-spec-fallback"]');
    expect(fallback.element.open).toBe(false);
    fallback.element.open = true;
    const send = fallback.get('button.stream-action-card__btn');
    expect(send.attributes("disabled")).toBeDefined();
    await spec.get('[data-test="modeling-input"]').setValue(true);
    for (const [key, value] of Object.entries({
      continuous: "0-100", train: "0-60", validation: "60-80", test: "80-100",
    })) await spec.get('[data-test="modeling-' + key + '"]').setValue(value);

    api.confirmCopilotStep.mockResolvedValueOnce({});
    await send.trigger("click");
    await flushPromises();
    expect(api.confirmCopilotStep).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({
      execution_id: "selection-run", step_id: "recommend", approved: true,
      recommendation_request: expect.objectContaining({
        experiment_spec: expect.objectContaining({
          dataset_version_id: "version", dataset_version_sha256: source.csv_sha256,
          input_columns: ["u1"], target_column: "y",
        }),
      }),
    }));
    expect(api.chatWithCopilot).not.toHaveBeenCalled();
    expect(api.executeConfirmedModel).not.toHaveBeenCalled();
    expect(wrapper.get(modelSelect).text()).toBe("XGBOOST");
    wrapper.unmount();
  });

  it("restores the persisted leakage warning and keeps model choice enabled", async () => {
    const state = snapshot("pending");
    state.step_runs[0]!.result_payload!.recommendation!.leakage = { status: "unknown", evidence: [] };
    api.getCopilotExecution.mockResolvedValue(state);
    const first = workspace();
    await flushPromises();
    expect(first.get('[data-test="recommendation-leakage"]').text()).toContain("数据泄漏风险尚未核实");
    await chooseModel(first, "pls");
    first.unmount();
    const restored = workspace();
    await flushPromises();
    expect(restored.get('[data-test="recommendation-leakage"]').exists()).toBe(true);
    expect(restored.get(modelSelect).text()).toBe("XGBOOST");
    expect(restored.get('[data-test="approve-choose"]').attributes("disabled")).toBeUndefined();
    restored.unmount();
  });

  it("blocks approval and shows reasons when no model is eligible", async () => {
    const state = snapshot("pending");
    const result = state.step_runs[0]!.result_payload!.recommendation!;
    result.recommended_models = [];
    result.candidates = result.candidates.map(item => ({
      ...item,
      eligibility_status: "excluded",
      reasons: ["有效训练样本不足"],
    }));
    api.getCopilotExecution.mockResolvedValue(state);
    const wrapper = workspace();
    await flushPromises();
    expect(wrapper.get('[data-test="no-recommended-model"]').text()).toContain("没有可推荐模型");
    expect(wrapper.text()).toContain("有效训练样本不足");
    expect(wrapper.find(modelSelect).exists()).toBe(false);
    const approve = wrapper.get('[data-test="approve-choose"]');
    expect(approve.attributes("disabled")).toBeDefined();
    await approve.trigger("click");
    expect(api.confirmCopilotStep).not.toHaveBeenCalled();
    expect(api.executeConfirmedModel).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("confirms original order for the final CSV identity in the same task", async () => {
    const paused = snapshot("pending");
    paused.pending_confirmation_step_id = paused.current_step_id = "recommend";
    paused.step_runs[0] = step("recommend", "recommend_models", {
      status: "WAITING_CONFIRMATION", confirmation_status: "PENDING", requires_confirmation: true,
      result_payload: { spec_requirement: { field: "row_order" } },
    });
    paused.step_runs[1]!.status = "PENDING";
    getDatasetVersions.mockResolvedValueOnce({ dataset_id: "data", nodes: [{
      id: "version", name: "最终版本", row_count: 1000, sha256: source.csv_sha256,
    }] });
    api.getCopilotExecution.mockResolvedValueOnce(paused);
    api.confirmCopilotStep.mockResolvedValueOnce({});
    const wrapper = workspace();
    await flushPromises();
    expect(wrapper.find('[data-test="modeling-input"]').exists()).toBe(false);
    await wrapper.get('[data-test="confirm-model-row-order"]').trigger("click");
    await flushPromises();
    expect(api.confirmCopilotStep).toHaveBeenCalledExactlyOnceWith({
      execution_id: "selection-run", copilot_run_id: "copilot-run", confirmation_id: "recommend",
      step_id: "recommend", approved: true,
      row_order_confirmation: { dataset_version_id: "version", csv_sha256: source.csv_sha256 },
    });
    expect(api.chatWithCopilot).not.toHaveBeenCalled();
    expect(api.executeConfirmedModel).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("keeps polling pending dispatch and shows persisted Worker transitions", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    api.getCopilotExecution.mockResolvedValue(snapshot("locked"));
    api.getConfirmedModelExecution
      .mockResolvedValueOnce(trainingStatus())
      .mockResolvedValueOnce(trainingStatus({ dispatch_status: "queued" }))
      .mockResolvedValueOnce(trainingStatus({ dispatch_status: "started", execution_status: "running", training_status: "running" }))
      .mockResolvedValueOnce(trainingStatus({ dispatch_status: "started", execution_status: "failed", training_status: "failed", training_error: "PLATFORM_TRAINING_REJECTED" }));
    const wrapper = workspace();
    try {
      await flushPromises();
      const panel = wrapper.get('[data-test="agent-model-training"]');
      expect(panel.text()).toContain("等待派发");
      expect(panel.findAll("ol li")).toHaveLength(4);
      expect(panel.text()).not.toMatch(/\d+%/);
      for (const label of ["已派发", "正在训练", "训练失败"]) {
        await vi.advanceTimersByTimeAsync(2000);
        expect(panel.text()).toContain(label);
      }
      expect(panel.text()).toContain("训练服务拒绝了本次输入");
      expect(panel.get("details").text()).toContain("PLATFORM_TRAINING_REJECTED");
      await vi.advanceTimersByTimeAsync(4000);
      expect(api.getConfirmedModelExecution).toHaveBeenCalledTimes(4);
      expect(api.confirmCopilotStep).not.toHaveBeenCalled();
      expect(api.executeConfirmedModel).not.toHaveBeenCalled();
    } finally {
      wrapper.unmount();
      vi.useRealTimers();
    }
  });

  it("looks up a committed training intent after the confirm response is lost", async () => {
    const wrapper = workspace();
    await flushPromises();
    await chooseModel(wrapper, "timexer");
    api.confirmCopilotStep.mockRejectedValueOnce(new Error("connection dropped"));
    api.getCopilotExecution.mockResolvedValue(snapshot("locked"));
    api.getConfirmedModelExecution.mockResolvedValue(trainingStatus({
      execution_status: "unconfirmed", training_status: "unconfirmed", dispatch_status: "started",
    }));
    await wrapper.get('[data-test="approve-choose"]').trigger("click");
    await flushPromises();
    expect(api.confirmCopilotStep).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({
      dispatch_training: true,
      model_selection: expect.objectContaining({
        selected_model_type_id: "timexer", selection_source: "manual",
        selected_parameters: { ...forecast, prediction_length: 1, patch_length: 8, embedding_dim: 32 },
        forecast_spec: { ...forecast, prediction_length: 1 },
      }),
    }));
    expect(api.getConfirmedModelExecution).toHaveBeenCalledWith(trainingRefs);
    const review = wrapper.get('[data-test="agent-model-training"]');
    expect(review.get('[role="status"]').text()).toBe("待人工核验");
    expect(review.text()).not.toMatch(/执行完成|执行失败/);
    expect(messages.error).not.toHaveBeenCalled();
    expect(api.executeConfirmedModel).not.toHaveBeenCalled();
    wrapper.unmount();

    api.getConfirmedModelExecution.mockResolvedValue(trainingStatus({
      execution_status: "succeeded", training_status: "succeeded", dispatch_status: "started",
      manifest_status: "published", model_id: "real-model", training_run_id: "real-run",
      evaluation_status: "failed", comparison_status: "skipped", evaluation_error: "VALIDATION_BUILD_SAMPLES_FAILED",
    }));
    const restored = workspace();
    await flushPromises();
    const state = restored.get('[data-test="agent-model-training"]').text();
    expect(state).toContain("训练成功");
    expect(state).toContain("评价失败");
    expect(state).toContain("执行失败");
    const details = restored.get<HTMLDetailsElement>('[data-test="training-details"]');
    expect(details.element.open).toBe(false);
    expect(details.get("summary").text()).toBe("执行详情");
    details.element.open = true;
    expect(details.get("dl").text()).toContain("child");
    expect(details.get("dl").text()).toContain("real-model");
    expect(details.get("dl").text()).toContain("real-run");
    expect(details.get("dl").text()).toContain("VALIDATION_BUILD_SAMPLES_FAILED");
    details.element.open = false;
    expect(details.element.open).toBe(false);
    expect(api.confirmCopilotStep).toHaveBeenCalledTimes(1);
    expect(api.executeConfirmedModel).not.toHaveBeenCalled();
    restored.unmount();
  });

  it("keeps all four steps after completion and displays the actual comparison result", async () => {
    api.getCopilotExecution.mockResolvedValue(snapshot("locked"));
    api.getConfirmedModelExecution.mockResolvedValue(trainingStatus({
      execution_status: "succeeded", training_status: "succeeded", dispatch_status: "started",
      manifest_status: "published", evaluation_status: "succeeded", comparison_status: "not_comparable",
    }));
    const wrapper = workspace();
    await flushPromises();
    const card = wrapper.get('[data-test="agent-model-training"]');
    expect(card.get('[role="status"]').text()).toBe("执行完成");
    expect(card.findAll("ol li").map(step => step.attributes("data-state")))
      .toEqual(["succeeded", "succeeded", "succeeded", "skipped"]);
    expect(card.text()).toContain("无可比结果");
    wrapper.unmount();
  });

  it("keeps an uncertain confirmation pending when the server has not committed yet", async () => {
    api.confirmCopilotStep.mockRejectedValueOnce(new Error("request timed out"));
    api.getConfirmedModelExecution.mockRejectedValueOnce(
      Object.assign(new Error("selection not approved"), { code: "MODEL_EXECUTION_SELECTION_INVALID" }),
    );
    const wrapper = workspace();
    await flushPromises();
    await wrapper.get('[data-test="approve-choose"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[data-test="approve-choose"]').attributes("disabled")).toBeDefined();
    const panel = wrapper.get('[data-test="agent-model-training"]');
    expect(panel.text()).toContain("训练状态待核验");
    api.getCopilotExecution.mockResolvedValue(snapshot("locked"));
    api.getConfirmedModelExecution.mockResolvedValue(trainingStatus({ dispatch_status: "queued" }));
    await panel.get("button").trigger("click");
    await flushPromises();
    expect(panel.text()).toContain("已派发");
    expect(api.confirmCopilotStep).toHaveBeenCalledTimes(1);
    expect(api.executeConfirmedModel).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("preserves the draft on a source conflict and shows the persisted rejection", async () => {
    const wrapper = workspace();
    await flushPromises();
    await chooseModel(wrapper, "pls");
    api.confirmCopilotStep.mockRejectedValueOnce(
      Object.assign(new Error("模型选择来源冲突"), { code: "MODEL_SELECTION_SOURCE_CHANGED" }),
    );
    api.getConfirmedModelExecution.mockRejectedValueOnce(
      Object.assign(new Error("selection not approved"), { code: "MODEL_EXECUTION_SELECTION_INVALID" }),
    );
    await wrapper.get('[data-test="approve-choose"]').trigger("click");
    await flushPromises();
    expect(messages.error).toHaveBeenCalledWith("模型选择来源冲突");
    expect(wrapper.get(modelSelect).text()).toBe("PLS");
    expect(wrapper.find('[data-test="locked-model-name"]').exists()).toBe(false);
    api.confirmCopilotStep.mockResolvedValueOnce({});
    api.getCopilotExecution.mockResolvedValue(snapshot("rejected"));
    await wrapper.get('[data-test="reject-choose"]').trigger("click");
    await flushPromises();
    expect(api.confirmCopilotStep).toHaveBeenLastCalledWith({
      execution_id: "selection-run", copilot_run_id: "copilot-run", step_id: "choose",
      confirmation_id: "choose", approved: false,
    });
    expect(wrapper.get('[data-test="model-selection-rejected"]').text()).toContain("已拒绝");
    expect(wrapper.find('[data-test="approve-choose"]').exists()).toBe(false);
    wrapper.unmount();
  });
});
