<template>
  <div class="page-container segmentation-view">
    <!-- Top Stage Header Navigation -->
    <div class="pipeline-stage-nav">
      <div class="stage-badge font-mono">STAGE 03 · D-OPTIMAL SEGMENTATION</div>
      <div class="stage-links">
        <span class="stage-link" @click="$router.push('/preprocessing/cleaning')">02 时间清洗</span>
        <span class="stage-sep">›</span>
        <span class="stage-link active">03 D-最优优选</span>
        <span class="stage-sep">›</span>
        <span class="stage-link" @click="$router.push('/preprocessing/delay')">04 时滞对齐</span>
        <span class="stage-sep">›</span>
        <span class="stage-link" @click="$router.push('/preprocessing/collinearity')">05 VIF 降维</span>
      </div>
    </div>

    <!-- Header with Breadcrumb & Quick Action -->
    <div class="page-header-row">
      <div class="page-header">
        <span class="page-eyebrow font-mono">FISHER INFORMATION MATRIX DET-MAXIMIZATION</span>
        <h2>质量约束 D-最优区间剪辑工作台</h2>
        <p class="subtitle">先做质量门控过滤稳态与坏段，再由 CELF 延迟贪心算法截取信息量极大化高动态过渡带</p>
      </div>

      <div class="top-segment-trigger">
        <el-button type="primary" size="large" :loading="loading" icon="Search" @click="handleSegment">
          执行门控与 D-最优区间剪辑
        </el-button>
      </div>
    </div>

    <!-- FORMAT 2: Collapsible Top Parameter Bar with Badges -->
    <div class="industrial-card segment-param-bar">
      <div class="param-grid-row">
        <div class="param-item">
          <label>数据版本 ID</label>
          <el-input v-model="form.version_id" placeholder="version_id" size="small" />
        </div>
        <div class="param-item">
          <label>输入变量 (u)</label>
          <el-input v-model="inputColumnsText" placeholder="u1,u2,u3" size="small" />
        </div>
        <div class="param-item">
          <label>输出变量 (y)</label>
          <el-input v-model="form.output_column" placeholder="y" size="small" />
        </div>
        <div class="param-item">
          <label>窗长 (L)</label>
          <el-input-number v-model="form.window_size" :min="5" :max="2000" :step="10" size="small" />
        </div>
        <div class="param-item">
          <label>保留段数 (K)</label>
          <el-input-number v-model="form.max_segments" :min="1" :max="100" size="small" />
        </div>
        <div class="param-item">
          <label>最低 SNR (dB)</label>
          <el-input-number v-model="form.min_snr_db" :min="-20" :max="60" size="small" />
        </div>
      </div>
    </div>

    <el-alert v-if="errorMessage" type="error" :closable="false" show-icon class="alert-gap">
      <template #title>优选失败：{{ errorMessage }}</template>
    </el-alert>

    <!-- FORMAT 2: Full-Width Waveform Scrubber with Floating KPI HUD (全景时序切片看板) -->
    <section class="industrial-card scrubber-card">
      <div class="scrubber-header">
        <div class="scrubber-title">
          <el-icon><DataLine /></el-icon>
          <span>全景响应时序与选定过渡带切片 (SELECTED D-OPTIMAL SLICES)</span>
        </div>
        <div class="scrubber-badges" v-if="result && result.selection">
          <el-tag :type="result.selection.excitation_satisfied ? 'success' : 'danger'" effect="light">
            {{ result.selection.excitation_satisfied ? "🟢 持续激励条件满足" : "🔴 持续激励不足" }}
          </el-tag>
        </div>
      </div>

      <!-- Floating 5-KPI HUD -->
      <div class="hud-kpi-bar" v-if="result && result.selection">
        <div class="hud-item">
          <span class="hud-label font-mono">CANDIDATES</span>
          <span class="hud-val font-mono">{{ result.selection.candidate_count }}</span>
        </div>
        <div class="hud-sep"></div>
        <div class="hud-item">
          <span class="hud-label font-mono">GATED PASS</span>
          <span class="hud-val font-mono text-cyan">{{ result.selection.gated_count }}</span>
        </div>
        <div class="hud-sep"></div>
        <div class="hud-item">
          <span class="hud-label font-mono">SELECTED SEGMENTS</span>
          <span class="hud-val font-mono text-primary">{{ result.selection.selected_count }}</span>
        </div>
        <div class="hud-sep"></div>
        <div class="hud-item">
          <span class="hud-label font-mono">SAMPLE COVERAGE</span>
          <span class="hud-val font-mono text-green">{{ percent(result.selection.coverage_ratio) }}</span>
        </div>
        <div class="hud-sep"></div>
        <div class="hud-item">
          <span class="hud-label font-mono">COND NUMBER</span>
          <span class="hud-val font-mono">{{ formatNumber(result.selection.design_matrix_condition_number) }}</span>
        </div>
      </div>

      <div v-if="result && result.selection">
        <ChartContainer :options="chartOptions" height="340px" />
      </div>
      <div class="scrubber-empty" v-else>
        <el-icon><Crop /></el-icon>
        <p>输入参数后点击右上角「执行门控与 D-最优区间剪辑」，在此高亮渲染全景时序与黄金区间切片。</p>
      </div>
    </section>

    <!-- FORMAT 2: Master-Detail Dual Table & Quality Filter Funnel (主从双表决策看板) -->
    <div class="segment-master-detail-grid" v-if="result && result.selection">
      <!-- Left: Selected Segments Leaderboard -->
      <div class="industrial-card detail-pane">
        <div class="industrial-card-header">
          <div class="industrial-card-title">
            <el-icon><TrendCharts /></el-icon>
            <span>优选区间贡献排行榜</span>
          </div>
          <span class="card-tag font-mono">RANKED LIST</span>
        </div>

        <el-table :data="result.segments" stripe height="280" style="width: 100%">
          <el-table-column prop="rank" label="排名" width="70">
            <template #default="{ row }">
              <span class="rank-badge font-mono">#{{ row.rank }}</span>
            </template>
          </el-table-column>
          <el-table-column label="样本索引区间" width="160">
            <template #default="{ row }">
              <span class="font-mono">[{{ row.start_index }} - {{ row.end_index }}]</span>
            </template>
          </el-table-column>
          <el-table-column label="区间点数" width="100">
            <template #default="{ row }">
              <span><span class="font-mono">{{ row.end_index - row.start_index }}</span> 点</span>
            </template>
          </el-table-column>
          <el-table-column label="信噪比 SNR" width="110">
            <template #default="{ row }">
              <span class="font-mono text-green">{{ formatNumber(row.snr_db) }} dB</span>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <!-- Right: Gated Funnel Breakdown -->
      <div class="industrial-card detail-pane">
        <div class="industrial-card-header">
          <div class="industrial-card-title">
            <el-icon><Filter /></el-icon>
            <span>质量门控过滤漏斗明细</span>
          </div>
          <el-tag type="info" effect="plain">共扫描 {{ result.gated_windows.length }} 个窗口</el-tag>
        </div>

        <el-table :data="result.gated_windows" stripe height="280" style="width: 100%">
          <el-table-column prop="window_index" label="窗口" width="70" />
          <el-table-column label="样本范围" width="140">
            <template #default="{ row }">
              <span class="font-mono">[{{ row.start_index }} - {{ row.end_index }}]</span>
            </template>
          </el-table-column>
          <el-table-column label="门控状态" width="90">
            <template #default="{ row }">
              <el-tag :type="row.accepted ? 'success' : 'info'" size="small">
                {{ row.accepted ? "通过" : "剔除" }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="缺失率" width="80">
            <template #default="{ row }">{{ percent(row.missing_ratio) }}</template>
          </el-table-column>
          <el-table-column label="剔除原因">
            <template #default="{ row }">
              <span v-if="!row.rejection_reasons.length">—</span>
              <el-tag
                v-for="reason in row.rejection_reasons"
                :key="reason"
                size="small"
                type="warning"
                effect="plain"
                class="rejection-tag"
              >
                {{ reasonLabel(reason) }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from "vue";
import { Crop, DataLine, Filter, TrendCharts } from "@element-plus/icons-vue";
import ChartContainer from "../components/ChartContainer.vue";
import { segmentDataset } from "../api/preprocessing";
import type { SegmentRequest, SegmentResponse } from "../types/api";
import { ApiError } from "../api/client";
import { ElMessage } from "element-plus";

const REASON_LABELS: Record<string, string> = {
  missing_ratio_exceeded: "缺失率超限",
  anomaly_ratio_exceeded: "异常率超限",
  snr_below_threshold: "信噪比不足",
  steady_state_segment: "稳态段",
  no_input_excitation: "输入无激励",
};

const loading = ref(false);
const result = ref<SegmentResponse | null>(null);
const errorMessage = ref("");
const inputColumnsText = ref("u1,u2,u3");

const form = reactive<SegmentRequest>({
  version_id: "",
  input_columns: [],
  output_column: "y",
  window_size: 60,
  max_segments: 8,
  min_snr_db: 0,
  max_missing_ratio: 0.2,
  max_anomaly_ratio: 0.1,
});

const handleSegment = async () => {
  errorMessage.value = "";
  if (!form.version_id) {
    errorMessage.value = "请先填写数据版本 ID。";
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
    result.value = await segmentDataset(form);
    ElMessage.success(
      `优选完成：${result.value.selection?.selected_count ?? 0} 个区间，采样占比 ${percent(
        result.value.selection?.coverage_ratio ?? 0
      )}`
    );
  } catch (err) {
    result.value = null;
    errorMessage.value = err instanceof ApiError ? err.message : String(err);
  } finally {
    loading.value = false;
  }
};

const outputSeries = computed<(number | null)[]>(() => {
  if (!result.value) return [];
  return result.value.series[form.output_column] ?? [];
});

const chartOptions = computed(() => {
  const values = outputSeries.value;
  const marks = (result.value?.segments ?? []).map((segment) => [
    { name: `#${segment.rank ?? ""}`, xAxis: segment.start_index },
    { xAxis: segment.end_index },
  ]);
  return {
    tooltip: { trigger: "axis" },
    grid: { left: "3%", right: "4%", bottom: "12%", top: "8%", containLabel: true },
    dataZoom: [{ type: "inside" }, { type: "slider", height: 20, bottom: 2 }],
    xAxis: { type: "category", data: values.map((_, index) => index) },
    yAxis: { type: "value", scale: true },
    series: [
      {
        name: form.output_column,
        type: "line",
        showSymbol: false,
        color: "#6E9B69",
        lineStyle: { width: 2 },
        data: values,
        markArea: {
          itemStyle: { color: "rgba(130, 169, 120, 0.15)", borderColor: "rgba(130, 169, 120, 0.35)", borderWidth: 1 },
          data: marks,
        },
      },
    ],
  };
});

const reasonLabel = (reason: string) => REASON_LABELS[reason] ?? reason;

const percent = (value: number | null | undefined) =>
  value === null || value === undefined ? "—" : `${(value * 100).toFixed(2)}%`;

const formatNumber = (value: number | null | undefined) => {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  if (Math.abs(value) >= 10000) return value.toExponential(2);
  return value.toFixed(3);
};
</script>

<style scoped>
.segmentation-view {
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

.page-header-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 20px;
  flex-wrap: wrap;
}

/* Format 2: Parameter Bar */
.segment-param-bar {
  padding: 14px 18px;
  background: #ffffff;
  border-radius: 10px;
  margin-bottom: 0;
}

.param-grid-row {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 14px;
}

.param-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.param-item label {
  font-family: var(--font-sans);
  font-size: 11px;
  font-weight: 500;
  color: var(--text-muted);
  letter-spacing: normal;
}

.alert-gap {
  margin-top: 4px;
}

/* Scrubber Card */
.scrubber-card {
  padding: 20px;
  background: #ffffff;
  border-radius: 12px;
  margin-bottom: 0;
}

.scrubber-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.scrubber-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-family: var(--font-sans);
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  letter-spacing: normal;
}

.segmentation-view .industrial-card-title {
  font-family: var(--font-sans);
  font-size: 12px;
  font-weight: 500;
  letter-spacing: normal;
  text-transform: none;
}

.hud-kpi-bar {
  display: flex;
  align-items: center;
  justify-content: space-around;
  padding: 10px 16px;
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
  border-radius: 8px;
  margin-bottom: 14px;
}

.hud-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}

