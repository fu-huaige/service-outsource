<template>
  <header class="app-header">
    <div class="header-left">
      <div class="logo">
        <el-icon class="logo-icon"><DataAnalysis /></el-icon>
        <span class="logo-text">IndusOpt 工模智优</span>
        <span class="logo-tag">A14</span>
      </div>
      <div class="dataset-selector" v-if="datasetStore.activeDataset">
        <span class="label">当前工作数据</span>
        <el-tooltip
          :content="`版本 ID：${datasetStore.activeDataset.version_id}`"
          placement="bottom"
        >
          <el-tag type="primary" effect="light" class="ds-tag">
            {{ datasetStore.activeDataset.name }}
          </el-tag>
        </el-tooltip>
      </div>
    </div>

    <div class="header-right">
      <el-tooltip content="后端、PostgreSQL 与 Redis 的健康状态，每 5 秒自动检测" placement="bottom">
        <div class="status-indicator">
          <span class="dot" :class="systemStore.status"></span>
          <span class="status-text">{{ statusLabel }}</span>
        </div>
      </el-tooltip>

      <el-button type="primary" size="default" class="copilot-btn" @click="$emit('toggle-copilot')">
        <el-icon><ChatDotSquare /></el-icon>
        <span>打开 Agent</span>
      </el-button>
    </div>
  </header>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { DataAnalysis, ChatDotSquare } from "@element-plus/icons-vue";
import { useDatasetStore } from "../stores/datasetStore";
import { useSystemStore } from "../stores/systemStore";

defineEmits(["toggle-copilot"]);

const datasetStore = useDatasetStore();
const systemStore = useSystemStore();
const statusLabel = computed(() => ({
  connecting: "正在检测",
  ready: "系统就绪",
  offline: "服务离线",
}[systemStore.status]));
</script>

<style scoped>
.app-header {
  height: 56px;
  background: var(--bg-header);
  border-bottom: 1px solid var(--border-light);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
}

.header-left, .header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.logo {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 700;
  font-size: 18px;
  color: var(--color-primary);
}

.logo-text {
  white-space: nowrap;
}

.logo-icon {
  font-size: 22px;
}

.logo-tag {
  font-size: 11px;
  font-weight: 500;
  background: var(--color-primary-light);
  color: var(--color-primary);
  padding: 1px 6px;
  border-radius: 4px;
}

.dataset-selector {
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding-left: 16px;
  border-left: 1px solid var(--border-light);
}

.ds-tag {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.label {
  color: var(--text-secondary);
}

.status-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-secondary);
  font-family: var(--font-mono);
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-warning);
}

.dot.ready {
  background: var(--color-success);
}

.dot.offline {
  background: var(--color-danger);
}

@media (max-width: 980px) {
  .dataset-selector,
  .logo-tag {
    display: none;
  }
}

@media (max-width: 620px) {
  .app-header {
    padding: 0 12px;
  }

  .copilot-btn span {
    display: none;
  }
}
</style>
