<template>
  <div class="delay-view">
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
            <el-form-item label="数据版本 ID">
              <el-input v-model="form.version_id" placeholder="version_id" />
            </el-form-item>

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

            <el-button type="primary" size="large" :loading="loading" icon="Search" @click="handleEstimate" style="width: 100%; margin-top: 6px">
              执行预白化时滞估计
            </el-button>
          </el-form>

          <el-alert v-if="errorMessage" type="error" :closable="false" show-icon class="alert-gap">
            <template #title>时滞估计失败：{{ errorMessage }}</template>
          </el-alert>
        </div>

        <div class="industrial-card rail-card theory-box">
          <div class="t-title font-mono">⚡ 为什么必须预白化？</div>
          <p class="t-p">工业慢信号自相关严重，直接互相关会导致峰值严重展宽和虚假偏移。系统先通过 AR 模型滤除自相关残差，再与输出互相关求得真实物理延迟。</p>
        </div>
      </aside>

      <!-- Right Main Studio -->
      <main class="delay-main-studio">
        <template v-if="result">
          <!-- Top Multi-Channel Card Array (多通道卡阵列) -->
          <div class="channel-cards-grid">
            <div
              v-for="row in delayRows"
              :key="row.column"
              class="channel-tile industrial-card"
            >
              <div class="channel-top">
                <span class="channel-name font-mono">{{ row.column }}</span>
                <span class="channel-status-pill font-mono">CONFIRMED</span>
              </div>
              <div class="channel-main-lag">
                <span class="lag-label font-mono">BEST DELAY \(n_k\)</span>
                <span class="lag-num font-mono">{{ row.refined }} <span class="lag-unit">steps</span></span>
              </div>
              <div class="channel-candidates">
                <span class="c-label font-mono">TOP-K PEAKS:</span>
                <div class="c-chips">
                  <span
                    v-for="peak in row.candidates"
                    :key="peak.lag"
                    class="c-chip font-mono"
                    :class="{ selected: peak.lag === row.refined }"
                  >
                    lag {{ peak.lag }} (r={{ formatNumber(peak.correlation) }})
                  </span>
                </div>
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
              <span class="font-mono text-cyan">FIT 验证优度: {{ formatNumber(result.validation_fit) }}%</span>
            </div>
            <ChartContainer :options="chartOptions" height="320px" />
          </div>

          <!-- Bottom 1-Click Apply Action Strip -->
          <div class="industrial-card studio-apply-strip">
            <div class="apply-left">
              <div class="apply-h font-mono">APPLY DELAY COMPENSATION · 创建移位版本</div>
              <div class="apply-d">保持 y 与时间轴不变，将各输入特征按 \(u(t - n_k)\) 移位对齐，并派生全新版本。</div>
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
          <h3>时滞对齐工作室就绪</h3>
          <p>请在左侧侧边栏设置输入控制通道与搜索最大步长，点击「执行预白化时滞估计」在此渲染多通道卡片与相位谱。</p>
        </div>
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from "vue";
import { DataLine, Search, Timer } from "@element-plus/icons-vue";
import ChartContainer from "../components/ChartContainer.vue";
import { applyLagCompensation, calculateDelay } from "../api/preprocessing";
import type { DelayRequest, DelayResponse } from "../types/api";
import { ApiError } from "../api/client";
import { ElMessage, ElMessageBox } from "element-plus";

const PALETTE = ["#2563eb", "#059669", "#d97706", "#dc2626", "#8b5cf6", "#0284c7"];

const loading = ref(false);
const applying = ref(false);
const result = ref<DelayResponse | null>(null);
const errorMessage = ref("");
const inputColumnsText = ref("u1,u2");

const form = reactive<DelayRequest>({
  version_id: "",
  input_columns: [],
  output_column: "y",
  max_lag: 30,
  top_k: 3,
});

const handleEstimate = async () => {
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
    result.value = await calculateDelay(form);
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
    form.version_id = applied.result_version_id;
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
      peak: candidates[0]?.lag ?? "—",
      correlation: candidates[0]?.correlation ?? null,
      candidates,
    };
  });
});

const chartOptions = computed(() => {
  if (!result.value) return {};
  const columns = Object.keys(result.value.correlations);
  const maxLength = Math.max(...columns.map((c) => result.value!.correlations[c].length), 1);
  return {
    tooltip: { trigger: "axis" },
    legend: { data: columns, top: "2%" },
    grid: { left: "3%", right: "4%", bottom: "10%", top: "14%", containLabel: true },
    xAxis: {
      type: "category",
      name: "滞后步数",
      data: Array.from({ length: maxLength }, (_, i) => `${i}`),
    },
    yAxis: { type: "value", name: "预白化互相关 r" },
    series: columns.map((column, index) => ({
      name: column,
      type: "line",
      showSymbol: false,
      color: PALETTE[index % PALETTE.length],
      lineStyle: { width: 2 },
      data: result.value!.correlations[column],
      markLine: {
        symbol: "none",
        silent: true,
        lineStyle: { type: "dashed", color: PALETTE[index % PALETTE.length] },
        data: [{ xAxis: String(result.value!.best_delays[column] ?? 0) }],
      },
    })),
  };
});

const formatNumber = (value: number | null | undefined) => {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return value.toFixed(3);
};
</script>

<style scoped>
.delay-view {
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
  font-size: 11px;
  font-weight: 800;
  color: var(--color-primary);
  margin-bottom: 6px;
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

.c-chip.selected {
  background: var(--color-primary-light);
  color: var(--color-primary);
  font-weight: 700;
}

/* Studio Spectrum */
.studio-spectrum-card {
  padding: 20px;
  background: #ffffff;
  border-radius: 12px;
  margin-bottom: 0;
}

/* Studio Apply Strip */
.studio-apply-strip {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 18px 22px;
  background: linear-gradient(135deg, #ffffff 0%, #f0f7ff 100%);
  border: 1px solid #bfdbfe;
  border-radius: 12px;
  margin-bottom: 0;
  gap: 20px;
}

.apply-h {
  font-size: 12px;
  font-weight: 800;
  color: #1e3a8a;
  margin-bottom: 3px;
}

.apply-d {
  font-size: 12px;
  color: #475569;
}

.studio-empty-card {
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

.studio-empty-card h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 800;
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
}
</style>
