<template>
  <div class="dashboard-view">
    <div class="page-header">
      <h2>工作台概览 (Dashboard Overview)</h2>
      <p class="subtitle">面向流程工业系统辨识的自主建模数据工程师 Agent 系统</p>
    </div>

    <!-- Stat Cards -->
    <div class="stat-cards">
      <div class="industrial-card stat-card">
        <div class="stat-title">活跃数据集</div>
        <div class="stat-val">{{ datasetCount }} <span class="unit">个</span></div>
        <div class="stat-sub">上传与仿真数据均计入</div>
      </div>
      <div class="industrial-card stat-card">
        <div class="stat-title">最高辨识 FIT 拟合度</div>
        <div class="stat-val highlight">{{ topEntry ? formatFit(topEntry.validation_fit) : "—" }}</div>
        <div class="stat-sub">{{ topEntry ? topEntry.dataset_name : "暂无已完成寻优" }}</div>
      </div>
      <div class="industrial-card stat-card">
        <div class="stat-title">已完成闭环研究</div>
        <div class="stat-val">{{ leaderboardData.length }} <span class="unit">项</span></div>
        <div class="stat-sub">仅统计真实成功的 Optuna study</div>
      </div>
      <div class="industrial-card stat-card">
        <div class="stat-title">排行榜数据源</div>
        <div class="stat-val success-text">{{ loadError ? "不可用" : "真实记录" }}</div>
        <div class="stat-sub">仅使用数据库中已完成的寻优结果</div>
      </div>
    </div>

    <!-- Quick Actions -->
    <div class="industrial-card">
      <div class="industrial-card-header">
        <div class="industrial-card-title">
          <el-icon><Lightning /></el-icon> 快捷行动入口
        </div>
      </div>
      <div class="action-buttons">
        <el-button type="primary" size="large" icon="Plus" @click="$router.push('/simulation')">
          新建 S1-S6 仿真数据集
        </el-button>
        <el-button type="success" size="large" icon="Upload" @click="$router.push('/datasets')">
          上传工业 CSV 数据集
        </el-button>
        <el-button type="warning" size="large" icon="ChatDotSquare" @click="$router.push('/copilot')">
          启动 Agent 智能闭环建模
        </el-button>
      </div>
    </div>

    <!-- Leaderboard Table -->
    <div class="industrial-card">
      <div class="industrial-card-header">
        <div class="industrial-card-title">
          <el-icon><Trophy /></el-icon> 预处理与辨识效果 Leaderboard
        </div>
        <el-tag type="info">按验证集 FIT 排名</el-tag>
      </div>
      <el-alert v-if="loadError" type="error" :title="loadError" show-icon :closable="false" style="margin-bottom: 16px" />
      <el-table v-if="leaderboardData.length" :data="leaderboardData" stripe style="width: 100%">
        <el-table-column prop="dataset_name" label="数据集名称" width="180" />
        <el-table-column label="首轮验证 FIT" width="120">
          <template #default="{ row }">{{ formatFit(row.baseline_fit) }}</template>
        </el-table-column>
        <el-table-column label="优化后验证 FIT" width="130">
          <template #default="{ row }">
            <span class="fit-val">{{ formatFit(row.optimized_fit) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="improvement" label="提升幅度" width="120">
          <template #default="{ row }">
            <span :class="row.improvement >= 0 ? 'improvement-text' : 'risk-text'">{{ formatSigned(row.improvement) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="真实最优参数">
          <template #default="{ row }">{{ row.contribution_summary || "—" }}</template>
        </el-table-column>
        <el-table-column label="泛化风险" width="150">
          <template #default="{ row }">
            {{ row.generalization_gap === null ? "暂无测试集指标" : `测试差距 ${formatFit(row.generalization_gap)}` }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button type="primary" text size="small" @click="goToDataset(row.dataset_id)">查看细节</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else description="暂无已完成的闭环寻优结果。请先生成或上传数据集并完成一次闭环寻优。" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { Lightning, Trophy } from "@element-plus/icons-vue";
import { useRouter } from "vue-router";
import { getDashboardLeaderboard } from "../api/dashboard";
import { getDatasets } from "../api/datasets";
import type { DashboardLeaderboardEntry } from "../types/api";

const router = useRouter();
const datasetCount = ref(0);
const loadError = ref("");
const leaderboardData = ref<DashboardLeaderboardEntry[]>([]);
const topEntry = computed(() => leaderboardData.value[0] ?? null);
const formatFit = (value: number) => value.toFixed(2) + "%";
const formatSigned = (value: number) => (value >= 0 ? "+" : "") + value.toFixed(2) + "%";
const goToDataset = (datasetId: string) => router.push("/datasets/" + datasetId);

onMounted(async () => {
  try {
    const [datasets, leaderboard] = await Promise.all([getDatasets(1, 1), getDashboardLeaderboard()]);
    datasetCount.value = datasets.page?.total ?? datasets.items.length;
    leaderboardData.value = leaderboard.items;
  } catch (error: any) {
    loadError.value = "获取真实 Dashboard 数据失败：" + (error.message || "未知错误");
  }
});
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

.stat-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
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

.stat-val.success-text {
  color: var(--color-success);
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
</style>
