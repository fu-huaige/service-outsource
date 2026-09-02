<template>
  <div class="page-container delay-view">
    <!-- Top Stage Header Navigation -->
    <div class="pipeline-stage-nav">
      <div class="stage-badge font-mono">STAGE 04 · DELAY ALIGNMENT STUDIO</div>
      <div class="stage-links">
        <span class="stage-link" @click="$router.push('/preprocessing/cleaning')">02 时间清洗</span>
        <span class="stage-sep">›</span>
        <span class="stage-link" @click="$router.push('/preprocessing/segmentation')">03 D-最优优选</span>
        <span class="stage-sep">›</span>
        <span class="stage-link active">04 时滞对齐</span>
        <span class="stage-sep">›</span>
        <span class="stage-link" @click="$router.push('/preprocessing/collinearity')">05 VIF 降维</span>
      </div>
    </div>

    <div class="page-header">
      <span class="page-eyebrow font-mono">PRE-WHITENING CROSS CORRELATION & PHASE ALIGNMENT</span>
      <h2>多变量时滞对齐工作室</h2>
      <p class="subtitle">预白化去除输入慢变自相关伪峰，并结合自由仿真 FIT 精修各通道物理纯滞后 \(n_k\)</p>
    </div>

    <!-- FORMAT 3: Left-Rail Control Dock + Right Channel Grid Studio -->
    <div class="delay-studio-layout">
      <!-- Left Rail Control Dock -->
      <aside class="delay-rail-dock">
        <div class="industrial-card rail-card">
          <div class="industrial-card-header">
            <div class="industrial-card-title">
              <el-icon><Timer /></el-icon>
              <span>时滞对齐参数</span>
            </div>
          </div>

          <el-form :model="form" label-position="top" class="rail-form">
            <el-form-item label="Delay Source Version">
              <el-select
                v-model="selectedSourceVersionId"
                :loading="loadingSources"
                :disabled="loadingSources || !delaySources.length"
                placeholder="选择 Cleaning 历史版本"
                style="width: 100%"
                @change="handleSourceChange"
              >
                <el-option
                  v-for="source in delaySources"
                  :key="source.version_id"
                  :label="source.name"
                  :value="source.version_id"
                >
                  <div class="source-option">
                    <div class="source-option-main">
                      <span>{{ source.name }}</span>
                      <span class="source-status" :class="source.delay_status">
                        {{ delayStatusLabel(source.delay_status) }}
                      </span>
                    </div>
                    <div class="source-option-meta">
                      {{ formatSourceDate(source.created_at) }} · {{ shortVersionId(source.version_id) }}
                    </div>
                  </div>
                </el-option>
              </el-select>
            </el-form-item>

            <div v-if="selectedSource" class="selected-source-detail">
              <div class="selected-source-status" :class="selectedSource.delay_status">
                {{ delayStatusLabel(selectedSource.delay_status) }}
              </div>
              <div>{{ delayStatusDescription(selectedSource.delay_status) }}</div>
              <div class="selected-source-id font-mono">UUID · {{ selectedSource.version_id }}</div>
            </div>

            <el-alert
              v-else-if="!loadingSources && activeDatasetId"
              title="当前数据集尚无可用于时滞分析的 Cleaning 版本。"
              type="info"
              :closable="false"
              show-icon
              class="source-alert"
            />

            <el-form-item label="输入变量 (u)">
              <el-input v-model="inputColumnsText" placeholder="u1,u2" />
            </el-form-item>

            <el-form-item label="输出变量 (y)">
              <el-input v-model="form.output_column" placeholder="y" />
            </el-form-item>

            <el-form-item label="最大滞后搜索 (Max Lag)">
              <el-input-number v-model="form.max_lag" :min="1" :max="1000" :step="5" style="width: 100%" />
            </el-form-item>

            <el-form-item label="候选数 (Top-K)">
              <el-input-number v-model="form.top_k" :min="1" :max="10" style="width: 100%" />
            </el-form-item>

            <el-button type="primary" size="large" :loading="loading" :disabled="!selectedSource" icon="Search" @click="handleEstimate" style="width: 100%; margin-top: 6px">
              执行预白化时滞估计
            </el-button>
          </el-form>

          <el-alert v-if="errorMessage" type="error" :closable="false" show-icon class="alert-gap">
            <template #title>时滞分析提示：{{ errorMessage }}</template>
          </el-alert>
        </div>

        <div class="industrial-card rail-card theory-box">
          <div class="t-title">⚡ 为什么必须预白化？</div>
          <p class="t-p">工业慢信号自相关严重，直接互相关会导致峰值严重展宽和虚假偏移。系统先通过 AR 模型滤除自相关残差，再与输出互相关求得真实物理延迟。</p>
        </div>
      </aside>

      <!-- Right Main Studio -->
      <main class="delay-main-studio">
        <el-alert
          v-if="restoringResult && !result"
          title="正在读取最近一次已持久化的时滞分析结果…"
          type="info"
          :closable="false"
          show-icon
          class="restore-alert"
        />
        <template v-if="result">
          <!-- Top Multi-Channel Card Array (多通道卡阵列) -->
          <div class="channel-cards-grid">
            <div
              v-for="row in delayRows"
              :key="row.column"
              class="channel-tile industrial-card"
              :class="{ uncertain: row.uncertain }"
            >
              <div class="channel-top">
                <span class="channel-name font-mono">{{ row.column }}</span>
                <span class="channel-status-pill font-mono" :class="{ uncertain: row.uncertain }">
                  {{ row.uncertain ? "UNCERTAIN" : "CONFIRMED" }}
                </span>
              </div>
              <div class="channel-main-lag">
                <span class="lag-label font-mono">VALIDATION-REFINED BEST LAG \(n_k\)</span>
                <span class="lag-num font-mono">{{ row.refined }} <span class="lag-unit">steps</span></span>
              </div>
              <div class="channel-candidates">
                <span class="c-label font-mono">CORRELATION CANDIDATE PEAKS (TOP-K)</span>
                <div v-if="row.candidates.length" class="c-chips">
                  <span
                    v-for="(peak, index) in row.candidates"
                    :key="peak.lag"
                    class="c-chip font-mono"
                    :class="{ 'matches-refined': peak.lag === row.refined }"
                  >
                    #{{ index + 1 }} · lag {{ peak.lag }} · r={{ formatNumber(peak.correlation) }}
                  </span>
                </div>
                <span v-else class="c-unavailable font-mono">N/A</span>
              </div>
              <div class="channel-evidence">
                <span class="evidence-label font-mono">PREWHITENING ORDER</span>
                <strong class="evidence-value font-mono">{{ formatInteger(row.prewhiteningOrder) }}</strong>
              </div>
            </div>
          </div>

          <!-- Central Spectrum Waveform -->
          <div class="industrial-card studio-spectrum-card">
            <div class="industrial-card-header">
              <div class="industrial-card-title">
                <el-icon><DataLine /></el-icon>
                <span>预白化互相关函数响应图谱 (SPECTRUM)</span>
              </div>
              <div class="spectrum-metrics font-mono">
                <span class="text-cyan">VALIDATION FIT: {{ formatNumber(result.validation_fit) }}%</span>
                <span>REFINEMENT: {{ formatInteger(result.refinement_rounds) }} rounds</span>
              </div>
            </div>
            <div class="spectrum-explainer">
              <span><strong>Candidate Peaks</strong> 来自 correlation spectrum。</span>
              <span><strong>Validation-Refined Best Lag</strong> 由后续 validation refinement 选定，可能与候选峰不同。</span>
            </div>
            <ChartContainer :options="chartOptions" height="380px" />
          </div>

          <!-- Bottom 1-Click Apply Action Strip -->
          <div class="industrial-card studio-apply-strip">
            <div class="apply-left">
              <div class="apply-h">APPLY DELAY COMPENSATION · 创建移位版本</div>
              <div class="apply-d">
                {{ result.uncertain_columns.length
                  ? "存在 UNCERTAIN 通道，请先复核 correlation candidate peaks 后再应用。"
                  : "保持 y 与时间轴不变，将各输入特征按 \\(u(t - n_k)\\) 移位对齐，并派生全新版本。" }}
              </div>
            </div>
            <el-button type="primary" size="large" :loading="applying" :disabled="!!result.uncertain_columns.length" @click="handleApply">
              确认应用并生成时滞补偿版本 →
            </el-button>
          </div>
        </template>

        <!-- Empty Placeholder -->
        <div class="industrial-card studio-empty-card" v-else>
          <div class="empty-icon">
            <el-icon><Timer /></el-icon>
          </div>
          <h3>{{ emptyStateTitle }}</h3>
          <p>{{ emptyStateDescription }}</p>
        </div>
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { DataLine, Search, Timer } from "@element-plus/icons-vue";
import ChartContainer from "../components/ChartContainer.vue";
import { applyLagCompensation, calculateDelay, getLatestDelay } from "../api/preprocessing";
import { getDelaySourceVersions } from "../api/datasets";
import type { DelayRequest, DelayResponse, DelaySourceStatus, DelaySourceVersion } from "../types/api";
import { ApiError } from "../api/client";
import { ElMessage, ElMessageBox } from "element-plus";
import { useDatasetStore } from "../stores/datasetStore";

