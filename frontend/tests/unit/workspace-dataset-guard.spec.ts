import { defineComponent } from "vue";
import { flushPromises, shallowMount } from "@vue/test-utils";
import { createPinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import WorkspaceView from "../../src/views/WorkspaceView.vue";
import type { CopilotExecutionSnapshot, DatasetItem } from "../../src/types/api";

const route = vi.hoisted(() => ({
  params: {} as Record<string, string>,
  query: {} as Record<string, string>,
}));
const routerPush = vi.hoisted(() => vi.fn());
const copilotApi = vi.hoisted(() => ({
  chatWithCopilot: vi.fn(),
  getCopilotExecution: vi.fn(),
  confirmCopilotStep: vi.fn(),
  executeModelEvaluation: vi.fn(),
  executePipelineOptimization: vi.fn(),
}));
const messageApi = vi.hoisted(() => ({
  warning: vi.fn(),
  error: vi.fn(),
}));
const datasetApi = vi.hoisted(() => ({
  listDatasets: vi.fn(),
}));

vi.mock("vue-router", () => ({
  useRoute: () => route,
  useRouter: () => ({ push: routerPush }),
}));

vi.mock("../../src/api/copilot", () => copilotApi);
vi.mock("../../src/api/datasets", () => datasetApi);

vi.mock("element-plus", () => ({
  ElMessage: messageApi,
}));

function mountWorkspace(payload: {
  message: string;
  datasetId?: string | null;
  versionId?: string | null;
}) {
  const AgentComposer = defineComponent({
    name: "AgentComposer",
    emits: ["submit"],
    template: '<button class="composer-submit-stub" @click="$emit(\'submit\', payload)">submit</button>',
    setup() {
      return { payload };
    },
  });
  return shallowMount(WorkspaceView, {
    global: {
      plugins: [createPinia()],
      stubs: {
        AgentComposer,
        AgentStream: true,
        ArtifactWorkbench: true,
        RouterLink: true,
      },
    },
  });
}

const dataset = (id: string, name: string): DatasetItem => ({
  id,
  name,
  version_id: id + "-version",
  file_size_bytes: 128,
  row_count: 10,
  col_count: 3,
  created_at: "2026-09-09T10:00:00Z",
  time_column: "timestamp",
  input_columns: ["u"],
  output_column: "y",
});

const executionSnapshot = (): CopilotExecutionSnapshot => ({
  execution_id: "execution-visible-id",
  copilot_run_id: null,
  dataset_id: "dataset-visible-uuid",
  initial_version_id: "version-initial-uuid",
  current_version_id: "version-current-uuid",
  planner_source: "deterministic",
  workflow_status: "SUCCEEDED",
  current_step_id: null,
  pending_confirmation_step_id: null,
  plan: {
    goal: "分析长名称数据集",
    dataset_id: "dataset-visible-uuid",
    steps: [],
    stop_conditions: [],
    assumptions: [],
  },
  artifacts: {},
  error_code: null,
  error_message: null,
  created_at: "2026-09-09T10:00:00Z",
  updated_at: "2026-09-09T10:00:01Z",
  finished_at: "2026-09-09T10:00:01Z",
  step_runs: [],
});

describe("WorkspaceView dataset context guard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    route.params = {};
    route.query = {};
    localStorage.clear();
    copilotApi.chatWithCopilot.mockResolvedValue({ execution_id: "execution-1" });
    datasetApi.listDatasets.mockResolvedValue({ items: [] });
  });

  it("blocks a composer task without both dataset and version", async () => {
    const wrapper = mountWorkspace({ message: "建立 ARX 模型", datasetId: null, versionId: null });

    await wrapper.get(".composer-submit-stub").trigger("click");
    await flushPromises();

    expect(messageApi.warning).toHaveBeenCalledWith("请先挂载数据集后再发起 Agent 任务。");
    expect(copilotApi.chatWithCopilot).not.toHaveBeenCalled();
  });

  it("starts normally when dataset and version are both explicit", async () => {
    const wrapper = mountWorkspace({
      message: "建立 ARX 模型",
      datasetId: "dataset-1",
      versionId: "version-1",
    });

    await wrapper.get(".composer-submit-stub").trigger("click");
    await flushPromises();

    expect(copilotApi.chatWithCopilot).toHaveBeenCalledWith({
      message: "建立 ARX 模型",
      dataset_id: "dataset-1",
      active_version_id: "version-1",
    });
    expect(routerPush).toHaveBeenCalledWith("/workspace/execution-1");
  });

  it("blocks a direct Home query that has a prompt but no dataset context", async () => {
    route.query = { prompt: "完整建模流程" };

    mountWorkspace({ message: "unused" });
    await flushPromises();

    expect(messageApi.warning).toHaveBeenCalledWith("请先挂载数据集后再发起 Agent 任务。");
    expect(copilotApi.chatWithCopilot).not.toHaveBeenCalled();
  });

  it("shows the resolved dataset name and hides dataset and version UUIDs from the current-task summary", async () => {
    const longName = "verify_feature_apply_refresh_with_a_long_dataset_name";
    route.params = { executionId: "execution-visible-id" };
    copilotApi.getCopilotExecution.mockResolvedValue(executionSnapshot());
    datasetApi.listDatasets.mockResolvedValue({
      items: [dataset("dataset-visible-uuid", longName)],
    });

    const wrapper = mountWorkspace({ message: "unused" });
    await flushPromises();

    const metadata = wrapper.get(".ws-sidebar__dataset-meta");
    expect(metadata.text()).toBe("数据集：" + longName);
    expect(metadata.text()).not.toContain("dataset-visible-uuid");
    expect(metadata.text()).not.toContain("version-current-uuid");
    expect(metadata.get(".ws-sidebar__dataset-name").attributes("title")).toBe(longName);
    expect(copilotApi.getCopilotExecution).toHaveBeenCalledWith("execution-visible-id");
    expect(datasetApi.listDatasets).toHaveBeenCalledWith({ page: 1, page_size: 100 });

    const source = readFileSync(resolve(process.cwd(), "src/views/WorkspaceView.vue"), "utf8");
    const nameRule = source.match(/\.ws-sidebar__dataset-name\s*\{([^}]+)\}/)?.[1] ?? "";
    expect(nameRule).toContain("text-overflow: ellipsis");
    expect(nameRule).toContain("white-space: nowrap");
    const artifactExecution = wrapper.getComponent({ name: "ArtifactWorkbench" })
      .props("execution") as CopilotExecutionSnapshot;
    expect(artifactExecution.current_version_id).toBe("version-current-uuid");
    expect(artifactExecution.dataset_id).toBe("dataset-visible-uuid");
    expect(artifactExecution.execution_id).toBe("execution-visible-id");
    expect(source).not.toContain("execution.current_version_id.slice");
    expect(source).not.toContain("execution.dataset_id.slice");
  });

  it("lets the title shrink while status and workbench controls remain intact", () => {
    const source = readFileSync(resolve(process.cwd(), "src/views/WorkspaceView.vue"), "utf8");
    const topBar = source.match(/\.ws-top-bar\s*\{([^}]+)\}/)?.[1] ?? "";
    const left = source.match(/\.ws-top-bar__left\s*\{([^}]+)\}/)?.[1] ?? "";
    const goal = source.match(/\.ws-top-goal\s*\{([^}]+)\}/)?.[1] ?? "";
    const status = source.match(/\.ws-top-bar__left\s*>\s*\.status-badge\s*\{([^}]+)\}/)?.[1] ?? "";
    const right = source.match(/\.ws-top-bar__right\s*\{([^}]+)\}/)?.[1] ?? "";
    const button = source.match(/\.ws-top-btn\s*\{([^}]+)\}/)?.[1] ?? "";

    expect(topBar).toContain("min-width: 0");
    expect(left).toContain("flex: 1 1 auto");
    expect(left).toContain("min-width: 0");
    expect(goal).toContain("flex: 1 1 auto");
    expect(goal).toContain("min-width: 0");
    expect(goal).toContain("overflow: hidden");
    expect(goal).toContain("text-overflow: ellipsis");
    expect(goal).toContain("white-space: nowrap");
    expect(status).toContain("flex-shrink: 0");
    expect(status).toContain("white-space: nowrap");
    expect(right).toContain("flex-shrink: 0");
    expect(button).toContain("flex-shrink: 0");
    expect(button).toContain("white-space: nowrap");
    expect(button).not.toContain("width:");
  });
});
