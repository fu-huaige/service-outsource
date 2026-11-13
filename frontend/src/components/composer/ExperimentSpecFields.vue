<template>
  <fieldset :disabled="disabled" class="experiment-fields">
    <legend>实验配置 · 监督回归</legend>
    <p class="section-note">所选版本：{{ version.name }} · {{ version.row_count }} 行</p>

    <fieldset class="experiment-section">
      <legend>建模任务</legend>
      <div class="control-grid">
        <div class="control-field">
          <label :for="controlId('goal')">建模目标</label>
          <ElSelect
            :id="controlId('goal')"
            v-model="goal"
            :disabled="disabled"
            class="modeling-select"
            popper-class="modeling-select-popper"
            data-test="modeling-goal"
          >
            <ElOption label="由 Agent 判断" value="auto" />
            <ElOption label="静态回归" value="static_regression" />
            <ElOption label="非线性回归" value="nonlinear_regression" />
            <ElOption label="时序预测" value="temporal_forecast" />
          </ElSelect>
        </div>
        <div class="control-field">
          <label :for="controlId('target')">目标变量</label>
          <ElSelect
            :id="controlId('target')"
            v-model="target"
            :disabled="disabled"
            class="modeling-select"
            popper-class="modeling-select-popper"
            placeholder="请选择目标变量"
            data-test="modeling-target"
          >
            <ElOption label="请选择目标变量" value="" />
            <ElOption v-for="column in columns" :key="column" :label="column" :value="column" />
          </ElSelect>
        </div>
      </div>
    </fieldset>

    <fieldset class="experiment-section">
      <legend>输入变量</legend>
      <div class="variable-summary">
        <p>已选 {{ inputs.length }} 项</p>
        <p class="section-note">按勾选顺序提交</p>
      </div>
      <div class="variable-list">
        <label
          v-for="column in columns"
          :key="column"
          class="variable-option"
          :class="{ 'is-selected': inputOrder.has(column), 'is-disabled': disabled || column === target }"
        >
          <input
            v-model="inputs"
            type="checkbox"
            :value="column"
            :disabled="disabled || column === target"
            data-test="modeling-input"
          />
          <span class="variable-name">{{ column }}</span>
          <span v-if="column === target" class="section-note">目标变量</span>
          <span v-else-if="inputOrder.has(column)" class="variable-order">顺序 {{ inputOrder.get(column) }}</span>
        </label>
      </div>
      <p v-if="inputs.length" class="section-note input-order">输入顺序：{{ inputs.join(' → ') }}</p>
    </fieldset>

    <fieldset class="experiment-section">
      <legend>数据分区</legend>
      <p :id="controlId('range-help')" class="section-note">
        使用零基行号，起点包含、终点不包含。多个区间以逗号分隔，例如 0-120, 150-200。
      </p>
      <div class="control-grid">
        <div v-for="field in rangeFields" :key="field.id" class="control-field">
          <label :for="controlId(field.id)">{{ field.label }}</label>
          <input
            :id="controlId(field.id)"
            v-model="ranges[field.id]"
            class="modeling-input"
            type="text"
            :placeholder="field.placeholder"
            :aria-invalid="Boolean(rangeErrors[field.id])"
            :aria-describedby="controlId('range-help') + (rangeErrors[field.id] ? ' ' + controlId(field.id + '-error') : '')"
            :data-test="'modeling-' + field.id"
            @blur="rangeTouched[field.id] = true"
          />
          <p v-if="rangeErrors[field.id]" :id="controlId(field.id + '-error')" class="field-error">
            {{ rangeErrors[field.id] }}
          </p>
        </div>
      </div>
    </fieldset>

    <fieldset class="experiment-section">
      <legend>采样与预测配置</legend>
      <div v-if="version.time_column" class="control-grid">
        <div class="control-field">
          <label :for="controlId('sampling')">采样状态 · {{ version.time_column }}</label>
          <ElSelect
            :id="controlId('sampling')"
            v-model="sampling"
            :disabled="disabled"
            class="modeling-select"
            popper-class="modeling-select-popper"
            data-test="modeling-sampling"
          >
            <ElOption label="尚未核验" value="unknown" />
            <ElOption label="等间隔" value="uniform" />
            <ElOption label="非等间隔" value="irregular" />
          </ElSelect>
        </div>
        <div v-if="sampling === 'uniform'" class="control-field">
          <label :for="controlId('period')">采样周期（秒）</label>
          <input
            :id="controlId('period')"
            v-model="period"
            class="modeling-input"
            type="number"
            min="0"
            step="any"
            :aria-invalid="validated.field === 'period'"
            :aria-describedby="validated.field === 'period' ? controlId('spec-issue') : undefined"
            data-test="modeling-period"
          />
        </div>
      </div>
      <label class="variable-option" :class="{ 'is-selected': useForecast, 'is-disabled': disabled }">
        <input v-model="useForecast" type="checkbox" data-test="modeling-forecast" />
        <span class="variable-name">配置 TimeXer 预测时域</span>
      </label>
      <fieldset v-if="useForecast" class="forecast-fields">
        <legend>TimeXer 预测契约</legend>
        <div class="control-grid">
          <div v-for="field in forecastFields" :key="field.id" class="control-field">
            <label :for="controlId(field.id)">{{ field.label }}</label>
            <input
              :id="controlId(field.id)"
              v-model="forecast[field.id]"
              class="modeling-input"
              type="number"
              :min="field.min"
              :max="field.max"
              step="1"
              :aria-invalid="validated.field === field.id"
              :aria-describedby="validated.field === field.id ? controlId('spec-issue') : undefined"
              :data-test="'modeling-' + field.id"
            />
          </div>
        </div>
      </fieldset>
    </fieldset>

    <p v-if="issue" :id="controlId('spec-issue')" class="form-issue" role="status" data-test="modeling-spec-issue">{{ issue }}</p>
  </fieldset>
