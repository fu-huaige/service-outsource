<template>
  <div class="selection-fields">
    <div v-if="recommendedModel" class="recommendation-summary" data-test="recommended-model">
      <p><span class="recommendation-label">Agent 推荐</span> <strong>{{ recommendedModel.model_name }}</strong></p>
      <p v-if="recommendationReason">{{ recommendationReason }}</p>
    </div>
    <p v-else role="status" data-test="no-recommended-model">当前没有可推荐模型。</p>

    <div v-if="recommendedModel" class="model-choice">
      <label :id="selectId">当前选择</label>
      <SelectRoot :model-value="selectedModel?.model_type_id" :disabled="disabled" @update:model-value="selectModel">
        <SelectTrigger class="model-select-trigger" :aria-labelledby="selectId" data-test="model-select">
          <SelectValue>{{ selectedModel?.model_name }}</SelectValue>
          <SelectIcon class="model-select-chevron"><ArrowDown aria-hidden="true" /></SelectIcon>
        </SelectTrigger>
        <SelectPortal>
          <SelectContent class="model-select-content" position="popper" :side-offset="6" :collision-padding="8">
            <SelectViewport class="model-select-viewport">
              <SelectItem v-for="candidate in availableModels" :key="candidate.model_type_id"
                :value="candidate.model_type_id" class="model-select-item" :data-model="candidate.model_type_id">
                <SelectItemText>{{ candidate.model_name }}</SelectItemText>
                <SelectItemIndicator class="model-select-check"><Check aria-hidden="true" /></SelectItemIndicator>
              </SelectItem>
            </SelectViewport>
          </SelectContent>
        </SelectPortal>
      </SelectRoot>
      <p v-if="selectedModel" class="model-fit" data-test="selected-model-fit">
        {{ selectedModel.suitability === 'preferred' ? '优先适用' : '符合条件' }}
        <template v-if="selectedModel.training_sample_count !== null">
          · 有效训练样本 {{ selectedModel.training_sample_count }}
        </template>
        <template v-if="selectedModel.forecast_spec">
          · 预测 {{ selectedModel.forecast_spec.prediction_length }} 步
        </template>
      </p>
      <p v-if="selectedModel?.limitations[0]" class="model-fit">{{ selectedModel.limitations[0] }}</p>
    </div>

    <details v-if="unavailableModels.length" :open="!recommendedModel" class="selection-details">
      <summary>不可用模型（{{ unavailableModels.length }}）</summary>
      <ul>
        <li v-for="candidate in unavailableModels" :key="candidate.model_type_id">
          <strong>{{ candidate.model_name }}</strong>
          <span> · {{ candidate.eligibility_status === 'excluded' ? '不适用' : '待核实' }}</span>
          <p v-for="(reason, index) in candidate.reasons" :key="index">{{ reason }}</p>
        </li>
      </ul>
    </details>

    <p v-if="recommendation.leakage?.status === 'unknown'" data-test="recommendation-leakage">
      <strong>数据泄漏风险尚未核实</strong>。当前无法确认所有预处理拟合操作是否严格限制在训练集内，是否发生泄漏仍待核验。
    </p>
    <details v-if="recommendedModel" class="selection-details">
      <summary>数据来源</summary>
      <p>数据版本 {{ recommendation.source.dataset_version_id }}</p>
      <p>目标 {{ recommendation.source.target_name }} · 输入 {{ recommendation.source.feature_names.join('、') }}</p>
    </details>
  </div>
</template>

<script setup lang="ts">
import { ArrowDown, Check } from '@element-plus/icons-vue';
import {
  SelectContent, SelectIcon, SelectItem, SelectItemIndicator, SelectItemText,
  SelectPortal, SelectRoot, SelectTrigger, SelectValue, SelectViewport,
} from 'reka-ui';
import { computed, ref, useId, watch } from 'vue';
import type {
  CopilotModelSelection,
  ModelCandidate,
  ModelRecommendationResult,
  RecommendationModelType,
} from '../../types/api';

const props = defineProps<{
  recommendation: ModelRecommendationResult;
  recommendationStepId: string;
  disabled?: boolean;
}>();
const emit = defineEmits<{ change: [selection: CopilotModelSelection | null] }>();

const selectId = useId();
const selectedId = ref<RecommendationModelType>();
const isSelectable = (candidate: ModelCandidate) =>
  candidate.eligibility_status === 'eligible' && candidate.actual_parameters != null;