const PALETTE = ["#6E9B69", "#7995A8", "#B28B50", "#96799F", "#B8746E", "#52735A"];

const loading = ref(false);
const applying = ref(false);
const loadingSources = ref(false);
const restoringResult = ref(false);
const result = ref<DelayResponse | null>(null);
const errorMessage = ref("");
const inputColumnsText = ref("u1,u2");
const datasetStore = useDatasetStore();
const delaySources = ref<DelaySourceVersion[]>([]);
const selectedSourceVersionId = ref<string | null>(null);
let rehydrationRequest = 0;
let delaySourcesRequest = 0;

const form = reactive<DelayRequest>({
  version_id: "",
  input_columns: [],
  output_column: "y",
  max_lag: 30,
  top_k: 3,
});

const activeDatasetId = computed(() => datasetStore.activeDataset?.id ?? null);
const selectedSource = computed(
  () => delaySources.value.find((source) => source.version_id === selectedSourceVersionId.value) ?? null
);

const delayStatusLabel = (status: DelaySourceStatus) =>
  ({
    complete: "已完成，可恢复",
    not_analyzed: "尚无成功可用分析",
    unrehydratable: "历史结果无法恢复",
  })[status];

const delayStatusDescription = (status: DelaySourceStatus) =>
  ({
    complete: "将读取该版本已持久化的完整 Delay 分析结果。",
    not_analyzed: "该 Cleaning 版本尚无成功可用 Delay 分析，可直接执行新的预白化时滞估计。",
    unrehydratable: "历史分析存在，但无法恢复完整频谱；可重新执行分析生成新的完整结果。",
  })[status];

