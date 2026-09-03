<template>
  <div class="artifact-workbench">
    <!-- Header -->
    <div class="aw-header">
      <div class="aw-header__left">
        <span class="aw-header__title font-mono">WORKSPACE ARTIFACTS · 成果工作区</span>
      </div>
      <div class="aw-header__right">
        <button
          type="button"
          class="aw-icon-btn"
          :title="isPinned ? '取消固定' : '固定面板'"
          :aria-label="isPinned ? '取消固定' : '固定面板'"
          @click="isPinned = !isPinned"
        >
          <svg viewBox="0 0 24 24" fill="none" :stroke="isPinned ? 'var(--accent)' : 'currentColor'" stroke-width="2" width="14" height="14" stroke-linecap="round" stroke-linejoin="round">
            <line x1="12" x2="12" y1="17" y2="22"/><path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1v4.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24Z"/>
          </svg>
        </button>
        <button
          type="button"
          class="aw-icon-btn"
          title="关闭面板"
          aria-label="关闭面板"
          @click="$emit('toggle')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14" stroke-linecap="round" stroke-linejoin="round">
            <path d="m9 18 6-6-6-6"/>
          </svg>
        </button>
      </div>
    </div>

    <!-- Artifact Tabs -->
    <div class="aw-tabs" v-if="availableArtifacts.length > 0">
      <button
        v-for="art in availableArtifacts"
        :key="art.stepId"
        type="button"
        class="aw-tab"
        :class="{ 'is-active': activeTab === art.stepId }"
        @click="activeTab = art.stepId"
      >
        <span class="aw-tab__label">{{ art.label }}</span>
      </button>
    </div>

    <!-- Artifact Content -->
    <div class="aw-content" v-if="activeArtifact">
      <!-- Model Artifact (arx_fit / evaluate_model) -->
      <template v-if="activeArtifact.type === 'model' || activeArtifact.type === 'evaluation'">
        <MetricStrip :metrics="modelMetrics(activeArtifact)" />
        <div class="aw-section">
          <div class="aw-section__label">模型结构 (Model Structure)</div>
          <div class="aw-kv-list">
            <div v-if="activeArtifact.payload.na !== undefined" class="aw-kv">
              <span class="aw-kv__key font-mono">输出阶数 na</span>
              <span class="aw-kv__val font-mono">{{ activeArtifact.payload.na }}</span>
            </div>
            <div v-if="activeArtifact.payload.nb !== undefined" class="aw-kv">
              <span class="aw-kv__key font-mono">输入阶数 nb</span>
              <span class="aw-kv__val font-mono">{{ activeArtifact.payload.nb }}</span>
            </div>
            <div v-if="activeArtifact.payload.nk !== undefined" class="aw-kv">
              <span class="aw-kv__key font-mono">延迟阶数 nk</span>
              <span class="aw-kv__val font-mono">{{ activeArtifact.payload.nk }}</span>
            </div>
            <div v-if="activeArtifact.payload.model_id" class="aw-kv">
              <span class="aw-kv__key font-mono">模型唯一 ID</span>
              <span class="aw-kv__val font-mono" style="font-size:11px">{{ activeArtifact.payload.model_id }}</span>
            </div>
          </div>
        </div>
      </template>

      <!-- Optimization Artifact -->
      <template v-else-if="activeArtifact.type === 'optimization'">
        <MetricStrip :metrics="optimizationMetrics(activeArtifact)" />
        <div class="aw-section">
          <div class="aw-section__label">最优参数 (Best Parameters)</div>
          <div class="aw-kv-list">
            <div v-for="(val, key) in activeArtifact.payload.best_params" :key="key" class="aw-kv">
              <span class="aw-kv__key font-mono">{{ key }}</span>
              <span class="aw-kv__val font-mono">{{ val }}</span>
            </div>
          </div>
        </div>
      </template>

      <!-- Delay Artifact -->
      <template v-else-if="activeArtifact.type === 'delay'">
        <div class="aw-section">
          <div class="aw-section__label">估计纯时滞 (Estimated Delays)</div>
          <div class="aw-kv-list">
            <div v-for="(val, key) in activeArtifact.payload.estimated_delays" :key="key" class="aw-kv">
              <span class="aw-kv__key font-mono">{{ key }}</span>
              <span class="aw-kv__val font-mono">{{ val }} 采样点</span>
            </div>
          </div>
        </div>
      </template>

      <!-- Feature / Collinearity Artifact -->
      <template v-else-if="activeArtifact.type === 'feature'">
        <div class="aw-section">
          <div class="aw-section__label">保留特征列 (Kept Features)</div>
          <div class="aw-tag-list">
            <span v-for="col in activeArtifact.payload.kept_columns" :key="col" class="aw-tag kept">{{ col }}</span>
          </div>
        </div>
        <div class="aw-section" v-if="activeArtifact.payload.removed_columns?.length">
          <div class="aw-section__label">剔除冗余列 (Removed Features)</div>
          <div class="aw-tag-list">
            <span v-for="col in activeArtifact.payload.removed_columns" :key="col" class="aw-tag removed">{{ col }}</span>
          </div>
        </div>
      </template>

      <!-- Cleaning / Segmentation / Generic -->
      <template v-else>
        <div class="aw-section">
          <div class="aw-section__label">工件详细数据 (Payload Details)</div>
          <pre class="aw-json font-mono">{{ JSON.stringify(activeArtifact.payload, null, 2) }}</pre>
        </div>
      </template>
    </div>

    <!-- Empty state -->
    <div class="aw-empty" v-else-if="availableArtifacts.length === 0">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="28" height="28" stroke-linecap="round" stroke-linejoin="round">
        <rect width="18" height="18" x="3" y="3" rx="2" ry="2"/><line x1="3" x2="21" y1="9" y2="9"/><line x1="3" x2="21" y1="15" y2="15"/><line x1="9" x2="9" y1="9" y2="21"/><line x1="15" x2="15" y1="9" y2="21"/>
      </svg>
      <p>Agent 任务执行完成后，辨识模型、寻优参数与工件将实时在此呈现</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue';