.hud-label {
  font-size: 10px;
  font-weight: 700;
  color: var(--text-muted);
}

.hud-val {
  font-size: 18px;
  font-weight: 800;
  color: var(--text-primary);
}

.hud-sep {
  width: 1px;
  height: 28px;
  background: var(--border-light);
}

.text-primary { color: var(--color-primary); }
.text-cyan { color: #0284c7; }
.text-green { color: #059669; }

.scrubber-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  text-align: center;
  color: var(--text-muted);
}

.scrubber-empty .el-icon {
  font-size: 32px;
  margin-bottom: 8px;
  color: var(--color-primary);
}

/* Master-Detail Dual Pane */
.segment-master-detail-grid {
  display: grid;
  grid-template-columns: 1.1fr 1.4fr;
  gap: 20px;
}

.detail-pane {
  padding: 18px;
  background: var(--surface-1);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  margin-bottom: 0;
}

.rank-badge {
  font-weight: 800;
  color: var(--color-primary);
  background: var(--color-primary-light);
  padding: 1px 6px;
  border-radius: 4px;
}

.card-tag {
  font-size: 10px;
  font-weight: 700;
  color: var(--text-muted);
}

.rejection-tag {
  margin-right: 4px;
}

@media (max-width: 1100px) {
  .param-grid-row {
    grid-template-columns: repeat(3, 1fr);
  }
  .segment-master-detail-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 680px) {
  .param-grid-row {
    grid-template-columns: 1fr;
  }
  .hud-kpi-bar {
    flex-direction: column;
    gap: 8px;
  }
  .hud-sep {
    display: none;
  }
}
</style>
