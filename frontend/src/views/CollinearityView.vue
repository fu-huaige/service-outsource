<template>
  <div class="collinearity-view">
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
      <span class="page-eyebrow font-mono">PEARSON COVARIANCE & VARIANCE INFLATION FACTOR</span>
      <h2>共线性检测与冗余特征剔除面板</h2>
      <p class="subtitle">计算 Pearson 协方差矩阵、方差膨胀因子 VIF 与矩阵条件数；由工程师安全确认后派生 V3_FeatureSet</p>
    </div>

    <!-- FORMAT 4: Top Slider Controller Strip (顶部横向控制条) -->
    <div class="industrial-card collin-control-strip">
      <div class="cs-row">
        <div class="cs-item">
          <label class="font-mono">数据版本 ID</label>
          <el-input v-model="form.version_id" placeholder="version_id" size="small" />
        </div>
        <div class="cs-item">
          <label class="font-mono">输入特征候选 (u)</label>
          <el-input v-model="inputColumnsText" placeholder="u1,u2,u3,u4" size="small" />
        </div>
        <div class="cs-item">
          <label class="font-mono">相关报警阈值</label>
          <el-input-number v-model="form.correlation_threshold" :min="0.5" :max="1" :step="0.01" :precision="2" size="small" />
        </div>
        <div class="cs-item">
          <label class="font-mono">VIF 膨胀阈值</label>
          <el-input-number v-model="form.vif_threshold" :min="1.5" :max="100" :step="0.5" size="small" />
        </div>
        <div class="cs-actions">
          <el-button type="primary" size="small" :loading="loading" icon="Search" @click="handleAnalyze">
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
          <span class="card-tag font-mono">阈值: {{ form.vif_threshold || 10 }}</span>
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
          <div class="stat-mini-box font-mono">
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
            <div class="cl-title font-mono">强相关共线性通道组：</div>
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
            <div class="rec-title font-mono">⚠️ 建议剔除列表 (人工确认后生效):</div>
            <div
              v-for="item in dropCandidates"
              :key="item.variable"
              class="rec-item"
            >
              <span class="rec-var font-mono">{{ item.variable }}</span>
              <span class="rec-vif font-mono">VIF = {{ formatNumber(result.vif_scores[item.variable]) }}</span>
            </div>
          </div>
          <div class="no-drops font-mono" v-else>
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
      <h3>共线性诊断面板就绪</h3>
      <p>在上方工具栏输入数据版本与输入特征集合，点击「执行诊断分析」在此展开 Pearson 协方差热力图、VIF 直方图与剔除决策看板。</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from "vue";
import { Grid, Histogram, Share, TrendCharts } from "@element-plus/icons-vue";
import ChartContainer from "../components/ChartContainer.vue";
import { applyFeatureSelection, calculateCollinearity } from "../api/preprocessing";
import type { CollinearityRequest, CollinearityResponse } from "../types/api";
import { ApiError } from "../api/client";
import { ElMessage, ElMessageBox } from "element-plus";

const loading = ref(false);
const applying = ref(false);
const result = ref<CollinearityResponse | null>(null);
const errorMessage = ref("");
const inputColumnsText = ref("u1,u2,u3");

const form = reactive<CollinearityRequest>({
  version_id: "",
  input_columns: [],
  correlation_threshold: 0.85,
  vif_threshold: 10,
});

const handleAnalyze = async () => {
  errorMessage.value = "";
  if (!form.version_id) {
    errorMessage.value = "请先填写数据版本 ID。";
    return;
  }
  form.input_columns = inputColumnsText.value
    .split(",")
    .map((name) => name.trim())
    .filter(Boolean);
  if (form.input_columns.length < 2) {
    errorMessage.value = "共线性诊断需要至少两个输入变量。";
    return;
  }

  loading.value = true;
  try {
    result.value = await calculateCollinearity(form);
    ElMessage.success("共线性诊断完成");
  } catch (err) {
    result.value = null;
    errorMessage.value = err instanceof ApiError ? err.message : String(err);
  } finally {
    loading.value = false;
  }
};

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
      inRange: { color: ["#2563eb", "#ffffff", "#dc2626"] },
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
            itemStyle: { color: value >= threshold ? "#dc2626" : "#2563eb" },
          };
        }),
        markLine: {
          symbol: "none",
          data: [{ yAxis: threshold, name: "VIF阈值" }],
          lineStyle: { type: "dashed", color: "#d97706", width: 1.5 },
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
  gap: 16px;
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

/* FORMAT 4: Controller Strip */
.collin-control-strip {
  padding: 14px 18px;
  background: #ffffff;
  border-radius: 10px;
  margin-bottom: 0;
}

.cs-row {
  display: grid;
  grid-template-columns: minmax(180px, 1.2fr) minmax(220px, 1.5fr) minmax(140px, 1fr) minmax(140px, 1fr) auto;
  gap: 14px;
  align-items: flex-end;
}

.cs-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.cs-item label {
  font-size: 10px;
  font-weight: 700;
  color: var(--text-muted);
}

.cs-actions {
  display: flex;
  align-items: flex-end;
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
  font-size: 10px;
  font-weight: 700;
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
  font-size: 10px;
  font-weight: 700;
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
  font-size: 11px;
  color: #059669;
  padding: 10px;
  background: #ecfdf5;
  border-radius: 6px;
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
  background: #ffffff;
  border-radius: 12px;
}

.empty-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  background: var(--color-primary-light);
  color: var(--color-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  margin-bottom: 12px;
}

.collin-empty-card h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 800;
  color: var(--text-primary);
}

.collin-empty-card p {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--text-secondary);
  max-width: 440px;
}

@media (max-width: 1180px) {
  .cs-row {
    grid-template-columns: 1fr 1fr;
  }
  .collin-tri-grid {
    grid-template-columns: 1fr;
  }
}
</style>
