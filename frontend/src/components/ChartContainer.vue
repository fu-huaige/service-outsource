<template>
  <div class="chart-wrapper">
    <div ref="chartRef" class="chart-canvas" :style="{ height: height || '350px' }"></div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch } from "vue";
import * as echarts from "echarts/core";
import { BarChart, HeatmapChart, LineChart, ScatterChart } from "echarts/charts";
import type {
  BarSeriesOption,
  HeatmapSeriesOption,
  LineSeriesOption,
  ScatterSeriesOption,
} from "echarts/charts";
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  MarkPointComponent,
  TooltipComponent,
  VisualMapComponent,
} from "echarts/components";
import type {
  DataZoomComponentOption,
  GridComponentOption,
  LegendComponentOption,
  TooltipComponentOption,
  VisualMapComponentOption,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { ComposeOption } from "echarts/core";

// Register only the chart types / components actually used across the app's
// ChartContainer consumers (Cleaning/Segmentation/Delay/Collinearity/
// ARXModeling/Optuna): line, bar, scatter and heatmap series, plus tooltip,
// legend, grid, dataZoom, visualMap and mark line/area/point. This keeps the
// bundle free of unused echarts modules (3D, maps, gl, etc.) that a full
// `import * as echarts from "echarts"` would otherwise pull in.
echarts.use([
  LineChart,
  BarChart,
  ScatterChart,
  HeatmapChart,
  TooltipComponent,
  LegendComponent,
  GridComponent,
  DataZoomComponent,
  VisualMapComponent,
  MarkLineComponent,
  MarkAreaComponent,
  MarkPointComponent,
  CanvasRenderer,
]);

export type ChartOption = ComposeOption<
  | LineSeriesOption
  | BarSeriesOption
  | ScatterSeriesOption
  | HeatmapSeriesOption
  | TooltipComponentOption
  | LegendComponentOption
  | GridComponentOption
  | DataZoomComponentOption
  | VisualMapComponentOption
>;

const props = defineProps<{
  options: ChartOption;
  height?: string;
}>();

const chartRef = ref<HTMLDivElement | null>(null);
let chartInstance: echarts.ECharts | null = null;

const initChart = () => {
  if (!chartRef.value) return;
  chartInstance = echarts.init(chartRef.value);
  chartInstance.setOption(props.options);
};

const handleResize = () => {
  chartInstance?.resize();
};

watch(
  () => props.options,
  (newOpt) => {
    // Incremental merge instead of a full notMerge rebuild: grid/tooltip/
    // legend/dataZoom state (e.g. current zoom window, legend toggles) is
    // preserved across data updates. `replaceMerge: ["series"]` still fully
    // replaces the series list (rather than merging it item-by-item), which
    // matters because some pages (e.g. DelayView) can change the *number* of
    // series between updates — a plain merge would leave stale series behind.
    chartInstance?.setOption(newOpt, { replaceMerge: ["series"] });
  },
  { deep: true }
);

onMounted(() => {
  initChart();
  window.addEventListener("resize", handleResize);
});

onBeforeUnmount(() => {
  window.removeEventListener("resize", handleResize);
  chartInstance?.dispose();
});
</script>

<style scoped>
.chart-wrapper {
  width: 100%;
}
.chart-canvas {
  width: 100%;
}
</style>
