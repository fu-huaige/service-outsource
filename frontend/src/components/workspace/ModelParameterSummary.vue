<template>
  <div class="model-configuration">
    <section class="configuration-card" :aria-labelledby="overviewHeading" data-test="model-overview-card">
      <h3 :id="overviewHeading">模型概览</h3>
      <div class="model-heading">
        <div class="model-identity">
          <strong>{{ candidate.model_name }}</strong>
          <span v-if="entry">{{ entry.category }}</span>
        </div>
        <span class="model-fit" data-test="selected-model-fit">
          {{ candidate.suitability === 'preferred' ? '优先适用' : '符合条件' }}
        </span>
      </div>
      <p v-if="entry?.description" class="model-context">{{ entry.description }}</p>
      <p v-if="candidate.reasons[0]" class="model-context">{{ candidate.reasons[0] }}</p>
      <p v-for="limitation in candidate.limitations" :key="limitation" class="model-context">{{ limitation }}</p>
    </section>

    <section class="configuration-card" :aria-labelledby="parametersHeading"
      :data-test="isDynamic ? candidate.model_type_id + '-candidate-contract' : 'model-core-parameters'">
      <h3 :id="parametersHeading">核心模型参数</h3>
      <dl v-if="coreParameters.length || showPredictionHorizon" class="parameter-grid">
        <div v-for="item in coreParameters" :key="item.key">
          <dt>{{ item.label }}</dt><dd>{{ formatValue(item.value) }}</dd>
        </div>
        <div v-if="showPredictionHorizon"><dt>预测步长</dt><dd>{{ candidate.prediction_horizon }} 步</dd></div>
      </dl>
      <div v-if="lagRows.length" class="lag-table-scroll">
        <table class="lag-table">
          <caption class="sr-only">各输入变量的阶次与纯滞后</caption>
          <colgroup><col class="lag-column-name"><col><col></colgroup>
          <thead><tr><th scope="col">输入变量</th><th scope="col">输入阶次 nb</th><th scope="col">纯滞后 nk</th></tr></thead>
          <tbody>
            <tr v-for="row in lagRows" :key="row.name">
              <th scope="row">{{ row.name }}</th><td>{{ row.nb }}</td><td>{{ row.nk }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="isOe && oeNumerators.length" class="additional-parameters">
        <h4>分子与输入纯滞后</h4>
        <dl class="parameter-grid">
          <div v-for="entry in oeNumerators" :key="entry.name">
            <dt>{{ entry.name }}</dt><dd>{{ entry.order }} 项 · 滞后 {{ entry.delay }} 步</dd>
          </div>
        </dl>
      </div>
      <p v-if="isFir && parameters.regularization_kernel === 'tc'" class="model-context">
        TC 核要求标准化、Ridge 估计和正的正则化系数。
      </p>
    </section>

    <section class="configuration-card" :aria-labelledby="trainingHeading" data-test="model-training-card">
      <h3 :id="trainingHeading">数据与训练配置</h3>
      <dl class="parameter-grid training-grid">
        <div v-if="targetName"><dt>目标变量</dt><dd>{{ targetName }}</dd></div>
        <div v-if="versionId"><dt>数据版本</dt><dd><code>{{ versionId.slice(0, 8) }}{{ versionId.length > 8 ? '…' : '' }}</code></dd></div>
        <div v-if="trainRange"><dt>Train 行区间</dt><dd>{{ trainRange }}</dd></div>
        <div v-if="validationRange"><dt>Validation 行区间</dt><dd>{{ validationRange }}</dd></div>
        <div v-if="samplePeriod != null"><dt>采样间隔</dt><dd>{{ samplePeriod }} 秒</dd></div>
        <div v-if="candidate.training_sample_count != null"><dt>有效训练样本</dt><dd>{{ candidate.training_sample_count }}</dd></div>
        <div v-if="!isDynamic && featureNames.length" class="training-wide"><dt>输入变量</dt><dd>{{ featureNames.join('、') }}</dd></div>
      </dl>
    </section>

    <details class="configuration-card technical-details">
      <summary>技术详情<ArrowDown class="technical-chevron" aria-hidden="true" /></summary>
      <dl class="parameter-grid technical-grid">
        <div class="version-field">
          <dt>完整数据版本 UUID</dt>
          <dd class="copy-value">
            <code>{{ versionId }}</code>
            <button type="button" @click="copyVersion" aria-label="复制完整数据版本 UUID">复制</button>
          </dd>
        </div>
        <div><dt>数据集 UUID</dt><dd><code>{{ recommendation.source.dataset_id }}</code></dd></div>
        <div v-if="spec?.time_axis.column"><dt>时间列</dt><dd>{{ spec.time_axis.column }}</dd></div>
        <div><dt>CSV SHA-256</dt><dd><code>{{ spec?.dataset_version_sha256 ?? recommendation.source.csv_sha256 }}</code></dd></div>
        <div><dt>Spec SHA-256</dt><dd><code>{{ candidate.experiment_spec_hash ?? recommendation.source.experiment_spec_hash }}</code></dd></div>
        <div v-if="lagContract"><dt>Lag 来源</dt><dd>{{ lagContract.lag_compensation_version_id ?? '当前数据版本的相对滞后' }}</dd></div>
        <div v-if="spec?.split.history_guard != null"><dt>历史保护间隔</dt><dd>{{ spec.split.history_guard }} 行</dd></div>
        <div v-if="spec?.oe_contract"><dt>拟合数据 SHA-256</dt><dd><code>{{ spec.oe_contract.training_data_sha256 }}</code></dd></div>
      </dl>
      <div v-if="spec?.oe_contract" class="additional-parameters">
        <h4>仿真目标与初始化历史</h4>
        <ul>
          <li v-for="interval in spec.oe_contract.simulation_intervals" :key="interval.start">
            历史行 {{ interval.history_start + 1 }}–{{ interval.start }}，目标行 {{ interval.start + 1 }}–{{ interval.stop }}
          </li>
        </ul>
      </div>
      <p v-if="copyStatus" role="status" class="model-context">{{ copyStatus }}</p>
      <div v-if="extraParameters.length" class="additional-parameters">
        <h4>其他模型参数</h4>
        <dl class="parameter-grid">
          <div v-for="([key, value]) in extraParameters" :key="key">
            <dt>{{ key }}</dt><dd>{{ formatValue(value) }}</dd>
          </div>
        </dl>
      </div>
    </details>
  </div>
</template>

<script setup lang="ts">
import { ArrowDown } from '@element-plus/icons-vue';
import { computed, ref, useId } from 'vue';
import type { ExperimentRowRange, ModelCandidate, ModelRecommendationResult, RecommendationCatalogEntry } from '../../types/api';

const props = defineProps<{
  candidate: ModelCandidate;
  entry?: RecommendationCatalogEntry;
  recommendation: ModelRecommendationResult;
}>();

const panelId = useId();
const overviewHeading = panelId + '-overview';
const parametersHeading = panelId + '-parameters';
const trainingHeading = panelId + '-training';

const coreFields: Record<string, Record<string, string>> = {
  arx: { na: '输出历史阶次 na', estimator: '估计器', ridge_alpha: '正则化系数' },
  oe: { na: '分母阶数', initialization_policy: '初始化策略', simulation_horizons: '仿真时域',
    loss_weighting: '多步损失权重', standardize: '标准化', fit_intercept: '截距',
    simulation_max_nfev: '每个初值的求解预算', ridge_alpha: 'Ridge 系数' },
  fir: { estimator: '估计器', regularization_kernel: '正则化核', kernel_decay: 'TC 核衰减', ridge_alpha: '正则化系数' },
  pls: { n_components: '潜变量成分数', scale: '标准化' },
  xgboost: { num_boost_round: '提升轮数', max_depth: '最大树深', learning_rate: '学习率' },
  tcn: { hidden_channels: '隐藏通道', kernel_size: '卷积核尺寸（固定）', dilations: '膨胀率（固定）', window_length: '历史窗口' },
  timexer: { target_window_length: '目标历史窗口', exogenous_window_length: '外生变量窗口', prediction_length: '预测步数', patch_length: '分块长度', embedding_dim: '嵌入维度', num_heads: '注意力头数' },
};

const isFir = computed(() => props.candidate.model_type_id === 'fir');
const isOe = computed(() => props.candidate.model_type_id === 'oe');
const isDynamic = computed(() => isFir.value || isOe.value || props.candidate.model_type_id === 'arx');
const spec = computed(() => props.candidate.experiment_spec ?? props.recommendation.experiment_spec);
const lagContract = computed(() => spec.value?.arx_contract ?? spec.value?.fir_contract ?? spec.value?.oe_contract);
const versionId = computed(() => spec.value?.dataset_version_id ?? props.recommendation.source.dataset_version_id);
const targetName = computed(() => spec.value?.target_column ?? props.recommendation.source.target_name);
const featureNames = computed(() => spec.value?.input_columns ?? props.recommendation.source.feature_names);
const trainRange = computed(() => formatRanges(spec.value?.split.train ?? props.recommendation.source.train_rows.ranges));
const validationRange = computed(() => formatRanges(spec.value?.split.validation));
const samplePeriod = computed(() => spec.value?.time_axis.sample_period_seconds ?? props.recommendation.profile.sample_period_seconds);
const parameters = computed(() => ({
  ...props.candidate.actual_parameters, ...props.candidate.fixed_parameters,
  ...(spec.value?.oe_contract ? { loss_weighting: spec.value.oe_contract.loss_weighting } : {}),
} as Record<string, unknown>));
const fields = computed(() => coreFields[props.candidate.model_type_id]);
const sourceKeys = new Set(['dataset_id', 'version_id', 'input_columns', 'output_column', 'model_type', 'train_ratio', 'validation_ratio']);

const coreParameters = computed(() => Object.entries(fields.value ?? parameters.value).flatMap(([key, label]) => {
  if (key === 'kernel_decay' && parameters.value.regularization_kernel !== 'tc') return [];
  const value = key === 'estimator' ? parameters.value.estimation_method ?? parameters.value[key] : parameters.value[key];
  return value == null ? [] : [{ key, label: fields.value ? String(label) : key, value }];
}));
const extraParameters = computed(() => {
  if (!fields.value) return [];
  const excluded = new Set([...sourceKeys, ...Object.keys(fields.value), 'estimation_method']);
  if (lagRows.value.length || oeNumerators.value.length) { excluded.add('nb'); excluded.add('delays'); }
  if (isFir.value) excluded.add('na');
  return Object.entries(parameters.value).filter(([key, value]) => !excluded.has(key) && value != null);
});
const showPredictionHorizon = computed(() => props.candidate.model_type_id === 'tcn' ||
  (props.candidate.forecast_spec != null && parameters.value.prediction_length == null));
const oeNumerators = computed(() => isOe.value ? Object.entries(spec.value?.feature_spec.input_lags ?? {})
  .filter(([, lags]) => lags.length)
  .map(([name, lags]) => ({ name, order: lags.length, delay: lags[0] })) : []);
const lagRows = computed(() => isDynamic.value && !isOe.value ? Object.entries(spec.value?.feature_spec.input_lags ?? {})
  .filter(([, lags]) => lags.length > 0)
  .map(([name, lags]) => ({ name, nb: lags.length, nk: lags[0] })) : []);

const copyStatus = ref('');
async function copyVersion() {
  try {
    await navigator.clipboard.writeText(versionId.value);
    copyStatus.value = '已复制数据版本 UUID';
  } catch {
    copyStatus.value = '无法访问剪贴板，请选中 UUID 后手动复制。';
  }
}

function formatRanges(ranges?: ExperimentRowRange[]): string {
  return ranges?.length ? ranges.map(({ start, stop }) => (start + 1) + '–' + stop).join('、') : '';
}

function formatValue(value: unknown): string {
  if (typeof value === 'boolean') return value ? '开启' : '关闭';
  if (value === 'tc') return 'TC';
  if (value === 'identity') return 'Identity';
  if (isOe.value && value === 'fixed') return '固定历史';
  if (value === 'equal_interval_and_horizon') return '区间与时域等权';
  if (isOe.value && value === parameters.value.simulation_horizons && Array.isArray(value)) {
    return value.map(horizon => horizon === 0 ? '整段（0）' : String(horizon) + ' 步').join('、');
  }
  return typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value);
}
</script>

