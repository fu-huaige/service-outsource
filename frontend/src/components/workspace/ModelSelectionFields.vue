<template>
  <div class="selection-fields">
    <div v-if="recommendedModel" class="recommendation-summary" data-test="recommended-model">
      <p><span class="recommendation-label">Agent 推荐</span> <strong>{{ recommendedModel.model_name }}</strong></p>
      <p v-if="recommendationReason">{{ recommendationReason }}</p>
    </div>
    <p v-else role="status" data-test="no-recommended-model">当前没有可推荐模型。</p>

    <div v-if="recommendedModel || groups.length" class="model-choice">
      <label :id="selectId">模型目录</label>
      <SelectRoot :model-value="selectedModel?.model_type_id" :disabled="disabled" @update:model-value="selectModel">
        <SelectTrigger class="model-select-trigger" :aria-labelledby="selectId" data-test="model-select">
          <SelectValue placeholder="查看模型目录">{{ selectedModel?.model_name }}</SelectValue>
          <SelectIcon class="model-select-chevron"><ArrowDown aria-hidden="true" /></SelectIcon>
        </SelectTrigger>
        <SelectPortal>
          <SelectContent class="model-select-content" position="popper" :side-offset="6" :collision-padding="8">
            <SelectViewport class="model-select-viewport">
              <SelectGroup v-for="[category, items] in groups" :key="category">
                <SelectLabel class="model-menu-group">{{ category }}</SelectLabel>
                <SelectItem v-for="entry in items" :key="entry.model_type_id"
                  :value="entry.model_type_id" :disabled="!isCatalogSelectable(entry.model_type_id)"
                  class="model-select-item model-catalog-option" :data-model="entry.model_type_id"
                  :aria-describedby="selectId + '-' + entry.model_type_id">
                  <div class="model-menu-body">
                    <div class="model-menu-title">
                      <SelectItemText>{{ entry.model_name }}</SelectItemText>
                      <span v-if="recommendedModel?.model_type_id === entry.model_type_id" class="model-menu-recommended">Agent 首选</span>
                      <span v-else-if="!isCatalogSelectable(entry.model_type_id)" class="model-menu-status">
                        {{ catalogStatusLabels[entry.eligibility_status] }}
                      </span>
                    </div>
                    <div :id="selectId + '-' + entry.model_type_id" class="model-menu-description">
                      <p v-if="entry.description">{{ entry.description }}</p>
                      <p v-if="isCatalogSelectable(entry.model_type_id)">资格通过</p>
                      <p v-else v-for="reason in entry.reasons" :key="reason">{{ reason }}</p>
                    </div>
                  </div>
                  <SelectItemIndicator class="model-select-check" aria-label="已选中"><Check aria-hidden="true" /></SelectItemIndicator>
                </SelectItem>
              </SelectGroup>
              <template v-if="!groups.length">
                <SelectItem v-for="candidate in availableModels" :key="candidate.model_type_id"
                  :value="candidate.model_type_id" class="model-select-item" :data-model="candidate.model_type_id">
                  <SelectItemText>{{ candidate.model_name }}</SelectItemText>
                  <SelectItemIndicator class="model-select-check"><Check aria-hidden="true" /></SelectItemIndicator>
                </SelectItem>
              </template>
            </SelectViewport>
          </SelectContent>
        </SelectPortal>
      </SelectRoot>
    </div>

    <ModelParameterSummary v-if="selectedModel" :key="selectedModel.model_type_id"
      :candidate="selectedModel" :entry="catalog.get(selectedModel.model_type_id)" :recommendation="recommendation" />
    <details v-if="!groups.length && unavailableModels.length" :open="!recommendedModel" class="selection-details">
      <summary>不可用模型（{{ unavailableModels.length }}）</summary>
      <ul>
        <li v-for="candidate in unavailableModels" :key="candidate.model_type_id">
          <strong>{{ candidate.model_name }}</strong>
          <span> · {{ candidate.eligibility_status === 'excluded' ? '不适用' : '待核实' }}</span>
          <p v-for="(reason, index) in candidate.reasons" :key="index">{{ reason }}</p>
        </li>
      </ul>
    </details>

    <aside v-if="recommendation.leakage?.status === 'unknown' || recommendation.leakage?.status === 'potential_leakage'"
      class="leakage-notice" role="note" data-test="recommendation-leakage">
      <template v-if="recommendation.leakage.status === 'unknown'">
        <strong>数据泄漏风险尚未核实</strong>
        <p>现有记录无法核实上游预处理是否只在 Train 上拟合。预处理的拟合范围待核验。</p>
      </template>
      <template v-else>
        <strong>检测到潜在数据泄漏风险</strong>
        <ul v-if="recommendation.leakage.evidence.length">
          <li v-for="evidence in recommendation.leakage.evidence" :key="evidence">{{ evidence }}</li>
        </ul>
      </template>
    </aside>
  </div>
