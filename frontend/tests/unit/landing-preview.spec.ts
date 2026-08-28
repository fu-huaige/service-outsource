import { afterEach, describe, expect, it, vi } from "vitest";
import { mount, type VueWrapper } from "@vue/test-utils";
import { createMemoryHistory, createRouter, type Router } from "vue-router";
import { nextTick } from "vue";
import DefaultLayout from "../../src/layouts/DefaultLayout.vue";
import appRouter from "../../src/router";
import LandingPreviewView from "../../src/views/LandingPreviewView.vue";

interface MountedPreview {
  wrapper: VueWrapper;
  router: Router;
}

const mountedWrappers: VueWrapper[] = [];
let animationFrameId = 0;
let animationFrames = new Map<number, FrameRequestCallback>();

interface MockEntryInput {
  target: Element;
  isIntersecting: boolean;
  top: number;
  bottom: number;
}

class MockIntersectionObserver {
  static instances: MockIntersectionObserver[] = [];

  readonly root = null;
  readonly rootMargin: string;
  readonly thresholds: readonly number[];
  readonly observe = vi.fn();
  readonly unobserve = vi.fn();
  readonly disconnect = vi.fn();
  readonly takeRecords = vi.fn(() => []);

  constructor(
    private readonly callback: IntersectionObserverCallback,
    options: IntersectionObserverInit = {}
  ) {
    this.rootMargin = options.rootMargin ?? "0px";
    this.thresholds = Array.isArray(options.threshold)
      ? options.threshold
      : [options.threshold ?? 0];
    MockIntersectionObserver.instances.push(this);
  }

  trigger(inputs: MockEntryInput[]) {
    const rootBounds = makeRect(96, 704);
    const entries = inputs.map((input) => ({
      time: 0,
      target: input.target,
      rootBounds,
      boundingClientRect: makeRect(input.top, input.bottom),
      intersectionRect: input.isIntersecting ? makeRect(96, 704) : makeRect(0, 0),
      isIntersecting: input.isIntersecting,
      intersectionRatio: input.isIntersecting ? 0.2 : 0,
    })) as IntersectionObserverEntry[];
    this.callback(entries, this as unknown as IntersectionObserver);
  }
}

function makeRect(top: number, bottom: number): DOMRectReadOnly {
  return {
    x: 0,
    y: top,
    top,
    right: 100,
    bottom,
    left: 0,
    width: 100,
    height: Math.max(0, bottom - top),
    toJSON: () => ({}),
  };
}

function installIntersectionObserver() {
  MockIntersectionObserver.instances = [];
  animationFrameId = 0;
  animationFrames = new Map();
  vi.stubGlobal("IntersectionObserver", MockIntersectionObserver);
  vi.stubGlobal(
    "requestAnimationFrame",
    vi.fn((callback: FrameRequestCallback) => {
      animationFrameId += 1;
      animationFrames.set(animationFrameId, callback);
      return animationFrameId;
    })
  );
  vi.stubGlobal(
    "cancelAnimationFrame",
    vi.fn((frameId: number) => animationFrames.delete(frameId))
  );
}

function setScrollY(value: number) {
  Object.defineProperty(window, "scrollY", { configurable: true, value });
}

async function flushAnimationFrames() {
  const callbacks = [...animationFrames.values()];
  animationFrames.clear();
  callbacks.forEach((callback) => callback(0));
  await nextTick();
}

async function scrollTo(value: number) {
  setScrollY(value);
  window.dispatchEvent(new Event("scroll"));
  await flushAnimationFrames();
}

function installMatchMedia(reducedMotion = false) {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: reducedMotion && query === "(prefers-reduced-motion: reduce)",
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
}

async function mountPreview(
  theme: "dark" | "light",
  options: { reducedMotion?: boolean; attachTo?: HTMLElement } = {}
): Promise<MountedPreview> {
  installMatchMedia(options.reducedMotion);
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: "/preview/:theme",
        component: LandingPreviewView,
        props: (route) => ({ theme: route.params.theme }),
      },
      { path: "/dashboard", component: { template: "<div>Dashboard</div>" } },
    ],
  });
  await router.push(`/preview/${theme}`);
  await router.isReady();
  const wrapper = mount(LandingPreviewView, {
    props: { theme },
    attachTo: options.attachTo,
    global: { plugins: [router] },
  });
  mountedWrappers.push(wrapper);
  await nextTick();
  return { wrapper, router };
}

