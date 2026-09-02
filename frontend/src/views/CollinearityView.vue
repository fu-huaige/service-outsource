<template>
  <div class="page-container collinearity-view">
    <!-- Top Stage Header Navigation -->
    <div class="pipeline-stage-nav">
      <div class="stage-badge font-mono">STAGE 05 · COLLINEARITY & FEATURE REDUCTION</div>
      <div class="stage-links">
        <span class="stage-link" @click="$router.push('/preprocessing/cleaning')">02 时间清洗</span>
        <span class="stage-sep">›</span>
        <span class="stage-link" @click="$router.push('/preprocessing/segmentation')">03 D-最优优选</span>
        <span class="stage-sep">›</span>
        <span class="stage-link" @click="$router.push('/preprocessing/delay')">04 时滞对齐</span>
        <span class="stage-sep">›</span>
        <span class="stage-link active">05 VIF 降维</span>
      </div>
    </div>

    <!-- Header with Quick Action -->
    <div class="page-header">
      <span class="page-eyebrow font-mono">PEARSON CORRELATION & VARIANCE INFLATION FACTOR</span>
      <h2>共线性检测与冗余特征剔除面板</h2>
      <p class="subtitle">计算 Pearson 相关系数矩阵、方差膨胀因子 VIF 与矩阵条件数；由工程师安全确认后派生 V3_FeatureSet</p>
    </div>

    <div class="industrial-card analysis-context-card">
      <div class="analysis-context-header">
        <div>
          <span class="context-eyebrow font-mono">ANALYSIS CONTEXT</span>
          <h3>分析上下文</h3>
        </div>
        <span class="context-note">先选择数据集，再选择后端确认的时滞补偿版本</span>
      </div>

      <div class="analysis-context-grid">
        <div class="context-field">
          <label>数据集</label>
          <el-select
            v-model="selectedDatasetId"
            data-test="dataset-select"
            filterable
            :loading="loadingDatasets"
            placeholder="按名称选择数据集"
            style="width: 100%"
            @change="handleDatasetChange"
          >
            <el-option
              v-for="dataset in datasetOptions"
              :key="dataset.id"
              :label="dataset.name"
              :value="dataset.id"
            >
              <div class="selector-option">
                <span class="selector-option-name">{{ dataset.name }}</span>
                <span class="selector-option-meta font-mono">
                  {{ dataset.row_count }} rows · {{ dataset.col_count ?? dataset.column_count ?? 0 }} cols · {{ shortId(dataset.id) }}
                </span>
              </div>
            </el-option>
          </el-select>
        </div>

        <div class="context-field">
          <label>时滞补偿版本</label>
          <el-select
            v-model="selectedSourceVersionId"
            data-test="source-select"
            :loading="loadingSources"
            :disabled="loadingSources || !collinearitySources.length"
            placeholder="选择时滞补偿版本"
            style="width: 100%"
            @change="handleSourceChange"
          >
            <el-option
              v-for="source in collinearitySources"
              :key="source.version_id"
              :label="source.name"
              :value="source.version_id"
            >
              <div class="selector-option source-selector-option">
                <div class="selector-option-line">
                  <span class="selector-option-name">{{ source.name }}</span>
                  <span class="source-status" :class="source.collinearity_status">
                    {{ sourceStatusLabel(source.collinearity_status) }}
                  </span>
                </div>
                <span class="selector-option-meta font-mono">
                  V{{ source.version_index }} · {{ formatSourceDate(source.created_at) }} · {{ shortId(source.version_id) }}
                </span>
              </div>
            </el-option>
          </el-select>
        </div>
      </div>

      <el-alert
        v-if="datasetError || sourceError"
        :title="datasetError || sourceError"
        type="error"
        :closable="false"
        show-icon
        class="context-alert"
      />
      <el-alert
        v-else-if="selectedDatasetId && !loadingSources && !collinearitySources.length"
        title="该数据集暂无可用于共线性分析的时滞补偿版本。"
        description="请先完成时滞补偿后再进行共线性分析。"
        type="info"
        :closable="false"
        show-icon
        class="context-alert"
      />
      <div v-else-if="selectedSource" class="selected-source-detail">
        <span class="source-status" :class="selectedSource.collinearity_status">
          {{ sourceStatusLabel(selectedSource.collinearity_status) }}
        </span>
        <span>{{ sourceStatusDescription(selectedSource.collinearity_status) }}</span>
        <span class="selected-source-id font-mono">UUID · {{ selectedSource.version_id }}</span>
      </div>
      <div v-else-if="!loadingDatasets && !selectedDatasetId" class="context-prompt">
        请选择数据集以读取可用于共线性分析的时滞补偿版本。
      </div>
    </div>

    <!-- FORMAT 4: Top Slider Controller Strip (顶部横向控制条) -->
    <div class="industrial-card collin-control-strip">
      <div class="cs-row">
        <div class="cs-item">
          <label>输入特征候选 (u)</label>
          <el-input
            v-model="inputColumnsText"
            data-test="input-columns"
            placeholder="u1,u2,u3,u4"
            size="small"
          />
        </div>
        <div class="cs-item">
          <label>相关报警阈值</label>
          <el-input-number v-model="form.correlation_threshold" :min="0.5" :max="1" :step="0.01" :precision="2" size="small" />
        </div>
        <div class="cs-item">
          <label>VIF 膨胀阈值</label>
          <el-input-number v-model="form.vif_threshold" :min="1.5" :max="100" :step="0.5" size="small" />
        </div>
        <div class="cs-actions">
          <el-button
            data-test="analyze-button"
            type="primary"
            size="small"
            :loading="loading || restoringResult"
            :disabled="analyzeDisabled"
            icon="Search"
            @click="handleAnalyze"
          >
            执行诊断分析
          </el-button>
        </div>
      </div>
    </div>

    <el-alert v-if="errorMessage" type="error" :closable="false" show-icon class="alert-gap">
      <template #title>诊断失败：{{ errorMessage }}</template>
    </el-alert>

    <!-- FORMAT 4: 3-Panel Tri-View Studio Grid (三联视窗工作台) -->
    <div class="collin-tri-grid" v-if="result">
      <!-- Panel A: Pearson Heatmap Matrix -->
      <div class="industrial-card tri-panel">
        <div class="industrial-card-header">
          <div class="industrial-card-title">
            <el-icon><Grid /></el-icon>
            <span>Pearson 相关性矩阵</span>
          </div>
          <span class="card-tag font-mono">HEATMAP</span>
        </div>
        <ChartContainer :options="heatmapOptions" height="340px" />
      </div>

      <!-- Panel B: VIF Bar Chart Radar -->
      <div class="industrial-card tri-panel">
        <div class="industrial-card-header">
          <div class="industrial-card-title">
            <el-icon><Histogram /></el-icon>
            <span>各特征 VIF 膨胀因子</span>
          </div>
          <span class="card-tag localized-card-tag">
            阈值: <span class="font-mono">{{ form.vif_threshold || 10 }}</span>
          </span>
        </div>
        <ChartContainer :options="vifOptions" height="340px" />
      </div>

      <!-- Panel C: Elimination & Human Approval Board -->
      <div class="industrial-card tri-panel decision-panel">
        <div class="industrial-card-header">
          <div class="industrial-card-title">
            <el-icon><TrendCharts /></el-icon>
            <span>特征剔除决策</span>
          </div>
          <el-tag :type="conditionSeverity" effect="light" size="small" class="font-mono">
            Cond: {{ formatNumber(result.condition_number) }}
          </el-tag>
        </div>

        <div class="decision-content">
          <div class="stat-mini-box">
            <div>
              <span class="s-l">总特征数</span>
              <strong class="s-v">{{ result.variables.length }}</strong>
            </div>
            <div class="s-div"></div>
            <div>
              <span class="s-l">高相关组</span>
              <strong class="s-v text-cyan">{{ result.correlated_groups.length }}</strong>
            </div>
            <div class="s-div"></div>
            <div>
              <span class="s-l">建议剔除</span>
              <strong class="s-v text-danger">{{ dropCount }}</strong>
            </div>
          </div>

          <div v-if="result.correlated_groups.length" class="correlated-list">
            <div class="cl-title">强相关共线性通道组：</div>
            <div class="cl-chips">
              <el-tag
                v-for="(group, index) in result.correlated_groups"
                :key="index"
                type="warning"
                effect="plain"
                size="small"
                class="font-mono"
              >
                {{ group.join(" ↔ ") }}
              </el-tag>
            </div>
          </div>

          <div class="drop-recommendations-list" v-if="dropCandidates.length">
            <div class="rec-title">⚠️ 建议剔除列表 (人工确认后生效):</div>
            <div
              v-for="item in dropCandidates"
              :key="item.variable"
              class="rec-item"
            >
              <span class="rec-var font-mono">{{ item.variable }}</span>
              <span class="rec-vif font-mono">VIF = {{ formatNumber(result.vif_scores[item.variable]) }}</span>
            </div>
          </div>
          <div class="no-drops" v-else>
            🟢 无重度共线性特征，全通道设计矩阵满秩且数值稳定。
          </div>

          <div class="decision-action-strip" v-if="dropCandidates.length">
            <el-button type="danger" size="default" :loading="applying" @click="handleApply" style="width: 100%">
              确认剔除并生成 V3_FeatureSet →
            </el-button>
          </div>
        </div>
      </div>
    </div>

    <!-- Empty Placeholder -->
    <div class="industrial-card collin-empty-card" v-else>
      <div class="empty-icon">
        <el-icon><Share /></el-icon>
      </div>
      <h3>{{ emptyStateTitle }}</h3>
      <p>{{ emptyStateDescription }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { Grid, Histogram, Share, TrendCharts } from "@element-plus/icons-vue";
import ChartContainer from "../components/ChartContainer.vue";
import {
  applyFeatureSelection,
  calculateCollinearity,
  getLatestCollinearity,
} from "../api/preprocessing";
import {
  getCollinearitySourceVersions,
  getDatasetDetail,
  listDatasets,
} from "../api/datasets";
import type {
  CollinearityRequest,
  CollinearityResponse,
  CollinearitySourceStatus,
  CollinearitySourceVersionItem,
  DatasetItem,
} from "../types/api";
import { ApiError } from "../api/client";
import { ElMessage, ElMessageBox } from "element-plus";
import { useDatasetStore } from "../stores/datasetStore";

const loading = ref(false);
const applying = ref(false);
const loadingDatasets = ref(false);
const loadingSources = ref(false);
const restoringResult = ref(false);
const result = ref<CollinearityResponse | null>(null);
const errorMessage = ref("");
const datasetError = ref("");
const sourceError = ref("");
const inputColumnsText = ref("");
const datasetStore = useDatasetStore();
const datasetOptions = ref<DatasetItem[]>([]);
const selectedDatasetId = ref<string | null>(null);
const collinearitySources = ref<CollinearitySourceVersionItem[]>([]);
const selectedSourceVersionId = ref<string | null>(null);
let datasetListRequest = 0;
let datasetContextRequest = 0;
let sourceListRequest = 0;
let rehydrationRequest = 0;
let analysisRequest = 0;

const form = reactive<CollinearityRequest>({
  version_id: "",
  input_columns: [],
  correlation_threshold: 0.85,
  vif_threshold: 10,
});

const selectedSource = computed(
  () =>
    collinearitySources.value.find(
      (source) => source.version_id === selectedSourceVersionId.value
    ) ?? null
);

const hasValidLagCompensationSource = computed(
  () =>
    collinearitySources.value.length > 0 &&
    selectedSource.value?.operation_name === "preprocessing.lag_compensation"
);

const analyzeDisabled = computed(
  () =>
    !selectedDatasetId.value ||
    collinearitySources.value.length === 0 ||
    !hasValidLagCompensationSource.value ||
    loadingDatasets.value ||
    loadingSources.value ||
    restoringResult.value ||
    loading.value
);

const sourceStatusLabel = (status: CollinearitySourceStatus) =>
  ({
    complete: "已完成，可恢复",
    not_analyzed: "尚未分析",
    unrehydratable: "历史结果不可恢复",
  })[status];

const sourceStatusDescription = (status: CollinearitySourceStatus) =>
  ({
    complete: "正在使用该版本已持久化的完整共线性分析结果。",
    not_analyzed: "该时滞补偿版本尚未进行共线性分析。",
    unrehydratable: "该版本存在历史分析记录，但结果无法按当前格式完整恢复，可重新执行分析。",
  })[status];

const shortId = (value: string) => `${value.slice(0, 8)}…`;

const formatSourceDate = (value: string) => {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("zh-CN", { dateStyle: "short", timeStyle: "short" }).format(date);
};

const emptyStateTitle = computed(() => {
  if (loadingDatasets.value) return "正在读取数据集…";
  if (!selectedDatasetId.value) return "请先选择数据集";
  if (loadingSources.value) return "正在读取时滞补偿版本…";
  if (!collinearitySources.value.length) return "暂无时滞补偿版本";
  if (restoringResult.value) return "正在恢复历史共线性结果…";
  if (selectedSource.value) return sourceStatusLabel(selectedSource.value.collinearity_status);
  return "请选择时滞补偿版本";
});

const emptyStateDescription = computed(() => {
  if (!selectedDatasetId.value) return "请在分析上下文中按名称选择数据集。";
  if (!collinearitySources.value.length && !loadingSources.value) {
    return "该数据集暂无可用于共线性分析的时滞补偿版本，请先完成时滞补偿。";
  }
  if (selectedSource.value) return sourceStatusDescription(selectedSource.value.collinearity_status);
  return "选择后端确认的 Lag Compensation Source 后，可恢复历史结果或手动执行诊断。";
});

const invalidateSourceRequests = () => {
  sourceListRequest += 1;
  rehydrationRequest += 1;
  analysisRequest += 1;
  loadingSources.value = false;
  restoringResult.value = false;
  loading.value = false;
};

const clearSourceContext = () => {
  invalidateSourceRequests();
  collinearitySources.value = [];
  selectedSourceVersionId.value = null;
  form.version_id = "";
  form.dataset_id = null;
  form.input_columns = [];
  inputColumnsText.value = "";
  result.value = null;
  errorMessage.value = "";
  sourceError.value = "";
};

const hydratePersistedResult = async (versionId: string, datasetId: string) => {
  const request = ++rehydrationRequest;
  restoringResult.value = true;
  errorMessage.value = "";
  result.value = null;
  try {
    const persisted = await getLatestCollinearity({
      version_id: versionId,
      dataset_id: datasetId,
    });
    if (
      request !== rehydrationRequest ||
      selectedDatasetId.value !== datasetId ||
      selectedSourceVersionId.value !== versionId
    ) {
      return;
    }
    result.value = persisted;
    form.version_id = versionId;
    form.dataset_id = datasetId;
    if (persisted.variables.length) {
      form.input_columns = [...persisted.variables];
      inputColumnsText.value = persisted.variables.join(",");
    }
  } catch (error) {
    if (request !== rehydrationRequest) return;
    result.value = null;
    errorMessage.value =
      error instanceof ApiError &&
      (error.code === "COLLINEARITY_RESULT_NOT_FOUND" ||
        error.code === "COLLINEARITY_RESULT_UNAVAILABLE")
        ? "历史结果状态已变化，无法恢复该版本的完整共线性结果；请重新分析或刷新版本状态。"
        : error instanceof ApiError
          ? error.message
          : String(error);
  } finally {
    if (request === rehydrationRequest) restoringResult.value = false;
  }
};

const selectCollinearitySource = async (versionId: string | null, datasetId: string) => {
  const source =
    collinearitySources.value.find((item) => item.version_id === versionId) ?? null;
  rehydrationRequest += 1;
  analysisRequest += 1;
  restoringResult.value = false;
  loading.value = false;
  result.value = null;
  errorMessage.value = "";
  selectedSourceVersionId.value = source?.version_id ?? null;
  form.version_id = source?.version_id ?? "";
  form.dataset_id = datasetId;

  if (source?.collinearity_status === "complete") {
    await hydratePersistedResult(source.version_id, datasetId);
  }
};

const handleSourceChange = (versionId: string) => {
  const datasetId = selectedDatasetId.value;
  if (datasetId) void selectCollinearitySource(versionId, datasetId);
};

const loadDatasetContext = async (datasetId: string) => {
  const contextRequest = ++datasetContextRequest;
  clearSourceContext();
  form.dataset_id = datasetId;
  loadingSources.value = true;
  try {
    const detail = await getDatasetDetail(datasetId);
    if (
      contextRequest !== datasetContextRequest ||
      selectedDatasetId.value !== datasetId
    ) {
      return;
    }
    datasetStore.setActiveDataset(detail);
    form.input_columns = [...detail.input_columns];
    inputColumnsText.value = detail.input_columns.join(",");

    const sourceRequest = ++sourceListRequest;
    const data = await getCollinearitySourceVersions(datasetId);
    if (
      contextRequest !== datasetContextRequest ||
      sourceRequest !== sourceListRequest ||
      selectedDatasetId.value !== datasetId
    ) {
      return;
    }
    collinearitySources.value = data.sources;
    loadingSources.value = false;
    await selectCollinearitySource(data.default_source_version_id, datasetId);
  } catch (error) {
    if (contextRequest !== datasetContextRequest) return;
    sourceError.value = error instanceof ApiError ? error.message : String(error);
  } finally {
    if (contextRequest === datasetContextRequest) loadingSources.value = false;
  }
};

const handleDatasetChange = (datasetId: string) => {
  datasetError.value = "";
  if (!datasetId) {
    datasetContextRequest += 1;
    clearSourceContext();
    return;
  }
  void loadDatasetContext(datasetId);
};

const initializeDatasets = async () => {
  const request = ++datasetListRequest;
  loadingDatasets.value = true;
  datasetError.value = "";
  try {
    const data = await listDatasets({ page: 1, page_size: 100 });
    if (request !== datasetListRequest) return;
    datasetOptions.value = data.items;
    datasetStore.setDatasetsList(data.items);
    const activeDatasetId = datasetStore.activeDataset?.id ?? null;
    if (activeDatasetId && data.items.some((dataset) => dataset.id === activeDatasetId)) {
      selectedDatasetId.value = activeDatasetId;
      await loadDatasetContext(activeDatasetId);
    }
  } catch (error) {
    if (request !== datasetListRequest) return;
    datasetOptions.value = [];
    selectedDatasetId.value = null;
    datasetError.value = error instanceof ApiError ? error.message : String(error);
  } finally {
    if (request === datasetListRequest) loadingDatasets.value = false;
  }
};

const refreshSourcesAfterAnalyze = async (
  datasetId: string,
  sourceVersionId: string,
  analyzeRequest: number,
  contextRequest: number
) => {
  const request = ++sourceListRequest;
  loadingSources.value = true;
  try {
    const data = await getCollinearitySourceVersions(datasetId);
    if (
      request !== sourceListRequest ||
      analyzeRequest !== analysisRequest ||
      contextRequest !== datasetContextRequest ||
      selectedDatasetId.value !== datasetId ||
      selectedSourceVersionId.value !== sourceVersionId
    ) {
      return;
    }
    collinearitySources.value = data.sources;
    const refreshedSource = data.sources.find(
      (source) => source.version_id === sourceVersionId
    );
    if (refreshedSource) {
      selectedSourceVersionId.value = refreshedSource.version_id;
      form.version_id = refreshedSource.version_id;
    }
  } catch (error) {
    if (request !== sourceListRequest || analyzeRequest !== analysisRequest) return;
    sourceError.value = `分析已完成，但版本状态刷新失败：${
      error instanceof ApiError ? error.message : String(error)
    }`;
  } finally {
    if (request === sourceListRequest) loadingSources.value = false;
  }
};

const handleAnalyze = async () => {
  rehydrationRequest += 1;
  restoringResult.value = false;
  errorMessage.value = "";
  sourceError.value = "";
  const source = selectedSource.value;
  const datasetId = selectedDatasetId.value;
  if (!source || !datasetId) {
    errorMessage.value = "请先选择数据集和时滞补偿版本。";
    return;
  }
  const inputColumns = inputColumnsText.value
    .split(",")
    .map((name) => name.trim())
    .filter(Boolean);
  if (inputColumns.length < 2) {
    errorMessage.value = "共线性诊断需要至少两个输入变量。";
    return;
  }

  const request = ++analysisRequest;
  const contextRequest = datasetContextRequest;
  form.version_id = source.version_id;
  form.dataset_id = datasetId;
  form.input_columns = inputColumns;
  loading.value = true;
  try {
    const analyzed = await calculateCollinearity({
      ...form,
      version_id: source.version_id,
      dataset_id: datasetId,
      input_columns: inputColumns,
    });
    if (
      request !== analysisRequest ||
      contextRequest !== datasetContextRequest ||
      selectedDatasetId.value !== datasetId ||
      selectedSourceVersionId.value !== source.version_id
    ) {
      return;
    }
    result.value = analyzed;
    source.collinearity_status = "complete";
    source.latest_complete_collinearity_run_id = analyzed.processing_run_id;
    ElMessage.success("共线性诊断完成");
    await refreshSourcesAfterAnalyze(datasetId, source.version_id, request, contextRequest);
  } catch (err) {
    if (request !== analysisRequest) return;
    result.value = null;
    errorMessage.value = err instanceof ApiError ? err.message : String(err);
  } finally {
    if (request === analysisRequest) loading.value = false;
  }
};

onMounted(() => {
  void initializeDatasets();
});

const dropCount = computed(
  () => (result.value?.recommendations ?? []).filter((item) => item.action === "drop").length
);
const dropCandidates = computed(
  () => (result.value?.recommendations ?? []).filter((item) => item.action === "drop")
);

const conditionSeverity = computed(() => {
  const value = result.value?.condition_number;
  if (value === null || value === undefined) return "info";
  if (value >= 100) return "danger";
  if (value >= 30) return "warning";
  return "success";
});

const heatmapOptions = computed(() => {
  if (!result.value) return {};
  const names = result.value.variables;
  const data: [number, number, number][] = [];
  result.value.matrix.forEach((row, i) => {
    row.forEach((value, j) => data.push([j, i, Number(value.toFixed(3))]));
  });
  return {
    tooltip: {
      formatter: (params: any) =>
        `${names[params.value[1]]} × ${names[params.value[0]]}<br/>r = ${params.value[2]}`,
    },
    grid: { left: "12%", right: "12%", bottom: "12%", top: "6%", containLabel: true },
    xAxis: { type: "category", data: names, splitArea: { show: true } },
    yAxis: { type: "category", data: names, splitArea: { show: true } },
    visualMap: {
      min: -1,
      max: 1,
      calculable: true,
      orient: "vertical",
      right: "2%",
      top: "middle",
      inRange: { color: ["#7995A8", "#FFFFFF", "#B8746E"] },
    },
    series: [
      {
        type: "heatmap",
        data,
        label: { show: names.length <= 8 },
        emphasis: { itemStyle: { shadowBlur: 10 } },
      },
    ],
  };
});

const vifOptions = computed(() => {
  if (!result.value) return {};
  const names = result.value.variables;
  const threshold = form.vif_threshold ?? 10;
  return {
    tooltip: { trigger: "axis" },
    grid: { left: "3%", right: "4%", bottom: "10%", top: "8%", containLabel: true },
    xAxis: { type: "category", data: names },
    yAxis: { type: "value", name: "VIF" },
    series: [
      {
        type: "bar",
        data: names.map((name) => {
          const value = result.value!.vif_scores[name] ?? 0;
          return {
            value: Number.isFinite(value) ? value : 0,
            itemStyle: { color: value >= threshold ? "#B96560" : "#6E9B69" },
          };
        }),
        markLine: {
          symbol: "none",
          data: [{ yAxis: threshold, name: "VIF阈值" }],
          lineStyle: { type: "dashed", color: "#B48A47", width: 1.5 },
        },
      },
    ],
  };
});

const formatNumber = (value: number | null | undefined) => {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  if (Math.abs(value) >= 10000) return value.toExponential(2);
  return value.toFixed(2);
};

const handleApply = async () => {
  if (!result.value || !dropCandidates.value.length) return;
  const names = dropCandidates.value.map((item) => item.variable);
  try {
    await ElMessageBox.confirm(
      `将从新版本中删除：${names.join(", ")}。源版本不会被覆盖。是否确认？`,
      "确认变量筛选",
      { type: "warning" }
    );
    applying.value = true;
    const applied = await applyFeatureSelection({
      version_id: form.version_id,
      drop_columns: names,
      user_confirmed: true,
      recommendation_source: "collinearity_analysis",
      evidence: Object.fromEntries(
        dropCandidates.value.map((item) => [
          item.variable,
          {
            reason: item.reason,
            related_variables: item.related_variables,
            vif: result.value!.vif_scores[item.variable],
            threshold: form.vif_threshold ?? 10,
          },
        ])
      ),
    });
    ElMessage.success(`已创建变量筛选版本：${applied.result_version_id}`);
    form.version_id = applied.result_version_id;
  } catch (err) {
    if (err !== "cancel") ElMessage.error(err instanceof ApiError ? err.message : String(err));
  } finally {
    applying.value = false;
  }
};
</script>

<style scoped>
.collinearity-view {
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

/* Analysis Context */
.analysis-context-card {
  padding: 16px 18px;
  background: #ffffff;
  border-radius: 10px;
  margin-bottom: 0;
}

.analysis-context-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.analysis-context-header h3 {
  margin: 2px 0 0;
  font-size: 15px;
  color: var(--text-primary);
}

.context-eyebrow {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.05em;
  color: var(--color-primary);
}

.context-note {
  font-size: 12px;
  color: var(--text-muted);
}

.analysis-context-grid {
  display: grid;
  grid-template-columns: minmax(220px, 0.9fr) minmax(320px, 1.4fr);
  gap: 14px;
}

.context-field {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.context-field label {
  font-family: var(--font-sans);
  font-size: 11px;
  font-weight: 500;
  color: var(--text-muted);
  letter-spacing: normal;
}

.selector-option {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  padding: 3px 0;
}

.selector-option-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.selector-option-name {
  overflow: hidden;
  color: var(--text-primary);
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selector-option-meta,
.selected-source-id {
  color: var(--text-faint);
  font-size: 10px;
}

.source-status {
  flex: none;
  padding: 2px 7px;
  border: 1px solid var(--border-default);
  border-radius: 999px;
  font-size: 10px;
  font-weight: 700;
  line-height: 1.35;
  color: var(--text-muted);
  background: var(--surface-2);
}

.source-status.complete {
  color: var(--success);
  background: var(--success-soft);
  border-color: var(--color-success-border);
}

.source-status.unrehydratable {
  color: #9a6700;
  background: #fff8e6;
  border-color: #ecd7a4;
}

.selected-source-detail,
.context-prompt {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--border-light);
  color: var(--text-secondary);
  font-size: 12px;
}

.selected-source-id {
  margin-left: auto;
}

.context-alert {
  margin-top: 12px;
}

/* FORMAT 4: Controller Strip */
.collin-control-strip {
  padding: 14px 18px;
  background: #ffffff;
  border-radius: 10px;
  margin-bottom: 0;
}

.cs-row {
  display: grid;
  grid-template-columns: minmax(220px, 1.5fr) minmax(140px, 1fr) minmax(140px, 1fr) auto;
  gap: 14px;
  align-items: flex-end;
}

.cs-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.cs-item label {
  font-family: var(--font-sans);
  font-size: 11px;
  font-weight: 500;
  color: var(--text-muted);
  letter-spacing: normal;
}

.cs-actions {
  display: flex;
  align-items: flex-end;
}

.cs-actions :deep(.el-button--primary.is-disabled),
.cs-actions :deep(.el-button--primary.is-disabled:hover),
.cs-actions :deep(.el-button--primary.is-disabled:active),
.cs-actions :deep(.el-button--primary:disabled) {
  background: var(--surface-3) !important;
  border-color: var(--border-default) !important;
  color: var(--text-disabled) !important;
  box-shadow: none !important;
  cursor: not-allowed;
  opacity: 0.78;
}

.alert-gap {
  margin-top: 4px;
}

/* FORMAT 4: Tri-Grid */
.collin-tri-grid {
  display: grid;
  grid-template-columns: 1.2fr 1.1fr 1fr;
  gap: 16px;
}

.tri-panel {
  padding: 18px;
  background: #ffffff;
  border-radius: 12px;
  margin-bottom: 0;
  display: flex;
  flex-direction: column;
}

.card-tag {
  font-size: 10px;
  font-weight: 700;
  color: var(--text-muted);
}

.localized-card-tag {
  font-family: var(--font-sans);
  font-size: 11px;
  font-weight: 500;
  letter-spacing: normal;
}

/* Decision Panel */
.decision-panel {
  background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
}

.decision-content {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-top: 4px;
}

.stat-mini-box {
  display: flex;
  justify-content: space-around;
  align-items: center;
  padding: 10px;
  background: #ffffff;
  border: 1px solid var(--border-light);
  border-radius: 8px;
}

.s-l {
  font-size: 9px;
  color: var(--text-muted);
  display: block;
}

.s-v {
  font-family: var(--font-mono);
  font-size: 16px;
  font-weight: 800;
  color: var(--text-primary);
}

.s-div {
  width: 1px;
  height: 24px;
  background: var(--border-light);
}

.text-cyan { color: #0284c7; }
.text-danger { color: #dc2626; }

.correlated-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.cl-title {
  font-family: var(--font-sans);
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
}

.cl-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.drop-recommendations-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 12px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 6px;
}

.rec-title {
  font-family: var(--font-sans);
  font-size: 11px;
  font-weight: 600;
  color: #991b1b;
}

.rec-item {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: #b91c1c;
  font-weight: 600;
}

.no-drops {
  font-family: var(--font-sans);
  font-size: 11px;
  font-weight: 400;
  line-height: 1.5;
  color: var(--success);
  padding: 10px;
  background: var(--success-soft);
  border: 1px solid var(--color-success-border);
  border-radius: var(--radius-xs);
}

.tri-panel .industrial-card-title {
  font-family: var(--font-sans);
  font-size: 12px;
  font-weight: 500;
  letter-spacing: normal;
  text-transform: none;
}

.decision-action-strip {
  margin-top: auto;
  padding-top: 10px;
}

.collin-empty-card {
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

.collin-empty-card h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}

.collin-empty-card p {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--text-secondary);
  max-width: 440px;
}

@media (max-width: 1180px) {
  .analysis-context-grid {
    grid-template-columns: 1fr;
  }
  .cs-row {
    grid-template-columns: 1fr 1fr;
  }
  .collin-tri-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .analysis-context-header,
  .selected-source-detail {
    align-items: flex-start;
    flex-direction: column;
  }

  .selected-source-id {
    margin-left: 0;
  }
}
</style>
