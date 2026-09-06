import { beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent, h } from "vue";
import CleaningVersionCompareWorkbench from "../../src/components/cleaning/CleaningVersionCompareWorkbench.vue";
import VersionLineagePicker from "../../src/components/versioning/VersionLineagePicker.vue";
import {
  getCleaningVersionCompare,
  getCleaningVersionCompareChannels,
} from "../../src/api/datasets";
import { ApiError } from "../../src/api/client";
import type {
  CleaningVersionCompareChannelsData,
  CleaningVersionCompareData,
  DatasetItem,
  DatasetVersionNode,
} from "../../src/types/api";

vi.mock("../../src/api/datasets", () => ({
  getCleaningVersionCompare: vi.fn(),
  getCleaningVersionCompareChannels: vi.fn(),
}));

const mockedCompare = vi.mocked(getCleaningVersionCompare);
const mockedChannels = vi.mocked(getCleaningVersionCompareChannels);
const chartDispatchAction = vi.fn();

const ChartContainerStub = defineComponent({
  name: "ChartContainer",
  props: { options: { type: Object, required: true }, height: String },
  setup(_props, { expose }) {
    expose({ dispatchAction: chartDispatchAction });
    return () => h("div", { "data-test": "version-compare-chart" });
  },
});

const ElPopoverStub = defineComponent({
  name: "ElPopover",
  setup(_props, { slots }) {
    return () => h("div", [slots.reference?.(), slots.default?.()]);
  },
});

const stubs = {
  "el-popover": ElPopoverStub,
  "el-icon": { template: "<span><slot /></span>" },
  "el-select": {
    props: ["modelValue", "disabled", "loading"],
    emits: ["update:modelValue"],
    template: '<select :value="modelValue ?? \'\'" :disabled="disabled" @change="$emit(\'update:modelValue\', $event.target.value)"><slot /></select>',
  },
  "el-option": { props: ["label", "value"], template: '<option :value="value">{{ label }}</option>' },
  "el-button": {
    props: ["disabled", "loading"],
    template: '<button :disabled="disabled || loading" @click="$emit(\'click\')"><slot /></button>',
  },
  "el-tag": { template: "<span><slot /></span>" },
  "el-alert": { props: ["title"], template: "<div>{{ title }}<slot /></div>" },
  ChartContainer: ChartContainerStub,
  ArrowDown: true,
};

const dataset: DatasetItem = {
  id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  name: "accept_collinearity_phase2",
  version_id: "",
  latest_version_id: "",
  file_size_bytes: 0,
  row_count: 4,
  col_count: 3,
  created_at: "2026-09-06T00:00:00Z",
  time_column: "timestamp",
  input_columns: ["u1"],
  output_column: "y",
};

const raw: DatasetVersionNode = {
  id: "11111111-1111-4111-8111-111111111111",
  name: "V0 · 原始数据",
  tool: "raw_upload",
  parent_version_id: null,
  created_at: "2026-09-06T00:00:00Z",
  row_count: 4,
  column_count: 3,
  artifact_path: "raw.csv",
};
const clean: DatasetVersionNode = {
  ...raw,
  id: "22222222-2222-4222-8222-222222222222",
  name: "V1 · 清洗规整",
  tool: "preprocessing.clean",
  parent_version_id: raw.id,
  artifact_path: "clean.csv",
};
const branch: DatasetVersionNode = {
  ...clean,
  id: "33333333-3333-4333-8333-333333333333",
  name: "V1B · 清洗规整",
  artifact_path: "branch.csv",
};
const simulation: DatasetVersionNode = {
  ...raw,
  id: "44444444-4444-4444-8444-444444444444",
  name: "V0B · 仿真数据",
  tool: "simulation_generate",
  artifact_path: "simulation.csv",
};
const lag: DatasetVersionNode = {
  ...clean,
  id: "55555555-5555-4555-8555-555555555555",
  name: "V2 · 时滞补偿",
  tool: "preprocessing.lag_compensation",
  parent_version_id: clean.id,
  artifact_path: "lag.csv",
};
const feature: DatasetVersionNode = {
  ...lag,
  id: "66666666-6666-4666-8666-666666666666",
  name: "V3 · 特征优选",
  tool: "preprocessing.feature_selection",
  parent_version_id: lag.id,
  artifact_path: "feature.csv",
};

