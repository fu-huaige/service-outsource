<template>
  <div class="dashboard-view">
    <div class="page-header">
      <span class="page-eyebrow">流程工业建模工作区</span>
      <h2>建模工作台</h2>
      <p class="subtitle">从数据准备到模型寻优，沿着当前数据版本继续工作</p>
    </div>

    <section class="workbench-hero industrial-card">
      <div class="hero-main">
        <span class="hero-kicker">{{ currentDataset ? "当前任务" : "开始建模" }}</span>
        <h3>{{ currentDataset ? `继续处理「${currentDataset.name}」` : "从一份可信数据开始" }}</h3>
        <p>
          {{ currentDataset
            ? "先查看数据质量和版本血缘，再选择清洗、优选或系统辨识步骤。"
            : "上传真实工业 CSV，或生成一组带真值的仿真数据，用于完整验证建模流程。" }}
        </p>
        <div class="hero-actions">
          <el-button type="primary" size="large" @click="continueWork">
            {{ currentDataset ? "继续当前任务" : "上传工业数据" }}
          </el-button>
          <el-button size="large" plain @click="$router.push('/simulation')">生成仿真数据</el-button>
        </div>
      </div>

      <dl class="hero-context" v-if="currentDataset">
        <div>
          <dt>当前数据集</dt>
          <dd>{{ currentDataset.name }}</dd>
        </div>
        <div>
          <dt>当前版本</dt>
          <dd>
            <span>{{ shortIdentifier(currentDataset.version_id || currentDataset.latest_version_id) }}</span>
            <el-tooltip :content="currentDataset.version_id || currentDataset.latest_version_id" placement="top">
              <span class="context-help">完整 ID</span>
            </el-tooltip>
          </dd>
        </div>
        <div>
          <dt>数据规模</dt>
          <dd>{{ currentDataset.row_count }} 行 · {{ currentDataset.col_count || currentDataset.column_count }} 列</dd>
        </div>
      </dl>
      <div v-else class="hero-context hero-context--empty">
        <span>建议下一步</span>
        <strong>准备数据并完成列角色配置</strong>
        <p>系统会据此识别时间列、过程输入和目标输出。</p>
      </div>
    </section>

    <div class="stat-cards">
      <div class="industrial-card stat-card">
        <div class="stat-title">数据资产</div>
        <div class="stat-val">{{ dashboardAvailable ? datasetCount : "暂不可用" }} <span v-if="dashboardAvailable" class="unit">个</span></div>
        <div class="stat-sub">已登记的上传与仿真数据</div>
      </div>
      <div class="industrial-card stat-card">
        <div class="stat-title">已完成寻优</div>
        <div class="stat-val">{{ dashboardAvailable ? leaderboardData.length : "暂不可用" }} <span v-if="dashboardAvailable" class="unit">项</span></div>
        <div class="stat-sub">数据库中成功完成的 Optuna 研究</div>
      </div>
      <div class="industrial-card stat-card">
        <div class="stat-title">最佳验证集 FIT</div>
        <div class="stat-val highlight">{{ topEntry ? formatOptionalFit(topEntry.optimized_validation_fit) : "暂无结果" }}</div>
        <div class="stat-sub">{{ dashboardAvailable ? (topEntry ? topEntry.dataset_name : "完成寻优后显示") : "工作台数据暂不可用" }}</div>
      </div>
    </div>

    <div class="industrial-card secondary-actions-card">
      <div class="industrial-card-header">
        <div class="industrial-card-title">
          <el-icon><Lightning /></el-icon> 其他操作
        </div>
      </div>
      <div class="action-buttons">
        <el-button plain @click="$router.push('/datasets')">
          管理数据资产
        </el-button>
        <el-button plain @click="$router.push('/copilot')">
          打开 Agent 工作台
        </el-button>
      </div>
    </div>

    <div class="industrial-card">
      <div class="industrial-card-header">
        <div class="industrial-card-title">
          <el-icon><Trophy /></el-icon> 建模结果排行
        </div>
        <el-tag type="info">按验证集 FIT 排名</el-tag>
      </div>
      <el-alert
        v-if="loadError"
        type="error"
        title="工作台数据加载失败"
        description="请确认后端服务已启动，并检查数据库与任务队列状态后重新加载。"
        show-icon
        :closable="false"
        style="margin-bottom: 16px"
      >
        <template #default>
          <p class="error-help">请确认后端服务已启动，并检查数据库与任务队列状态。</p>
          <el-button type="danger" plain size="small" :loading="isLoading" @click="loadDashboard">重新加载</el-button>
          <details class="error-detail">
            <summary>查看技术信息</summary>
            <code>{{ loadError }}</code>
          </details>
        </template>
      </el-alert>
      <el-alert
        v-else
        type="info"
        title="指标说明：一步预测使用真实历史输出预测下一步；自由仿真仅依赖模型自身历史预测连续滚动，因而更严格。"
        :closable="false"
        style="margin-bottom: 16px"
      />
      <el-table v-if="dashboardAvailable && leaderboardData.length" :data="leaderboardData" stripe style="width: 100%">
        <el-table-column prop="dataset_name" label="数据集名称" width="180" />
        <el-table-column label="基线验证 FIT" width="120">
          <template #default="{ row }">{{ formatOptionalFit(row.baseline_validation_fit) }}</template>
        </el-table-column>
        <el-table-column label="优化后验证 FIT" width="130">
          <template #default="{ row }">
            <span class="fit-val">{{ formatOptionalFit(row.optimized_validation_fit) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="优化后测试 FIT" width="130">
          <template #default="{ row }">
            {{ row.optimized_test_fit === null ? "暂无测试集评价" : formatFit(row.optimized_test_fit) }}
          </template>
        </el-table-column>
        <el-table-column label="测试一步 FIT" width="120">
          <template #default="{ row }">{{ formatOptionalFit(row.optimized_test_one_step_fit) }}</template>
        </el-table-column>
        <el-table-column label="测试一步 R²" width="120">
          <template #default="{ row }">{{ formatOptionalNumber(row.optimized_test_one_step_r2) }}</template>
        </el-table-column>
        <el-table-column label="测试自由仿真 R²" width="140">
          <template #default="{ row }">{{ formatOptionalNumber(row.optimized_test_free_run_r2) }}</template>
        </el-table-column>
        <el-table-column label="提升幅度" width="120">
          <template #default="{ row }">
            <span v-if="row.improvement !== null" :class="row.improvement >= 0 ? 'improvement-text' : 'risk-text'">
              {{ formatSigned(row.improvement) }}
            </span>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="真实最优参数">
          <template #default="{ row }">{{ row.contribution_summary || "—" }}</template>
        </el-table-column>
        <el-table-column label="泛化差距" width="130">
          <template #default="{ row }">
            {{ row.generalization_gap === null ? "暂无测试集评价" : formatFit(row.generalization_gap) }}
          </template>
        </el-table-column>
        <el-table-column label="系统工程风险提示" width="180">
          <template #default="{ row }">
            <el-tag :type="riskTagType(row.generalization_risk)">{{ row.risk_message }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button type="primary" text size="small" @click="goToDataset(row.dataset_id)">查看细节</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty
        v-else-if="dashboardAvailable"
        description="暂无建模结果。准备数据后，可从 ARX 辨识开始建立第一条结果。"
      >
        <el-button type="primary" @click="$router.push('/datasets')">选择数据集</el-button>
        <el-button @click="$router.push('/simulation')">生成仿真数据</el-button>
      </el-empty>
      <el-empty v-else-if="isLoading" description="正在加载工作台数据" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { Lightning, Trophy } from "@element-plus/icons-vue";
import { useRouter } from "vue-router";
import { getDashboardLeaderboard } from "../api/dashboard";
import { getDatasets } from "../api/datasets";
import { useDatasetStore } from "../stores/datasetStore";
import { useSystemStore } from "../stores/systemStore";
import type { DashboardLeaderboardEntry, DatasetItem } from "../types/api";

const router = useRouter();
const systemStore = useSystemStore();
const datasetStore = useDatasetStore();
const datasetCount = ref<number | null>(null);
const loadError = ref("");
const datasetItems = ref<DatasetItem[]>([]);
const leaderboardData = ref<DashboardLeaderboardEntry[]>([]);
const isLoading = ref(false);
const hasLoaded = ref(false);
const topEntry = computed(() => leaderboardData.value[0] ?? null);
const currentDataset = computed(() => datasetStore.activeDataset ?? datasetItems.value[0] ?? null);
const dashboardAvailable = computed(() => hasLoaded.value && !loadError.value);
const formatFit = (value: number) => value.toFixed(2) + "%";
const formatOptionalFit = (value: number | null) => value === null ? "—" : formatFit(value);
const formatOptionalNumber = (value: number | null) => value === null ? "—" : value.toFixed(3);
const formatSigned = (value: number) => (value >= 0 ? "+" : "") + value.toFixed(2) + "%";
const goToDataset = (datasetId: string) => router.push("/datasets/" + datasetId);
const shortIdentifier = (value?: string) => value ? `${value.slice(0, 8)}…` : "尚未生成";
const continueWork = () => currentDataset.value
  ? router.push(`/datasets/${currentDataset.value.id}`)
  : router.push("/datasets");
const riskTagType = (risk: DashboardLeaderboardEntry["generalization_risk"]) => ({
  normal: "success",
  attention: "warning",
  high: "danger",
  unavailable: "info",
}[risk] as "success" | "warning" | "danger" | "info");

const loadDashboard = async () => {
  if (isLoading.value) {
    return;
  }

  isLoading.value = true;
  try {
    const [datasets, leaderboard] = await Promise.all([getDatasets(1, 20), getDashboardLeaderboard()]);
    datasetItems.value = datasets.items;
    datasetStore.setDatasetsList(datasets.items);
    datasetCount.value = datasets.page?.total_items ?? datasets.items.length;
    leaderboardData.value = leaderboard.items;
    loadError.value = "";
    hasLoaded.value = true;
  } catch (error: any) {
    datasetCount.value = null;
    datasetItems.value = [];
    leaderboardData.value = [];
    hasLoaded.value = false;
    loadError.value = error.message || "未知错误";
  } finally {
    isLoading.value = false;
  }
};

watch(() => systemStore.status, (next, previous) => {
  if (next === "ready" && previous !== "ready" && loadError.value) {
    void loadDashboard();
  }
});

onMounted(() => {
  void loadDashboard();
});
</script>

<style scoped>
.page-header {
  margin-bottom: 20px;
}

.workbench-hero {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(300px, 0.8fr);
  gap: 32px;
  padding: 28px;
  color: #ffffff;
  background: linear-gradient(125deg, #17324a 0%, #1e6091 62%, #287b9d 100%);
  border: 0;
  box-shadow: 0 12px 28px rgba(23, 50, 74, 0.16);
}

.hero-main {
  align-self: center;
}

.hero-kicker {
  display: block;
  margin-bottom: 8px;
  color: rgba(255, 255, 255, 0.72);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.08em;
}

.hero-main h3 {
  margin: 0;
  font-size: clamp(22px, 2vw, 30px);
  line-height: 1.3;
}

.hero-main p {
  max-width: 640px;
  margin-top: 10px;
  color: rgba(255, 255, 255, 0.78);
  font-size: 14px;
}

.hero-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 22px;
}

.hero-actions :deep(.el-button) {
  margin-left: 0;
}

.hero-actions :deep(.el-button--primary) {
  color: var(--color-primary);
  background: #ffffff;
  border-color: #ffffff;
}

.hero-actions :deep(.el-button.is-plain) {
  color: #ffffff;
  background: rgba(255, 255, 255, 0.08);
  border-color: rgba(255, 255, 255, 0.45);
}

.hero-context {
  display: grid;
  align-content: center;
  gap: 14px;
  padding: 18px;
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.16);
  border-radius: 10px;
  backdrop-filter: blur(8px);
}

.hero-context > div {
  padding-bottom: 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.14);
}

.hero-context > div:last-child {
  padding-bottom: 0;
  border-bottom: 0;
}

.hero-context dt,
.hero-context--empty span {
  color: rgba(255, 255, 255, 0.64);
  font-size: 11px;
}

.hero-context dd {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-top: 3px;
  font-size: 13px;
}

.context-help {
  color: rgba(255, 255, 255, 0.7);
  cursor: help;
  font-size: 11px;
  text-decoration: underline dotted;
  text-underline-offset: 3px;
}

.hero-context--empty strong {
  font-size: 15px;
}

.hero-context--empty p {
  color: rgba(255, 255, 255, 0.7);
  font-size: 12px;
}

.subtitle {
  font-size: 13px;
  color: var(--text-secondary);
  margin-top: 4px;
}

.stat-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

.stat-card {
  margin-bottom: 20px;
}

.stat-title {
  font-size: 13px;
  color: var(--text-secondary);
}

.stat-val {
  font-size: 28px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 6px 0;
  font-family: var(--font-mono);
}

.stat-val.highlight {
  color: var(--color-primary);
}

.unit {
  font-size: 14px;
  font-weight: 400;
  color: var(--text-secondary);
}

.stat-sub {
  font-size: 12px;
  color: var(--text-muted);
}

.action-buttons {
  display: flex;
  gap: 16px;
}

.secondary-actions-card {
  padding-top: 14px;
  padding-bottom: 14px;
}

.secondary-actions-card .industrial-card-header {
  margin-bottom: 12px;
}

.error-detail {
  margin-top: 10px;
  color: var(--text-secondary);
  font-size: 12px;
}

.error-help {
  margin-bottom: 10px;
  color: var(--text-secondary);
  font-size: 13px;
}

.error-detail code {
  display: block;
  margin-top: 6px;
  overflow-wrap: anywhere;
}

.fit-val {
  font-weight: 600;
  color: var(--color-primary);
  font-family: var(--font-mono);
}

.improvement-text {
  color: var(--color-success);
  font-weight: 600;
  font-family: var(--font-mono);
}

.risk-text {
  color: var(--color-danger);
  font-weight: 600;
  font-family: var(--font-mono);
}

@media (max-width: 1050px) {
  .workbench-hero {
    grid-template-columns: minmax(0, 1fr);
  }

  .stat-cards {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 680px) {
  .workbench-hero {
    padding: 22px;
  }

  .stat-cards {
    grid-template-columns: minmax(0, 1fr);
  }

  .hero-actions,
  .action-buttons {
    align-items: stretch;
    flex-direction: column;
  }

  .hero-actions :deep(.el-button),
  .action-buttons :deep(.el-button) {
    width: 100%;
    margin-left: 0;
  }
}
</style>
