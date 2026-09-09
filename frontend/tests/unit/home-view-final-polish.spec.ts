import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import HomeView from "../../src/views/HomeView.vue";
import { listDatasets } from "../../src/api/datasets";
import type { DatasetItem } from "../../src/types/api";

const push = vi.fn();

vi.mock("vue-router", () => ({ useRouter: () => ({ push }) }));
vi.mock("../../src/api/datasets", () => ({ listDatasets: vi.fn() }));

const mockedListDatasets = vi.mocked(listDatasets);

const RouterLinkStub = {
  props: ["to"],
  template: '<a :data-to="to"><slot /></a>',
};

const dataset = (id: string, name: string): DatasetItem => ({
  id,
  name,
  version_id: `${id}-version`,
  file_size_bytes: 128,
  row_count: 10,
  col_count: 3,
  created_at: "2026-09-09T10:00:00Z",
  time_column: "timestamp",
  input_columns: ["u"],
  output_column: "y",
});

const recentExecution = (executionId: string, datasetId: string, goal: string) => ({
  execution_id: executionId,
  dataset_id: datasetId,
  workflow_status: "SUCCEEDED",
  created_at: "2026-09-09T10:00:00Z",
  plan: { goal },
});

const mountHome = () => mount(HomeView, {
  global: {
    stubs: {
      AgentComposer: { template: '<div data-test="agent-composer" />' },
      RouterLink: RouterLinkStub,
    },
  },
});

beforeEach(() => {
  localStorage.clear();
  push.mockReset();
  mockedListDatasets.mockReset();
});

describe("HomeView final polish", () => {
  it("resolves recent dataset names with one list request and safely falls back when absent", async () => {
    const knownDatasetId = "2ba22e3c-known-dataset";
    const missingDatasetId = "missing-dataset-id";
    localStorage.setItem("indusopt.recent_executions", JSON.stringify([
      recentExecution("execution-known", knownDatasetId, "分析数据"),
      recentExecution("execution-missing", missingDatasetId, "诊断历史数据"),
    ]));
    mockedListDatasets.mockResolvedValue({
      items: [dataset(knownDatasetId, "demo_cleaning_visible_diff")],
    });

    const wrapper = mountHome();
    await flushPromises();

    const labels = wrapper.findAll(".recent-item__dataset");
    expect(labels).toHaveLength(2);
    expect(labels[0]!.text()).toBe("数据集：demo_cleaning_visible_diff");
    expect(labels[0]!.attributes("title")).toBe("demo_cleaning_visible_diff");
    expect(labels[1]!.text()).toBe("数据集：未知数据集");
    expect(labels[1]!.attributes("title")).toBe(missingDatasetId);
    expect(wrapper.text()).not.toContain("Dataset:");
    expect(wrapper.text()).not.toContain(knownDatasetId);
    expect(wrapper.text()).not.toContain("undefined");
    expect(wrapper.text()).not.toContain("null");
    expect(mockedListDatasets).toHaveBeenCalledTimes(1);
    expect(mockedListDatasets).toHaveBeenCalledWith({ page: 1, page_size: 100 });
    expect(wrapper.get('.recent-item[data-to="/workspace/execution-known"]').exists()).toBe(true);
  });

  it("keeps long names accessible while using formal responsive layout spacing", async () => {
    const datasetId = "dataset-long-name";
    const longName = "demo_cleaning_visible_diff_with_a_very_long_dataset_name";
    localStorage.setItem("indusopt.recent_executions", JSON.stringify([
      recentExecution("execution-long", datasetId, "分析长名称数据集"),
    ]));
    mockedListDatasets.mockResolvedValue({ items: [dataset(datasetId, longName)] });

    const wrapper = mountHome();
    await flushPromises();

    expect(wrapper.get(".recent-item__dataset").attributes("title")).toBe(longName);

    const source = readFileSync(resolve(process.cwd(), "src/views/HomeView.vue"), "utf8");
    const homeRule = source.match(/\.home-view\s*\{([^}]+)\}/)?.[1] ?? "";
    const datasetRule = source.match(/\.recent-item__dataset\s*\{([^}]+)\}/)?.[1] ?? "";
    expect(homeRule).toContain("padding-top: calc(clamp(48px, 6vh, 88px) + var(--space-10))");
    expect(homeRule).not.toContain("transform");
    expect(homeRule).not.toContain("position:");
    expect(source).toContain("padding-top: calc(clamp(48px, 6vh, 88px) + var(--space-4))");
    expect(datasetRule).toContain("text-overflow: ellipsis");
    expect(datasetRule).toContain("white-space: nowrap");
    expect(datasetRule).toContain("font-family: var(--font-sans)");
  });
});
