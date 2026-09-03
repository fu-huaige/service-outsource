import { defineComponent } from "vue";
import { flushPromises, shallowMount } from "@vue/test-utils";
import { createPinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import WorkspaceView from "../../src/views/WorkspaceView.vue";

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

vi.mock("vue-router", () => ({
  useRoute: () => route,
  useRouter: () => ({ push: routerPush }),
}));

vi.mock("../../src/api/copilot", () => copilotApi);

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

describe("WorkspaceView dataset context guard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    route.params = {};
    route.query = {};
    localStorage.clear();
    copilotApi.chatWithCopilot.mockResolvedValue({ execution_id: "execution-1" });
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
});