import MetricStrip from './MetricStrip.vue';
import type { CopilotExecutionSnapshot } from '../../types/api';

const props = defineProps<{
  execution: CopilotExecutionSnapshot;
  activeStepId?: string | null;
}>();

defineEmits<{ toggle: [] }>();

const isPinned = ref(false);
const activeTab = ref<string | null>(null);

interface ArtifactDef {
  stepId: string;
  type: 'model' | 'evaluation' | 'optimization' | 'delay' | 'feature' | 'cleaning' | 'segmentation' | 'report' | 'generic';
  label: string;
  payload: Record<string, any>;
}

const TOOL_META: Record<string, { type: ArtifactDef['type']; label: string }> = {
  arx_fit:                 { type: 'model',        label: 'ARX 模型' },
  evaluate_model:          { type: 'evaluation',   label: '模型评价' },
  optimize_pipeline:       { type: 'optimization', label: '寻优结果' },
  delay_analyze:           { type: 'delay',        label: '时滞分析' },
  collinearity:            { type: 'feature',      label: '特征筛选' },
  feature_apply:           { type: 'feature',      label: '特征筛选' },
  feature_selection_apply: { type: 'feature',      label: '特征筛选' },
  clean:                   { type: 'cleaning',     label: '数据清洗' },
  segment:                 { type: 'segmentation', label: '区间优选' },
  generate_report:         { type: 'report',       label: '分析报告' },
};

const availableArtifacts = computed<ArtifactDef[]>(() => {
  return props.execution.step_runs
    .filter(r => r.status === 'completed' && r.result_payload && Object.keys(r.result_payload).length > 0)
    .map(r => {
      const plan = props.execution.plan?.steps?.find(s => s.step_id === r.step_id);
      const meta = TOOL_META[plan?.tool ?? ''] ?? { type: 'generic', label: plan?.tool ?? r.step_id };
      return {
        stepId: r.step_id,
        type: meta.type,
        label: meta.label,
        payload: r.result_payload ?? {},
      };
    });
});

const activeArtifact = computed(() =>
  availableArtifacts.value.find(a => a.stepId === activeTab.value) ?? null
);

watch(availableArtifacts, (arts) => {
  if (!activeTab.value && arts.length > 0) {
    activeTab.value = arts[arts.length - 1].stepId;
  }
}, { immediate: true });

watch(() => props.activeStepId, (id) => {
  if (id) activeTab.value = id;
});

