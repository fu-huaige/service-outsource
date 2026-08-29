<template>
  <header class="app-header">
    <div class="header-left">
      <router-link to="/" class="logo" title="返回产品概览首页">
        <el-icon class="logo-icon"><DataAnalysis /></el-icon>
        <span class="logo-text">IndusOpt 工模智优</span>
        <span class="logo-tag">A14</span>
      </router-link>

      <div class="dataset-selector" v-if="datasetStore.activeDataset">
        <span class="label">当前数据：</span>
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

    <!-- Center / Right Command & Status Bar -->
    <div class="header-right">
      <!-- Quick Command Hub Trigger Button -->
      <button class="cmd-trigger-btn" type="button" @click="emit('openCommand')">
        <el-icon><Search /></el-icon>
        <span class="cmd-trigger-text">快速指令 / 页面跳转</span>
        <span class="cmd-kbd font-mono">{{ isMac ? '⌘K' : 'Ctrl+K' }}</span>
      </button>

      <!-- Return to Landing Overview -->
      <router-link to="/" class="landing-link" title="返回首页系统介绍">
        <span>产品概览</span>
      </router-link>

      <!-- System Health Indicator -->
      <el-tooltip content="后端、PostgreSQL 与 Redis 的健康状态，每 5 秒自动检测" placement="bottom">
        <div class="status-indicator">
          <span class="dot" :class="systemStore.status"></span>
          <span class="status-text">{{ statusLabel }}</span>
        </div>
      </el-tooltip>
    </div>
  </header>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { DataAnalysis, Search } from "@element-plus/icons-vue";
import { useDatasetStore } from "../stores/datasetStore";
import { useSystemStore } from "../stores/systemStore";

const emit = defineEmits<{
  openCommand: [];
}>();

const datasetStore = useDatasetStore();
const systemStore = useSystemStore();

const isMac = typeof navigator !== "undefined" && /Mac|iPod|iPhone|iPad/.test(navigator.platform);

const statusLabel = computed(() => ({
  connecting: "正在检测",
  ready: "系统就绪",
  offline: "服务离线",
}[systemStore.status]));
</script>

<style scoped>
.app-header {
  height: 52px;
  background: var(--bg-header);
  border-bottom: 1px solid var(--border-light);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 18px;
}

.header-left, .header-right {
  display: flex;
  align-items: center;
  gap: 14px;
}

.logo {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 700;
  font-size: 16px;
  color: var(--color-primary);
  text-decoration: none;
  transition: opacity 0.2s ease;
}

.logo:hover {
  opacity: 0.85;
}

.logo-text {
  white-space: nowrap;
}

.logo-icon {
  font-size: 20px;
}

.logo-tag {
  font-size: 10px;
  font-weight: 600;
  background: var(--color-primary-light);
  color: var(--color-primary);
  padding: 1px 5px;
  border-radius: 3px;
}

.dataset-selector {
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 6px;
  padding-left: 14px;
  border-left: 1px solid var(--border-light);
}

.ds-tag {
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 12px;
}

.label {
  color: var(--text-secondary);
  font-size: 12px;
}

/* Command Palette Trigger */
.cmd-trigger-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 5px 12px;
  border-radius: 6px;
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.cmd-trigger-btn:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: var(--color-primary-light);
}

.cmd-kbd {
  font-size: 10px;
  padding: 1px 5px;
  background: rgba(0, 0, 0, 0.06);
  border-radius: 3px;
  border: 1px solid var(--border-light);
  color: var(--text-muted);
}

.landing-link {
  font-size: 13px;
  color: var(--text-secondary);
  text-decoration: none;
  padding: 4px 8px;
  border-radius: 4px;
  transition: color 0.2s ease;
}

.landing-link:hover {
  color: var(--color-primary);
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

.font-mono {
  font-family: var(--font-mono);
}

@media (max-width: 980px) {
  .dataset-selector,
  .logo-tag,
  .landing-link {
    display: none;
  }
}

@media (max-width: 640px) {
  .cmd-trigger-text {
    display: none;
  }
}
</style>
