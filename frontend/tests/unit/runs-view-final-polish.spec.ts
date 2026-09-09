import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { beforeEach, describe, expect, it } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent, nextTick } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import RunsView from "../../src/views/RunsView.vue";

const ElSelectStub = defineComponent({
  name: "ElSelect",
  props: ["modelValue"],
  emits: ["update:modelValue"],
  template: "<div><slot /></div>",
});

const execution = (
  executionId: string,
  goal: string,
  status: string,
  createdAt: string
) => ({
  execution_id: executionId,
  workflow_status: status,
  created_at: createdAt,
  plan: { goal, steps: [{ step_id: "step-1" }] },
  artifacts: {},
});

beforeEach(() => {
  localStorage.clear();
});

describe("RunsView final polish", () => {
  it("keeps metadata content, filtering, sorting, and detail navigation while using Sans", async () => {
    localStorage.setItem("indusopt.recent_executions", JSON.stringify([
      execution("execution-new-123456", "最新分析数据", "SUCCEEDED", "2026-09-09T10:00:00Z"),
      execution("execution-old-123456", "较早失败任务", "FAILED", "2026-09-08T10:00:00Z"),
    ]));
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: "/:pathMatch(.*)*", component: { template: "<div />" } }],
    });
    await router.push("/runs");
    await router.isReady();
    const wrapper = mount(RunsView, {
      global: {
        plugins: [router],
        stubs: {
          PageHeader: { props: ["title", "description"], template: "<header><h1>{{ title }}</h1><p>{{ description }}</p><slot name='actions' /></header>" },
          AppEmptyState: { template: "<div data-test='empty-state' />" },
          ElSelect: ElSelectStub,
          ElOption: true,
        },
      },
    });
    await nextTick();

    const metadata = wrapper.findAll(".run-row__meta");
    expect(metadata).toHaveLength(2);
    expect(metadata[0]!.classes()).not.toContain("font-mono");
    expect(metadata[0]!.text()).toContain("execution-…");
    expect(metadata[0]!.text()).toContain("1 个阶段");

    const source = readFileSync(resolve(process.cwd(), "src/views/RunsView.vue"), "utf8");
    const metadataRule = source.match(/\.run-row__meta\s*\{([^}]+)\}/)?.[1] ?? "";
    expect(metadataRule).toContain("font-family: var(--font-sans)");
    expect(metadataRule).toContain("letter-spacing: normal");

    await wrapper.get(".runs-search-input").setValue("较早失败");
    expect(wrapper.findAll(".run-row")).toHaveLength(1);
    expect(wrapper.get(".run-row__goal").text()).toBe("较早失败任务");

    await wrapper.get(".runs-search-input").setValue("");
    const selects = wrapper.findAllComponents(ElSelectStub);
    selects[0]!.vm.$emit("update:modelValue", "FAILED");
    await nextTick();
    expect(wrapper.findAll(".run-row")).toHaveLength(1);
    expect(wrapper.get(".run-row__goal").text()).toBe("较早失败任务");

    selects[0]!.vm.$emit("update:modelValue", "");
    selects[1]!.vm.$emit("update:modelValue", "asc");
    await nextTick();
    expect(wrapper.findAll(".run-row__goal").map((node) => node.text())).toEqual([
      "较早失败任务",
      "最新分析数据",
    ]);

    await wrapper.findAll(".run-row")[0]!.trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.path).toBe("/workspace/execution-old-123456");
  });
});