const channelResponse = (
  baselineId = raw.id,
  compareId = clean.id,
  names = ["u1", "y"],
  warnings: string[] = []
): CleaningVersionCompareChannelsData => ({
  dataset_id: dataset.id,
  baseline_version_id: baselineId,
  compare_version_id: compareId,
  channels: names.map((name) => ({
    name,
    baseline_inferred_type: "float",
    compare_inferred_type: "float",
    unit: null,
  })),
  warnings,
});

const compareResponse = (overrides: Partial<CleaningVersionCompareData> = {}): CleaningVersionCompareData => ({
  dataset_id: dataset.id,
  baseline: {
    version_id: raw.id,
    name: raw.name,
    operation_name: raw.tool,
    parent_version_id: null,
    created_at: raw.created_at,
    row_count: 4,
    column_count: 3,
    sha256: "a".repeat(64),
  },
  compare: {
    version_id: clean.id,
    name: clean.name,
    operation_name: clean.tool,
    parent_version_id: raw.id,
    created_at: clean.created_at,
    row_count: 4,
    column_count: 3,
    sha256: "b".repeat(64),
  },
  relation: "DIRECT_PARENT",
  direction: "BASELINE_TO_COMPARE",
  channel: { name: "u1", inferred_type: "float", unit: null },
  baseline_series: {
    input_point_count: 3,
    returned_point_count: 3,
    projected: false,
    points: [
      { timestamp: "2026-01-01T00:00:00Z", occurrence_index: 0, value: 1 },
      { timestamp: "2026-01-01T00:00:01Z", occurrence_index: 0, value: 2 },
      { timestamp: "2026-01-01T00:00:03Z", occurrence_index: 0, value: 4 },
    ],
  },
  compare_series: {
    input_point_count: 3,
    returned_point_count: 3,
    projected: false,
    points: [
      { timestamp: "2026-01-01T00:00:00Z", occurrence_index: 0, value: 1.5 },
      { timestamp: "2026-01-01T00:00:01Z", occurrence_index: 0, value: 2 },
      { timestamp: "2026-01-01T00:00:02Z", occurrence_index: 0, value: 3 },
    ],
  },
  difference_points: [
    {
      timestamp: "2026-01-01T00:00:00Z",
      difference_kind: "VALUE_CHANGED",
      baseline_value: 1,
      compare_value: 1.5,
      absolute_delta: 0.5,
      baseline_occurrences: [],
      compare_occurrences: [],
    },
    {
      timestamp: "2026-01-01T00:00:02Z",
      difference_kind: "POINT_ADDED",
      baseline_value: null,
      compare_value: 3,
      absolute_delta: null,
      baseline_occurrences: [],
      compare_occurrences: [{ timestamp: "2026-01-01T00:00:02Z", occurrence_index: 0, value: 3 }],
    },
    {
      timestamp: "2026-01-01T00:00:03Z",
      difference_kind: "POINT_REMOVED",
      baseline_value: 4,
      compare_value: null,
      absolute_delta: null,
      baseline_occurrences: [{ timestamp: "2026-01-01T00:00:03Z", occurrence_index: 0, value: 4 }],
      compare_occurrences: [],
    },
    {
      timestamp: "2026-01-01T00:00:04Z",
      difference_kind: "AMBIGUOUS_ALIGNMENT",
      baseline_value: null,
      compare_value: null,
      absolute_delta: null,
      baseline_occurrences: [
        { timestamp: "2026-01-01T00:00:04Z", occurrence_index: 0, value: 4 },
        { timestamp: "2026-01-01T00:00:04Z", occurrence_index: 1, value: 5 },
      ],
      compare_occurrences: [{ timestamp: "2026-01-01T00:00:04Z", occurrence_index: 0, value: 4.5 }],
    },
  ],
  difference_points_truncated: false,
  generic_diff_summary: {
    scope: "selected_channel",
    baseline_point_count: 4,
    compare_point_count: 4,
    unique_matched_timestamps: 2,
    unchanged_values: 1,
    changed_values: 1,
    added_points: 1,
    removed_points: 1,
    ambiguous_timestamp_groups: 1,
    baseline_duplicate_occurrences: 1,
    compare_duplicate_occurrences: 0,
    contains_null_transitions: false,
  },
  direct_derivation_summary: null,
  convergence_evidence: { baseline: null, compare: null },
  artifacts_identical: false,
  projection: {
    applied: false,
    max_points: 10_000,
    strategy: "none",
    diff_computed_before_projection: true,
  },
  warnings: [],
  ...overrides,
});