afterEach(() => {
  mountedWrappers.splice(0).forEach((wrapper) => wrapper.unmount());
  document.body.innerHTML = "";
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("dual landing preview", () => {
  it("resolves both previews outside DefaultLayout without changing business routes", () => {
    const dark = appRouter.resolve("/landing-preview/dark");
    const light = appRouter.resolve("/landing-preview/light");
    const dashboard = appRouter.resolve("/dashboard");
    const copilot = appRouter.resolve("/copilot");

    expect(dark.name).toBe("LandingPreviewDark");
    expect(light.name).toBe("LandingPreviewLight");
    expect(dark.matched).toHaveLength(1);
    expect(light.matched).toHaveLength(1);
    expect(dark.matched.some((record) => record.components?.default === DefaultLayout)).toBe(false);
    expect(light.matched.some((record) => record.components?.default === DefaultLayout)).toBe(false);
    expect(dashboard.path).toBe("/dashboard");
    expect(copilot.path).toBe("/copilot");
    expect(dashboard.matched[0]?.components?.default).toBe(DefaultLayout);
    expect(copilot.matched[0]?.components?.default).toBe(DefaultLayout);
  });

  it("renders identical content structure with distinct dark and light themes", async () => {
    const dark = (await mountPreview("dark")).wrapper;
    const light = (await mountPreview("light")).wrapper;
    const sectionNames = (wrapper: VueWrapper) =>
      wrapper.findAll("[data-section]").map((section) => section.attributes("data-section"));

    expect(dark.get(".landing-preview").attributes("data-theme")).toBe("dark");
    expect(light.get(".landing-preview").attributes("data-theme")).toBe("light");
    expect(sectionNames(dark)).toEqual(sectionNames(light));
    expect(dark.get("h1").text()).toBe("让工业建模，从数据走向闭环决策");
    expect(light.get("h1").text()).toBe("让工业建模，从数据走向闭环决策");
    expect(dark.text()).toContain("按工程目标组合步骤，并非每个任务固定执行全部流程。");
    expect(dark.text()).toContain("Example Lineage");
  });

  it("navigates to the existing dashboard from Start Explore", async () => {
    const { wrapper, router } = await mountPreview("dark");
    const button = wrapper.findAll("button").find((candidate) => candidate.text().includes("开始探索"));

    expect(button).toBeDefined();
    await button?.trigger("click");
    await vi.waitFor(() => {
      expect(router.currentRoute.value.path).toBe("/dashboard");
    });
  });

  it("smooth scrolls to the Agent Workflow section", async () => {
    const host = document.createElement("div");
    document.body.appendChild(host);
    const { wrapper } = await mountPreview("light", { attachTo: host });
    const workflow = wrapper.get("#agent-workflow").element;
    const scrollIntoView = vi.fn();
    Object.defineProperty(workflow, "scrollIntoView", { configurable: true, value: scrollIntoView });
    const button = wrapper.findAll("button").find((candidate) => candidate.text() === "查看工作流程");

    expect(button).toBeDefined();
    await button?.trigger("click");
    expect(scrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "start" });
  });

  it("replays a section reveal after exit and supports both scroll directions", async () => {
    installIntersectionObserver();
    setScrollY(0);
    const { wrapper } = await mountPreview("light");
    const observer = MockIntersectionObserver.instances[0];
    const section = wrapper.get('[data-section="trusted-engineering"]');

    expect(observer).toBeDefined();
    expect(observer?.rootMargin).toBe("-12% 0px -12%");
    expect(section.classes()).toContain("reveal-from-bottom");
    expect(section.classes()).not.toContain("is-visible");

    await scrollTo(420);
    observer?.trigger([{ target: section.element, isIntersecting: true, top: 620, bottom: 1320 }]);
    await flushAnimationFrames();
    expect(section.classes()).toContain("is-visible");
    expect(section.classes()).toContain("reveal-from-bottom");

    await scrollTo(1380);
    observer?.trigger([{ target: section.element, isIntersecting: false, top: -720, bottom: 70 }]);
    expect(section.classes()).not.toContain("is-visible");
    expect(section.classes()).toContain("reveal-from-bottom");

    await scrollTo(1040);
    observer?.trigger([{ target: section.element, isIntersecting: true, top: -180, bottom: 560 }]);
    await flushAnimationFrames();
    expect(section.classes()).toContain("is-visible");
    expect(section.classes()).toContain("reveal-from-top");

    await scrollTo(300);
    observer?.trigger([{ target: section.element, isIntersecting: false, top: 730, bottom: 1450 }]);
    expect(section.classes()).not.toContain("is-visible");
    expect(section.classes()).toContain("reveal-from-top");

    await scrollTo(302);
    observer?.trigger([{ target: section.element, isIntersecting: true, top: 590, bottom: 1280 }]);
    await flushAnimationFrames();
    expect(section.classes()).toContain("is-visible");
    expect(section.classes()).toContain("reveal-from-top");

    await scrollTo(620);
    observer?.trigger([{ target: section.element, isIntersecting: false, top: -720, bottom: 70 }]);
    expect(section.classes()).not.toContain("is-visible");
    expect(section.classes()).toContain("reveal-from-bottom");

    observer?.trigger([{ target: section.element, isIntersecting: true, top: 590, bottom: 1280 }]);
    await flushAnimationFrames();
    expect(section.classes()).toContain("is-visible");
    expect(section.classes()).toContain("reveal-from-bottom");
    expect(observer?.unobserve).not.toHaveBeenCalled();
  });

  it("registers one passive scroll tracker and cleans up its pending frame", async () => {
    installIntersectionObserver();
    setScrollY(0);
    const addEventListener = vi.spyOn(window, "addEventListener");
    const removeEventListener = vi.spyOn(window, "removeEventListener");
    const { wrapper } = await mountPreview("light");
    const scrollRegistration = addEventListener.mock.calls.find(([event]) => event === "scroll");

    expect(scrollRegistration).toBeDefined();
    expect(scrollRegistration?.[2]).toEqual({ passive: true });

    setScrollY(20);
    window.dispatchEvent(new Event("scroll"));
    wrapper.unmount();

    expect(removeEventListener).toHaveBeenCalledWith("scroll", scrollRegistration?.[1]);
    expect(window.cancelAnimationFrame).toHaveBeenCalled();
  });

  it("keeps pointer interaction independent from replayable section observation", async () => {
    installIntersectionObserver();
    const { wrapper } = await mountPreview("dark");
    const arxNode = wrapper.findAll(".workflow-node").find((node) => node.text().includes("ARX"));

    expect(arxNode).toBeDefined();
    await arxNode?.trigger("pointerenter");
    expect(arxNode?.classes()).toContain("active");
    expect(MockIntersectionObserver.instances[0]?.unobserve).not.toHaveBeenCalled();
  });

  it("keeps all core content visible and exposes reduced-motion state", async () => {
    installIntersectionObserver();
    const addEventListener = vi.spyOn(window, "addEventListener");
    const { wrapper } = await mountPreview("dark", { reducedMotion: true });

    expect(wrapper.get(".landing-preview").attributes("data-reduced-motion")).toBe("true");
    expect(MockIntersectionObserver.instances).toHaveLength(0);
    expect(addEventListener.mock.calls.some(([event]) => event === "scroll")).toBe(false);
    expect(wrapper.text()).toContain("数据可信");
    expect(wrapper.text()).toContain("模型可信");
    expect(wrapper.text()).toContain("决策过程可信");
    expect(wrapper.text()).toContain("Human Approval");
    expect(wrapper.text()).toContain("User Trigger");
    expect(wrapper.text()).toContain("Held-out Evaluation");
    expect(wrapper.text()).not.toMatch(/(?:FIT|R²|RMSE)\s*[:：]?\s*-?\d/);
    wrapper.findAll("[data-section]").forEach((section) => {
      expect(section.classes()).toContain("is-visible");
    });
  });
});
