<template>
  <div class="page-container cleaning-view">
    <!-- Top Stage Header Navigation -->
    <div class="pipeline-stage-nav">
      <div class="stage-badge font-mono">STAGE 02 · DATA CLEANING LAB</div>
      <div class="stage-links">
        <span class="stage-link active">02 时间清洗</span>
        <span class="stage-sep">›</span>
        <span class="stage-link" @click="$router.push('/preprocessing/segmentation')">03 D-最优优选</span>
        <span class="stage-sep">›</span>
        <span class="stage-link" @click="$router.push('/preprocessing/delay')">04 时滞对齐</span>
        <span class="stage-sep">›</span>
        <span class="stage-link" @click="$router.push('/preprocessing/collinearity')">05 VIF 降维</span>
      </div>
    </div>

    <!-- Page Header with Inline Dataset Pill -->
    <div class="cleaning-hero-bar">
      <div>
        <span class="page-eyebrow font-mono">EQUISPACED RESAMPLING & 3-SIGMA TRIAGE</span>
        <h2>时间规整与清洗实验室</h2>
        <p class="subtitle">消除采样不均匀、补全缺失值并过滤尖峰异常点，派生可信基准版本 V1_Cleaned</p>
      </div>

      <div class="source-hero-badge" v-if="sourceVersion">
        <div class="badge-top font-mono">
          <span class="badge-dot"></span>
          <span>源数据版本 (SOURCE)</span>
          <el-tag size="small" type="primary" effect="light">本次清洗输入</el-tag>
        </div>
        <div class="badge-name">{{ sourceVersion.name }}</div>
        <div class="badge-hash font-mono">{{ sourceVersion.id }}</div>
      </div>
      <div class="source-hero-badge pending" v-else>
        <span class="font-mono">源数据版本</span>
        <p>{{ sourceLoadMessage }}</p>
      </div>
    </div>

    <!-- FORMAT 1: Horizontal High-Density Control Strip (横向参数控制中枢) -->
    <section class="cleaning-toolbar industrial-card">
      <div class="toolbar-section">
        <span class="tb-label font-mono">重采样周期 Ts (s)</span>
        <el-input-number v-model="form.target_sample_period_seconds" :min="0.1" :max="60" :step="0.5" size="default" />
      </div>

      <div class="tb-divider"></div>

      <div class="toolbar-section">
        <span class="tb-label font-mono">异常值检测算法</span>
        <el-select v-model="form.anomaly_detector" size="default" style="width: 190px">
          <el-option label="Hampel Filter (3σ 稳健)" value="hampel" />
          <el-option label="IQR 四分位距" value="iqr" />
          <el-option label="Z-Score 阈值" value="z_score" />
        </el-select>
      </div>

      <div class="tb-divider" v-if="form.anomaly_detector === 'hampel'"></div>

      <div class="toolbar-section" v-if="form.anomaly_detector === 'hampel'">
        <span class="tb-label font-mono">Hampel 滑窗 k</span>
        <el-input-number v-model="form.hampel_window" :min="3" :max="21" :step="2" size="default" />
      </div>

      <div class="tb-divider"></div>

      <div class="toolbar-section">
        <span class="tb-label font-mono">缺失值插值策略</span>
        <el-select v-model="form.interpolation" size="default" style="width: 170px">
          <el-option label="线性插值 (Linear)" value="linear" />
          <el-option label="前向填充 (Forward)" value="forward_fill" />
          <el-option label="后向填充 (Backward)" value="backward_fill" />
        </el-select>
      </div>

      <div class="tb-actions">
        <el-button
          type="primary"
          size="default"
          :loading="loading"
          :disabled="!sourceVersion || loading"
          icon="MagicStick"
          @click="handleClean"
        >
          执行规整并派生 V1_Cleaned
        </el-button>
      </div>
    </section>

    <el-alert v-if="errorMessage" type="error" :title="errorMessage" :closable="false" show-icon>
      <ul v-if="validationIssues.length" class="validation-issues">
        <li v-for="issue in validationIssues" :key="issue">{{ issue }}</li>
      </ul>
    </el-alert>

    <!-- FORMAT 1: Full-Width Dual-Track Waveform Inspection Deck (全宽双轨波形对账) -->
    <section class="industrial-card waveform-inspection-card">
      <div class="industrial-card-header">
        <div class="industrial-card-title">
          <el-icon><DataAnalysis /></el-icon>
          <span>多通道时序规整波形对比 (RAW VS CLEANED)</span>
        </div>
        <div class="header-pills" v-if="cleanedData">
          <el-tag type="success" effect="light" class="font-mono">已修复 {{ cleanedData.total_cleaned_points }} 个唯一数据单元格</el-tag>
        </div>
      </div>

      <div v-if="cleanedData">
        <el-alert
          class="cleaning-summary"
          type="success"
          :title="cleaningResultSummary"
          :closable="false"
          show-icon
        />
        <ChartContainer :options="compareChartOptions" height="380px" />
      </div>

      <div class="clean-empty-state" v-else>
        <div class="clean-empty-icon">
          <el-icon><Operation /></el-icon>
        </div>
        <h4>等待清洗触发</h4>
        <p>在上方工具栏调整重采样周期与 3σ 滤波参数，点击「执行规整」在此生成高分辨率对账波形。</p>
      </div>
    </section>

    <!-- FORMAT 1: Bottom 3-Card Telemetry Triage Strip (底部修复三联卡) -->
    <div class="triage-cards-grid">
      <div class="triage-card industrial-card">
        <div class="triage-num font-mono">01</div>
        <div class="triage-content">
          <div class="triage-title font-mono">HAMPEL 3-SIGMA FILTER</div>
          <div class="triage-desc">计算滑窗中位数绝对差 (MAD)，自适应截断偏离 3σ 的高频孤立尖峰，避免极大异常值拉偏最小二乘超平面。</div>
        </div>
      </div>

      <div class="triage-card industrial-card">
        <div class="triage-num font-mono">02</div>
        <div class="triage-content">
          <div class="triage-title font-mono">EQUISPACED RESAMPLING</div>
          <div class="triage-desc">重构严格单调递增的等间隔时间轴，统一多源 DCS 采样率，为后续差分方程辨识提供稳定的时间步长基准。</div>
        </div>
      </div>

      <div class="triage-card industrial-card next-triage-card" @click="$router.push('/preprocessing/segmentation')">
        <div class="triage-num font-mono">03</div>
        <div class="triage-content">
          <div class="triage-title font-mono">NEXT STEP · D-OPTIMAL</div>
          <div class="triage-desc">清洗数据已固化至当前资产树。点击直接进入质量门控与 D-最优高动态区间优选 →</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from "vue";