const shortVersionId = (versionId: string) => `${versionId.slice(0, 8)}…`;

const formatSourceDate = (value: string) => {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("zh-CN", { dateStyle: "short", timeStyle: "short" }).format(date);
};

const emptyStateTitle = computed(() => {
  if (loadingSources.value) return "正在读取 Delay Source 历史版本…";
  if (!activeDatasetId.value) return "请先选择数据集";
  if (!delaySources.value.length) return "暂无 Cleaning 版本";
  if (selectedSource.value?.delay_status === "not_analyzed") return "该版本尚无成功可用 Delay 分析";
  if (selectedSource.value?.delay_status === "unrehydratable") return "历史 Delay 结果无法恢复";
  return "时滞对齐工作室就绪";
});

const emptyStateDescription = computed(() => {
  if (loadingSources.value) return "正在读取后端已确认的 Cleaning 版本及其 Delay 分析状态。";
  if (!activeDatasetId.value) return "请从数据资产中心选择数据集后再进入时滞分析。";
  if (!delaySources.value.length) return "当前数据集尚无可用于时滞分析的 Cleaning 版本。";
  if (selectedSource.value) return delayStatusDescription(selectedSource.value.delay_status);
  return "请选择一个 Cleaning 历史版本后再执行时滞分析。";
});