</template>

<script setup lang="ts">
import { ArrowDown, Check } from '@element-plus/icons-vue';
import {
  SelectContent, SelectGroup, SelectIcon, SelectItem, SelectItemIndicator, SelectItemText, SelectLabel,
  SelectPortal, SelectRoot, SelectTrigger, SelectValue, SelectViewport,
} from 'reka-ui';
import { computed, ref, useId, watch } from 'vue';
import ModelParameterSummary from './ModelParameterSummary.vue';
import type {
  CopilotModelSelection,
  ModelCandidate,
  ModelRecommendationResult,
  RecommendationCatalogEntry,
  RecommendationModelType,
} from '../../types/api';

const props = defineProps<{
  recommendation: ModelRecommendationResult;
  recommendationStepId: string;
  disabled?: boolean;
}>();
const emit = defineEmits<{ change: [selection: CopilotModelSelection | null] }>();

const catalogStatusLabels: Record<RecommendationCatalogEntry['eligibility_status'], string> = {
  eligible: '待核验', task_mismatch: '不适用', not_integrated: '未接入',
  excluded: '资格未通过', unknown: '待核验',
};
const selectId = useId();
const selectedId = ref<RecommendationModelType>();
const catalog = computed(() => new Map(
  (props.recommendation.catalog_models ?? []).map(entry => [entry.model_type_id, entry]),
));
const groups = computed(() => {
  const categories = new Map<string, RecommendationCatalogEntry[]>();
  for (const entry of catalog.value.values()) {
    const items = categories.get(entry.category) ?? [];
    items.push(entry);
    categories.set(entry.category, items);
  }
  return [...categories];
});
const isSelectable = (candidate: ModelCandidate) =>
  candidate.eligibility_status === 'eligible' && candidate.actual_parameters != null &&
  (!catalog.value.size || catalog.value.get(candidate.model_type_id)?.eligibility_status === 'eligible');
const isCatalogSelectable = (id: string) => eligibleModels.value.some(candidate => candidate.model_type_id === id);

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
    source.experiment_spec_hash, props.recommendation.task_type].join(':');
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
    experiment_spec_hash: candidate.experiment_spec_hash ?? source.experiment_spec_hash,
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
  width: max(360px, var(--reka-select-trigger-width));
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
.model-menu-group { padding: 8px 10px 4px; color: var(--text-secondary, #53645b); font-size: 12px; font-weight: 600; }
.model-catalog-option { min-height: 44px; padding: 7px 10px; }
.model-catalog-option[data-disabled] { color: var(--text-secondary, #53645b); cursor: default; background: #f5f7f6; }
.model-menu-body { min-width: 0; }
.model-menu-title { display: flex; flex-wrap: wrap; gap: 5px 10px; font-weight: 600; }
.model-menu-description { margin-top: 2px; color: var(--text-secondary, #53645b); font-size: 12px; line-height: 1.5; }
.model-menu-description p { margin: 0; }
.model-menu-recommended { color: #326549; font-size: 12px; }
.model-menu-status { color: var(--text-secondary, #53645b); font-size: 12px; font-weight: 500; }
.leakage-notice { border-inline-start: 3px solid #a4792c; padding: 7px 11px; background: #fbf8ef; }
.leakage-notice p { margin: 3px 0 0; }
.selection-details summary {
  cursor: pointer;
}
.selection-details ul {
  margin: 6px 0 0;
  padding-inline-start: 20px;
}
</style>
