import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import AgentComposer from "../../src/components/composer/AgentComposer.vue";
import { useDatasetStore } from "../../src/stores/datasetStore";
import type { DatasetItem } from "../../src/types/api";

const listDatasetsApi = vi.hoisted(() => vi.fn());
const messageApi = vi.hoisted(() => ({ warning: vi.fn(), error: vi.fn() }));

vi.mock("../../src/api/datasets", () => ({
  listDatasets: listDatasetsApi,
}));

vi.mock("element-plus", () => ({
  ElMessage: messageApi,
}));

const makeDataset = (index: number): DatasetItem => ({
  id: `dataset-${index}`,
  name: `数据集 ${index}`,
  version_id: `version-${index}`,
  file_size_bytes: 100,
  row_count: 1000 + index,
  col_count: 4,
  created_at: "2026-09-01T00:00:00Z",
  time_column: "timestamp",
  input_columns: ["u1", "u2"],
  output_column: "y",
});

const rect = (values: Partial<DOMRect>): DOMRect =>
  ({
    x: values.left ?? 0,
    y: values.top ?? 0,
    left: 0,
    top: 0,
    right: 0,
    bottom: 0,
    width: 0,
    height: 0,
    toJSON: () => ({}),
    ...values,
  }) as DOMRect;

describe("AgentComposer dataset picker viewport positioning", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setActivePinia(createPinia());
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 800 });
    Object.defineProperty(window, "innerHeight", { configurable: true, value: 600 });
    Object.defineProperty(window, "visualViewport", { configurable: true, value: undefined });
    listDatasetsApi.mockResolvedValue({
      items: Array.from({ length: 40 }, (_, index) => makeDataset(index + 1)),
    });
  });

  it("preserves an explicitly active dataset without loading a default", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    useDatasetStore().setActiveDataset(makeDataset(7));

    const wrapper = mount(AgentComposer, { global: { plugins: [pinia] } });
    await flushPromises();

    expect(wrapper.get(".attachment-name").text()).toBe("数据集 7");
    expect(listDatasetsApi).not.toHaveBeenCalled();
  });

  it("does not silently attach the first dataset on mount", async () => {
    const wrapper = mount(AgentComposer, { global: { plugins: [createPinia()] } });
    await flushPromises();

    expect(wrapper.find(".composer-attachments").exists()).toBe(false);
    expect(listDatasetsApi).not.toHaveBeenCalled();
  });

  it("loads datasets only after the picker is opened and allows an explicit choice", async () => {
    const wrapper = mount(AgentComposer, { global: { plugins: [createPinia()] } });

    await wrapper.get(".composer-btn--dataset").trigger("click");
    await flushPromises();
    expect(listDatasetsApi).toHaveBeenCalledWith({ page: 1, page_size: 50 });

    await wrapper.get(".dataset-picker__item").trigger("click");
    expect(wrapper.get(".attachment-name").text()).toBe("数据集 1");
    expect(useDatasetStore().activeDataset?.id).toBe("dataset-1");
  });

  it("warns and does not submit when no dataset is attached", async () => {
    const wrapper = mount(AgentComposer, { global: { plugins: [createPinia()] } });
    await wrapper.get(".composer-textarea").setValue("建立 ARX 模型");

    await wrapper.get(".composer-submit").trigger("click");

    expect(messageApi.warning).toHaveBeenCalledOnce();
    expect(wrapper.emitted("submit")).toBeUndefined();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("chooses the safer side, clamps to viewport margins, and keeps a long list internally scrollable", async () => {
    const wrapper = mount(AgentComposer, { global: { plugins: [createPinia()] } });
    let composerRect = rect({
      left: -40,
      right: 820,
      width: 860,
      top: 24,
      bottom: 170,
      height: 146,
    });
    vi.spyOn(
      wrapper.get<HTMLElement>(".agent-composer").element,
      "getBoundingClientRect"
    ).mockImplementation(() => composerRect);

    await wrapper.get(".composer-btn--dataset").trigger("click");
    await flushPromises();

    const picker = wrapper.get<HTMLElement>(".dataset-picker");
    expect(picker.classes()).toContain("is-positioned");
    expect(picker.element.style.top).toBe("178px");
    expect(picker.element.style.bottom).toBe("auto");
    expect(picker.element.style.left).toBe("12px");
    expect(picker.element.style.width).toBe("776px");
    expect(picker.element.style.maxHeight).toBe("288px");

    composerRect = rect({
      left: 20,
      right: 780,
      width: 760,
      top: 460,
      bottom: 580,
      height: 120,
    });
    window.dispatchEvent(new Event("scroll"));
    await wrapper.vm.$nextTick();

    expect(picker.element.style.top).toBe("auto");
    expect(picker.element.style.bottom).toBe("148px");
    expect(picker.element.style.maxHeight).toBe("288px");

    Object.defineProperty(window, "innerHeight", { configurable: true, value: 360 });
    composerRect = rect({
      left: 20,
      right: 780,
      width: 760,
      top: 160,
      bottom: 260,
      height: 100,
    });
    window.dispatchEvent(new Event("resize"));
    await wrapper.vm.$nextTick();

    expect(picker.element.style.bottom).toBe("208px");
    expect(picker.element.style.maxHeight).toBe("140px");
    expect(wrapper.findAll(".dataset-picker__item")).toHaveLength(40);

    wrapper.unmount();
  });
});