const hydratePersistedResult = async (versionId: string, datasetId: string) => {
  const request = ++rehydrationRequest;
  restoringResult.value = true;
  errorMessage.value = "";
  result.value = null;
  try {
    const persisted = await getLatestDelay({ version_id: versionId, dataset_id: datasetId });
    if (request !== rehydrationRequest) return;
    result.value = persisted;
    form.version_id = persisted.source_version_id;
    form.dataset_id = persisted.dataset_id ?? datasetId;
    const persistedInputs = Object.keys(persisted.correlations);
    if (persistedInputs.length) {
      form.input_columns = persistedInputs;
      inputColumnsText.value = persistedInputs.join(",");
    }
  } catch (error) {
    if (request !== rehydrationRequest) return;
    result.value = null;
    errorMessage.value =
      error instanceof ApiError &&
      (error.code === "DELAY_RESULT_NOT_FOUND" || error.code === "DELAY_RESULT_UNAVAILABLE")
        ? "历史结果状态已变化，无法恢复该版本的完整频谱；请重新分析或刷新版本状态。"
        : error instanceof ApiError
          ? error.message
          : String(error);
  } finally {
    if (request === rehydrationRequest) restoringResult.value = false;
  }
};

const selectDelaySource = async (versionId: string | null, datasetId: string) => {
  const source = delaySources.value.find((item) => item.version_id === versionId) ?? null;
  rehydrationRequest += 1;
  restoringResult.value = false;
  result.value = null;
  errorMessage.value = "";
  selectedSourceVersionId.value = source?.version_id ?? null;
  form.version_id = source?.version_id ?? "";
  form.dataset_id = source ? datasetId : null;

  if (source?.delay_status === "complete") {
    await hydratePersistedResult(source.version_id, datasetId);
  }
};

const handleSourceChange = (versionId: string) => {
  const datasetId = activeDatasetId.value;
  if (datasetId) void selectDelaySource(versionId, datasetId);
};

const initializeFromActiveDataset = async () => {
  const activeDataset = datasetStore.activeDataset;
  const request = ++delaySourcesRequest;
  rehydrationRequest += 1;
  loadingSources.value = false;
  restoringResult.value = false;
  delaySources.value = [];
  selectedSourceVersionId.value = null;
  result.value = null;
  errorMessage.value = "";

  if (!activeDataset?.id) {
    form.version_id = "";
    form.dataset_id = null;
    form.input_columns = [];
    inputColumnsText.value = "";
    return;
  }

  form.dataset_id = activeDataset.id;
  form.input_columns = [...activeDataset.input_columns];
  inputColumnsText.value = activeDataset.input_columns.join(",");
  if (activeDataset.output_column) form.output_column = activeDataset.output_column;
  loadingSources.value = true;
  try {
    const data = await getDelaySourceVersions(activeDataset.id);
    if (request !== delaySourcesRequest) return;
    delaySources.value = data.sources;
    await selectDelaySource(data.default_source_version_id, activeDataset.id);
  } catch (error) {
    if (request !== delaySourcesRequest) return;
    errorMessage.value = error instanceof ApiError ? error.message : String(error);
  } finally {
    if (request === delaySourcesRequest) loadingSources.value = false;
  }
};