import { useRoute } from "vue-router";
import { Operation, MagicStick, DataAnalysis } from "@element-plus/icons-vue";
import ChartContainer from "../components/ChartContainer.vue";
import { cleanDataset } from "../api/preprocessing";
import { getDatasetDetail, getDatasetVersions } from "../api/datasets";
import { useDatasetStore } from "../stores/datasetStore";
import { ApiError } from "../api/client";
import type { CleanRequest, CleanResponse, DatasetItem, DatasetVersionNode } from "../types/api";
import { ElMessage } from "element-plus";

type CleaningForm = Pick<
  CleanRequest,
  "target_sample_period_seconds" | "interpolation" | "anomaly_detector" | "hampel_window"
>;

const route = useRoute();
const datasetStore = useDatasetStore();
const loading = ref(false);
const cleanedData = ref<CleanResponse | null>(null);
const sourceDataset = ref<DatasetItem | null>(null);
const sourceVersion = ref<DatasetVersionNode | null>(null);
const sourceLoadMessage = ref("正在加载源数据版本…");
const errorMessage = ref("");
const validationIssues = ref<string[]>([]);

const form = reactive<CleaningForm>({
  target_sample_period_seconds: 1.0,
  interpolation: "linear",
  anomaly_detector: "hampel",
  hampel_window: 5,
});

const queryValue = (name: "dataset_id" | "version_id") => {
  const value = route.query[name];
  return typeof value === "string" && value ? value : undefined;
};

