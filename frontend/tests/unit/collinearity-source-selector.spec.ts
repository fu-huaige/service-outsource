import { beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { defineComponent, h } from "vue";
import CollinearityView from "../../src/views/CollinearityView.vue";
import { useDatasetStore } from "../../src/stores/datasetStore";
import type {
  CollinearityResponse,
  CollinearitySourceStatus,
  CollinearitySourceVersionsData,
  DatasetItem,
} from "../../src/types/api";

const apiMocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  messageSuccess: vi.fn(),
  messageError: vi.fn(),
  confirm: vi.fn(),
}));

vi.mock("../../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../src/api/client")>();
  return {
    ...actual,
    default: {
      get: apiMocks.get,
      post: apiMocks.post,
      delete: vi.fn(),
    },
  };
});

vi.mock("element-plus", () => ({
  ElMessage: { success: apiMocks.messageSuccess, error: apiMocks.messageError },
  ElMessageBox: { confirm: apiMocks.confirm },
}));

const ElSelectStub = defineComponent({
  name: "ElSelect",
  inheritAttrs: false,
  props: {
    modelValue: { type: String, default: "" },
    disabled: Boolean,
    loading: Boolean,
  },
  emits: ["update:modelValue", "change"],
  setup(props, { attrs, emit, slots }) {
    return () =>
      h(
        "select",
        {
          ...attrs,
          value: props.modelValue ?? "",
          disabled: props.disabled,
          "data-loading": String(props.loading),
          onChange: (event: Event) => {
            const value = (event.target as HTMLSelectElement).value;
            emit("update:modelValue", value);
            emit("change", value);
          },
        },
        [h("option", { value: "" }, "请选择"), slots.default?.()]
      );
  },
});

const ElOptionStub = defineComponent({
  name: "ElOption",
  props: { label: String, value: String },
  setup(props) {
    return () => h("option", { value: props.value }, props.label);
  },
});

const ElInputStub = defineComponent({
  name: "ElInput",
  props: { modelValue: { type: String, default: "" } },
  emits: ["update:modelValue"],
  setup(props, { emit }) {
    return () =>
      h("input", {
        value: props.modelValue,
        onInput: (event: Event) =>
          emit("update:modelValue", (event.target as HTMLInputElement).value),
      });
  },
});

const ElInputNumberStub = defineComponent({
  name: "ElInputNumber",
  props: { modelValue: Number },
  emits: ["update:modelValue"],
  setup(props, { emit }) {
    return () =>
      h("input", {
        type: "number",
        value: props.modelValue,
        onInput: (event: Event) =>
          emit("update:modelValue", Number((event.target as HTMLInputElement).value)),
      });
  },
});

const ElButtonStub = defineComponent({
  name: "ElButton",
  inheritAttrs: false,
  props: { disabled: Boolean, loading: Boolean },
  emits: ["click"],
  setup(props, { attrs, emit, slots }) {
    return () =>
      h(
        "button",
        {
          ...attrs,
          type: "button",
          disabled: props.disabled,
          "data-loading": String(props.loading),
          onClick: () => emit("click"),
        },
        slots.default?.()
      );
  },
});

const ElAlertStub = defineComponent({
  name: "ElAlert",
  props: { title: String, description: String },
  setup(props, { slots }) {
    return () =>
      h("div", { class: "el-alert-stub" }, [
        slots.title?.() ?? props.title,
        props.description ? h("span", props.description) : null,
      ]);
  },
});

const simpleSlotStub = { template: "<span><slot /></span>" };
const stubs = {
  "el-select": ElSelectStub,
  "el-option": ElOptionStub,
  "el-input": ElInputStub,
  "el-input-number": ElInputNumberStub,
  "el-button": ElButtonStub,
  "el-alert": ElAlertStub,
  "el-icon": simpleSlotStub,
  "el-tag": simpleSlotStub,
  ChartContainer: { template: '<div class="chart-container-stub" />' },
};

