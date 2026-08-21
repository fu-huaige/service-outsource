<template>
  <div class="cleaning-view">
    <div class="page-header">
      <h2>时间规整与清洗 (Cleaning & Resampling)</h2>
      <p class="subtitle">消除采样不均匀、补全缺失值并过滤尖峰异常点，派生可信数据版本</p>
    </div>

    <div class="cleaning-layout">
      <!-- Config Panel -->
      <div class="industrial-card form-card">
        <div class="industrial-card-header">
          <div class="industrial-card-title">
            <el-icon><Operation /></el-icon> 清洗规整算法参数
          </div>
        </div>

        <el-form :model="form" label-width="140px" label-position="left">
          <el-form-item label="源数据版本（本次清洗输入）">
            <template v-if="sourceVersion">
              <span>{{ sourceVersion.name }}</span>
              <span class="code-inline source-version-id">{{ sourceVersion.id }}</span>
            </template>
            <span v-else class="source-version-pending">{{ sourceLoadMessage }}</span>
          </el-form-item>

          <p class="source-version-note">清洗成功后将生成新的不可变版本，源版本不会被覆盖。</p>

          <el-form-item label="重采样周期 Ts">
            <el-input-number v-model="form.target_sample_period_seconds" :min="0.1" :max="60" :step="0.5" />
            <span style="margin-left: 8px">秒 (s)</span>
          </el-form-item>

          <el-form-item label="缺失值插值算法">
            <el-radio-group v-model="form.interpolation">
              <el-radio label="linear">线性插值 (Linear)</el-radio>
              <el-radio label="forward_fill">前向填充 (FFill)</el-radio>
              <el-radio label="backward_fill">后向填充 (BFill)</el-radio>
            </el-radio-group>
          </el-form-item>

          <el-form-item label="异常值检测算法">
            <el-select v-model="form.anomaly_detector" style="width: 220px">
              <el-option label="Hampel Filter (推荐)" value="hampel" />
              <el-option label="IQR 四分位距" value="iqr" />
              <el-option label="Z-Score 阈值" value="z_score" />
            </el-select>
          </el-form-item>

          <el-form-item label="Hampel 滑窗 k" v-if="form.anomaly_detector === 'hampel'">
            <el-input-number v-model="form.hampel_window" :min="3" :max="21" :step="2" />
          </el-form-item>

          <el-form-item>
            <el-button type="primary" :loading="loading" :disabled="!sourceVersion || loading" icon="MagicStick" @click="handleClean">
              执行清洗并生成新版本 V1_Cleaned
            </el-button>
          </el-form-item>
        </el-form>

        <el-alert v-if="errorMessage" type="error" :title="errorMessage" :closable="false" show-icon>
          <ul v-if="validationIssues.length" class="validation-issues">
            <li v-for="issue in validationIssues" :key="issue">{{ issue }}</li>
          </ul>
        </el-alert>
      </div>

      <!-- Comparison Chart Card -->
      <div class="industrial-card result-card" v-if="cleanedData">
        <div class="industrial-card-header">
          <div class="industrial-card-title">
            <el-icon><DataAnalysis /></el-icon> 清洗前后叠加对比图 (Before vs After)
          </div>
          <el-tag type="success">已修复 {{ cleanedData.total_cleaned_points }} 个唯一数据单元格</el-tag>
        </div>

        <el-alert
          class="cleaning-summary"
          type="success"
          :title="cleaningResultSummary"
          :closable="false"
          show-icon
        />

        <ChartContainer :options="compareChartOptions" height="360px" />

        <div style="margin-top: 16px; display: flex; justify-content: flex-end; gap: 12px">
          <el-button type="success" icon="ArrowRight" @click="$router.push('/preprocessing/segmentation')">
            下一步: 动态响应区间优选 ->
          </el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from "vue";
import { useRoute } from "vue-router";
import { Operation, MagicStick, DataAnalysis, ArrowRight } from "@element-plus/icons-vue";
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
  const versionId = queryValue("version_id") || selectedDataset?.version_id || selectedDataset?.latest_version_id;
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
    sourceLoadMessage.value = error instanceof ApiError
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
    legend: { data: ["原始序列 (Raw Series)", "清洗后序列 (Cleaned Series)"] },
    grid: { left: "3%", right: "4%", bottom: "10%", containLabel: true },
    xAxis: { type: "category", data: xData },
    yAxis: { type: "value" },
    series: [
      {
        name: "原始序列 (Raw Series)",
        type: "line",
        color: "#E76F51",
        lineStyle: { type: "dashed", width: 1 },
        data: cleanedData.value.raw_series,
      },
      {
        name: "清洗后序列 (Cleaned Series)",
        type: "line",
        color: "#1E6091",
        lineStyle: { width: 2 },
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
.page-header {
  margin-bottom: 20px;
}

.subtitle {
  font-size: 13px;
  color: var(--text-secondary);
  margin-top: 4px;
}

.source-version-id {
  margin-left: 8px;
}

.source-version-pending,
.source-version-note {
  color: var(--text-secondary);
  font-size: 13px;
}

.source-version-note {
  margin: -8px 0 16px 140px;
}

.validation-issues {
  margin: 8px 0 0;
  padding-left: 20px;
}

.cleaning-summary {
  margin-bottom: 16px;
}

.cleaning-layout {
  display: flex;
  flex-direction: column;
  gap: 20px;
}
</style>