const loadSourceVersion = async () => {
  const selectedDataset = datasetStore.activeDataset;
  const datasetId = queryValue("dataset_id") || selectedDataset?.id;
  const versionId =
    queryValue("version_id") ||
    selectedDataset?.version_id ||
    selectedDataset?.latest_version_id;
  if (!datasetId || !versionId) {
    sourceLoadMessage.value = "请从数据资产中心或数据集详情页选择源数据版本。";
    return;
  }
  try {
    const [dataset, versions] = await Promise.all([
      getDatasetDetail(datasetId),
      getDatasetVersions(datasetId),
    ]);
    const version = versions.nodes.find((node) => node.id === versionId);
    if (!version) {
      sourceLoadMessage.value = "指定的源数据版本不存在于当前数据集。";
      return;
    }
    sourceDataset.value = dataset;
    sourceVersion.value = version;
    datasetStore.setActiveDataset(dataset);
  } catch (error) {
    sourceLoadMessage.value =
      error instanceof ApiError
        ? `源版本加载失败 [${error.code}]：${error.message}`
        : "源版本加载失败，请确认后端服务和数据资产状态。";
  }
};

const formatValidationIssues = (error: unknown): string[] => {
  if (!(error instanceof ApiError) || !Array.isArray(error.details?.issues)) return [];
  return error.details.issues.map((issue: { loc?: unknown; msg?: unknown }) => {
    const location = Array.isArray(issue.loc)
      ? issue.loc.filter((item) => item !== "body").join(".")
      : "请求参数";
    return `${location || "请求参数"}：${typeof issue.msg === "string" ? issue.msg : "参数无效"}`;
  });
};

const handleClean = async () => {
  if (loading.value || !sourceDataset.value || !sourceVersion.value) return;
  loading.value = true;
  errorMessage.value = "";
  validationIssues.value = [];
  try {
    const request: CleanRequest = {
      dataset_id: sourceDataset.value.id,
      version_id: sourceVersion.value.id,
      target_sample_period_seconds: form.target_sample_period_seconds,
      interpolation: form.interpolation,
      anomaly_detector: form.anomaly_detector,
      hampel_window: form.hampel_window,
    };
    const res = await cleanDataset(request);
    cleanedData.value = res;
    ElMessage.success(`成功生成清洗后数据版本: ${res.new_version_id}`);
  } catch (error) {
    cleanedData.value = null;
    const code = error instanceof ApiError ? error.code : "ERR";
    const message = error instanceof Error ? error.message : "未知错误";
    validationIssues.value = formatValidationIssues(error);
    errorMessage.value = `清洗失败 [${code}]: ${message}`;
    ElMessage.error(errorMessage.value);
  } finally {
    loading.value = false;
  }
};

const compareChartOptions = computed(() => {
  if (!cleanedData.value) return {};
  const xData = Array.from({ length: cleanedData.value.raw_series.length }, (_, i) => `${i}s`);

  return {
    tooltip: { trigger: "axis" },
    legend: { data: ["原始序列 (Raw)", "清洗后序列 (Cleaned)"], top: "2%" },
    grid: { left: "3%", right: "4%", bottom: "8%", top: "14%", containLabel: true },
    xAxis: { type: "category", data: xData },
    yAxis: { type: "value" },
    series: [
      {
        name: "原始序列 (Raw)",
        type: "line",
        color: "#B8746E",
        lineStyle: { type: "dashed", width: 1.5 },
        data: cleanedData.value.raw_series,
      },
      {
        name: "清洗后序列 (Cleaned)",
        type: "line",
        color: "#6E9B69",
        lineStyle: { width: 2.2 },
        data: cleanedData.value.cleaned_series,
      },
    ],
  };
});

