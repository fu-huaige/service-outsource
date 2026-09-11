import { defineComponent, nextTick } from "vue";
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ArtifactWorkbench from "../../src/components/artifact/ArtifactWorkbench.vue";
import { ApiError } from "../../src/api/client";
import type { ChartOption } from "../../src/components/ChartContainer.vue";
import type { CopilotExecutionSnapshot } from "../../src/types/api";

const deliveryApi = vi.hoisted(() => ({ exportDataset: vi.fn() }));
const messageApi = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));

vi.mock("../../src/api/delivery", () => deliveryApi);
vi.mock("element-plus", () => ({ ElMessage: messageApi }));

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

beforeEach(() => {
  vi.clearAllMocks();
});

const reportExecution = (): CopilotExecutionSnapshot => {
  const reportId = "44444444-4444-4444-4444-444444444444";
  const execution = executionWith("generate_report", {
    report_id: reportId,
    execution_id: "execution-1",
    dataset_id: "dataset-1",
    title: "生产分析报告",
    markdown: "# 关键结论\n\n- 清洗与异常检测均已完成。",
    fully_resolved: true,
    unresolved: [],
    bindings: [],
    artifact_uri: `reports/${reportId}.md`,
    narration_source: "template",
    llm_provider: "none",
    llm_model: "none",
  });
  const steps = [
    ["profile", "profile_dataset", { summary: "画像完成", result: { n_samples: 1200 } }],
    ["anomaly", "detect_anomalies", { summary: "异常检测完成", result: { anomaly_count: 6, anomaly_ratio: 0.005 } }],
    ["clean", "clean_data", {
      summary: {
        rows_before: 1200,
        rows_after: 1198,
        changes: {
          unique_changed_cells: 7,
          missing_value_fills: 4,
          outlier_replacements: 3,
          duplicate_timestamps_processed: 0,
          resampling_empty_rows_created: 0,
          smoothing_changes: 0,
        },
      },
      total_cleaned_points: 7,
    }],
    ["report", "generate_report", execution.step_runs[0].result_payload],
  ] as const;
  execution.plan.steps = steps.map(([stepId, tool]) => ({
    step_id: stepId,
    tool,
    depends_on: [],
    parameters: {},
    requires_confirmation: false,
    status: "completed",
  }));
  execution.step_runs = steps.map(([stepId, tool, payload], index) => ({
    ...execution.step_runs[0],
    step_id: stepId,
    sequence: index + 1,
    tool,
    result_payload: payload,
  }));
  return execution;
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
            anomaly_ratio: 0.2242,
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
    expect(wrapper.get('[data-test="profile-overview"]').text()).toContain("画像离群比例22.42%");
    expect(wrapper.get('[data-test="profile-overview"]').text()).not.toContain("异常率");
    expect(wrapper.get('[data-test="profile-overview"]').text()).not.toContain("0.2242");
    expect(wrapper.get('[data-test="profile-overview"]').text()).toContain("42.00%");
    expect(wrapper.get('[data-test="profile-metrics"]').text()).toContain("样本规模指纹");
    expect(wrapper.get('[data-test="profile-metrics"]').text()).toContain("不代表原始样本数");
    expect(wrapper.get('[data-test="profile-metrics"]').text()).toContain("指标明细");
    expect(wrapper.get('[data-test="profile-metrics"]').text()).toContain("说明");
    expect(wrapper.get('[data-test="profile-metrics"]').text()).toContain("画像离群比例");
    expect(wrapper.get('[data-test="profile-metrics"]').text()).toContain("与正式 Hampel 异常检测结果不是同一指标");
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
      expect.objectContaining({ type: "bar", data: [2, 22.42] }),
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

  it("keeps unknown generic artifacts on the existing JSON renderer", async () => {
    const wrapper = await mountWorkbench(executionWith("select_variables", {
      summary: "特征筛选完成",
      result: { selected_count: 2 },
    }));

    expect(wrapper.find('[data-test="profile-artifact-renderer"]').exists()).toBe(false);
    expect(wrapper.find('[data-test="anomaly-artifact-renderer"]').exists()).toBe(false);
    expect(wrapper.find('[data-test="cleaning-artifact-renderer"]').exists()).toBe(false);
    expect(wrapper.get(".aw-section__label").text()).toBe("工件详细数据 (Payload Details)");
    expect(wrapper.get(".aw-json").text()).toContain('"selected_count": 2');
  });

  it("keeps the existing model renderer for ARX artifacts", async () => {
    const wrapper = await mountWorkbench(executionWith("arx_fit", {
      na: 2,
      nb: 3,
      nk: 1,
      fit_pct: 88.4,
    }));

    expect(wrapper.find('[data-test="profile-artifact-renderer"]').exists()).toBe(false);
    expect(wrapper.find('[data-test="anomaly-artifact-renderer"]').exists()).toBe(false);
    expect(wrapper.find('[data-test="cleaning-artifact-renderer"]').exists()).toBe(false);
    expect(wrapper.text()).toContain("模型结构 (Model Structure)");
    expect(wrapper.text()).toContain("输出阶数 na");
    expect(wrapper.text()).toContain("FIT 拟合度");
    expect(wrapper.find(".aw-json").exists()).toBe(false);
  });
});