const handleEstimate = async () => {
  rehydrationRequest += 1;
  restoringResult.value = false;
  errorMessage.value = "";
  if (!selectedSource.value || form.version_id !== selectedSource.value.version_id) {
    errorMessage.value = "请先选择一个 Cleaning 历史版本。";
    return;
  }
  form.input_columns = inputColumnsText.value
    .split(",")
    .map((name) => name.trim())
    .filter(Boolean);
  if (!form.input_columns.length) {
    errorMessage.value = "请至少指定一个输入变量。";
    return;
  }

  loading.value = true;
  try {
    result.value = await calculateDelay(form);
    const source = delaySources.value.find(
      (item) => item.version_id === selectedSourceVersionId.value
    );
    if (source) {
      source.delay_status = "complete";
      source.latest_complete_delay_run_id = result.value.processing_run_id;
    }
    ElMessage.success("时滞估计完成");
  } catch (err) {
    result.value = null;
    errorMessage.value = err instanceof ApiError ? err.message : String(err);
  } finally {
    loading.value = false;
  }
};

const handleApply = async () => {
  if (!result.value) return;
  try {
    await ElMessageBox.confirm(
      "将创建新的不可变 DatasetVersion，源版本不会被覆盖。是否继续？",
      "确认时滞补偿",
      { type: "warning" }
    );
    applying.value = true;
    const applied = await applyLagCompensation({
      version_id: form.version_id,
      lag_map: result.value.best_delays,
      user_confirmed: true,
      recommendation_source: "delay_analysis",
      evidence_summary: Object.fromEntries(
        Object.entries(result.value.best_delays).map(([column, lag]) => [
          column,
          `validation-refined nk=${lag}`,
        ])
      ),
    });
    ElMessage.success(`已创建时滞补偿版本：${applied.result_version_id}`);
  } catch (err) {
    if (err !== "cancel") ElMessage.error(err instanceof ApiError ? err.message : String(err));
  } finally {
    applying.value = false;
  }
};

const delayRows = computed(() => {
  if (!result.value) return [];
  return form.input_columns.map((column) => {
    const candidates = result.value?.candidate_peaks[column] ?? [];
    return {
      column,
      refined: result.value?.best_delays[column] ?? 0,
      candidates,
      uncertain: result.value?.uncertain_columns.includes(column) ?? false,
      prewhiteningOrder: result.value?.prewhitening_orders[column],
    };
  });
});

const chartOptions = computed(() => {
  if (!result.value) return {};
  const columns = Object.keys(result.value.correlations);
  const maxLength = Math.max(...columns.map((c) => result.value!.correlations[c].length), 1);
  const tickInterval = maxLength <= 16 ? 0 : maxLength <= 40 ? 2 : Math.ceil(maxLength / 12);
  return {
    tooltip: {
      trigger: "axis",
      formatter: (params: any[]) => {
        const points = Array.isArray(params) ? params : [params];
        const lag = points[0]?.axisValueLabel ?? points[0]?.axisValue ?? "—";
        return [
          `Lag ${lag}（滞后步数）`,
          ...points.map((point) => `${point.marker}${point.seriesName}: ${Number(point.value).toFixed(3)}`),
        ].join("<br/>");
      },
    },
    legend: { data: columns, top: "2%" },
    grid: { left: "3%", right: "4%", bottom: 106, top: "14%", containLabel: true },
    xAxis: {
      type: "category",
      name: "滞后步数 Lag (samples)",
      nameLocation: "middle",
      nameGap: 42,
      data: Array.from({ length: maxLength }, (_, i) => `${i}`),
      axisLabel: { interval: tickInterval, margin: 12 },
    },
    yAxis: { type: "value", name: "预白化互相关 r" },
    series: columns.map((column, index) => ({
      name: column,
      type: "line",
      showSymbol: false,
      color: PALETTE[index % PALETTE.length],
      lineStyle: { width: 2 },
      data: result.value!.correlations[column],
      markPoint: {
        symbol: "circle",
        symbolSize: 10,
        label: { show: false },
        itemStyle: { color: PALETTE[index % PALETTE.length] },
        tooltip: { formatter: "{b}<br/>correlation r = {c}" },
        data: (result.value!.candidate_peaks[column] ?? []).map((peak, rank) => ({
          name: `${column} · candidate #${rank + 1} · lag ${peak.lag}`,
          coord: [String(peak.lag), peak.correlation],
          value: peak.correlation,
        })),
      },
      markLine: {
        symbol: "none",
        silent: true,
        lineStyle: { type: "dashed", color: PALETTE[index % PALETTE.length] },
        label: { show: false },
        data: [
          {
            name: `${column} · validation-refined best lag`,
            xAxis: String(result.value!.best_delays[column] ?? 0),
          },
        ],
      },
    })),
    dataZoom: [
      { type: "inside", xAxisIndex: 0, filterMode: "none" },
      { type: "slider", xAxisIndex: 0, filterMode: "none", height: 16, bottom: 8 },
    ],
  };
});