const cleaningResultSummary = computed(() => {
  if (!cleanedData.value) return "";
  const changes = cleanedData.value.summary?.changes;
  if (!changes || changes.breakdown_status === "not_recorded") {
    return `共修复 ${cleanedData.value.total_cleaned_points} 个唯一数据单元格；历史结果未记录分类明细。`;
  }
  const parts = [
    `缺失值填补 ${changes.missing_value_fills ?? 0} 个`,
    `异常值替换 ${changes.outlier_replacements ?? 0} 个`,
    `平滑修改 ${changes.smoothing_changes ?? 0} 个`,
  ];
  const rowOperations = [
    `重复时间戳处理 ${changes.duplicate_timestamps_processed ?? 0} 行`,
    `重采样新增空行 ${changes.resampling_empty_rows_created ?? 0} 行`,
  ];
  const overlap = changes.category_counts_may_overlap
    ? "各类别可能重叠，总数按唯一变更单元格去重。"
    : "";
  return `共修复 ${changes.unique_changed_cells ?? cleanedData.value.total_cleaned_points} 个唯一数据单元格：${parts.join("、")}；另有${rowOperations.join("、")}。${overlap}`;
});

onMounted(loadSourceVersion);
</script>

<style scoped>
.cleaning-view {
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

/* Hero Bar */
.cleaning-hero-bar {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 20px;
  flex-wrap: wrap;
}

.source-hero-badge {
  padding: 10px 16px;
  background: #ffffff;
  border: 1px solid var(--border-light);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 260px;
}

.badge-top {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 10px;
  font-weight: 700;
  color: var(--text-muted);
}

.badge-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #059669;
}

.badge-name {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-primary);
}

.badge-hash {
  font-size: 11px;
  color: var(--text-muted);
}

.source-hero-badge.pending {
  color: var(--text-secondary);
  font-size: 12px;
}

/* Format 1: Horizontal Toolbar */
.cleaning-toolbar {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 16px 20px;
  background: #ffffff;
  border-radius: 10px;
  margin-bottom: 0;
  flex-wrap: wrap;
}

.toolbar-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.tb-label {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-muted);
  letter-spacing: 0.04em;
}

.tb-divider {
  width: 1px;
  height: 38px;
  background: var(--border-light);
}

.tb-actions {
  margin-left: auto;
  display: flex;
  align-items: flex-end;
  padding-top: 18px;
}

/* Full-width Waveform Deck */
.waveform-inspection-card {
  padding: 20px;
  background: #ffffff;
  border-radius: 12px;
  margin-bottom: 0;
}

.clean-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 70px 20px;
  text-align: center;
}

.clean-empty-icon {
  width: 50px;
  height: 50px;
  border-radius: 12px;
  background: var(--color-primary-light);
  color: var(--color-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  margin-bottom: 12px;
}

.clean-empty-state h4 {
  margin: 0;
  font-size: 16px;
  font-weight: 800;
  color: var(--text-primary);
}

.clean-empty-state p {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--text-secondary);
  max-width: 440px;
}

/* 3-Card Triage */
.triage-cards-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

.triage-card {
  display: flex;
  gap: 14px;
  padding: 16px 18px;
  background: #ffffff;
  border-radius: 10px;
  margin-bottom: 0;
}

.triage-num {
  font-size: 13px;
  font-weight: 800;
  color: var(--color-primary);
  background: var(--color-primary-light);
  width: 26px;
  height: 26px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.triage-content {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.triage-title {
  font-size: 11px;
  font-weight: 800;
  color: var(--text-primary);
  letter-spacing: 0.04em;
}

.triage-desc {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.5;
}

.next-triage-card {
  cursor: pointer;
  border-color: var(--border-default);
  background: var(--surface-1);
  transition: all 0.2s ease;
}

.next-triage-card:hover {
  transform: translateY(-2px);
  background: var(--surface-2);
  border-color: var(--border-strong);
}

.validation-issues {
  margin: 6px 0 0;
  padding-left: 16px;
  font-size: 12px;
}

@media (max-width: 1000px) {
  .cleaning-toolbar {
    flex-direction: column;
    align-items: stretch;
  }
  .tb-divider {
    display: none;
  }
  .tb-actions {
    margin-left: 0;
    padding-top: 0;
  }
  .triage-cards-grid {
    grid-template-columns: 1fr;
  }
}
</style>
