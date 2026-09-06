import { describe, expect, it, vi } from "vitest";
import { mount } from "@vue/test-utils";
import ChartContainer from "../../src/components/ChartContainer.vue";

const chartMock = vi.hoisted(() => {
  const handlers = new Map<string, (params: unknown) => void>();
  const instance = {
    setOption: vi.fn(),
    on: vi.fn((event: string, handler: (params: unknown) => void) => {
      handlers.set(event, handler);
    }),
    off: vi.fn(),
    resize: vi.fn(),
    dispatchAction: vi.fn(),
    convertToPixel: vi.fn(() => [120, 180]),
    containPixel: vi.fn(() => true),
    getWidth: vi.fn(() => 640),
    getHeight: vi.fn(() => 420),
    dispose: vi.fn(),
  };
  return {
    handlers,
    instance,
    init: vi.fn(() => instance),
    use: vi.fn(),
  };
});

vi.mock("echarts/core", () => ({
  init: chartMock.init,
  use: chartMock.use,
}));

describe("ChartContainer interaction bridge", () => {
  it("forwards chart clicks and exposes generic chart actions", () => {
    const wrapper = mount(ChartContainer, {
      props: { options: {} },
    });
    const clickPayload = {
      seriesId: "stable-series-id",
      dataIndex: 2,
      data: { value: ["2026-01-01T00:00:02Z", 4.2] },
    };

    chartMock.handlers.get("click")?.(clickPayload);
    expect(wrapper.emitted("chartClick")).toEqual([[clickPayload]]);

    const action = { type: "dataZoom", start: 0, end: 100 };
    (wrapper.vm as unknown as { dispatchAction: (payload: typeof action) => void })
      .dispatchAction(action);
    expect(chartMock.instance.dispatchAction).toHaveBeenCalledWith(action);

    const chartApi = wrapper.vm as unknown as {
      convertToPixel: (finder: object, value: unknown) => number[] | null;
      containPixel: (finder: object, value: number[]) => boolean;
      getSize: () => { width: number; height: number };
    };
    expect(chartApi.convertToPixel(
      { xAxisIndex: 0, yAxisIndex: 0 },
      ["2026-01-01T00:00:02Z", 4.2]
    )).toEqual([120, 180]);
    expect(chartMock.instance.convertToPixel).toHaveBeenCalledWith(
      { xAxisIndex: 0, yAxisIndex: 0 },
      ["2026-01-01T00:00:02Z", 4.2]
    );
    expect(chartApi.containPixel({ gridIndex: 0 }, [120, 180])).toBe(true);
    expect(chartApi.getSize()).toEqual({ width: 640, height: 420 });

    chartMock.handlers.get("datazoom")?.({});
    expect(wrapper.emitted("chartViewportChange")).toHaveLength(1);
    window.dispatchEvent(new Event("resize"));
    expect(chartMock.instance.resize).toHaveBeenCalledOnce();
    expect(wrapper.emitted("chartViewportChange")).toHaveLength(2);

    wrapper.unmount();
    expect(chartMock.instance.off).toHaveBeenCalledWith("click", expect.any(Function));
    expect(chartMock.instance.off).toHaveBeenCalledWith("datazoom", expect.any(Function));
    expect(chartMock.instance.dispose).toHaveBeenCalledOnce();
  });
});
