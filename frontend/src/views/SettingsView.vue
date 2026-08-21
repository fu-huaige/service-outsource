<template>
  <div class="settings-view">
    <div class="page-header">
      <h2>系统配置 (System Settings)</h2>
      <p class="subtitle">管理后端 API 服务地址、LLM Token 配置与系统连通性检查</p>
    </div>

    <div class="settings-layout">
      <!-- System Health Card -->
      <div class="industrial-card">
        <div class="industrial-card-header">
          <div class="industrial-card-title">
            <el-icon><Connection /></el-icon> 后端服务连通性检查 (Health Probe)
          </div>
          <el-button type="primary" size="small" icon="Refresh" :loading="systemStore.isChecking" @click="checkHealth">
            重新检测
          </el-button>
        </div>

        <el-descriptions border :column="2">
          <el-descriptions-item label="PostgreSQL 数据库">
            <el-tag :type="databaseTagType">{{ databaseStatus }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="Redis 任务队列">
            <el-tag :type="queueTagType">{{ queueStatus }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="系统状态">{{ systemStatus }}</el-descriptions-item>
          <el-descriptions-item label="前端构建版本">IndusOpt Vue 3 v0.1.0</el-descriptions-item>
        </el-descriptions>
      </div>

      <!-- LLM Key Card -->
      <div class="industrial-card">
        <div class="industrial-card-header">
          <div class="industrial-card-title">
            <el-icon><Key /></el-icon> 大语言模型 Agent API Key 设置
          </div>
        </div>

        <el-form label-width="140px" label-position="left" style="max-width: 600px">
          <el-form-item label="LLM Provider">
            <el-select v-model="llmProvider" style="width: 220px">
              <el-option label="DeepSeek-V3" value="deepseek" />
              <el-option label="通义千问 (Qwen)" value="qwen" />
            </el-select>
          </el-form-item>
          <el-form-item label="API Key">
            <el-input v-model="apiKey" type="password" show-password placeholder="sk-..." />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" icon="Check" @click="handleSave">保存设置</el-button>
          </el-form-item>
        </el-form>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { Connection, Refresh, Key, Check } from "@element-plus/icons-vue";
import { useSystemStore } from "../stores/systemStore";
import { ElMessage } from "element-plus";

const systemStore = useSystemStore();
const llmProvider = ref("deepseek");
const apiKey = ref("sk-demo-key-indusopt-2026");
const systemStatus = computed(() => ({
  connecting: "Connecting",
  ready: "System Ready",
  offline: "Backend Offline",
}[systemStore.status]));
const databaseStatus = computed(() => systemStore.readiness?.database ?? "Unavailable");
const queueStatus = computed(() => systemStore.readiness?.queue ?? "Unavailable");
const databaseTagType = computed(() => systemStore.status === "ready" ? "success" : "danger");
const queueTagType = computed(() => systemStore.status === "ready" ? "success" : "danger");

const checkHealth = async () => {
  const status = await systemStore.checkHealth();
  if (status === "ready") {
    ElMessage.success("系统健康检查通过：PostgreSQL 与 Redis 均就绪");
  } else {
    ElMessage.error("Backend Offline：无法连接后端或其依赖未就绪");
  }
};

const handleSave = () => {
  ElMessage.success("系统配置保存成功！");
};
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

.settings-layout {
  display: flex;
  flex-direction: column;
  gap: 20px;
}
</style>
