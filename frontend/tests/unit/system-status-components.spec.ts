import { beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { nextTick } from "vue";
import { createPinia, setActivePinia } from "pinia";
import AppHeader from "../../src/components/AppHeader.vue";
import DashboardView from "../../src/views/DashboardView.vue";
import SettingsView from "../../src/views/SettingsView.vue";
import { useSystemStore } from "../../src/stores/systemStore";
import { getDashboardLeaderboard } from "../../src/api/dashboard";
import { getDatasets } from "../../src/api/datasets";
import { getHealthLive, getHealthReady } from "../../src/api/health";
import { ElMessage } from "element-plus";

vi.mock("../../src/api/dashboard", () => ({ getDashboardLeaderboard: vi.fn() }));
vi.mock("../../src/api/datasets", () => ({ getDatasets: vi.fn() }));
vi.mock("../../src/api/health", () => ({ getHealthLive: vi.fn(), getHealthReady: vi.fn() }));
vi.mock("vue-router", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("element-plus", () => ({
  ElMessage: { success: vi.fn(), error: vi.fn() },
}));

const mockedGetDashboardLeaderboard = vi.mocked(getDashboardLeaderboard);
const mockedGetDatasets = vi.mocked(getDatasets);
const mockedGetHealthLive = vi.mocked(getHealthLive);
const mockedGetHealthReady = vi.mocked(getHealthReady);

const componentStubs = {
  "el-tooltip": { template: "<div><slot /></div>" },
  "el-icon": { template: "<span><slot /></span>" },
  "el-tag": { template: "<span><slot /></span>" },
  "el-button": { template: "<button @click=\"$emit('click')\"><slot /></button>" },
  "el-alert": { props: ["title"], template: "<div>{{ title }}<slot /></div>" },
  "el-empty": { props: ["description"], template: "<div>{{ description }}</div>" },
  "el-table": { template: "<div><slot /></div>" },
  "el-table-column": { template: "<div><slot /></div>" },
  "el-descriptions": { template: "<div><slot /></div>" },
  "el-descriptions-item": { template: "<div><slot /></div>" },
  "el-form": { template: "<form><slot /></form>" },
  "el-form-item": { template: "<div><slot /></div>" },
  "el-select": { template: "<select><slot /></select>" },
  "el-option": true,
  "el-input": true,
  DataAnalysis: true,
  ChatDotSquare: true,
  Lightning: true,
  Trophy: true,
  Connection: true,
  Refresh: true,
  Key: true,
  Check: true,
};

const mountWithPinia = (component: typeof AppHeader | typeof DashboardView | typeof SettingsView) => {
  const pinia = createPinia();
  setActivePinia(pinia);
  return mount(component, { global: { plugins: [pinia], stubs: componentStubs } });
};
const leaderboard = { items: [] };
const datasets = { items: [], page: { current_page: 1, page_size: 1, total_items: 2, total_pages: 2 } };

describe("system status components", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it.each([
    ["connecting", "Connecting"],
    ["ready", "System Ready"],
    ["offline", "Backend Offline"],
  ] as const)("renders %s as %s in the header", async (status, expected) => {
    const wrapper = mountWithPinia(AppHeader);
    useSystemStore().status = status;
    await nextTick();
    expect(wrapper.get(".status-text").text()).toBe(expected);
  });

  it("shows Dashboard failure instead of normal zero-data KPIs and supports a manual retry", async () => {
    mockedGetDatasets.mockRejectedValueOnce(new Error("Bad Gateway"));
    mockedGetDashboardLeaderboard.mockRejectedValueOnce(new Error("Bad Gateway"));
    const wrapper = mountWithPinia(DashboardView);
    await flushPromises();

    expect(wrapper.text()).toContain("Dashboard数据加载失败");
    expect(wrapper.text()).toContain("不可用");
    expect(wrapper.text()).not.toContain("0 个");

    mockedGetDatasets.mockResolvedValue(datasets);
    mockedGetDashboardLeaderboard.mockResolvedValue(leaderboard);
    const retryButton = wrapper.findAll("button").find((button) => button.text() === "重新加载");
    expect(retryButton).toBeDefined();
    await retryButton!.trigger("click");
    await flushPromises();

    expect(wrapper.text()).not.toContain("Dashboard数据加载失败");
    expect(wrapper.text()).toContain("真实记录");
  });

  it("retries a failed Dashboard request once when health recovers", async () => {
    mockedGetDatasets.mockRejectedValueOnce(new Error("Bad Gateway")).mockResolvedValue(datasets);
    mockedGetDashboardLeaderboard.mockRejectedValueOnce(new Error("Bad Gateway")).mockResolvedValue(leaderboard);
    const wrapper = mountWithPinia(DashboardView);
    const systemStore = useSystemStore();
    systemStore.status = "offline";
    await flushPromises();

    systemStore.status = "ready";
    await flushPromises();

    expect(mockedGetDashboardLeaderboard).toHaveBeenCalledTimes(2);
    expect(wrapper.text()).toContain("真实记录");
  });

  it("reports a real offline result in Settings without a mock success", async () => {
    mockedGetHealthLive.mockRejectedValue(new Error("connection refused"));
    const wrapper = mountWithPinia(SettingsView);

    await wrapper.get("button").trigger("click");
    await flushPromises();

    expect(useSystemStore().status).toBe("offline");
    expect(ElMessage.error).toHaveBeenCalledWith("Backend Offline：无法连接后端或其依赖未就绪");
    expect(ElMessage.success).not.toHaveBeenCalled();
  });
});