</template>

<script setup lang="ts">
import { computed, reactive, ref, useId, watch } from 'vue';
import { ElOption, ElSelect } from 'element-plus';
import type {
  DatasetVersionNode,
  ExperimentRowRange,
  ExperimentSpec,
  ModelRecommendationRequest,
} from '../../types/api';

const props = defineProps<{ datasetId: string; version: DatasetVersionNode; disabled?: boolean }>();
const emit = defineEmits<{ change: [request: ModelRecommendationRequest | null] }>();

const columns = computed(() => [...new Set([
  ...(props.version.input_columns ?? []),
  ...(props.version.output_column ? [props.version.output_column] : []),
])]);
const goal = ref<NonNullable<ModelRecommendationRequest['goal']>>('auto');
const target = ref(props.version.output_column ?? '');
const inputs = ref<string[]>([]);
const inputOrder = computed(() => new Map(inputs.value.map((column, index) => [column, index + 1])));
const formId = useId();
const controlId = (name: string) => formId + '-' + name;
const sampling = ref<ExperimentSpec['time_axis']['sampling_status']>('unknown');
const period = ref<number | string>('');
const useForecast = ref(false);
const ranges = reactive({ continuous: '', train: '', validation: '', test: '' });
const rangeFields = [
  { id: 'continuous', label: '连续区段', placeholder: '例如 0-120, 150-200' },
  { id: 'train', label: '训练集（Train）', placeholder: '例如 0-80' },
  { id: 'validation', label: '验证集（Validation）', placeholder: '例如 80-100' },
  { id: 'test', label: '测试集（Test）', placeholder: '例如 100-120' },
] as const;
type RangeField = typeof rangeFields[number]['id'];
const rangeTouched = reactive<Partial<Record<RangeField, boolean>>>({});
const forecast = reactive({
  target_window_length: '',
  exogenous_window_length: '',
  prediction_length: '',
  patch_length: 8,
});
const forecastFields = [
  { id: 'target_window_length', label: '目标历史窗口（T）', min: 8, max: 256 },
  { id: 'exogenous_window_length', label: '外生变量历史窗口（Tex）', min: 8, max: 256 },
  { id: 'prediction_length', label: '未来预测步数（H）', min: 1, max: 32 },
  { id: 'patch_length', label: 'Patch 长度', min: 4, max: 32 },
] as const;

