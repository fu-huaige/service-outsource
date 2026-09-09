import { defineComponent, nextTick } from "vue";
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import ArtifactWorkbench from "../../src/components/artifact/ArtifactWorkbench.vue";
import type { ChartOption } from "../../src/components/ChartContainer.vue";
import type { CopilotExecutionSnapshot } from "../../src/types/api";

const ChartContainerStub = defineComponent({
  name: "ChartContainer",
  props: {
    options: { type: Object, required: true },
    height: { type: String, default: undefined },
  },
  template: '<div data-test="profile-chart" :data-height="height" />',
});

const executionWith = (
  tool: string,
  resultPayload: Record<string, unknown>
): CopilotExecutionSnapshot => ({
  execution_id: "execution-1",
  copilot_run_id: null,
  dataset_id: "dataset-1",
  initial_version_id: "version-0",
  current_version_id: "version-0",
  planner_source: "deterministic",
  workflow_status: "SUCCEEDED",
  current_step_id: null,
  pending_confirmation_step_id: null,
  plan: {
    goal: "test artifact rendering",
    dataset_id: "dataset-1",
    steps: [{
      step_id: "step-1",
      tool,
      depends_on: [],
      parameters: {},
      requires_confirmation: false,
      status: "completed",
    }],
    stop_conditions: [],
    assumptions: [],
  },
  artifacts: {},
  error_code: null,
  error_message: null,
  created_at: "2026-09-09T00:00:00Z",
  updated_at: "2026-09-09T00:00:01Z",
  finished_at: "2026-09-09T00:00:01Z",
  step_runs: [{
    step_id: "step-1",
    sequence: 1,
    tool,
    status: "completed",
    requires_confirmation: false,
    confirmation_status: "NOT_REQUIRED",
    attempt_count: 1,
    source_version_id: "version-0",
    result_version_id: null,
    input_payload: {},
    result_payload: resultPayload,
    processing_run_ids: [],
    error_code: null,
    error_message: null,
    started_at: "2026-09-09T00:00:00Z",
    finished_at: "2026-09-09T00:00:01Z",
  }],
});

const mountWorkbench = async (execution: CopilotExecutionSnapshot) => {
  const wrapper = mount(ArtifactWorkbench, {
    props: { execution },
    global: { stubs: { ChartContainer: ChartContainerStub } },
  });
  await nextTick();
  return wrapper;
};

describe("ArtifactWorkbench profile_dataset rendering", () => {
  it("renders the persisted profile envelope as summary, cards, chart, details, and collapsed raw data", async () => {
    const wrapper = await mountWorkbench(executionWith("profile_dataset", {
      summary: "数据画像完成：1200 个样本，2 个输入变量。",
      result: {
        n_samples: 1200,
        fingerprint: {
          fields: [
            "log_sample_count",
            "input_count",
            "missing_ratio",
            "anomaly_ratio",
            "snr_db_scaled",
            "dynamic_ratio",
            "output_autocorrelation",
            "input_autocorrelation",
            "collinearity_scaled",
            "future_metric",
          ],
          values: {
            log_sample_count: 0.5132,
            input_count: 0.25,
            missing_ratio: 0.02,
            anomaly_ratio: 0.01,
            snr_db_scaled: 0.72,
            dynamic_ratio: 0.42,
            output_autocorrelation: 0.81,
            input_autocorrelation: 0.68,
            collinearity_scaled: 0.36,
            future_metric: "raw-value",
          },
        },
      },
    }));

    expect(wrapper.get('[data-test="profile-artifact-renderer"]').exists()).toBe(true);
    expect(wrapper.get('[data-test="profile-summary"]').text()).toBe(
      "数据画像完成：1200 个样本，2 个输入变量。"
    );
    expect(wrapper.get('[data-test="profile-overview"]').text()).toContain("1,200");
    expect(wrapper.get('[data-test="profile-overview"]').text()).toContain("2.00%");
    expect(wrapper.get('[data-test="profile-overview"]').text()).toContain("1.00%");
    expect(wrapper.get('[data-test="profile-overview"]').text()).toContain("42.00%");
    expect(wrapper.get('[data-test="profile-metrics"]').text()).toContain("样本规模指纹");
    expect(wrapper.get('[data-test="profile-metrics"]').text()).toContain("不代表原始样本数");
    expect(wrapper.get('[data-test="profile-metrics"]').text()).toContain("指标明细");
    expect(wrapper.get('[data-test="profile-metrics"]').text()).toContain("说明");
    expect(wrapper.get('[data-test="profile-metrics"]').text()).not.toContain("仅解释后端已定义的指纹语义");
    expect(wrapper.get('[data-test="profile-other-metrics"]').text()).toContain("future_metric");
    expect(wrapper.get('[data-test="profile-other-metrics"]').text()).toContain("raw-value");
    expect(wrapper.get('[data-test="profile-chart"]').attributes("data-height")).toBe("180px");
    expect(wrapper.find('[data-test="profile-raw-data"]').exists()).toBe(false);
    expect(wrapper.find(".aw-json").exists()).toBe(false);

    const chart = wrapper.getComponent(ChartContainerStub);
    const options = chart.props("options") as ChartOption;
    expect(options.xAxis).toMatchObject({ type: "value", min: 0, max: 100 });
    expect(options.series).toEqual(expect.arrayContaining([
      expect.objectContaining({ type: "bar", data: [2, 1] }),
    ]));

    await wrapper.get(".profile-raw__toggle").trigger("click");
    expect(wrapper.get('[data-test="profile-raw-data"]').text()).toContain('"fingerprint"');
    expect(wrapper.get(".profile-raw__toggle").text()).toBe("收起原始数据");
  });

  it("handles malformed and missing profile fields without crashing or inventing values", async () => {
    const wrapper = await mountWorkbench(executionWith("profile_dataset", {
      result: {
        fingerprint: {
          fields: ["missing_ratio", "unknown_without_value"],
          values: { missing_ratio: "not-a-number" },
        },
      },
    }));

    expect(wrapper.get('[data-test="profile-artifact-renderer"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="profile-quality-chart"]').exists()).toBe(false);
    expect(wrapper.find('[data-test="profile-overview"]').exists()).toBe(false);
    expect(wrapper.get('[data-test="profile-metrics"]').text()).toContain("not-a-number");
    expect(wrapper.get('[data-test="profile-other-metrics"]').text()).toContain("unknown_without_value");
    expect(wrapper.get('[data-test="profile-other-metrics"]').text()).toContain("不可用");
    expect(wrapper.find('[data-test="profile-raw-data"]').exists()).toBe(false);
  });

  it("keeps non-profile artifacts on the existing generic JSON renderer", async () => {
    const wrapper = await mountWorkbench(executionWith("detect_anomalies", {
      summary: "异常检测完成",
      result: { anomaly_count: 2 },
    }));

    expect(wrapper.find('[data-test="profile-artifact-renderer"]').exists()).toBe(false);
    expect(wrapper.get(".aw-section__label").text()).toBe("工件详细数据 (Payload Details)");
    expect(wrapper.get(".aw-json").text()).toContain('"anomaly_count": 2');
  });
});