const formatNumber = (value: number | null | undefined) => {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return value.toFixed(3);
};

onMounted(() => void initializeFromActiveDataset());

watch(
  () => datasetStore.activeDataset?.id,
  (datasetId, previousDatasetId) => {
    if (datasetId !== previousDatasetId) void initializeFromActiveDataset();
  }
);

const formatInteger = (value: number | null | undefined) => {
  if (value === null || value === undefined || !Number.isFinite(value)) return "N/A";
  return `${value}`;
};
</script>

<style scoped>
.delay-view {
  display: flex;
  flex-direction: column;
  gap: var(--section-gap-md);
  min-height: 100%;
}

/* Stage Nav */
.pipeline-stage-nav {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 8px 14px;
  background: #ffffff;
  border: 1px solid var(--border-light);
  border-radius: 8px;
  font-size: 11px;
}

.stage-badge {
  font-weight: 800;
  color: var(--color-primary);
  background: var(--color-primary-light);
  padding: 2px 8px;
  border-radius: 4px;
  letter-spacing: 0.04em;
}

.stage-links {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}

.stage-link {
  color: var(--text-muted);
  cursor: pointer;
  transition: color 0.16s ease;
}

.stage-link:hover {
  color: var(--color-primary);
}

.stage-link.active {
  color: var(--text-primary);
  font-weight: 700;
  cursor: default;
}

.stage-sep {
  color: var(--text-faint);
}

/* FORMAT 3: Studio Layout */
.delay-studio-layout {
  display: grid;
  grid-template-columns: 310px 1fr;
  gap: 20px;
  align-items: start;
}

.delay-rail-dock {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.rail-card {
  padding: 18px;
  background: #ffffff;
  border-radius: 12px;
  margin-bottom: 0;
}

.theory-box {
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
}

.t-title {
  font-family: var(--font-sans);
  font-size: 12px;
  font-weight: 600;
  color: var(--color-primary);
  letter-spacing: normal;
  margin-bottom: 6px;
}

.delay-view .industrial-card-title {
  font-family: var(--font-sans);
  font-size: 12px;
  font-weight: 500;
  letter-spacing: normal;
  text-transform: none;
}

.t-p {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.5;
  margin: 0;
}

.alert-gap {
  margin-top: 12px;
}

.source-alert {
  margin: -2px 0 10px;
}

.source-option {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 3px 0;
  line-height: 1.35;
}

.source-option-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-weight: 700;
}

.source-option-meta,
.selected-source-id {
  color: var(--text-muted);
  font-size: 10px;
}

.source-status,
.selected-source-status {
  display: inline-flex;
  align-items: center;
  width: fit-content;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 700;
  line-height: 1.4;
  padding: 2px 6px;
}

.source-status.complete,
.selected-source-status.complete {
  background: #ecfdf5;
  color: #047857;
}

.source-status.not_analyzed,
.selected-source-status.not_analyzed {
  background: #eff6ff;
  color: #1d4ed8;
}

.source-status.unrehydratable,
.selected-source-status.unrehydratable {
  background: #fffbeb;
  color: #b45309;
}