const dataset = (id: string, name = id): DatasetItem => ({
  id,
  name,
  version_id: `${id}-active-version`,
  latest_version_id: `${id}-latest-version`,
  file_size_bytes: 100,
  row_count: 120,
  col_count: 3,
  created_at: "2026-09-01T00:00:00Z",
  time_column: "timestamp",
  input_columns: ["u1", "u2"],
  output_column: "y",
});

const source = (
  versionId: string,
  status: CollinearitySourceStatus,
  index = 2
) => ({
  version_id: versionId,
  version_index: index,
  name: `V${index} · 时滞补偿`,
  operation_name: "preprocessing.lag_compensation",
  parent_version_id: `${versionId}-parent`,
  created_at: "2026-09-01T02:00:00Z",
  collinearity_status: status,
  latest_complete_collinearity_run_id: status === "complete" ? `${versionId}-run` : null,
});

const analysisResult = (
  sourceVersionId: string,
  datasetId: string,
  variables = ["u1", "u2"]
): CollinearityResponse => ({
  source_version_id: sourceVersionId,
  processing_run_id: `${sourceVersionId}-processing-run`,
  dataset_id: datasetId,
  task: { task_id: "task-id", status: "completed", stage: "completed", progress: 1 },
  variables,
  matrix: [
    [1, 0.2],
    [0.2, 1],
  ],
  spearman_matrix: [
    [1, 0.18],
    [0.18, 1],
  ],
  vif_scores: { [variables[0]]: 1.1, [variables[1]]: null },
  condition_number: 2.4,
  correlated_groups: [],
  recommendations: variables.map((variable) => ({
    variable,
    action: "keep" as const,
    reason: "stable",
    related_variables: [],
  })),
});

