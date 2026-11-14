<template>
  <section class="prediction-charts" aria-label="逐样本评价">
    <p v-if="loading" role="status">正在读取评价预测文件…</p>
    <p v-else-if="message" role="status" data-test="fixed-evaluation-series-unavailable">{{ message }}</p>
    <template v-else-if="artifact && series">
      <header class="prediction-header">
        <h3>{{ artifact.target_variable }} · 逐样本评价</h3>
        <label v-if="artifact.horizons.length > 1">
          预测步
          <select v-model.number="step" aria-label="预测步">
            <option v-for="horizon in artifact.horizons" :key="horizon.horizon_step" :value="horizon.horizon_step">
              第 {{ horizon.horizon_step }} 步
            </option>
          </select>
        </label>
      </header>
      <section>
        <h4>真实值与预测值 <small>{{ axisName }}</small></h4>
        <ChartContainer :key="'prediction-' + step" :options="predictionChart" height="260px" />
      </section>
      <section>
        <h4>残差变化 <small>真实值 − 预测值</small></h4>
        <ChartContainer :key="'residual-' + step" :options="residualChart" height="210px" />
      </section>
      <section>
        <h4>残差分布 <small>各区间样本数</small></h4>
        <ChartContainer :options="distributionChart" height="190px" />
      </section>
      <section>
        <h4>残差自相关 <small v-if="series.acf">滞后单位为采样间隔</small></h4>
        <ChartContainer v-if="series.acf" :options="acfChart" height="190px" />
        <p v-else>仅对同一连续区段内、等间隔且有变化的残差计算 ACF。本次所选预测步没有满足条件的序列。</p>
      </section>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, shallowRef, watch } from 'vue';
import ChartContainer, { type ChartOption } from '../ChartContainer.vue';
import apiClient from '../../api/client';
import type { ModelEvaluationResult } from '../../types/api';

interface ForecastSeries {
  horizon_step: number;
  source_row_index: number[];
  timestamps: string[] | null;
  y_true: number[];
  y_pred: number[];
  residual: number[];
  acf: number[] | null;
}

interface PredictionArtifact {
  format_version: 1;
  target_variable: string;
  evaluation_run_id: string;
  model_id: string;
  training_run_id: string;
  model_type_id: ModelEvaluationResult['model_type_id'];
  dataset_version_id: string;
  experiment_spec_hash: string;
  partition: ModelEvaluationResult['partition'];
  horizons: ForecastSeries[];
}

const props = defineProps<{ evaluation: ModelEvaluationResult }>();
const artifact = shallowRef<PredictionArtifact>();
const step = ref(1);
const loading = ref(false);
const message = ref('');
const series = computed(() => artifact.value?.horizons.find(horizon => horizon.horizon_step === step.value));

watch(() => props.evaluation, async (result, _, onCleanup) => {
  const controller = new AbortController();
  onCleanup(() => controller.abort());
  artifact.value = undefined;
  step.value = 1;
  message.value = '';
  loading.value = false;
  if (!result.prediction_artifact_sha256) {
    message.value = '这次评价未保存逐样本真实值和预测值，暂无法绘制对比曲线和残差。';
    return;
  }
  loading.value = true;
  try {
    // The endpoint returns the verified JSON file directly.
    const data = await apiClient.get<unknown, PredictionArtifact>(
      '/modeling/evaluations/' + encodeURIComponent(result.evaluation_run_id) + '/predictions',
      { signal: controller.signal },
    );
    if (controller.signal.aborted) return;
    if (data.format_version !== 1 || data.evaluation_run_id !== result.evaluation_run_id ||
        data.model_id !== result.model_id || data.training_run_id !== result.training_run_id ||
        data.model_type_id !== result.model_type_id || data.partition !== result.partition ||
        data.dataset_version_id !== result.dataset_version_id ||
        data.experiment_spec_hash !== result.experiment_spec_hash ||
        data.horizons.length !== (result.horizon_metrics?.length || 1) ||
        !data.horizons.every((horizon, i) => horizon.horizon_step === i + 1 &&
          [horizon.source_row_index, horizon.y_true, horizon.y_pred, horizon.residual]
            .every(values => values.length === result.sample_count && values.every(Number.isFinite)) &&
          (!horizon.timestamps || horizon.timestamps.length === result.sample_count))) {
      message.value = '预测文件与当前评价不匹配。';
      return;
    }
    artifact.value = data;
  } catch {
    if (!controller.signal.aborted) message.value = '无法读取或校验评价预测文件。';
  } finally {
    if (!controller.signal.aborted) loading.value = false;
  }
}, { immediate: true });