<style scoped>
.model-configuration {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 12px;
  min-width: 0;
  container-type: inline-size;
}
.configuration-card {
  min-width: 0;
  padding: 14px;
  border: 1px solid var(--border-default);
  border-radius: 11px;
  background: var(--surface-1);
  color: var(--text-primary);
}
h3, .technical-details summary {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  line-height: 1.4;
}
h3 { margin-bottom: 10px; }
.model-heading { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: baseline; gap: 4px 12px; }
.model-identity { display: flex; flex-wrap: wrap; align-items: baseline; gap: 3px 10px; min-width: 0; }
.model-identity strong { font-size: 17px; font-weight: 650; }
.model-identity span, .model-context, dt { color: var(--text-secondary); }
.model-identity span, .model-context, .model-fit { font-size: 13px; }
.model-context { margin: 5px 0 0; line-height: 1.5; overflow-wrap: anywhere; }
.model-fit { color: var(--accent); }

.parameter-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 140px), 1fr));
  gap: 8px 16px;
  margin: 0;
}
.parameter-grid > div { min-width: 0; }
dt { font-size: 13px; overflow-wrap: anywhere; }
dd { margin: 2px 0 0; font-size: 14px; line-height: 1.45; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
.training-grid, .technical-grid { grid-template-columns: minmax(0, 1fr); }
.training-wide, .version-field { grid-column: 1 / -1; }
@container (min-width: 360px) {
  .training-grid, .technical-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

.lag-table-scroll { max-width: 100%; overflow-x: auto; margin-top: 9px; }
.lag-table { width: 100%; table-layout: fixed; text-align: left; border-collapse: collapse; font-variant-numeric: tabular-nums; }
.lag-column-name { width: 54%; }
.lag-table :is(th, td) { padding: 6px 8px; border-bottom: 1px solid var(--border-subtle); overflow-wrap: anywhere; }
.lag-table thead { background: var(--surface-2); color: var(--text-secondary); font-size: 13px; }
.lag-table tbody th { font-weight: 500; }
.lag-table tbody td { font-size: 14px; }
.lag-table tbody tr:last-child > * { border-bottom: 0; }

.technical-details summary { display: flex; align-items: center; justify-content: space-between; gap: 8px; cursor: pointer; list-style: none; }
.technical-details summary::-webkit-details-marker { display: none; }
.technical-chevron { width: 14px; height: 14px; flex: none; color: var(--text-secondary); }
.technical-details[open] .technical-chevron { transform: rotate(180deg); }
.technical-grid, .additional-parameters { margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--border-subtle); }
.additional-parameters h4 { margin: 0 0 8px; font-size: 13px; font-weight: 600; }
.copy-value { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 8px; }
.copy-value code { min-width: 0; }
.copy-value button { flex: none; color: var(--accent); text-decoration: underline; text-underline-offset: 2px; }
.technical-details :is(summary, button):focus-visible { outline: 2px solid var(--border-focus); outline-offset: 3px; }
</style>