const sourceData = (
  datasetId: string,
  sources: ReturnType<typeof source>[],
  defaultSourceVersionId: string | null
): CollinearitySourceVersionsData => ({
  dataset_id: datasetId,
  default_source_version_id: defaultSourceVersionId,
  sources,
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

let datasetsResponse: DatasetItem[];
let detailResponses: Map<string, DatasetItem | Promise<DatasetItem>>;
let sourceResponses: Map<
  string,
  Array<CollinearitySourceVersionsData | Promise<CollinearitySourceVersionsData>>
>;
let sourceCallCounts: Map<string, number>;
let latestResponses: Map<string, CollinearityResponse | Promise<CollinearityResponse>>;

const installApiBehavior = () => {
  apiMocks.get.mockImplementation((url: string, config?: { params?: Record<string, string> }) => {
    if (url === "/datasets?page=1&page_size=100") {
      return Promise.resolve({ items: datasetsResponse });
    }
    if (url === "/preprocessing/collinearity/latest") {
      const versionId = config?.params?.version_id ?? "";
      const response = latestResponses.get(versionId);
      if (!response) return Promise.reject(new Error(`Missing latest response for ${versionId}`));
      return response instanceof Promise ? response : Promise.resolve(response);
    }
    const sourceMatch = url.match(/^\/datasets\/([^/]+)\/collinearity-sources$/);
    if (sourceMatch) {
      const datasetId = sourceMatch[1];
      const queue = sourceResponses.get(datasetId) ?? [];
      const callIndex = sourceCallCounts.get(datasetId) ?? 0;
      sourceCallCounts.set(datasetId, callIndex + 1);
      const response = queue[Math.min(callIndex, queue.length - 1)];
      if (!response) return Promise.reject(new Error(`Missing source response for ${datasetId}`));
      return response instanceof Promise ? response : Promise.resolve(response);
    }
    const detailMatch = url.match(/^\/datasets\/([^/]+)$/);
    if (detailMatch) {
      const response = detailResponses.get(detailMatch[1]);
      if (!response) return Promise.reject(new Error(`Missing detail response for ${detailMatch[1]}`));
      return response instanceof Promise ? response : Promise.resolve(response);
    }
    return Promise.reject(new Error(`Unexpected GET ${url}`));
  });
};

const mountView = (activeDataset: DatasetItem | null = null) => {
  const pinia = createPinia();
  setActivePinia(pinia);
  const store = useDatasetStore();
  store.setActiveDataset(activeDataset);
  const wrapper = mount(CollinearityView, {
    global: {
      plugins: [pinia],
      stubs,
      mocks: { $router: { push: vi.fn() } },
    },
  });
  return { wrapper, store };
};

describe("CollinearityView dataset and Lag Compensation source context", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    datasetsResponse = [];
    detailResponses = new Map();
    sourceResponses = new Map();
    sourceCallCounts = new Map();
    latestResponses = new Map();
    apiMocks.post.mockRejectedValue(new Error("Unexpected POST"));
    installApiBehavior();
  });

  it("loads datasets, preselects a valid active Dataset ID, selects the default source, and rehydrates complete results", async () => {
    const active = { ...dataset("dataset-a", "生产数据 A"), version_id: "version-not-a-dataset" };
    datasetsResponse = [active, dataset("dataset-b", "生产数据 B")];
    detailResponses.set("dataset-a", active);
    sourceResponses.set("dataset-a", [
      sourceData("dataset-a", [source("lag-a", "complete")], "lag-a"),
    ]);
    latestResponses.set("lag-a", analysisResult("lag-a", "dataset-a"));

    const { wrapper } = mountView(active);
    await flushPromises();

    expect(apiMocks.get).toHaveBeenCalledWith("/datasets?page=1&page_size=100");
    expect(wrapper.get<HTMLSelectElement>('[data-test="dataset-select"]').element.value).toBe(
      "dataset-a"
    );
    expect(wrapper.get<HTMLSelectElement>('[data-test="source-select"]').element.value).toBe(
      "lag-a"
    );
    expect(apiMocks.get).toHaveBeenCalledWith("/datasets/dataset-a/collinearity-sources");
    expect(apiMocks.get).not.toHaveBeenCalledWith(
      "/datasets/version-not-a-dataset/collinearity-sources"
    );
    expect(apiMocks.get).toHaveBeenCalledWith("/preprocessing/collinearity/latest", {
      params: { version_id: "lag-a", dataset_id: "dataset-a" },
    });
    expect(wrapper.find(".collin-tri-grid").exists()).toBe(true);
  });

  it("does not treat a stale active DatasetVersion ID as a Dataset ID", async () => {
    const active = { ...dataset("stale-dataset"), version_id: "dataset-b" };
    datasetsResponse = [dataset("dataset-b", "生产数据 B")];

    const { wrapper } = mountView(active);
    await flushPromises();

    expect(wrapper.get<HTMLSelectElement>('[data-test="dataset-select"]').element.value).toBe("");
    expect(apiMocks.get).not.toHaveBeenCalledWith("/datasets/dataset-b");
    expect(apiMocks.get).not.toHaveBeenCalledWith("/datasets/dataset-b/collinearity-sources");
  });

  it("clears a complete result when switching sources and never auto-POSTs not_analyzed or unrehydratable sources", async () => {
    const active = dataset("dataset-a");
    const sources = [
      source("lag-complete", "complete", 2),
      source("lag-new", "not_analyzed", 3),
      source("lag-legacy", "unrehydratable", 4),
    ];
    datasetsResponse = [active];
    detailResponses.set("dataset-a", active);
    sourceResponses.set("dataset-a", [sourceData("dataset-a", sources, "lag-complete")]);
    latestResponses.set("lag-complete", analysisResult("lag-complete", "dataset-a"));

    const { wrapper } = mountView(active);
    await flushPromises();
    expect(wrapper.find(".collin-tri-grid").exists()).toBe(true);

    await wrapper.get('[data-test="source-select"]').setValue("lag-new");
    await flushPromises();
    expect(wrapper.find(".collin-tri-grid").exists()).toBe(false);
    expect(wrapper.text()).toContain("该时滞补偿版本尚未进行共线性分析。");
    expect(apiMocks.post).not.toHaveBeenCalled();
    expect(
      apiMocks.get.mock.calls.filter(([url]) => url === "/preprocessing/collinearity/latest")
    ).toHaveLength(1);

    await wrapper.get('[data-test="source-select"]').setValue("lag-legacy");
    await flushPromises();
    expect(wrapper.text()).toContain(
      "该版本存在历史分析记录，但结果无法按当前格式完整恢复，可重新执行分析。"
    );
    expect(apiMocks.post).not.toHaveBeenCalled();
    expect(
      apiMocks.get.mock.calls.filter(([url]) => url === "/preprocessing/collinearity/latest")
    ).toHaveLength(1);
  });

  it("shows the explicit no-source state and disables Analyze without falling back", async () => {
    const active = dataset("dataset-a");
    datasetsResponse = [active];
    detailResponses.set("dataset-a", active);
    sourceResponses.set("dataset-a", [sourceData("dataset-a", [], null)]);

    const { wrapper } = mountView(active);
    await flushPromises();

    expect(wrapper.text()).toContain("该数据集暂无可用于共线性分析的时滞补偿版本。");
    expect(wrapper.text()).toContain("请先完成时滞补偿后再进行共线性分析。");
    expect(wrapper.get<HTMLButtonElement>('[data-test="analyze-button"]').element.disabled).toBe(
      true
    );
    expect(apiMocks.get).not.toHaveBeenCalledWith(
      "/preprocessing/collinearity/latest",
      expect.anything()
    );
    expect(apiMocks.post).not.toHaveBeenCalled();
  });

  it("clears Dataset A results immediately, requests Dataset B sources, and updates the SPA context", async () => {
    const active = dataset("dataset-a", "数据集 A");
    const next = dataset("dataset-b", "数据集 B");
    const nextDetail = deferred<DatasetItem>();
    datasetsResponse = [active, next];
    detailResponses.set("dataset-a", active);
    detailResponses.set("dataset-b", nextDetail.promise);
    sourceResponses.set("dataset-a", [
      sourceData("dataset-a", [source("lag-a", "complete")], "lag-a"),
    ]);
    sourceResponses.set("dataset-b", [
      sourceData("dataset-b", [source("lag-b", "not_analyzed")], "lag-b"),
    ]);
    latestResponses.set("lag-a", analysisResult("lag-a", "dataset-a"));

    const { wrapper, store } = mountView(active);
    await flushPromises();
    expect(wrapper.find(".collin-tri-grid").exists()).toBe(true);

    await wrapper.get('[data-test="dataset-select"]').setValue("dataset-b");
    expect(wrapper.find(".collin-tri-grid").exists()).toBe(false);
    expect(wrapper.get<HTMLSelectElement>('[data-test="source-select"]').element.value).toBe("");

    nextDetail.resolve(next);
    await flushPromises();
    expect(apiMocks.get).toHaveBeenCalledWith("/datasets/dataset-b/collinearity-sources");
    expect(wrapper.get<HTMLSelectElement>('[data-test="source-select"]').element.value).toBe(
      "lag-b"
    );
    expect(store.activeDataset?.id).toBe("dataset-b");
  });

  it("ignores an older Dataset detail request that resolves after a newer selection", async () => {
    const first = dataset("dataset-a", "数据集 A");
    const second = dataset("dataset-b", "数据集 B");
    const firstDetail = deferred<DatasetItem>();
    datasetsResponse = [first, second];
    detailResponses.set("dataset-a", firstDetail.promise);
    detailResponses.set("dataset-b", second);
    sourceResponses.set("dataset-b", [
      sourceData("dataset-b", [source("lag-b", "not_analyzed")], "lag-b"),
    ]);

    const { wrapper, store } = mountView();
    await flushPromises();
    await wrapper.get('[data-test="dataset-select"]').setValue("dataset-a");
    await wrapper.get('[data-test="dataset-select"]').setValue("dataset-b");
    await flushPromises();

    firstDetail.resolve(first);
    await flushPromises();

    expect(wrapper.get<HTMLSelectElement>('[data-test="dataset-select"]').element.value).toBe(
      "dataset-b"
    );
    expect(wrapper.get<HTMLSelectElement>('[data-test="source-select"]').element.value).toBe(
      "lag-b"
    );
    expect(store.activeDataset?.id).toBe("dataset-b");
    expect(apiMocks.get).not.toHaveBeenCalledWith("/datasets/dataset-a/collinearity-sources");
  });

  it("ignores an older complete-result rehydrate after the user selects a newer source", async () => {
    const active = dataset("dataset-a");
    const firstLatest = deferred<CollinearityResponse>();
    datasetsResponse = [active];
    detailResponses.set("dataset-a", active);
    sourceResponses.set("dataset-a", [
      sourceData(
        "dataset-a",
        [source("lag-old", "complete", 2), source("lag-new", "complete", 3)],
        "lag-old"
      ),
    ]);
    latestResponses.set("lag-old", firstLatest.promise);
    latestResponses.set(
      "lag-new",
      analysisResult("lag-new", "dataset-a", ["new-u1", "new-u2"])
    );

    const { wrapper } = mountView(active);
    await flushPromises();
    await wrapper.get('[data-test="source-select"]').setValue("lag-new");
    await flushPromises();
    expect(wrapper.get<HTMLInputElement>('[data-test="input-columns"]').element.value).toBe(
      "new-u1,new-u2"
    );

    firstLatest.resolve(analysisResult("lag-old", "dataset-a", ["old-u1", "old-u2"]));
    await flushPromises();
    expect(wrapper.get<HTMLSelectElement>('[data-test="source-select"]').element.value).toBe(
      "lag-new"
    );
    expect(wrapper.get<HTMLInputElement>('[data-test="input-columns"]').element.value).toBe(
      "new-u1,new-u2"
    );
  });

  it("POSTs Analyze with the selected source version, refreshes its status, and exposes no manual version input", async () => {
    const active = dataset("dataset-a");
    const pendingSource = source("lag-selected", "not_analyzed");
    const completeSource = source("lag-selected", "complete");
    datasetsResponse = [active];
    detailResponses.set("dataset-a", active);
    sourceResponses.set("dataset-a", [
      sourceData("dataset-a", [pendingSource], "lag-selected"),
      sourceData("dataset-a", [completeSource], "lag-selected"),
    ]);
    apiMocks.post.mockImplementation((url: string) => {
      if (url === "/preprocessing/collinearity") {
        return Promise.resolve(analysisResult("lag-selected", "dataset-a"));
      }
      return Promise.reject(new Error(`Unexpected POST ${url}`));
    });

    const { wrapper } = mountView(active);
    await flushPromises();
    expect(apiMocks.post).not.toHaveBeenCalled();
    expect(wrapper.text()).not.toContain("数据版本 ID");

    await wrapper.get('[data-test="analyze-button"]').trigger("click");
    await flushPromises();

    expect(apiMocks.post).toHaveBeenCalledWith("/preprocessing/collinearity", {
      version_id: "lag-selected",
      dataset_id: "dataset-a",
      input_columns: ["u1", "u2"],
      correlation_threshold: 0.85,
      vif_threshold: 10,
    });
    expect(sourceCallCounts.get("dataset-a")).toBe(2);
    expect(wrapper.get<HTMLSelectElement>('[data-test="source-select"]').element.value).toBe(
      "lag-selected"
    );
    expect(wrapper.text()).toContain("已完成，可恢复");
    expect(wrapper.find(".collin-tri-grid").exists()).toBe(true);
  });
});