const targetTimes = computed(() => {
  const times = series.value?.timestamps?.map(value => Date.parse(value));
  return times?.length && times.every((time, i) => Number.isFinite(time) && (i === 0 || time > times[i - 1]!))
    ? times
    : null;
});
const axisName = computed(() => targetTimes.value ? '目标时间' : '源数据行索引（从 0 开始）');
const axisLabels = computed(() => series.value?.source_row_index.map(String) ?? []);

function timelineValues(values: number[] = []) {
  return targetTimes.value?.map((time, i) => [time, values[i]!]) ?? values;
}
const grid = { top: 28, bottom: 34, left: 8, right: 12, containLabel: true };
const timeline = computed<ChartOption>(() => ({
  grid,
  tooltip: { trigger: 'axis' },
  xAxis: targetTimes.value
    ? { type: 'time', axisLabel: { hideOverlap: true } }
    : { type: 'category', data: axisLabels.value, axisLabel: { hideOverlap: true } },
  yAxis: { type: 'value', scale: true },
  dataZoom: [{ type: 'inside' }, { type: 'slider', height: 14, bottom: 2 }],
}));
const predictionChart = computed<ChartOption>(() => ({
  ...timeline.value,
  legend: { top: 0 },
  series: [
    { name: '真实值', type: 'line', data: timelineValues(series.value?.y_true), showSymbol: false, color: '#376452' },
    { name: '预测值', type: 'line', data: timelineValues(series.value?.y_pred), showSymbol: false, color: '#637d9b', lineStyle: { type: 'dashed' } },
  ],
}));
const residualChart = computed<ChartOption>(() => ({
  ...timeline.value,
  series: [{ name: '残差', type: 'line', data: timelineValues(series.value?.residual), showSymbol: false, color: '#376452',
    markLine: { silent: true, symbol: 'none', data: [{ yAxis: 0, name: '零基准' }] } }],
}));

const distributionChart = computed<ChartOption>(() => {
  const residual = series.value?.residual ?? [];
  if (!residual.length) return {};
  const { min, max } = residual.reduce(
    (bounds, value) => ({ min: Math.min(bounds.min, value), max: Math.max(bounds.max, value) }),
    { min: residual[0]!, max: residual[0]! },
  );
  const count = min === max ? 1 : Math.min(24, Math.ceil(Math.sqrt(residual.length)));
  const width = (max - min) / count;
  const bins = Array<number>(count).fill(0);
  for (const value of residual) {
    const index = width ? Math.min(count - 1, Math.floor((value - min) / width)) : 0;
    bins[index] = bins[index]! + 1;
  }
  const labels = bins.map((_, i) => width
    ? (min + i * width).toPrecision(4) + '–' + (min + (i + 1) * width).toPrecision(4)
    : min.toPrecision(5));
  return {
    grid, tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: labels, axisLabel: { hideOverlap: true } },
    yAxis: { type: 'value', minInterval: 1 },
    series: [{ name: '样本数', type: 'bar', data: bins, color: '#618670' }],
  };
});
const acfChart = computed<ChartOption>(() => ({
  grid, tooltip: { trigger: 'axis' },
  xAxis: { type: 'category', data: series.value?.acf?.map((_, lag) => String(lag)) },
  yAxis: { type: 'value', min: -1, max: 1 },
  series: [{ name: 'ACF', type: 'bar', data: series.value?.acf ?? [], color: '#618670' }],
}));
</script>

<style scoped>
.prediction-charts { display: grid; gap: 18px; }
.prediction-header { display: flex; align-items: baseline; flex-wrap: wrap; gap: 8px 14px; }
.prediction-header label { margin-left: auto; }
.prediction-header select { font: inherit; margin-left: 6px; }
h3, h4, p { margin: 0; }
h3 { font-size: 15px; }
h4 { font-size: 13px; }
small, p { color: var(--text-secondary); font-size: 12px; }
small { margin-left: 6px; font-weight: 400; }
</style>