watch(target, column => {
  inputs.value = inputs.value.filter(input => input !== column);
});

function parseRanges(value: string, rowCount: number): ExperimentRowRange[] | null {
  if (!value.trim()) return null;
  const output: ExperimentRowRange[] = [];
  for (const token of value.split(/[,，]/)) {
    const match = /^(\d+)\s*-\s*(\d+)$/.exec(token.trim());
    if (!match) return null;
    const start = Number(match[1]);
    const stop = Number(match[2]);
    if (!Number.isSafeInteger(start) || !Number.isSafeInteger(stop) ||
        stop <= start || stop > rowCount || start < (output.at(-1)?.stop ?? 0)) return null;
    output.push({ start, stop });
  }
  return output;
}

const parsedRanges = computed(() => ({
  continuous: parseRanges(ranges.continuous, props.version.row_count),
  train: parseRanges(ranges.train, props.version.row_count),
  validation: parseRanges(ranges.validation, props.version.row_count),
  test: parseRanges(ranges.test, props.version.row_count),
}));

function fitsContinuousRun(interval: ExperimentRowRange, runs: ExperimentRowRange[]) {
  return runs.some(run => run.start <= interval.start && interval.stop <= run.stop);
}

const rangeErrors = computed(() => {
  const errors: Partial<Record<RangeField, string>> = {};
  const { continuous, train, validation, test } = parsedRanges.value;
  for (const { id } of rangeFields) {
    if (!parsedRanges.value[id] && (rangeTouched[id] || ranges[id].trim())) {
      errors[id] = '请输入有效的行区间，按行号排列且不可重叠。';
    }
  }
  if (train && validation && train.at(-1)!.stop > validation[0]!.start) {
    errors.validation = '验证集起点不能早于训练集终点。';
  }
  if (validation && test && validation.at(-1)!.stop > test[0]!.start) {
    errors.test = '测试集起点不能早于验证集终点。';
  }
  if (continuous) {
    for (const id of ['train', 'validation', 'test'] as const) {
      if (!errors[id] && parsedRanges.value[id]?.some(range => !fitsContinuousRun(range, continuous))) {
        errors[id] = '该分区的每个区间必须完整落在一个连续区段内。';
      }
    }
  }
  return errors;
});

