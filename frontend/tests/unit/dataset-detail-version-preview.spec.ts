import { beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia } from "pinia";
import { ElMessage } from "element-plus";
import DatasetDetailView from "../../src/views/DatasetDetailView.vue";
import { getDatasetDetail, getDatasetProfile, getDatasetVersions } from "../../src/api/datasets";

vi.mock("../../src/api/datasets", () => ({
  getDatasetDetail: vi.fn(),
  getDatasetProfile: vi.fn(),
  getDatasetVersions: vi.fn(),
}));
vi.mock("vue-router", () => ({
  useRoute: () => ({ params: { id: "dataset-id" } }),
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("element-plus", () => ({ ElMessage: { success: vi.fn(), error: vi.fn() } }));

const detailApi = vi.mocked(getDatasetDetail);
const profileApi = vi.mocked(getDatasetProfile);
const versionsApi = vi.mocked(getDatasetVersions);

const stubs = {
  "el-tabs": { template: "<div><slot /></div>" },
  "el-tab-pane": { template: "<section><slot /></section>" },
  "el-tag": { template: "<span><slot /></span>" },
  "el-icon": { template: "<span><slot /></span>" },
  "el-table": {
    props: ["data", "height"],
    template: "<div class=\"el-table-stub\" :data-row-count=\"data.length\" :data-height=\"height\" :data-json=\"JSON.stringify(data)\"><slot /></div>",
  },
  "el-table-column": { props: ["label"], template: "<div>{{ label }}</div>" },
  "el-row": { template: "<div><slot /></div>" },
  "el-col": { template: "<div><slot /></div>" },
  "el-divider": { template: "<hr />" },
  "el-empty": { props: ["description"], template: "<div>{{ description }}</div>" },
  "el-button": { template: "<button @click=\"$emit('click')\"><slot /></button>" },
  "el-alert": { props: ["title"], template: "<div>{{ title }}<slot /></div>" },
  "el-collapse": { template: "<div><slot /></div>" },
  "el-collapse-item": { props: ["title"], template: "<details><summary>{{ title }}</summary><slot /></details>" },
  "el-timeline": { template: "<div><slot /></div>" },
  "el-timeline-item": { template: "<div><slot /></div>" },
  "el-card": { template: "<div><slot /></div>" },
  StateView: { props: ["state", "title"], template: "<div>{{ state }}:{{ title }}</div>" },
  DataLine: true,
  Share: true,
  ArrowRight: true,
};

const baseDetail = {
  id: "dataset-id",
  name: "S4",
  version_id: "active-version-id",
  latest_version_id: "active-version-id",
  source: "simulation",
  row_count: 1200,
  column_count: 4,
  preview: {
    columns: ["timestamp", "u1", "u2", "y"],
    rows: Array.from({ length: 100 }, (_, index) => ({
      timestamp: `2026-01-01T00:${String(Math.floor(index / 60)).padStart(2, "0")}:${String(index % 60).padStart(2, "0")}Z`,
      u1: index,
      u2: index === 4 ? null : index * 2,
      y: index * 3,
    })),
    truncated: true,
    recommended_downsample_factor: 1,
  },
};

const profile = {
  dataset_id: "dataset-id",
  version_id: "active-version-id",
  total_rows: 1200,
  total_cols: 4,
  missing_rate: 0,
  missing_rates: {},
  anomaly_counts: {},
  interval_histogram: [],
  quality_score: 100,
  recommendations: [],
  candidate_frozen_segments: [],
  freeze_detection_summary: { candidate_count: 0, affected_column_count: 0, longest_segment: null },
};

function mountView() {
  return mount(DatasetDetailView, { global: { plugins: [createPinia()], stubs } });
}

describe("DatasetDetailView version audit and preview", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    profileApi.mockResolvedValue(profile as never);
    versionsApi.mockResolvedValue({
      dataset_id: "dataset-id",
      active_version_id: "active-version-id",
      nodes: [{
        id: "active-version-id",
        name: "V1 · 清洗规整",
        tool: "preprocessing.clean",
        parent_version_id: "root-version-id",
        created_at: "2026-08-21T00:00:00Z",
        row_count: 1200,
        column_count: 4,
        artifact_path: "derived/dataset/active-version.csv",
        parameters: {
          request: { interpolation: "linear" },
          resolved_parameters: { outlier_detector: "hampel" },
          frozen_segment_count: 140,
          unknown_evidence: { preserved: true },
        },
        audit_summary: {
          freeze: { historical_constant_value_segment_count: 140, candidate_frozen_segment_count: 1 },
          processing: {
            count_unit: "cell",
            unique_changed_cells: 111,
            missing_value_fills: 99,
            outlier_replacements: 12,
            duplicate_timestamps_processed: 12,
            smoothing_changes: 0,
          },
        },
      }],
      edges: [],
    } as never);
  });

  it("renders the active bounded preview object and preserves explicit null values", async () => {
    detailApi.mockResolvedValue(baseDetail as never);
    const wrapper = mountView();
    await flushPromises();

    expect(wrapper.text()).toContain("timestamp");
    expect(wrapper.text()).toContain("u1");
    expect(wrapper.text()).toContain("u2");
    expect(wrapper.text()).toContain("y");
    expect(wrapper.text()).not.toContain("无数据行预览");
    expect(wrapper.get(".el-table-stub").attributes("data-row-count")).toBe("100");
    expect(wrapper.get(".el-table-stub").attributes("data-height")).toBeUndefined();
    expect(wrapper.find(".preview-table-region").exists()).toBe(true);
    expect(wrapper.text()).toContain("当前预览 100 / 1200 行");
    expect(wrapper.text()).toContain("仅展示前100行");
    expect(detailApi).toHaveBeenCalledTimes(1);
  });

  it("keeps all preview rows after viewport changes without issuing another request", async () => {
    detailApi.mockResolvedValue(baseDetail as never);
    const wrapper = mountView();
    await flushPromises();

    window.dispatchEvent(new Event("resize"));
    await flushPromises();

    expect(wrapper.get(".el-table-stub").attributes("data-row-count")).toBe("100");
    expect(wrapper.get(".el-table-stub").attributes("data-height")).toBeUndefined();
    expect(detailApi).toHaveBeenCalledTimes(1);
  });

  it("keeps raw JSON out of the initial DAG and exposes a collapsed full audit entry", async () => {
    detailApi.mockResolvedValue(baseDetail as never);
    const wrapper = mountView();
    await flushPromises();

    expect(wrapper.text()).toContain("历史恒值区段审计数");
    expect(wrapper.text()).toContain("候选异常冻结段");
    expect(wrapper.text()).toContain("缺失值填补");
    expect(wrapper.text()).toContain("查看原始审计参数");
    expect(wrapper.text()).not.toContain("参数: {\"request\"");
    expect(wrapper.html()).toContain("unknown_evidence");
  });

  it("distinguishes loading, empty and error states and can retry an error", async () => {
    let resolveDetail: ((value: typeof baseDetail) => void) | undefined;
    detailApi.mockImplementationOnce(() => new Promise((resolve) => { resolveDetail = resolve; }));
    const loadingWrapper = mountView();
    expect(loadingWrapper.text()).toContain("正在加载真实数据预览");
    resolveDetail!({ ...baseDetail, preview: { ...baseDetail.preview, rows: [] } });
    await flushPromises();
    expect(loadingWrapper.text()).toContain("该版本文件不包含可预览的数据行");

    detailApi.mockRejectedValueOnce(new Error("network down"));
    const errorWrapper = mountView();
    await flushPromises();
    expect(errorWrapper.text()).toContain("数据预览加载失败");
    expect(errorWrapper.text()).toContain("重新加载");

    detailApi.mockResolvedValueOnce(baseDetail as never);
    const retry = errorWrapper.findAll("button").find((button) => button.text().includes("重新加载"));
    expect(retry).toBeDefined();
    await retry!.trigger("click");
    await flushPromises();
    expect(errorWrapper.text()).not.toContain("数据预览加载失败");
  });

  it("labels simulation request and resolved evidence as separate provenance groups", async () => {
    detailApi.mockResolvedValue(baseDetail as never);
    versionsApi.mockResolvedValueOnce({
      dataset_id: "dataset-id",
      active_version_id: "root",
      nodes: [{
        id: "root",
        name: "V0 · 仿真原始数据",
        tool: "simulation_generate",
        created_at: "2026-08-21T00:00:00Z",
        row_count: 1200,
        column_count: 4,
        artifact_path: "simulation/root.csv",
        parameters: { simulation_request: { scenario: "S4", anomaly_rate: 0, missing_rate: 0 } },
        provenance: {
          user_request: { scenario: "S4", anomaly_rate: 0, missing_rate: 0 },
          resolved_scenario_parameters: { anomaly_count: 12, missing_count_by_column: { u1: 36, y: 36 } },
          evidence_source: "ground_truth",
        },
      }],
      edges: [],
    } as never);
    const wrapper = mountView();
    await flushPromises();

    expect(wrapper.text()).toContain("用户请求参数");
    expect(wrapper.text()).toContain("场景解析后实际生效参数");
    expect(wrapper.text()).toContain("ground_truth");
  });
  it("renders resolved simulation evidence as localized structured tables", async () => {
    detailApi.mockResolvedValue(baseDetail as never);
    const rawParameters = {
      simulation_request: { scenario: "S4", dataset_name: "audit-data", num_samples: 1200 },
      unknown_evidence: { preserved: true },
    };
    versionsApi.mockResolvedValueOnce({
      dataset_id: "dataset-id",
      active_version_id: "root",
      nodes: [{
        id: "root",
        name: "V0 · 仿真原始数据",
        tool: "simulation_generate",
        created_at: "2026-08-21T00:00:00Z",
        row_count: 1200,
        column_count: 4,
        artifact_path: "simulation/root.csv",
        parameters: rawParameters,
        provenance: {
          user_request: {
            scenario: "S4",
            dataset_name: "audit-data",
            num_samples: 1200,
            sample_period_seconds: 1,
            input_count: 2,
            noise_level: 0,
            anomaly_rate: 0,
            missing_rate: 0,
            seed: 9999,
          },
          resolved_scenario_parameters: {
            noise_level: 0,
            anomaly_count_by_column: { y: 12 },
            anomaly_rate_by_column: { y: 0.01 },
            missing_count_by_column: { u1: 36, y: 36 },
            missing_rate_by_column: { u1: 0.03, y: 0.03 },
            freeze_segments: [{ column: "u1", start_idx: 540, end_idx: 620 }],
            drift_segments: [{ column: "y", start_idx: 864, end_idx: 1199 }],
            irregular_timestamp_count: 19,
            duplicate_timestamp_count: 12,
            seed: 9999,
          },
          evidence_source: "ground_truth",
        },
      }],
      edges: [],
    } as never);

    const wrapper = mountView();
    await flushPromises();

    const requestView = wrapper.get(".request-parameters-view");
    expect(wrapper.findAll("summary").filter((summary) => summary.text() === "用户请求参数")).toHaveLength(1);
    expect(requestView.find(".audit-section-title").exists()).toBe(false);
    expect(requestView.text()).toContain("1200个采样点");
    expect(requestView.text()).toContain("2个变量");
    expect(requestView.text()).toContain("使用场景默认值（原始请求值：0）");
    expect(requestView.text()).toContain("最终生效值见下方实际生效参数");

    const resolvedView = wrapper.get(".resolved-parameters-view");
    expect(wrapper.findAll("summary").filter((summary) => summary.text() === "场景解析后实际生效参数")).toHaveLength(1);
    expect(resolvedView.find(".audit-section-title").exists()).toBe(false);
    expect(resolvedView.find("pre").exists()).toBe(false);
    expect(resolvedView.text()).toContain("基础配置");
    expect(resolvedView.text()).toContain("异常值注入");
    expect(resolvedView.text()).toContain("缺失值注入");
    expect(resolvedView.text()).toContain("已知冻结注入");
    expect(resolvedView.text()).toContain("已知漂移注入");
    expect(resolvedView.text()).toContain("时间戳污染");
    expect(resolvedView.text()).not.toContain('{"y":12}');

    const anomalyRows = JSON.parse(resolvedView.get(".anomaly-injection-table").attributes("data-json"));
    const missingRows = JSON.parse(resolvedView.get(".missing-injection-table").attributes("data-json"));
    const freezeRows = JSON.parse(resolvedView.get(".freeze-injection-table").attributes("data-json"));
    const driftRows = JSON.parse(resolvedView.get(".drift-injection-table").attributes("data-json"));
    expect(anomalyRows).toEqual([{ variable: "y", count_label: "12个", rate_label: "1.00%" }]);
    expect(missingRows).toEqual([
      { variable: "u1", count_label: "36个", rate_label: "3.00%" },
      { variable: "y", count_label: "36个", rate_label: "3.00%" },
    ]);
    expect(freezeRows[0]).toMatchObject({ variable: "u1", start_label: "540", end_label: "620", length_label: "81点" });
    expect(driftRows[0]).toMatchObject({ variable: "y", start_label: "864", end_label: "1199", length_label: "336点" });

    const rawBlocks = wrapper.findAll("pre.audit-json");
    expect(rawBlocks).toHaveLength(1);
    expect(rawBlocks[0].text()).toContain('"unknown_evidence"');
    expect(rawBlocks[0].text()).toContain('"preserved": true');
  });

  it("distinguishes missing evidence from explicitly empty injection arrays", async () => {
    detailApi.mockResolvedValue(baseDetail as never);
    versionsApi.mockResolvedValueOnce({
      dataset_id: "dataset-id",
      active_version_id: "root",
      nodes: [{
        id: "root",
        name: "V0 · 仿真原始数据",
        tool: "simulation_generate",
        created_at: "2026-08-21T00:00:00Z",
        row_count: 100,
        column_count: 2,
        artifact_path: "simulation/root.csv",
        parameters: {},
        provenance: {
          user_request: { scenario: "S1" },
          resolved_scenario_parameters: {
            missing_count_by_column: {},
            missing_rate_by_column: {},
            freeze_segments: [],
            drift_segments: [],
          },
        },
      }],
      edges: [],
    } as never);

    const wrapper = mountView();
    await flushPromises();

    expect(wrapper.get('[data-audit-section="anomaly"]').text()).toContain("未记录");
    expect(wrapper.get('[data-audit-section="missing"]').text()).toContain("未注入");
    expect(wrapper.get('[data-audit-section="freeze"]').text()).toContain("未注入");
    expect(wrapper.get('[data-audit-section="drift"]').text()).toContain("未注入");
    expect(wrapper.get('[data-audit-field="irregular-timestamps"]').text()).toContain("未记录");
  });

  it("localizes cleaning enums and units with a safe unknown fallback", async () => {
    detailApi.mockResolvedValue(baseDetail as never);
    const cleanNode = {
      id: "clean",
      name: "V1 · 清洗规整",
      tool: "preprocessing.clean",
      parent_version_id: "root",
      created_at: "2026-08-21T00:00:00Z",
      row_count: 1200,
      column_count: 4,
      artifact_path: "derived/clean.csv",
      parameters: {
        request: { anomaly_strategy: "linear_interpolate", hampel_window: 5 },
        resolved_parameters: {
          resample_period_seconds: 1,
          interpolation: "linear",
          duplicate_strategy: "mean",
          outlier_detector: "hampel",
          outlier_strategy: "linear_interpolate",
          smoothing: "none",
          hampel_window: 5,
        },
        warnings: [
          "已按 mean 规则处理 12 个重复时间戳。",
          "检测到 140 个冻结段，未自动删除。",
        ],
      },
      audit_summary: {
        freeze: { historical_constant_value_segment_count: 140, candidate_frozen_segment_count: 1 },
        processing: {
          unique_changed_cells: 111,
          missing_value_fills: 99,
          outlier_replacements: 12,
          duplicate_timestamps_processed: 12,
          smoothing_changes: 0,
        },
        warnings: [
          "已按 mean 规则处理 12 个重复时间戳。",
          "历史版本记录了 140 个恒值区段审计项；按当前统一口径识别出 1 个候选异常冻结段。",
        ],
      },
    };
    const unknownNode = {
      ...cleanNode,
      id: "unknown-clean",
      name: "V2 · 未知参数兼容",
      parameters: {
        ...cleanNode.parameters,
        resolved_parameters: { ...cleanNode.parameters.resolved_parameters, outlier_detector: "future_detector" },
      },
    };
    versionsApi.mockResolvedValueOnce({
      dataset_id: "dataset-id",
      active_version_id: "clean",
      nodes: [cleanNode, unknownNode],
      edges: [],
    } as never);

    const wrapper = mountView();
    await flushPromises();
    const cleanCard = wrapper.findAll(".version-card")[0];
    const businessText = cleanCard.get(".audit-groups").text();
    const text = wrapper.text();

    expect(text).toContain("Hampel 滤波");
    expect(text).toContain("线性插值替换");
    expect(text).toContain("未启用");
    expect(text).toContain("线性插值");
    expect(text).toContain("均值聚合");
    expect(text).toContain("future_detector（未识别参数）");
    expect(text).toContain("1 秒");
    expect(text).toContain("5个采样点");
    expect(text).toContain("111个单元格");
    expect(text).toContain("99个单元格");
    expect(text).toContain("12个单元格");
    expect(text).toContain("12行");
    expect(text).toContain("0个单元格");
    expect(text).toContain("140段");
    expect(text).toContain("1段");
    expect(businessText).toContain("已采用均值聚合处理12行重复时间戳。");
    expect(businessText).not.toContain("mean");
    expect(businessText).toContain("历史版本记录了 140 个恒值区段审计项");

    const rawAuditText = cleanCard.get("pre.raw-audit-json").text();
    expect(rawAuditText).toContain('"duplicate_strategy": "mean"');
    expect(rawAuditText).toContain("已按 mean 规则处理 12 个重复时间戳。");
  });

  it("copies the exact raw audit JSON and reports both success and failure", async () => {
    detailApi.mockResolvedValue(baseDetail as never);
    const parameters = { request: { interpolation: "linear", duplicate_strategy: "mean" }, warnings: ["已按 mean 规则处理 12 个重复时间戳。"], unknown_field: [1, 2, 3] };
    versionsApi.mockResolvedValueOnce({
      dataset_id: "dataset-id",
      active_version_id: "clean",
      nodes: [{
        id: "clean",
        name: "V1 · 清洗规整",
        tool: "preprocessing.clean",
        created_at: "2026-08-21T00:00:00Z",
        row_count: 1200,
        column_count: 4,
        artifact_path: "derived/clean.csv",
        parameters,
      }],
      edges: [],
    } as never);
    const writeText = vi.fn().mockResolvedValueOnce(undefined).mockRejectedValueOnce(new Error("denied"));
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });

    const wrapper = mountView();
    await flushPromises();
    const copyButton = wrapper.findAll("button").find((button) => button.text().includes("复制 JSON"));
    expect(copyButton).toBeDefined();

    await copyButton!.trigger("click");
    await flushPromises();
    expect(writeText).toHaveBeenCalledWith(JSON.stringify(parameters, null, 2));
    expect(writeText.mock.calls[0][0]).toContain('"duplicate_strategy": "mean"');
    expect(writeText.mock.calls[0][0]).toContain("已按 mean 规则处理 12 个重复时间戳。");
    expect(vi.mocked(ElMessage.success)).toHaveBeenCalledWith("原始审计 JSON 已复制");

    await copyButton!.trigger("click");
    await flushPromises();
    expect(vi.mocked(ElMessage.error)).toHaveBeenCalledWith("复制失败，请手动选择原始审计 JSON");
  });
});