const eligibleModels = computed(() => props.recommendation.candidates.filter(isSelectable));
const rankedModels = computed(() => props.recommendation.recommended_models.flatMap(id =>
  eligibleModels.value.filter(candidate => candidate.model_type_id === id),
));
const recommendedModel = computed(() => rankedModels.value[0]);
const availableModels = computed(() => [
  ...rankedModels.value,
  ...eligibleModels.value.filter(candidate => !props.recommendation.recommended_models.includes(candidate.model_type_id)),
]);
const unavailableModels = computed(() => props.recommendation.candidates.filter(candidate => !isSelectable(candidate)));
const selectedModel = computed(() => {
  if (!recommendedModel.value) return undefined;
  return availableModels.value.find(candidate => candidate.model_type_id === selectedId.value) ?? recommendedModel.value;
});
const recommendationReason = computed(() => {
  const model = recommendedModel.value;
  return model?.suitability === 'preferred' ? model.reasons.at(-1) : model?.reasons[0];
});

watch(() => {
  const source = props.recommendation.source;
  return [props.recommendationStepId, source.dataset_id, source.dataset_version_id, source.csv_sha256,
    source.experiment_spec_hash].join(':');
}, () => { selectedId.value = undefined; }, { flush: 'sync' });

function selectModel(value: unknown) {
  const candidate = availableModels.value.find(item => item.model_type_id === value);
  if (props.disabled || !recommendedModel.value || !candidate) return;
  selectedId.value = candidate.model_type_id;
}

const selection = computed<CopilotModelSelection | null>(() => {
  const candidate = selectedModel.value;
  if (!candidate?.actual_parameters) return null;
  const source = props.recommendation.source;
  return {
    recommendation_step_id: props.recommendationStepId,
    selected_model_type_id: candidate.model_type_id,
    selected_parameters: { ...candidate.actual_parameters },
    selection_source: candidate.model_type_id === recommendedModel.value?.model_type_id
      ? 'agent_recommendation' : 'manual',
    dataset_id: source.dataset_id,
    dataset_version_id: source.dataset_version_id,
    csv_sha256: source.csv_sha256,
    experiment_spec_hash: source.experiment_spec_hash,
    forecast_spec: candidate.forecast_spec ? { ...candidate.forecast_spec } : null,
  };
});

watch(selection, value => emit('change', value), { immediate: true, flush: 'sync' });
</script>

<style scoped>
.selection-fields,
.model-choice {
  display: grid;
  gap: 8px;
}
.selection-fields p {
  margin: 0;
}
.recommendation-summary,
.selection-details {
  padding: 8px 10px;
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
}
.recommendation-summary p + p,
.selection-details summary + p {
  margin-top: 4px;
}
.recommendation-label {
  color: var(--accent);
  margin-inline-end: 6px;
}
.model-select-trigger {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  min-height: 36px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 7px 10px;
  color: inherit;
  background: var(--bg-card, white);
  font: inherit;
  cursor: pointer;
}
.model-select-trigger:disabled { opacity: .55; cursor: not-allowed; }
.model-select-trigger:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.model-select-chevron, :global(.model-select-check) { display: inline-flex; width: 14px; height: 14px; }
:global(.model-select-content) {
  z-index: 3000;
  box-sizing: border-box;
  width: var(--reka-select-trigger-width);
  max-width: var(--reka-select-content-available-width);
  max-height: var(--reka-select-content-available-height);
  overflow: hidden;
  border: 1px solid #dfe6e1;
  border-radius: 8px;
  background: #fff;
  color: #24362c;
  box-shadow: 0 6px 18px rgb(30 56 42 / 12%);
}
:global(.model-select-viewport) { padding: 4px; }
:global(.model-select-item) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 7px 8px;
  border-radius: 5px;
  font-size: 13px;
  cursor: pointer;
}
:global(.model-select-item + .model-select-item) { margin-top: 2px; }
:global(.model-select-item[data-state="checked"]) { background: #eef2ef; font-weight: 600; }
:global(.model-select-item[data-highlighted]) { outline: none; background: #e6ece8; }
:global(.model-select-check) { color: #326549; }
.model-fit {
  color: var(--text-secondary);
}
.selection-details summary {
  cursor: pointer;
}
.selection-details ul {
  margin: 6px 0 0;
  padding-inline-start: 20px;
}
</style>
