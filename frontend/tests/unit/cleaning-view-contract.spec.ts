import { beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia } from "pinia";
import CleaningView from "../../src/views/CleaningView.vue";
import { cleanDataset } from "../../src/api/preprocessing";
import { getDatasetDetail, getDatasetVersions } from "../../src/api/datasets";
import { ApiError } from "../../src/api/client";

const datasetId = "f4c27bd2-f27f-40eb-aa61-04988f71f616";
const versionId = "c13979a1-206e-4a8f-8e37-a22e12f6027d";

vi.mock("../../src/api/preprocessing", () => ({ cleanDataset: vi.fn() }));
vi.mock("../../src/api/datasets", () => ({ getDatasetDetail: vi.fn(), getDatasetVersions: vi.fn() }));
vi.mock("vue-router", () => ({
  useRoute: () => ({ query: { dataset_id: datasetId, version_id: versionId } }),
}));
vi.mock("element-plus", () => ({ ElMessage: { success: vi.fn(), error: vi.fn() } }));

const mockedCleanDataset = vi.mocked(cleanDataset);
const mockedGetDatasetDetail = vi.mocked(getDatasetDetail);
const mockedGetDatasetVersions = vi.mocked(getDatasetVersions);

const stubs = {
  "el-form": { template: "<form><slot /></form>" },
  "el-form-item": { props: ["label"], template: "<div>{{ label }}<slot /></div>" },
  "el-icon": { template: "<span><slot /></span>" },
  "el-input-number": true,
  "el-radio-group": { template: "<div><slot /></div>" },
  "el-radio": { template: "<label><slot /></label>" },
  "el-select": { template: "<select><slot /></select>" },
  "el-option": true,
  "el-button": {
    props: ["disabled", "loading"],
    template: "<button :disabled=\"disabled || loading\" @click=\"$emit('click')\"><slot /></button>",
  },
  "el-tag": { template: "<span><slot /></span>" },
  "el-alert": { props: ["title"], template: "<div>{{ title }}<slot /></div>" },
  ChartContainer: true,
  Operation: true,
  MagicStick: true,
  DataAnalysis: true,
  ArrowRight: true,
};

function setupApi() {
  mockedGetDatasetDetail.mockResolvedValue({
    id: datasetId,
    name: "S4 清洗验收数据",
    source: "simulation",
    status: "ready",
    version_id: versionId,
    latest_version_id: versionId,
    file_size_bytes: 0,
    row_count: 1200,
    column_count: 4,
    col_count: 4,
    created_at: "2026-08-20T00:00:00Z",
    preview: { columns: [], rows: [] },
  } as never);
  mockedGetDatasetVersions.mockResolvedValue({
    dataset_id: datasetId,
    active_version_id: versionId,
    nodes: [{
      id: versionId,
      name: "V0 · 仿真原始数据",
      tool: "simulation_generate",
      created_at: "2026-08-20T00:00:00Z",
      row_count: 1200,
      column_count: 4,
      artifact_path: "simulation/test.csv",
    }],
    edges: [],
  } as never);
}

describe("CleaningView request contract", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    setupApi();
  });

  it("uses the route source UUID and serializes the default form with canonical API fields", async () => {
    mockedCleanDataset.mockResolvedValue({
      dataset_id: datasetId,
      new_version_id: "e13979a1-206e-4a8f-8e37-a22e12f6027d",
      source_version_id: versionId,
      derived_version_id: "e13979a1-206e-4a8f-8e37-a22e12f6027d",
      processing_run_id: "d13979a1-206e-4a8f-8e37-a22e12f6027d",
      raw_series: [],
      cleaned_series: [],
      replaced_indices: [],
      total_cleaned_points: 0,
      warnings: [],
      recommended_downsample_factor: 1,
      series: [],
      summary: {},
      task: {} as never,
    });
    const wrapper = mount(CleaningView, { global: { plugins: [createPinia()], stubs } });
    await flushPromises();

    expect(wrapper.text()).toContain("源数据版本（本次清洗输入）");
    expect(wrapper.text()).toContain("V0 · 仿真原始数据");
    expect(wrapper.text()).toContain(versionId);
    await wrapper.get("button").trigger("click");

    expect(mockedCleanDataset).toHaveBeenCalledWith({
      dataset_id: datasetId,
      version_id: versionId,
      target_sample_period_seconds: 1,
      interpolation: "linear",
      anomaly_detector: "hampel",
      hampel_window: 5,
    });
  });

  it("shows a field-level validation error and prevents duplicate in-flight submissions", async () => {
    let resolveRequest: ((value: never) => void) | undefined;
    mockedCleanDataset.mockImplementationOnce(() => new Promise((resolve) => { resolveRequest = resolve; }));
    const wrapper = mount(CleaningView, { global: { plugins: [createPinia()], stubs } });
    await flushPromises();

    const button = wrapper.get("button");
    await button.trigger("click");
    await button.trigger("click");
    expect(mockedCleanDataset).toHaveBeenCalledTimes(1);

    resolveRequest!(undefined as never);
    await flushPromises();
    mockedCleanDataset.mockRejectedValueOnce(new ApiError(
      "REQUEST_VALIDATION_FAILED",
      "请求参数校验失败",
      "request-id",
      { issues: [{ loc: ["body", "version_id"], msg: "Input should be a valid UUID", type: "uuid_parsing" }] },
    ));
    await button.trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("清洗失败 [REQUEST_VALIDATION_FAILED]");
    expect(wrapper.text()).toContain("version_id：Input should be a valid UUID");
  });
});