const deferred = <T>() => {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
};

const mountWorkbench = (versions: DatasetVersionNode[], currentVersionId: string) =>
  mount(CleaningVersionCompareWorkbench, {
    props: { dataset, versions, currentVersionId },
    global: { stubs },
  });

describe("CleaningVersionCompareWorkbench", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mockedChannels.mockResolvedValue(channelResponse());
    mockedCompare.mockResolvedValue(compareResponse());
  });

  it("uses two independent lineage pickers with the exact eligibility contract", async () => {
    const wrapper = mountWorkbench([raw, clean, simulation, lag, feature], clean.id);
    await flushPromises();
    const pickers = wrapper.findAllComponents(VersionLineagePicker);

    expect(pickers).toHaveLength(2);
    expect(pickers[0].props("selectedVersionId")).toBe(raw.id);
    expect(pickers[1].props("selectedVersionId")).toBe(clean.id);
    expect(pickers[0].props("selectedBadgeLabel")).toBe("比较基线");
    expect(pickers[1].props("selectedBadgeLabel")).toBe("对照版本");
    const eligible = pickers[0].props("isEligible") as (version: DatasetVersionNode) => boolean;
    expect([raw, clean, simulation].every(eligible)).toBe(true);
    expect([lag, feature].some(eligible)).toBe(false);

    pickers[0].vm.$emit("select", clean.id);
    await flushPromises();
    expect(pickers[0].props("selectedVersionId")).toBe(clean.id);
    expect(pickers[1].props("selectedVersionId")).toBe(clean.id);
  });

  it("implements all four deterministic default-pair cases", async () => {
    let wrapper = mountWorkbench([raw, clean], clean.id);
    await flushPromises();
    let pickers = wrapper.findAllComponents(VersionLineagePicker);
    expect(pickers.map((picker) => picker.props("selectedVersionId"))).toEqual([raw.id, clean.id]);
    wrapper.unmount();

    wrapper = mountWorkbench([raw, clean], raw.id);
    await flushPromises();
    pickers = wrapper.findAllComponents(VersionLineagePicker);
    expect(pickers.map((picker) => picker.props("selectedVersionId"))).toEqual([raw.id, clean.id]);
    wrapper.unmount();

    mockedChannels.mockClear();
    wrapper = mountWorkbench([raw, clean, branch], raw.id);
    await flushPromises();
    pickers = wrapper.findAllComponents(VersionLineagePicker);
    expect(pickers.map((picker) => picker.props("selectedVersionId"))).toEqual([raw.id, null]);
    expect(mockedChannels).not.toHaveBeenCalled();
    wrapper.unmount();

    wrapper = mountWorkbench([raw], raw.id);
    await flushPromises();
    pickers = wrapper.findAllComponents(VersionLineagePicker);
    expect(pickers.map((picker) => picker.props("selectedVersionId"))).toEqual([raw.id, raw.id]);
  });

  it("loads channels for pair changes, ignores stale metadata, and handles empty/warning states", async () => {
    const first = deferred<CleaningVersionCompareChannelsData>();
    const second = deferred<CleaningVersionCompareChannelsData>();
    mockedChannels.mockReset().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const wrapper = mountWorkbench([raw, clean], clean.id);
    await flushPromises();
    const pickers = wrapper.findAllComponents(VersionLineagePicker);

    pickers[0].vm.$emit("select", clean.id);
    await flushPromises();
    second.resolve(channelResponse(clean.id, clean.id, ["y"], ["unit metadata warning"]));
    await flushPromises();
    first.resolve(channelResponse(raw.id, clean.id, ["u1"]));
    await flushPromises();

    expect(wrapper.get<HTMLSelectElement>("[data-test='version-compare-channel']").element.value).toBe("y");
    expect(wrapper.text()).toContain("unit metadata warning");

    mockedChannels.mockResolvedValueOnce(channelResponse(clean.id, raw.id, []));
    pickers[1].vm.$emit("select", raw.id);
    await flushPromises();
    expect(wrapper.text()).toContain("两个版本没有可共同比较的数值通道");
    expect(wrapper.get<HTMLButtonElement>("[data-test='version-compare-submit']").element.disabled).toBe(true);
  });

  it("executes only on explicit submit and clears a result when the channel changes", async () => {
    const wrapper = mountWorkbench([raw, clean], clean.id);
    await flushPromises();
    expect(mockedCompare).not.toHaveBeenCalled();

    await wrapper.get("[data-test='version-compare-channel']").setValue("y");
    await flushPromises();
    expect(mockedCompare).not.toHaveBeenCalled();
    await wrapper.get("[data-test='version-compare-submit']").trigger("click");
    await flushPromises();

    expect(mockedCompare).toHaveBeenCalledWith(dataset.id, {
      baseline_version_id: raw.id,
      compare_version_id: clean.id,
      channel: "y",
      max_points: 10_000,
    });
    expect(wrapper.find("[data-test='version-compare-result']").exists()).toBe(true);

    await wrapper.get("[data-test='version-compare-channel']").setValue("u1");
    await flushPromises();
    expect(wrapper.find("[data-test='version-compare-result']").exists()).toBe(false);
    expect(mockedCompare).toHaveBeenCalledTimes(1);
  });

  it("protects execution results from stale requests", async () => {
    const first = deferred<CleaningVersionCompareData>();
    const second = deferred<CleaningVersionCompareData>();
    mockedCompare.mockReset().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const wrapper = mountWorkbench([raw, clean], clean.id);
    await flushPromises();

    await wrapper.get("[data-test='version-compare-submit']").trigger("click");
    await wrapper.get("[data-test='version-compare-channel']").setValue("y");
    await wrapper.get("[data-test='version-compare-submit']").trigger("click");
    second.resolve(compareResponse({
      channel: { name: "y", inferred_type: "float", unit: null },
      generic_diff_summary: { ...compareResponse().generic_diff_summary, changed_values: 7 },
    }));
    await flushPromises();
    first.resolve(compareResponse({ generic_diff_summary: { ...compareResponse().generic_diff_summary, changed_values: 99 } }));
    await flushPromises();

    expect(wrapper.get(".metric-card.changed").text()).toContain("7");
    expect(wrapper.get(".metric-card.changed").text()).not.toContain("99");
  });

  it("renders relation, summary, identity, projection notices, and the overlay contract", async () => {
    mockedCompare.mockResolvedValueOnce(compareResponse({
      artifacts_identical: true,
      projection: { applied: true, max_points: 10_000, strategy: "evenly_spaced_index_with_endpoints", diff_computed_before_projection: true },
      difference_points_truncated: true,
      warnings: ["compare warning"],
    }));
    const wrapper = mountWorkbench([raw, clean], clean.id);
    await flushPromises();
    await wrapper.get("[data-test='version-compare-submit']").trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("直接派生");
    expect(wrapper.text()).toContain("Baseline → Compare");
    expect(wrapper.text()).toContain("数据内容一致");
    expect(wrapper.text()).toContain("值变化1");
    expect(wrapper.text()).toContain("新增点1");
    expect(wrapper.text()).toContain("移除点1");
    expect(wrapper.text()).toContain("对齐歧义组1");
    expect(wrapper.text()).toContain("图形已抽样显示，差异统计基于完整数据");
    expect(wrapper.text()).toContain("差异统计完整，图中仅显示部分差异点");
    expect(wrapper.text()).toContain("compare warning");
    expect(wrapper.text()).toContain("未建立 occurrence 间的推测配对");

    const options = wrapper.getComponent(ChartContainerStub).props("options") as {
      xAxis: { type: string };
      dataZoom: Array<{ type: string }>;
      series: Array<{ id: string; name: string; type: string; lineStyle?: { type: string; color: string }; data: Array<{ value?: unknown } | unknown[]> }>;
    };
    expect(options.xAxis.type).toBe("time");
    expect(options.dataZoom.map((zoom) => zoom.type)).toEqual(["inside", "slider"]);
    expect(options.series.find((series) => series.id === "version-compare-baseline")).toEqual(expect.objectContaining({
      name: "Baseline",
      type: "line",
      lineStyle: expect.objectContaining({ type: "dashed", color: "#A8665E" }),
      data: expect.arrayContaining([["2026-01-01T00:00:00Z", 1]]),
    }));
    expect(options.series.find((series) => series.id === "version-compare-target")).toEqual(expect.objectContaining({
      name: "Compare",
      type: "line",
      lineStyle: expect.objectContaining({ type: "solid", color: "#557562" }),
    }));
    expect(options.series.find((series) => series.id === "version-difference-changed")?.data).toHaveLength(1);
    expect(options.series.find((series) => series.id === "version-difference-added")?.data).toHaveLength(1);
    expect(options.series.find((series) => series.id === "version-difference-removed")?.data).toHaveLength(1);
    expect(options.series.flatMap((series) => series.data).some((datum) =>
      !Array.isArray(datum) && datum.value instanceof Array && datum.value[0] === "2026-01-01T00:00:04Z"
    )).toBe(false);

    await wrapper.get("[data-test='version-compare-reset-zoom']").trigger("click");
    expect(chartDispatchAction).toHaveBeenCalledWith({ type: "dataZoom", start: 0, end: 100 });
  });

  it("renders same-version zero diff and scoped API errors without fallback", async () => {
    mockedCompare.mockResolvedValueOnce(compareResponse({
      relation: "SAME_VERSION",
      direction: "NONE",
      artifacts_identical: true,
      generic_diff_summary: {
        ...compareResponse().generic_diff_summary,
        changed_values: 0,
        added_points: 0,
        removed_points: 0,
        ambiguous_timestamp_groups: 0,
      },
      difference_points: [],
    }));
    let wrapper = mountWorkbench([raw], raw.id);
    await flushPromises();
    await wrapper.get("[data-test='version-compare-submit']").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("同一版本，无数据差异");
    wrapper.unmount();

    mockedChannels.mockRejectedValueOnce(new ApiError("DATASET_ARTIFACT_MISSING", "产物不存在", "request"));
    wrapper = mountWorkbench([raw, clean], clean.id);
    await flushPromises();
    expect(wrapper.text()).toContain("共同通道加载失败 [DATASET_ARTIFACT_MISSING]：产物不存在");
    wrapper.unmount();

    mockedChannels.mockResolvedValueOnce(channelResponse());
    mockedCompare.mockRejectedValueOnce(new ApiError("CLEANING_COMPARE_CHANNEL_INVALID", "观察通道无效", "request"));
    wrapper = mountWorkbench([raw, clean], clean.id);
    await flushPromises();
    await wrapper.get("[data-test='version-compare-submit']").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("版本比较失败 [CLEANING_COMPARE_CHANNEL_INVALID]：观察通道无效");
    expect(wrapper.get<HTMLSelectElement>("[data-test='version-compare-channel']").element.value).toBe("u1");
  });
});