const validated = computed<{ request?: ModelRecommendationRequest; issue?: string; field?: string }>(() => {
  const version = props.version;
  const sha = version.sha256;
  if (!sha || !/^[a-f0-9]{64}$/.test(sha)) return { issue: '所选版本缺少可信 CSV SHA-256，无法推荐模型。' };
  if (!Number.isSafeInteger(version.row_count) || version.row_count < 1) return { issue: '所选版本缺少有效行数。' };
  if (columns.value.length < 2) return { issue: '所选版本缺少列角色，请先在数据资产中配置目标变量和输入变量。' };
  if (!columns.value.includes(target.value)) return { issue: '请选择目标变量。' };
  if (!inputs.value.length || inputs.value.some(input => input === target.value || !columns.value.includes(input))) {
    return { issue: '请选择至少一个与目标不同的输入变量。' };
  }

  const { continuous, train, validation, test } = parsedRanges.value;
  if (!continuous || !train || !validation || !test) {
    const invalid = rangeFields.find(field => !parsedRanges.value[field.id]);
    return { issue: '请填写有效的' + invalid?.label + '，区间应按行号排列且不重叠。' };
  }
  if (train.at(-1)!.stop > validation[0]!.start || validation.at(-1)!.stop > test[0]!.start) {
    return { issue: '训练集、验证集、测试集应按时间顺序排列且不重叠。' };
  }
  if ([...train, ...validation, ...test].some(range => !fitsContinuousRun(range, continuous))) return { issue: '每个分区区间必须完整落在一个连续区段内。' };

  const samplePeriod = Number(period.value);
  if (sampling.value === 'uniform' && (!Number.isFinite(samplePeriod) || samplePeriod <= 0)) {
    return { issue: '等间隔采样需要填写大于零的采样周期。', field: 'period' };
  }
  const request: ModelRecommendationRequest = {
    goal: goal.value,
    experiment_spec: {
      spec_version: 1,
      task_type: 'supervised_regression',
      dataset_id: props.datasetId,
      dataset_version_id: version.id,
      dataset_version_sha256: sha,
      row_count: version.row_count,
      target_column: target.value,
      input_columns: [...inputs.value],
      time_axis: {
        column: version.time_column ?? null,
        sample_period_seconds: sampling.value === 'uniform' ? samplePeriod : null,
        sampling_status: sampling.value,
        timestamp_policy: 'preserve_source',
      },
      feature_spec: { kind: 'tabular', prediction_horizon: 1 },
      continuous_runs: continuous,
      split: { train, validation, test },
      training_selection: { mode: 'full_train' },
      evaluation: { scopes: ['validation'], prediction_modes: ['prediction'] },
    },
  };
  if (useForecast.value) {
    if (!version.time_column || sampling.value !== 'uniform') {
      return { issue: 'TimeXer 需要时间列和等间隔采样配置。' };
    }
    for (const field of forecastFields) {
      const value = Number(forecast[field.id]);
      if (!Number.isInteger(value) || value < field.min || value > field.max) {
        return { issue: field.label + '应为 ' + field.min + '–' + field.max + ' 的整数。', field: field.id };
      }
    }
    const targetLength = Number(forecast.target_window_length);
    const patch = Number(forecast.patch_length);
    if (targetLength % patch !== 0 || targetLength / patch < 2 || targetLength / patch > 32) {
      return { issue: '目标历史窗口应包含 2–32 个完整 Patch。', field: 'patch_length' };
    }
    request.forecast_spec = {
      target_window_length: targetLength,
      exogenous_window_length: Number(forecast.exogenous_window_length),
      prediction_length: Number(forecast.prediction_length),
    };
    request.parameters = { timexer: { patch_length: patch } };
  }
  return { request };
});
const issue = computed(() => validated.value.issue);
watch(validated, ({ request }) => emit('change', request ?? null), { immediate: true });
</script>

<style scoped>
.experiment-fields {
  --modeling-control-height: 36px;
  display: grid;
  gap: 12px;
  min-inline-size: 0;
  margin: 0;
  padding: 4px 0 0;
  border: 0;
  text-align: left;
  color: var(--text-primary);
}

.experiment-fields p {
  margin: 0;
}

.experiment-fields legend {
  padding: 0;
  color: var(--text-primary);
  font-family: var(--font-sans);
  font-size: var(--font-size-base);
  font-weight: 600;
  line-height: var(--line-height-tight);
}

.experiment-fields > legend {
  font-size: var(--font-size-md);
}

.experiment-section {
  display: grid;
  gap: 8px;
  min-inline-size: 0;
  margin: 0;
  padding: 10px 12px 12px;
  border: 1px solid var(--border-default);
  border-radius: 8px;
  background: var(--surface-1);
}

/* Place the semantic legend inside the card instead of on its border. */
.experiment-section > legend,
.forecast-fields > legend {
  float: left;
  inline-size: 100%;
}

.control-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 180px), 1fr));
  gap: 10px 12px;
}

.control-field {
  display: grid;
  align-content: start;
  gap: 4px;
  min-width: 0;
}

.control-field label,
.section-note {
  color: var(--text-secondary);
}

.modeling-select,
.modeling-input {
  width: 100%;
  min-width: 0;
}

.modeling-select :deep(.el-select__wrapper),
.modeling-input {
  min-height: var(--modeling-control-height);
  border-radius: 6px;
  background: var(--surface-2);
  transition: background-color 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease;
}

.modeling-select :deep(.el-select__wrapper) {
  box-shadow: 0 0 0 1px var(--border-default) inset;
}