function modelMetrics(art: ArtifactDef) {
  const p = art.payload;
  const metrics: { label: string; value: string; sub?: string; primary?: boolean }[] = [];
  if (p.fit_pct !== undefined)  metrics.push({ label: 'FIT 拟合度', value: `${p.fit_pct.toFixed(1)}%`, primary: true });
  if (p.r2 !== undefined)       metrics.push({ label: '决定系数 R²', value: p.r2.toFixed(3) });
  if (p.rmse !== undefined)     metrics.push({ label: '均方根误差', value: p.rmse.toFixed(4) });
  if (p.free_run_fit !== undefined) metrics.push({ label: '自由仿真 FIT', value: `${p.free_run_fit.toFixed(1)}%` });
  if (p.nrmse !== undefined)    metrics.push({ label: 'NRMSE', value: p.nrmse.toFixed(3) });
  return metrics;
}

function optimizationMetrics(art: ArtifactDef) {
  const p = art.payload;
  const metrics: { label: string; value: string; primary?: boolean }[] = [];
  if (p.best_value !== undefined) metrics.push({ label: '最优目标 FIT', value: `${(p.best_value * 100).toFixed(1)}%`, primary: true });
  if (p.n_trials !== undefined)   metrics.push({ label: '试验次数', value: `${p.n_trials} 次` });
  return metrics;
}
</script>

<style scoped>
.artifact-workbench {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #FFFFFF;
  border-left: 1px solid #E5E5E8;
  overflow: hidden;
}

/* Header */
.aw-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  height: 48px;
  border-bottom: 1px solid #ECECED;
  background: #FAFAFA;
  flex-shrink: 0;
}

.aw-header__title {
  font-size: 11px;
  color: #426340;
  letter-spacing: 0.08em;
  font-weight: 600;
}

.aw-header__right {
  display: flex;
  gap: 4px;
}

.aw-icon-btn {
  width: 28px;
  height: 28px;
  background: none;
  border: none;
  color: #8E8E93;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.15s ease;
}

.aw-icon-btn:hover {
  background: #EFEFF1;
  color: #171717;
}

/* Tabs */
.aw-tabs {
  display: flex;
  gap: 4px;
  padding: 8px 12px;
  overflow-x: auto;
  flex-shrink: 0;
  border-bottom: 1px solid #ECECED;
  background: #F5F5F7;
}

.aw-tab {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  background: none;
  border: 1px solid transparent;
  border-radius: 6px;
  color: #666666;
  font-family: var(--font-sans);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s ease;
}

.aw-tab:hover {
  background: #EFEFF1;
  color: #171717;
}

.aw-tab.is-active {
  background: #FFFFFF;
  border-color: #E5E5E8;
  color: #426340;
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
}

/* Content */
.aw-content {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.aw-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.aw-section__label {
  font-family: var(--font-sans);
  font-size: 11px;
  color: #8E8E93;
  letter-spacing: normal;
  text-transform: none;
  font-weight: 600;
}

/* KV List */
.aw-kv-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.aw-kv {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: #F8F9F7;
  border: 1px solid #E5E5E8;
  border-radius: 6px;
  font-size: 13px;
}

.aw-kv__key {
  color: #666666;
}

.aw-kv__val {
  color: #171717;
  font-weight: 600;
}

/* Tag list */
.aw-tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.aw-tag {
  font-family: var(--font-mono);
  font-size: 12px;
  padding: 3px 10px;
  border-radius: 4px;
  font-weight: 500;
}

.aw-tag.kept {
  color: var(--success);
  background: var(--success-soft);
  border: 1px solid var(--color-success-border);
}

.aw-tag.removed {
  color: var(--danger);
  background: var(--danger-soft);
  border: 1px solid var(--color-error-border);
}

/* JSON fallback */
.aw-json {
  font-size: 11px;
  color: #171717;
  background: #F8F9F7;
  border: 1px solid #E5E5E8;
  border-radius: 6px;
  padding: 12px;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 300px;
  overflow-y: auto;
}

/* Empty */
.aw-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: #8E8E93;
  padding: 32px;
  text-align: center;
}

.aw-empty p {
  font-size: 13px;
  color: #8E8E93;
  line-height: 1.5;
  max-width: 240px;
}
</style>
