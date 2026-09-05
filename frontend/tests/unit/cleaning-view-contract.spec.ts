import { beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia } from "pinia";
import { defineComponent, h } from "vue";
import CleaningView from "../../src/views/CleaningView.vue";
import { cleanDataset } from "../../src/api/preprocessing";
import { getDatasetDetail, getDatasetVersions, listDatasets } from "../../src/api/datasets";
import { ApiError } from "../../src/api/client";

const datasetId = "f4c27bd2-f27f-40eb-aa61-04988f71f616";
const versionId = "c13979a1-206e-4a8f-8e37-a22e12f6027d";
const cleanVersionId = "caee11ea-9a81-4c85-9d95-4c66b10c3473";
const lagVersionId = "3eeef5a3-ed99-401d-9495-d303ee095f28";
const featureVersionId = "b13979a1-206e-4a8f-8e37-a22e12f6027d";
const routeState = vi.hoisted(() => ({
  query: {
    dataset_id: "f4c27bd2-f27f-40eb-aa61-04988f71f616",
    version_id: "c13979a1-206e-4a8f-8e37-a22e12f6027d",
  } as Record<string, string>,
}));

vi.mock("../../src/api/preprocessing", () => ({ cleanDataset: vi.fn() }));
vi.mock("../../src/api/datasets", () => ({
  getDatasetDetail: vi.fn(),
  getDatasetVersions: vi.fn(),
  listDatasets: vi.fn(),
}));
vi.mock("vue-router", () => ({
  useRoute: () => routeState,
}));
const messages = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("element-plus", () => ({ ElMessage: messages }));

const mockedCleanDataset = vi.mocked(cleanDataset);
const mockedGetDatasetDetail = vi.mocked(getDatasetDetail);
const mockedGetDatasetVersions = vi.mocked(getDatasetVersions);
const mockedListDatasets = vi.mocked(listDatasets);

const ElPopoverStub = defineComponent({
  name: "ElPopover",
  setup(_props, { slots }) {
    return () => h("div", [slots.reference?.(), slots.default?.()]);
  },
});

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
  "el-popover": ElPopoverStub,
  ChartContainer: true,
  Operation: true,
  MagicStick: true,
  DataAnalysis: true,
  ArrowRight: true,
  ArrowDown: true,
};

const datasetDetail = (activeVersionId = versionId) => ({
    id: datasetId,
    name: "S4 清洗验收数据",
    source: "simulation",
    status: "ready",
    version_id: activeVersionId,
    latest_version_id: activeVersionId,
    file_size_bytes: 0,
    row_count: 1200,
    column_count: 4,
    col_count: 4,
    created_at: "2026-08-20T00:00:00Z",
    preview: { columns: [], rows: [] },
  } as never);

function setupApi() {
  const detail = datasetDetail();
  const versions = {
    dataset_id: datasetId,
    active_version_id: versionId,
    nodes: [
      {
        id: versionId,
        name: "V0 · 仿真原始数据",
        tool: "simulation_generate",
        parent_version_id: null,
        created_at: "2026-08-20T00:00:00Z",
        row_count: 1200,
        column_count: 4,
        artifact_path: "simulation/test.csv",
      },
      {
        id: cleanVersionId,
        name: "V1 · 清洗规整",
        tool: "preprocessing.clean",
        parent_version_id: versionId,
        created_at: "2026-08-20T01:00:00Z",
        row_count: 1200,
        column_count: 4,
        artifact_path: "derived/clean.csv",
      },
      {
        id: lagVersionId,
        name: "V2 · 时滞补偿",
        tool: "preprocessing.lag_compensation",
        parent_version_id: cleanVersionId,
        created_at: "2026-08-20T02:00:00Z",
        row_count: 1191,
        column_count: 4,
        artifact_path: "derived/lag.csv",
      },
      {
        id: featureVersionId,
        name: "V3 · 特征优选",
        tool: "preprocessing.feature_selection",
        parent_version_id: lagVersionId,
        created_at: "2026-08-20T03:00:00Z",
        row_count: 1191,
        column_count: 3,
        artifact_path: "derived/feature.csv",
      },
    ],
    edges: [],
  };
  mockedListDatasets.mockResolvedValue({ items: [detail] });
  mockedGetDatasetDetail.mockResolvedValue(detail);
  mockedGetDatasetVersions.mockResolvedValue(versions as never);
  return { detail, versions };
}