.modeling-select :deep(.el-select__caret) {
  color: var(--text-secondary);
}

.modeling-select :deep(.el-select__wrapper.is-hovering:not(.is-disabled)),
.modeling-input:hover:not(:disabled) {
  background: var(--surface-hover);
}

.modeling-select :deep(.el-select__wrapper.is-hovering:not(.is-disabled)) {
  box-shadow: 0 0 0 1px var(--accent-border) inset;
}

.modeling-select :deep(.el-select__wrapper.is-focused:not(.is-disabled)),
.modeling-select :deep(.el-select__wrapper:not(.is-disabled):has(input:focus-visible)) {
  background: var(--surface-1);
  box-shadow: 0 0 0 1px var(--border-focus) inset, 0 0 0 2px var(--accent-soft);
}

.modeling-select :deep(.el-select__wrapper.is-disabled),
.modeling-input:disabled {
  background: var(--surface-3);
  color: var(--text-tertiary);
  cursor: not-allowed;
}

:global(.modeling-select-popper .el-select-dropdown__item.is-hovering:not(.is-disabled)) {
  background: var(--accent-soft);
}

:global(.modeling-select-popper .el-select-dropdown__item.is-selected:not(.is-disabled)) {
  background: var(--accent-soft);
  color: var(--accent-dark);
}

.modeling-input {
  padding: 4px 10px;
  border: 1px solid var(--border-default);
  color: inherit;
  font: inherit;
}

.modeling-input:hover:not(:disabled) {
  border-color: var(--accent-border);
}

.modeling-input:focus {
  outline: none;
  border-color: var(--border-focus);
  background: var(--surface-1);
}

.modeling-input:focus-visible {
  box-shadow: 0 0 0 2px var(--accent-soft);
}

.modeling-input[aria-invalid="true"]:not(:disabled) {
  border-color: var(--danger);
}

.modeling-input[aria-invalid="true"]:focus-visible {
  box-shadow: 0 0 0 2px var(--danger-soft);
}

.field-error,
.form-issue {
  color: var(--danger);
}

.form-issue {
  padding: 8px 10px;
  border: 1px solid var(--color-error-border);
  border-radius: 6px;
  background: var(--danger-soft);
}

.variable-summary,
.variable-option {
  display: flex;
  align-items: center;
  gap: 8px;
}

.variable-summary {
  justify-content: space-between;
  flex-wrap: wrap;
}

.variable-list {
  display: grid;
  gap: 6px;
}

.variable-option {
  min-height: var(--modeling-control-height);
  padding: 6px 10px;
  border: 1px solid var(--border-default);
  border-radius: 6px;
  background: var(--surface-2);
  cursor: pointer;
  transition: background-color 0.15s ease, border-color 0.15s ease;
}

.variable-option:hover:not(.is-disabled),
.variable-option.is-selected:not(.is-disabled) {
  border-color: var(--accent-border);
  background: var(--accent-soft);
}

.variable-option.is-selected:not(.is-disabled) {
  border-color: var(--border-focus);
}

.variable-option:has(input:focus-visible) {
  outline: 2px solid var(--border-focus);
  outline-offset: 1px;
}

.variable-option.is-disabled {
  color: var(--text-tertiary);
  cursor: not-allowed;
}

.variable-option input {
  flex: 0 0 16px;
  inline-size: 16px;
  block-size: 16px;
  margin: 0;
  accent-color: var(--accent);
  cursor: inherit;
}

.variable-name {
  flex: 1;
  min-width: 0;
  overflow-wrap: anywhere;
}

.variable-order {
  flex-shrink: 0;
  color: var(--accent-dark);
}

.input-order {
  overflow-wrap: anywhere;
}

.forecast-fields {
  display: grid;
  gap: 8px;
  min-inline-size: 0;
  margin: 0;
  padding: 4px 0 0;
  border: 0;
}

@media (prefers-reduced-motion: reduce) {
  .modeling-input,
  .modeling-select :deep(.el-select__wrapper),
  .variable-option {
    transition: none;
  }
}
</style>