describe("ArtifactWorkbench anomaly rendering", () => {
  it("renders the formal anomaly envelope without a default JSON wall or invented position evidence", async () => {
    const wrapper = await mountWorkbench(executionWith("detect_anomalies", {
      summary: "检出疑似异常点 6 个（占比 0.30%），噪声水平估计 0.02417。",
      result: {
        anomaly_count: 3,
        anomaly_ratio: 0.0025,
        future_metric: "raw-value",
      },
    }));

    expect(wrapper.get('[data-test="anomaly-artifact-renderer"]').exists()).toBe(true);
    expect(wrapper.get('[data-test="anomaly-summary"]').text()).toContain("噪声水平估计 0.02417");
    expect(wrapper.get('[data-test="anomaly-overview"]').text()).toContain("异常点数量3");
    expect(wrapper.get('[data-test="anomaly-overview"]').text()).toContain("异常比例0.25%");
    expect(wrapper.get('[data-test="anomaly-overview"]').text()).not.toContain("画像离群比例");
    expect(wrapper.get('[data-test="anomaly-metrics"]').text()).toContain("疑似异常样本数量");
    expect(wrapper.get('[data-test="anomaly-other-metrics"]').text()).toContain("future_metric");
    expect(wrapper.get('[data-test="anomaly-other-metrics"]').text()).toContain("raw-value");
    const ratioChart = wrapper.get('[data-test="anomaly-ratio-chart"]');
    const chart = ratioChart.getComponent(ChartContainerStub);
    expect(chart.attributes("data-height")).toBe("112px");
    const options = chart.props("options") as ChartOption;
    expect(options.xAxis).toMatchObject({ type: "value", min: 0, max: 100, interval: 20 });
    expect(options.yAxis).toMatchObject({ type: "category", data: ["异常比例"] });
    expect(options.series).toEqual([
      expect.objectContaining({ type: "bar", data: [0.25] }),
    ]);
    expect(options.series).not.toEqual(expect.arrayContaining([
      expect.objectContaining({ barMinHeight: expect.any(Number) }),
    ]));
    const tooltip = options.tooltip as { formatter?: (params: unknown) => string };
    expect(tooltip.formatter?.({ value: 0.25 })).toContain("异常比例：0.25%");
    expect(tooltip.formatter?.({ value: 0.25 })).toContain("异常样本：3 / 1,200 个样本");
    expect(wrapper.find('[data-test="anomaly-ratio-track"]').exists()).toBe(false);
    expect(wrapper.find('[data-test="anomaly-position-chart"]').exists()).toBe(false);
    expect(wrapper.find(".aw-json").exists()).toBe(false);
    expect(wrapper.find('[data-test="anomaly-raw-data"]').exists()).toBe(false);

    await wrapper.get(".anomaly-raw__toggle").trigger("click");
    expect(wrapper.get('[data-test="anomaly-raw-data"]').text()).toContain('"anomaly_count": 3');
  });

  it("uses the compact zero state for standalone anomaly results without drawing an empty chart", async () => {
    const wrapper = await mountWorkbench(executionWith("detect_anomalies", {
      result: { anomaly_count: 0, anomaly_ratio: 0 },
    }));

    expect(wrapper.get('[data-test="anomaly-zero-state"]').text()).toContain("本次未检出疑似异常点");
    expect(wrapper.get('[data-test="anomaly-zero-state"]').text()).toContain("0.00%");
    expect(wrapper.find('[data-test="anomaly-ratio-chart"]').exists()).toBe(false);
  });

  it("keeps a larger anomaly ratio on the same true zero-to-one-hundred bar scale", async () => {
    const wrapper = await mountWorkbench(executionWith("detect_anomalies", {
      result: {
        anomaly_count: 20,
        anomaly_ratio: 0.2,
        total: 100,
        n_samples: 99,
        sample_count: 98,
      },
    }));

    const options = wrapper
      .get('[data-test="anomaly-ratio-chart"]')
      .getComponent(ChartContainerStub)
      .props("options") as ChartOption;
    expect(options.xAxis).toMatchObject({ min: 0, max: 100 });
    expect(options.series).toEqual([
      expect.objectContaining({ type: "bar", data: [20] }),
    ]);
    const tooltip = options.tooltip as { formatter?: (params: unknown) => string };
    expect(tooltip.formatter?.({ value: 20 })).toContain("异常比例：20.00%");
    expect(tooltip.formatter?.({ value: 20 })).toContain("异常样本：20 / 100 个样本");
  });

  it("does not chart an invalid ratio and safely handles an empty historical envelope", async () => {
    const invalid = await mountWorkbench(executionWith("detect_anomalies", {
      result: { anomaly_count: "unknown", anomaly_ratio: 1.2 },
    }));
    expect(invalid.find('[data-test="anomaly-ratio-chart"]').exists()).toBe(false);
    expect(invalid.get('[data-test="anomaly-metrics"]').text()).toContain("unknown");
    expect(invalid.get('[data-test="anomaly-metrics"]').text()).toContain("1.2");

    const empty = await mountWorkbench(executionWith("detect_anomalies", {
      summary: null,
      result: null,
    }));
    expect(empty.get('[data-test="anomaly-empty"]').text()).toBe("暂无可结构化展示的异常检测结果");
    expect(empty.find('[data-test="anomaly-raw-data"]').exists()).toBe(false);
  });
});