.selected-source-detail {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: -2px 0 12px;
  padding: 10px;
  border: 1px solid var(--border-light);
  border-radius: 8px;
  background: var(--bg-subtle);
  color: var(--text-secondary);
  font-size: 11px;
  line-height: 1.45;
}

.restore-alert {
  margin: 0;
}

/* Right Main Studio */
.delay-main-studio {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* Channel Tiles Array */
.channel-cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 14px;
}

.channel-tile {
  padding: 16px;
  background: #ffffff;
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 0;
  border-top: 3px solid var(--color-primary);
}

.channel-tile.uncertain {
  border-top-color: #d97706;
}

.channel-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.channel-name {
  font-size: 14px;
  font-weight: 800;
  color: var(--text-primary);
}

.channel-status-pill {
  font-size: 9px;
  font-weight: 700;
  color: #059669;
  background: #ecfdf5;
  padding: 1px 5px;
  border-radius: 3px;
}

.channel-status-pill.uncertain {
  color: #b45309;
  background: #fffbeb;
}

.channel-main-lag {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.lag-label {
  font-size: 10px;
  font-weight: 700;
  color: var(--text-muted);
}

.lag-num {
  font-size: 24px;
  font-weight: 800;
  color: var(--color-primary);
  line-height: 1.1;
}

.lag-unit {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-muted);
}

.channel-candidates {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding-top: 8px;
  border-top: 1px dashed var(--border-light);
}

.c-label {
  font-size: 9px;
  color: var(--text-muted);
  font-weight: 700;
}

.c-chips {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.c-chip {
  font-size: 10px;
  color: var(--text-secondary);
  background: var(--bg-subtle);
  padding: 2px 6px;
  border-radius: 4px;
}

.c-chip.matches-refined {
  background: var(--color-primary-light);
  color: var(--color-primary);
  font-weight: 700;
}

.c-unavailable {
  font-size: 10px;
  color: var(--text-muted);
}

.channel-evidence {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--border-light);
}

.evidence-label {
  font-size: 9px;
  color: var(--text-muted);
  font-weight: 700;
}

.evidence-value {
  font-size: 12px;
  color: var(--text-primary);
}

/* Studio Spectrum */
.studio-spectrum-card {
  padding: 20px;
  background: #ffffff;
  border-radius: 12px;
  margin-bottom: 0;
  order: 1;
}

.channel-cards-grid {
  order: 2;
}

.spectrum-metrics {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px 14px;
  font-size: 11px;
  color: var(--text-muted);
}

.spectrum-explainer {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 18px;
  margin: 2px 0 12px;
  padding: 8px 10px;
  border-left: 3px solid var(--color-primary);
  background: var(--bg-subtle);
  color: var(--text-secondary);
  font-size: 11px;
  line-height: 1.5;
}

.spectrum-explainer strong {
  color: var(--text-primary);
}

/* Studio Apply Strip */
.studio-apply-strip {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 18px 22px;
  background: var(--surface-1);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  margin-bottom: 0;
  gap: 20px;
  order: 3;
}

.apply-h {
  font-family: var(--font-sans);
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  letter-spacing: normal;
  margin-bottom: 3px;
}

.apply-d {
  font-size: 12px;
  color: var(--text-secondary);
}

.studio-empty-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80px 20px;
  text-align: center;
  background: var(--surface-1);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
}

.empty-icon {
  width: 44px;
  height: 44px;
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  color: var(--text-tertiary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  margin-bottom: 12px;
}

.studio-empty-card h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}

.studio-empty-card p {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--text-secondary);
  max-width: 420px;
}

@media (max-width: 960px) {
  .delay-studio-layout {
    grid-template-columns: 1fr;
  }
  .studio-apply-strip {
    flex-direction: column;
    align-items: stretch;
  }
  .studio-spectrum-card .industrial-card-header {
    align-items: flex-start;
    gap: 8px;
  }
  .spectrum-metrics {
    justify-content: flex-start;
  }
}
</style>