describe("CleaningView request contract", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    routeState.query = { dataset_id: datasetId, version_id: versionId };
    setupApi();
  });

  it("shows full lineage eligibility and serializes the selected source with canonical API fields", async () => {
    mockedCleanDataset.mockResolvedValue({
      dataset_id: datasetId,
      new_version_id: "e13979a1-206e-4a8f-8e37-a22e12f6027d",
      source_version_id: versionId,
      effective_version_id: "e13979a1-206e-4a8f-8e37-a22e12f6027d",
      derived_version_id: "e13979a1-206e-4a8f-8e37-a22e12f6027d",
      created_new_version: true,
      no_op: true,
      converged: true,
      reused_existing_version: false,
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

    expect(wrapper.findAll("[data-test='lineage-node']")).toHaveLength(4);
    expect(wrapper.get(`[data-version-id='${versionId}']`).attributes("aria-disabled")).toBe("false");
    expect(wrapper.get(`[data-version-id='${cleanVersionId}']`).attributes("aria-disabled")).toBe("false");
    expect(wrapper.get(`[data-version-id='${lagVersionId}']`).attributes("aria-disabled")).toBe("true");
    expect(wrapper.get(`[data-version-id='${featureVersionId}']`).attributes("aria-disabled")).toBe("true");
    expect(wrapper.get(`[data-version-id='${lagVersionId}']`).text()).toContain("已进入后续处理阶段");
    expect(wrapper.text()).not.toContain(versionId);
    expect(wrapper.get("[data-test='cleaning-source-summary']").text()).toContain("初始版本");
    await wrapper.get("[data-test='clean-submit']").trigger("click");

    expect(mockedCleanDataset).toHaveBeenCalledWith({
      dataset_id: datasetId,
      version_id: versionId,
      target_sample_period_seconds: 1,
      interpolation: "linear",
      anomaly_detector: "hampel",
      hampel_window: 5,
    });
  });

  it("does not default to an active downstream version and selects the newest eligible source", async () => {
    routeState.query = { dataset_id: datasetId };
    const detail = datasetDetail(featureVersionId);
    mockedListDatasets.mockResolvedValue({ items: [detail] });
    mockedGetDatasetDetail.mockResolvedValue(detail);
    const wrapper = mount(CleaningView, { global: { plugins: [createPinia()], stubs } });
    await flushPromises();

    expect(
      wrapper.get("[data-test='cleaning-source-picker']").attributes("data-selected-version-id")
    ).toBe(cleanVersionId);
    expect(wrapper.get("[data-test='cleaning-source-summary']").text()).toContain(
      "可再次执行清洗规整"
    );
  });

  it("reloads lineage and advances the source to a newly created effective version", async () => {
    const { versions } = setupApi();
    const newVersionId = "e13979a1-206e-4a8f-8e37-a22e12f6027d";
    mockedGetDatasetDetail
      .mockResolvedValueOnce(datasetDetail())
      .mockResolvedValueOnce(datasetDetail(newVersionId));
    mockedGetDatasetVersions
      .mockResolvedValueOnce(versions as never)
      .mockResolvedValueOnce({
        ...versions,
        active_version_id: newVersionId,
        nodes: [
          ...versions.nodes,
          {
            id: newVersionId,
            name: "V4 · 清洗规整",
            tool: "preprocessing.clean",
            parent_version_id: versionId,
            created_at: "2026-08-20T04:00:00Z",
            row_count: 1200,
            column_count: 4,
            artifact_path: "derived/new-clean.csv",
          },
        ],
      } as never);
    mockedCleanDataset.mockResolvedValue({
      dataset_id: datasetId,
      new_version_id: newVersionId,
      effective_version_id: newVersionId,
      created_new_version: true,
      no_op: false,
      converged: false,
      reused_existing_version: false,
      raw_series: [1],
      cleaned_series: [1],
      replaced_indices: [],
      total_cleaned_points: 0,
    });
    const wrapper = mount(CleaningView, { global: { plugins: [createPinia()], stubs } });
    await flushPromises();
    await wrapper.get("[data-test='clean-submit']").trigger("click");
    await flushPromises();
    expect(wrapper.find(".cleaning-summary").exists()).toBe(true);
    expect(messages.success).toHaveBeenCalledWith(
      `成功生成清洗后数据版本: ${newVersionId}`
    );
    expect(wrapper.findAll("[data-test='lineage-node']")).toHaveLength(5);
    expect(
      wrapper.get("[data-test='cleaning-source-picker']").attributes("data-selected-version-id")
    ).toBe(newVersionId);
    expect(wrapper.get("[data-test='cleaning-source-summary']").text()).toContain(
      "V4 · 清洗规整"
    );
    await wrapper.get("[data-test='clean-submit']").trigger("click");
    expect(mockedCleanDataset).toHaveBeenLastCalledWith(expect.objectContaining({
      dataset_id: datasetId,
      version_id: newVersionId,
    }));
  });

  it("shows convergence without adding lineage or changing the selected Cleaning source", async () => {
    routeState.query = { dataset_id: datasetId, version_id: cleanVersionId };
    mockedCleanDataset.mockResolvedValue({
      dataset_id: datasetId,
      source_version_id: cleanVersionId,
      effective_version_id: cleanVersionId,
      derived_version_id: null,
      new_version_id: null,
      created_new_version: false,
      no_op: true,
      converged: true,
      reused_existing_version: false,
      processing_run_id: "d13979a1-206e-4a8f-8e37-a22e12f6027d",
      raw_series: [1],
      cleaned_series: [1],
      replaced_indices: [],
      total_cleaned_points: 0,
      warnings: [],
      summary: { changes: { count_unit: "cell", unique_changed_cells: 0 } },
    });
    const wrapper = mount(CleaningView, { global: { plugins: [createPinia()], stubs } });
    await flushPromises();
    const nodeCount = wrapper.findAll("[data-test='lineage-node']").length;

    await wrapper.get("[data-test='clean-submit']").trigger("click");
    await flushPromises();

    expect(wrapper.get("[data-test='cleaning-converged-badge']").text()).toBe("已收敛");
    expect(wrapper.get(".cleaning-summary").text()).toContain(
      "清洗结果已收敛，本次未产生新的数据版本"
    );
    expect(wrapper.get(".cleaning-summary").text()).toContain("当前有效版本：V1 · 清洗规整");
    expect(wrapper.get(".cleaning-summary").text()).toContain("修改单元：0");
    expect(wrapper.findAll("[data-test='lineage-node']")).toHaveLength(nodeCount);
    expect(
      wrapper.get("[data-test='cleaning-source-picker']").attributes("data-selected-version-id")
    ).toBe(cleanVersionId);
    expect(messages.success).toHaveBeenCalledWith(
      "清洗结果已收敛，本次未产生新的数据版本。"
    );
  });

  it("reloads lineage and advances to an idempotently reused Cleaning version", async () => {
    mockedCleanDataset.mockResolvedValue({
      dataset_id: datasetId,
      source_version_id: versionId,
      effective_version_id: cleanVersionId,
      derived_version_id: null,
      new_version_id: null,
      created_new_version: false,
      no_op: false,
      converged: false,
      reused_existing_version: true,
      processing_run_id: "d13979a1-206e-4a8f-8e37-a22e12f6027d",
      raw_series: [1],
      cleaned_series: [2],
      replaced_indices: [0],
      total_cleaned_points: 1,
      warnings: [],
      summary: { changes: { count_unit: "cell", unique_changed_cells: 1 } },
    });
    const wrapper = mount(CleaningView, { global: { plugins: [createPinia()], stubs } });
    await flushPromises();
    const nodeCount = wrapper.findAll("[data-test='lineage-node']").length;

    await wrapper.get("[data-test='clean-submit']").trigger("click");
    await flushPromises();

    expect(wrapper.get("[data-test='cleaning-reused-badge']").text()).toBe("已复用");
    expect(wrapper.get(".cleaning-summary").text()).toContain(
      "相同清洗结果已存在，已复用现有数据版本"
    );
    expect(wrapper.findAll("[data-test='lineage-node']")).toHaveLength(nodeCount);
    expect(
      wrapper.get("[data-test='cleaning-source-picker']").attributes("data-selected-version-id")
    ).toBe(cleanVersionId);
    expect(wrapper.get("[data-test='cleaning-source-summary']").text()).toContain(
      "V1 · 清洗规整"
    );
    expect(messages.success).toHaveBeenCalledWith(
      "相同清洗结果已存在，已复用现有数据版本。"
    );
  });

  it("distinguishes first-clean zero-change certification from repeated convergence", async () => {
    const newVersionId = "e13979a1-206e-4a8f-8e37-a22e12f6027d";
    mockedCleanDataset.mockResolvedValue({
      dataset_id: datasetId,
      source_version_id: versionId,
      effective_version_id: newVersionId,
      derived_version_id: newVersionId,
      new_version_id: newVersionId,
      created_new_version: true,
      no_op: true,
      converged: true,
      reused_existing_version: false,
      raw_series: [1],
      cleaned_series: [1],
      replaced_indices: [],
      total_cleaned_points: 0,
      warnings: [],
      summary: { changes: { count_unit: "cell", unique_changed_cells: 0 } },
    });
    const wrapper = mount(CleaningView, { global: { plugins: [createPinia()], stubs } });
    await flushPromises();

    await wrapper.get("[data-test='clean-submit']").trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("清洗认证完成");
    expect(wrapper.get(".cleaning-summary").text()).toContain(
      "数据无需修复，已完成清洗认证并生成 Cleaning Version"
    );
    expect(messages.success).toHaveBeenCalledWith(
      "数据无需修复，已完成清洗认证并生成 Cleaning Version。"
    );
  });

  it("preserves branching lineage and renders an empty state when no source is eligible", async () => {
    const response = await mockedGetDatasetVersions(datasetId);
    const branchId = "aa3979a1-206e-4a8f-8e37-a22e12f6027d";
    mockedGetDatasetVersions.mockResolvedValue({
      ...response,
      nodes: [
        ...response.nodes,
        {
          id: branchId,
          name: "V4 · 清洗分支",
          tool: "preprocessing.clean",
          parent_version_id: versionId,
          created_at: "2026-08-20T04:00:00Z",
          row_count: 1200,
          column_count: 4,
          artifact_path: "derived/clean-branch.csv",
        },
      ],
    });
    let wrapper = mount(CleaningView, { global: { plugins: [createPinia()], stubs } });
    await flushPromises();
    expect(wrapper.get(`[data-version-id='${branchId}']`).attributes("data-parent-id")).toBe(versionId);

    wrapper.unmount();
    routeState.query = { dataset_id: datasetId };
    const detail = datasetDetail(featureVersionId);
    mockedListDatasets.mockResolvedValue({ items: [detail] });
    mockedGetDatasetDetail.mockResolvedValue(detail);
    mockedGetDatasetVersions.mockResolvedValue({
      ...response,
      active_version_id: featureVersionId,
      nodes: response.nodes.filter((item) =>
        item.tool === "preprocessing.lag_compensation" ||
        item.tool === "preprocessing.feature_selection"
      ),
    });
    wrapper = mount(CleaningView, { global: { plugins: [createPinia()], stubs } });
    await flushPromises();
    expect(wrapper.get("[data-test='no-eligible-source']").text()).toContain(
      "暂无可用于清洗规整的数据版本"
    );
    expect(wrapper.get<HTMLButtonElement>("[data-test='clean-submit']").element.disabled).toBe(true);
  });

  it("shows a field-level validation error and prevents duplicate in-flight submissions", async () => {
    let resolveRequest: ((value: never) => void) | undefined;
    mockedCleanDataset.mockImplementationOnce(() => new Promise((resolve) => { resolveRequest = resolve; }));
    const wrapper = mount(CleaningView, { global: { plugins: [createPinia()], stubs } });
    await flushPromises();

    const button = wrapper.get("[data-test='clean-submit']");
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
