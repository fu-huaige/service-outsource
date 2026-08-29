import { afterEach, describe, expect, it, vi } from "vitest";
import { mount, type VueWrapper } from "@vue/test-utils";
import { createMemoryHistory, createRouter, type Router } from "vue-router";
import { nextTick } from "vue";
import DefaultLayout from "../../src/layouts/DefaultLayout.vue";
import appRouter from "../../src/router";
import { LANDING_SESSION_KEY } from "../../src/router/landingEntry";
import LandingView from "../../src/views/LandingView.vue";

interface MountedLanding {
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

async function mountLanding(
  options: { reducedMotion?: boolean; attachTo?: HTMLElement } = {}
): Promise<MountedLanding> {
  installMatchMedia(options.reducedMotion);
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: "/",
        component: LandingView,
        props: { theme: "light" },
      },
      { path: "/dashboard", component: { template: "<div>Dashboard</div>" } },
      { path: "/copilot", component: { template: "<div>Copilot</div>" } },
    ],
  });
  await router.push("/");
  await router.isReady();
  const wrapper = mount(LandingView, {
    props: { theme: "light" },
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
  window.sessionStorage.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("formal landing", () => {
  it("resolves outside DefaultLayout without changing business routes", () => {
    const landing = appRouter.resolve("/");
    const dashboard = appRouter.resolve("/dashboard");
    const copilot = appRouter.resolve("/copilot");

    expect(landing.name).toBe("Landing");
    expect(landing.matched).toHaveLength(1);
    expect(landing.matched.some((record) => record.components?.default === DefaultLayout)).toBe(false);
    expect(dashboard.path).toBe("/dashboard");
    expect(copilot.path).toBe("/copilot");
    expect(dashboard.matched[0]?.components?.default).toBe(DefaultLayout);
    expect(copilot.matched[0]?.components?.default).toBe(DefaultLayout);
  });

  it("renders the accepted light landing content", async () => {
    const landing = (await mountLanding()).wrapper;

    expect(landing.get(".landing-preview").attributes("data-theme")).toBe("light");
    expect(landing.get("h1").text()).toBe("让工业建模，从数据走向闭环决策");
    expect(landing.text()).toContain("按工程目标组合步骤，并非每个任务固定执行全部流程。");
    expect(landing.text()).toContain("Example Lineage");
  });

  it("marks the session and replaces the landing route from every Start Explore CTA", async () => {
    const { wrapper, router } = await mountLanding();
    const replace = vi.spyOn(router, "replace").mockResolvedValue(undefined);
    const buttons = wrapper.findAll("button").filter((candidate) => candidate.text().includes("开始探索"));

    expect(buttons).toHaveLength(3);
    for (const button of buttons) {
      window.sessionStorage.removeItem(LANDING_SESSION_KEY);
      await button.trigger("click");
      expect(window.sessionStorage.getItem(LANDING_SESSION_KEY)).toBe("1");
      expect(replace).toHaveBeenLastCalledWith("/dashboard");
    }
  });

  it("replaces a complete safe next route and rejects external next values", async () => {
    const safe = "/copilot?execution_id=abc#workflow";
    const safeMount = await mountLanding();
    const safeRouter = safeMount.router;
    await safeRouter.replace({ path: "/", query: { next: safe } });
    const safeReplace = vi.spyOn(safeRouter, "replace").mockResolvedValue(undefined);

    await safeMount.wrapper.findAll("button").find((button) => button.text().includes("开始探索"))?.trigger("click");
    expect(safeReplace).toHaveBeenLastCalledWith(safe);

    for (const unsafe of ["https://example.com", "//example.com", "/\\example.com"]) {
      const unsafeMount = await mountLanding();
      await unsafeMount.router.replace({ path: "/", query: { next: unsafe } });
      const unsafeReplace = vi.spyOn(unsafeMount.router, "replace").mockResolvedValue(undefined);
      await unsafeMount.wrapper.findAll("button").find((button) => button.text().includes("开始探索"))?.trigger("click");
      expect(unsafeReplace).toHaveBeenLastCalledWith("/dashboard");
    }
  });

  it("smooth scrolls to the Agent Workflow section", async () => {
    const host = document.createElement("div");
    document.body.appendChild(host);
    const { wrapper } = await mountLanding({ attachTo: host });
    const workflow = wrapper.get("#agent-workflow").element;
    const scrollIntoView = vi.fn();
    Object.defineProperty(workflow, "scrollIntoView", { configurable: true, value: scrollIntoView });
    const button = wrapper.findAll("button").find((candidate) => candidate.text() === "查看工作流程");

    expect(button).toBeDefined();
    await button?.trigger("click");
    expect(scrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "start" });
    expect(window.sessionStorage.getItem(LANDING_SESSION_KEY)).toBeNull();
  });

  it("replays a section reveal after exit and supports both scroll directions", async () => {
    installIntersectionObserver();
    setScrollY(0);
    const { wrapper } = await mountLanding();
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
    const { wrapper } = await mountLanding();
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
    const { wrapper } = await mountLanding();
    const arxNode = wrapper.findAll(".workflow-node").find((node) => node.text().includes("ARX"));

    expect(arxNode).toBeDefined();
    await arxNode?.trigger("pointerenter");
    expect(arxNode?.classes()).toContain("active");
    expect(MockIntersectionObserver.instances[0]?.unobserve).not.toHaveBeenCalled();
  });

  it("keeps all core content visible and exposes reduced-motion state", async () => {
    installIntersectionObserver();
    const addEventListener = vi.spyOn(window, "addEventListener");
    const { wrapper } = await mountLanding({ reducedMotion: true });

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
