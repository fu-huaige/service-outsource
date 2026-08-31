import { beforeEach, describe, expect, it } from "vitest";
import { createMemoryHistory } from "vue-router";
import DefaultLayout from "../../src/layouts/DefaultLayout.vue";
import { createAppRouter } from "../../src/router";
import { LANDING_SESSION_KEY } from "../../src/router/landingEntry";

function testRouter() {
  return createAppRouter(createMemoryHistory());
}

async function navigate(path: string) {
  const router = testRouter();
  await router.push(path);
  await router.isReady();
  return router;
}

beforeEach(() => {
  window.sessionStorage.clear();
});

describe("formal landing gate", () => {
  it("serves the accepted light landing at / without DefaultLayout", async () => {
    const router = await navigate("/");
    const route = router.currentRoute.value;

    expect(route.name).toBe("Landing");
    expect(route.matched).toHaveLength(1);
    expect(route.matched[0]?.props.default).toEqual({ theme: "light" });
    expect(route.matched.some((record) => record.components?.default === DefaultLayout)).toBe(false);
    expect(window.sessionStorage.getItem(LANDING_SESSION_KEY)).toBeNull();

    window.sessionStorage.setItem(LANDING_SESSION_KEY, "1");
    const enteredRouter = await navigate("/");
    expect(enteredRouter.currentRoute.value.name).toBe("Landing");
  });

  it("gates a fresh dashboard session and preserves its full target", async () => {
    const router = await navigate("/dashboard");

    expect(router.currentRoute.value.name).toBe("Landing");
    expect(router.currentRoute.value.query.next).toBe("/dashboard");
  });

  it("preserves an Agent execution deep link including query and hash", async () => {
    const target = "/copilot?execution_id=abc#workflow";
    const router = await navigate(target);

    expect(router.currentRoute.value.name).toBe("Landing");
    expect(router.currentRoute.value.query.next).toBe(target);
  });

  it("allows business routes directly after entry, including across router instances", async () => {
    window.sessionStorage.setItem(LANDING_SESSION_KEY, "1");

    const dashboardRouter = await navigate("/dashboard");
    expect(dashboardRouter.currentRoute.value.path).toBe("/dashboard");
    expect(dashboardRouter.currentRoute.value.matched[0]?.components?.default).toBe(DefaultLayout);

    const copilotRouter = await navigate("/copilot?execution_id=abc");
    expect(copilotRouter.currentRoute.value.fullPath).toBe("/copilot?execution_id=abc");
  });

  it("routes removed preview URLs through the existing public 404 flow", async () => {
    for (const path of ["/landing-preview/dark", "/landing-preview/light"]) {
      const router = await navigate(path);
      expect(router.currentRoute.value.path).toBe("/404");
      expect(router.currentRoute.value.matched).toHaveLength(1);
      expect(router.currentRoute.value.matched.some((record) => record.components?.default === DefaultLayout)).toBe(false);
      expect(window.sessionStorage.getItem(LANDING_SESSION_KEY)).toBeNull();
    }
  });

  it("preserves the existing public 404 behavior without a gate loop", async () => {
    const router = await navigate("/route-that-does-not-exist");

    expect(router.currentRoute.value.path).toBe("/404");
    expect(window.sessionStorage.getItem(LANDING_SESSION_KEY)).toBeNull();
  });
});