const cleaningPayload = (overrides: Record<string, unknown> = {}) => ({
  source_version_id: "11111111-1111-1111-1111-111111111111",
  effective_version_id: "22222222-2222-2222-2222-222222222222",
  derived_version_id: "22222222-2222-2222-2222-222222222222",
  created_new_version: true,
  no_op: false,
  converged: false,
  reused_existing_version: false,
  processing_run_id: "33333333-3333-3333-3333-333333333333",
  summary: {
    rows_before: 2000,
    rows_after: 1992,
    changes: {
      count_unit: "cell",
      unique_changed_cells: 7,
      missing_value_fills: 3,
      outlier_replacements: 2,
      smoothing_changes: 1,
      duplicate_timestamps_processed: 1,
      resampling_empty_rows_created: 0,
      overlapping_changed_cells: 1,
      category_counts_may_overlap: true,
      source_missing_cells: 4,
      aligned_missing_cells_before_interpolation: 5,
      future_scalar: 9,
      future_object: { ignored: true },
    },
  },
  ...overrides,
});

describe("ArtifactWorkbench cleaning rendering", () => {
  it("renders Normal Changed as impact facts without promoting version UUIDs", async () => {
    const wrapper = await mountWorkbench(executionWith("clean_data", cleaningPayload()));

    expect(wrapper.get('[data-test="cleaning-artifact-renderer"]').exists()).toBe(true);
    expect(wrapper.get('[data-test="cleaning-summary"]').text()).toBe(
      "本次清洗已生成新的数据版本，并对数据内容进行了实际修正。"
    );
    expect(wrapper.get('[data-test="cleaning-status"]').text()).toContain("已生成新版本");
    expect(wrapper.get('[data-test="cleaning-status"]').text()).toContain("结果有变化");
    expect(wrapper.get('[data-test="cleaning-status"]').text()).toContain("正常清洗");
    expect(wrapper.find('[data-test="cleaning-version-flow"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain("源版本");
    expect(wrapper.text()).not.toContain("有效版本");
    expect(wrapper.text()).not.toContain("11111111…");
    expect(wrapper.text()).not.toContain("22222222…");

    const impact = wrapper.get('[data-test="cleaning-impact-overview"]').text();
    expect(impact).toContain("修改单元格7");
    expect(impact).toContain("缺失填补3");
    expect(impact).toContain("异常替换2");
    expect(impact).toContain("重采样空行0");

    const actionSection = wrapper.get('[data-test="cleaning-action-distribution"]');
    const actionOptions = actionSection.getComponent(ChartContainerStub).props("options") as ChartOption;
    expect(actionOptions.yAxis).toMatchObject({
      type: "category",
      data: ["缺失填补", "异常替换", "重复时间戳处理", "平滑修改"],
    });
    expect(actionOptions.series).toEqual([
      expect.objectContaining({ type: "bar", data: [3, 2, 1, 1] }),
    ]);
    expect(actionOptions.series).not.toEqual(expect.arrayContaining([
      expect.objectContaining({ type: "pie" }),
      expect.objectContaining({ stack: expect.anything() }),
    ]));
    expect(wrapper.get('[data-test="cleaning-overlap-note"]').text()).toContain("不表示占比构成");

    const rowOptions = wrapper
      .get('[data-test="cleaning-row-count-chart"]')
      .getComponent(ChartContainerStub)
      .props("options") as ChartOption;
    expect(rowOptions.series).toEqual([
      expect.objectContaining({ type: "bar", data: [2000, 1992] }),
    ]);
    expect(wrapper.find('[data-test="cleaning-missing-count-chart"]').exists()).toBe(false);

    const metrics = wrapper.get('[data-test="cleaning-metrics"]').text();
    expect(metrics).toContain("本次 Cleaning 中发生实际修改的唯一单元格数量");
    expect(metrics).toContain("通过已配置异常处理策略实际替换的单元格数量");
    expect(metrics).not.toContain("Hampel");
    expect(wrapper.get('[data-test="cleaning-other-metrics"]').text()).toContain("future_scalar9");
    expect(wrapper.get('[data-test="cleaning-other-metrics"]').text()).not.toContain("future_object");
    expect(wrapper.get('[data-test="cleaning-provenance"]').text()).toContain("33333333…");
    expect(wrapper.find(".aw-json").exists()).toBe(false);
    expect(wrapper.find('[data-test="cleaning-raw-data"]').exists()).toBe(false);

    await wrapper.get(".cleaning-raw__toggle").trigger("click");
    expect(wrapper.get('[data-test="cleaning-raw-data"]').text()).toContain('"created_new_version": true');
  });

  it.each([
    {
      name: "Converged",
      payload: cleaningPayload({
        effective_version_id: "11111111-1111-1111-1111-111111111111",
        derived_version_id: null,
        created_new_version: false,
        no_op: true,
        converged: true,
        reused_existing_version: false,
      }),
      summary: "清洗结果已收敛，本次未生成新的数据版本。",
      statuses: ["未生成新版本", "数据状态不变", "已收敛"],
    },
    {
      name: "Reuse",
      payload: {
        summary: "正式清洗服务已复用现有不可变版本。",
        result: cleaningPayload({
          derived_version_id: null,
          created_new_version: false,
          no_op: false,
          converged: false,
          reused_existing_version: true,
        }),
      },
      summary: "正式清洗服务已复用现有不可变版本。",
      statuses: ["复用既有版本", "结果有变化", "幂等复用"],
    },
  ])("keeps $name semantics distinct", async ({ payload, summary, statuses }) => {
    const wrapper = await mountWorkbench(executionWith("clean_data", payload));

    expect(wrapper.get('[data-test="cleaning-summary"]').text()).toBe(summary);
    statuses.forEach((status) => {
      expect(wrapper.get('[data-test="cleaning-status"]').text()).toContain(status);
    });
    expect(wrapper.find('[data-test="cleaning-version-flow"]').exists()).toBe(false);
  });

  it("keeps first-clean zero-change certification distinct", async () => {
    const wrapper = await mountWorkbench(executionWith("clean_data", cleaningPayload({
      no_op: true,
      converged: true,
      summary: { changes: { unique_changed_cells: 0 } },
    })));

    expect(wrapper.get('[data-test="cleaning-summary"]').text()).toBe(
      "本次清洗完成零变化认证，并生成了新的数据版本。"
    );
    expect(wrapper.get('[data-test="cleaning-status"]').text()).toContain("零变化认证");
  });

  it("does not invent missing metrics, zeros, or before-after charts", async () => {
    const withoutChanges = await mountWorkbench(executionWith("clean_data", cleaningPayload({ summary: undefined })));
    expect(withoutChanges.find('[data-test="cleaning-impact-overview"]').exists()).toBe(false);
    expect(withoutChanges.find('[data-test="cleaning-action-distribution"]').exists()).toBe(false);
    expect(withoutChanges.find('[data-test="cleaning-row-count-chart"]').exists()).toBe(false);
    expect(withoutChanges.find('[data-test="cleaning-missing-count-chart"]').exists()).toBe(false);
    expect(withoutChanges.find('[data-test="cleaning-metrics"]').exists()).toBe(false);
    expect(withoutChanges.text()).not.toContain("修改单元格0");
    expect(withoutChanges.find('[data-test="cleaning-version-flow"]').exists()).toBe(false);
    expect(withoutChanges.get('[data-test="cleaning-provenance"]').exists()).toBe(true);

    const empty = await mountWorkbench(executionWith("clean_data", { summary: null, result: null }));
    expect(empty.get('[data-test="cleaning-empty"]').text()).toBe("暂无可结构化展示的数据清洗结果");
    expect(empty.find('[data-test="cleaning-raw-data"]').exists()).toBe(false);
  });

  it("shows an empty action message for explicit zeros and charts missing data only from a complete pair", async () => {
    const allZero = await mountWorkbench(executionWith("clean_data", cleaningPayload({
      summary: {
        changes: {
          missing_value_fills: 0,
          outlier_replacements: 0,
          duplicate_timestamps_processed: 0,
          resampling_empty_rows_created: 0,
          smoothing_changes: 0,
        },
      },
    })));
    expect(allZero.get('[data-test="cleaning-action-empty"]').text()).toBe(
      "本次未记录具体清洗动作计数。"
    );
    expect(allZero.find('[data-test="cleaning-action-chart"]').exists()).toBe(false);

    const complete = await mountWorkbench(executionWith("clean_data", cleaningPayload({
      summary: {
        missing: { before: 106, after: 0 },
        changes: { source_missing_cells: 106, missing_value_fills: 106 },
      },
    })));
    const missingOptions = complete
      .get('[data-test="cleaning-missing-count-chart"]')
      .getComponent(ChartContainerStub)
      .props("options") as ChartOption;
    expect(missingOptions.series).toEqual([
      expect.objectContaining({ type: "bar", data: [106, 0] }),
    ]);

    const incomplete = await mountWorkbench(executionWith("clean_data", cleaningPayload({
      summary: { changes: { source_missing_cells: 106, missing_value_fills: 106 } },
    })));
    expect(incomplete.find('[data-test="cleaning-missing-count-chart"]').exists()).toBe(false);
  });

  it("uses one sample-size status for equal standalone row counts while preserving content changes", async () => {
    const wrapper = await mountWorkbench(executionWith("clean_data", cleaningPayload({
      summary: {
        rows_before: 1200,
        rows_after: 1200,
        changes: {
          unique_changed_cells: 9,
          outlier_replacements: 9,
          category_counts_may_overlap: true,
        },
      },
    })));

    expect(wrapper.get('[data-test="cleaning-row-count-unchanged"]').text()).toContain("样本规模保持不变");
    expect(wrapper.get('[data-test="cleaning-row-count-unchanged"]').text()).toContain("1,200 → 1,200");
    expect(wrapper.find('[data-test="cleaning-row-count-chart"]').exists()).toBe(false);
    expect(wrapper.get('[data-test="cleaning-impact-overview"]').text()).toContain("修改单元格9");
    expect(wrapper.get('[data-test="cleaning-action-chart"]').exists()).toBe(true);
    expect(wrapper.text()).not.toContain("清洗无变化");
  });
});

describe("ArtifactWorkbench report and delivery actions", () => {
  it("uses the dedicated report renderer and restores real sibling results from a persisted snapshot", async () => {
    const wrapper = await mountWorkbench(reportExecution());

    expect(wrapper.get('[data-test="report-artifact-renderer"]').exists()).toBe(true);
    expect(wrapper.find(".aw-json").exists()).toBe(false);
    expect(wrapper.get('[data-test="report-core-metrics"]').text()).toContain("样本数1,200");
    expect(wrapper.get('[data-test="report-core-metrics"]').text()).toContain("异常点6");
    expect(wrapper.get('[data-test="report-core-metrics"]').text()).toContain("异常比例0.50%");
    expect(wrapper.get('[data-test="report-core-metrics"]').text()).toContain("修改单元格7");
    expect(wrapper.get('[data-test="report-profile-section"]').exists()).toBe(true);
    expect(wrapper.get('[data-test="report-anomaly-section"]').exists()).toBe(true);
    expect(wrapper.get('[data-test="report-cleaning-section"]').exists()).toBe(true);
    expect(wrapper.get('[data-test="report-markdown"]').text()).toContain("清洗与异常检测均已完成");
    expect(wrapper.get('[data-test="report-evidence"]').text()).toContain("样本数量");
    expect(wrapper.get('[data-test="report-evidence"]').text()).toContain("来源：本次数据画像");
    expect(wrapper.get('[data-test="report-evidence"]').text()).not.toContain("run type");
  });

  it("uses compact zero states and keeps technical identifiers out of the primary report UI", async () => {
    const execution = reportExecution();
    execution.current_version_id = "11111111-1111-1111-1111-111111111111";
    execution.step_runs[0].result_payload = {
      summary: "画像完成",
      result: {
        n_samples: 1500,
        fingerprint: { values: { missing_ratio: 0, anomaly_ratio: 0 } },
      },
    };
    execution.step_runs[1].result_payload = {
      summary: "异常检测完成",
      result: { anomaly_count: 0, anomaly_ratio: 0 },
    };
    execution.step_runs[2].result_payload = {
      total_cleaned_points: 0,
      processing_run_id: "22222222-2222-2222-2222-222222222222",
      task: {
        progress: {
          message: "正式清洗服务已生成不可变版本 11111111-1111-1111-1111-111111111111。",
        },
      },
      summary: {
        rows_before: 1500,
        rows_after: 1500,
        changes: {
          unique_changed_cells: 0,
          missing_value_fills: 0,
          outlier_replacements: 0,
          duplicate_timestamps_processed: 0,
          resampling_empty_rows_created: 0,
          smoothing_changes: 0,
        },
      },
    };
    execution.step_runs[2].processing_run_ids = ["22222222-2222-2222-2222-222222222222"];
    const report = execution.step_runs[3].result_payload;
    report.execution_id = execution.execution_id;
    report.title = "IndusOpt 数据质量分析与清洗报告";
    report.markdown = "## 一、分析概述\n\n本次仅执行数据质量分析与清洗。";

    const wrapper = await mountWorkbench(execution);

    expect(wrapper.get(".report-status").text()).toBe("本次任务证据已解析");
    expect(wrapper.get('[data-test="anomaly-zero-state"]').text()).toContain("本次未检出疑似异常点");
    expect(wrapper.get('[data-test="anomaly-zero-state"]').text()).toContain("0.00%");
    expect(wrapper.find('[data-test="anomaly-ratio-chart"]').exists()).toBe(false);
    expect(wrapper.get('[data-test="profile-quality-chart"]').exists()).toBe(true);
    expect(wrapper.get('[data-test="cleaning-action-empty"]').text()).toContain("本次清洗未修改数据");
    expect(wrapper.find('[data-test="cleaning-action-chart"]').exists()).toBe(false);
    expect(wrapper.get('[data-test="cleaning-row-count-unchanged"]').text()).toContain("1,500 → 1,500");
    expect(wrapper.find('[data-test="cleaning-row-count-chart"]').exists()).toBe(false);

    const primaryText = [
      wrapper.get(".report-header").text(),
      wrapper.get('[data-test="report-core-metrics"]').text(),
      wrapper.get('[data-test="report-stages"]').text(),
      wrapper.get('[data-test="report-evidence"]').text(),
      wrapper.get('[data-test="report-markdown"]').text(),
    ].join(" ");
    expect(primaryText).not.toContain("11111111-1111-1111-1111-111111111111");
    expect(primaryText).not.toContain("22222222-2222-2222-2222-222222222222");
    expect(primaryText).not.toContain("derived version id");
    expect(primaryText).not.toContain("constant value segment count");
    expect(primaryText).not.toContain("profile_dataset");
    expect(primaryText).not.toContain("detect_anomalies");
    expect(primaryText).not.toContain("clean_data");
    expect(primaryText).not.toContain("ARX");

    const technical = wrapper.get('[data-test="report-technical-details"]');
    expect(technical.attributes("open")).toBeUndefined();
    expect(technical.text()).toContain(execution.execution_id);
    expect(technical.text()).toContain("11111111-1111-1111-1111-111111111111");
    expect(technical.text()).toContain("22222222-2222-2222-2222-222222222222");
  });

  it("renders non-zero cleaning actions and changed row counts as comparison charts", async () => {
    const wrapper = await mountWorkbench(reportExecution());

    const actionOptions = wrapper
      .get('[data-test="cleaning-action-chart"]')
      .getComponent(ChartContainerStub)
      .props("options") as ChartOption;
    expect(actionOptions.yAxis).toEqual(expect.objectContaining({ type: "category" }));
    expect(actionOptions.series).toEqual([
      expect.objectContaining({ type: "bar", data: [4, 3] }),
    ]);
    expect(wrapper.get('[data-test="cleaning-row-count-chart"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="cleaning-row-count-unchanged"]').exists()).toBe(false);
  });

  it("does not invent absent metrics and keeps raw JSON and UUIDs in closed technical details", async () => {
    const reportId = "44444444-4444-4444-4444-444444444444";
    const wrapper = await mountWorkbench(executionWith("generate_report", {
      report_id: reportId,
      title: "无指标报告",
      markdown: "结论仅来自现有证据。",
      fully_resolved: true,
      unresolved: [],
      bindings: [],
    }));

    expect(wrapper.find('[data-test="report-core-metrics"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain("N/A");
    expect(wrapper.text()).not.toContain("综合评分");
    const technical = wrapper.get('[data-test="report-technical-details"]');
    expect(technical.attributes("open")).toBeUndefined();
    expect(technical.get('[data-test="report-raw-json"]').text()).toContain(reportId);
    expect(wrapper.get(".report-header").text()).not.toContain(reportId);
    expect(wrapper.get('[data-test="report-markdown"]').text()).not.toContain(reportId);
  });

  it("binds current-dataset download to the execution dataset and current version", async () => {
    const execution = executionWith("profile_dataset", { result: { n_samples: 10 } });
    execution.dataset_id = "dataset-current";
    execution.current_version_id = "version-current";
    const wrapper = await mountWorkbench(execution);

    expect(wrapper.get('[data-test="download-current-dataset"]').attributes("href")).toBe(
      "/api/v1/datasets/dataset-current/download?version_id=version-current"
    );
  });

  it("shows the formal no-selection message without falling back to a full dataset download", async () => {
    deliveryApi.exportDataset.mockRejectedValueOnce(
      new ApiError("EXPORT_NO_SELECTION", "no selection", "request-1")
    );
    const wrapper = await mountWorkbench(executionWith("profile_dataset", { result: { n_samples: 10 } }));

    await wrapper.get('[data-test="export-optimised-dataset"]').trigger("click");
    await flushPromises();

    expect(deliveryApi.exportDataset).toHaveBeenCalledWith({
      dataset_id: "dataset-1",
      version_id: "version-0",
    });
    expect(wrapper.get('[data-test="export-notice"]').text()).toBe(
      "尚未完成样本优选，无法导出优选数据集。"
    );
    expect(messageApi.error).toHaveBeenCalledWith("尚未完成样本优选，无法导出优选数据集。");
    expect(wrapper.get('[data-test="download-current-dataset"]').text()).toBe("下载当前数据集");
  });

  it("shows real export metrics and persisted artifact download routes after success", async () => {
    deliveryApi.exportDataset.mockResolvedValueOnce({
      export_id: "export-1",
      dataset_id: "dataset-1",
      version_id: "version-0",
      task: {},
      csv_uri: "exports/export-1.csv",
      manifest_uri: "exports/export-1.manifest.json",
      exported_rows: 25,
      source_rows: 100,
      coverage_ratio: 0.25,
      columns: ["timestamp", "u", "y"],
    });
    const wrapper = await mountWorkbench(executionWith("profile_dataset", { result: { n_samples: 100 } }));

    await wrapper.get('[data-test="export-optimised-dataset"]').trigger("click");
    await flushPromises();

    const notice = wrapper.get('[data-test="export-notice"]');
    expect(notice.text()).toContain("优选数据集导出完成");
    expect(notice.text()).toContain("导出 25 / 100 行，覆盖率 25.00%");
    expect(notice.get('a[href="/api/v1/delivery/exports/export-1/csv"]').text()).toBe("下载优选 CSV");
    expect(notice.get('a[href="/api/v1/delivery/exports/export-1/manifest"]').text()).toBe("下载 Manifest");
  });
});
