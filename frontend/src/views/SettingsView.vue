<template>
  <div class="settings-view">
    <div class="page-header">
      <span class="page-eyebrow">运行环境</span>
      <h2>系统设置</h2>
      <p class="subtitle">检查服务连接状态，了解 Agent 当前采用的规划方式</p>
    </div>

    <div class="settings-layout">
      <div class="industrial-card">
        <div class="industrial-card-header">
          <div class="industrial-card-title">
            <el-icon><Connection /></el-icon> 服务连接状态
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
          <el-descriptions-item label="系统状态">
            <el-tag :type="systemTagType">{{ systemStatus }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="后端版本">{{ backendVersion }}</el-descriptions-item>
        </el-descriptions>
      </div>

      <div class="industrial-card">
        <div class="industrial-card-header">
          <div class="industrial-card-title">
            <el-icon><Key /></el-icon> Agent 规划方式
          </div>
          <el-tag type="info" effect="plain">由后端运行环境管理</el-tag>
        </div>

        <el-alert
          type="info"
          title="当前网页不会读取、保存或回显 API Key"
          description="系统默认使用确定性规则生成计划。启用大语言模型时，由部署人员在后端运行环境中配置 OpenAI 兼容服务，修改后需要重启后端。"
          :closable="false"
          show-icon
        />

        <dl class="config-list">
          <div>
            <dt>默认规划方式</dt>
            <dd>确定性规则编排</dd>
          </div>
          <div>
            <dt>模型服务</dt>
            <dd>支持 OpenAI 兼容接口；实际提供方由后端配置决定</dd>
          </div>
          <div>
            <dt>安全边界</dt>
            <dd>密钥不进入浏览器、不写入前端存储，也不会在本页显示</dd>
          </div>
        </dl>

        <el-collapse class="config-help">
          <el-collapse-item title="查看部署配置项" name="llm-env">
            <p>在后端环境中设置以下配置，并重启服务后生效：</p>
            <ul>
              <li><code>INDUSOPT_LLM_PROVIDER</code>：服务提供方标识</li>
              <li><code>INDUSOPT_LLM_BASE_URL</code>：OpenAI 兼容接口地址</li>
              <li><code>INDUSOPT_LLM_MODEL</code>：模型名称</li>
              <li><code>INDUSOPT_LLM_API_KEY</code>：访问密钥</li>
            </ul>
          </el-collapse-item>
        </el-collapse>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from "vue";
import { Connection, Refresh, Key } from "@element-plus/icons-vue";
import { useSystemStore } from "../stores/systemStore";
import { getSystemInfo } from "../api/health";
import { ElMessage } from "element-plus";

const systemStore = useSystemStore();
const systemStatus = computed(() => ({
  connecting: "正在检测",
  ready: "系统就绪",
  offline: "服务离线",
}[systemStore.status]));
const databaseStatus = computed(() => systemStore.readiness?.database === "connected" ? "已连接" : systemStore.status === "connecting" ? "等待检测" : "未连接");
const queueStatus = computed(() => systemStore.readiness?.queue === "connected" ? "已连接" : systemStore.status === "connecting" ? "等待检测" : "未连接");
const databaseTagType = computed(() => systemStore.status === "ready" ? "success" : "danger");
const queueTagType = computed(() => systemStore.status === "ready" ? "success" : "danger");
const systemTagType = computed(() => systemStore.status === "ready" ? "success" : systemStore.status === "offline" ? "danger" : "warning");
const backendVersion = computed(() => systemStore.systemInfo?.version ? `v${systemStore.systemInfo.version}` : "等待读取");

const checkHealth = async () => {
  const status = await systemStore.checkHealth();
  if (status === "ready") {
    ElMessage.success("系统健康检查通过：PostgreSQL 与 Redis 均就绪");
  } else {
    ElMessage.error("服务离线：无法连接后端，或数据库、任务队列尚未就绪");
  }
};

onMounted(async () => {
  try {
    systemStore.setSystemInfo(await getSystemInfo());
  } catch {
    // The health card already exposes connection failures; version is optional metadata.
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

.settings-layout {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.config-list {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-top: 16px;
}

.config-list > div {
  padding: 14px;
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
  border-radius: 8px;
}

.config-list dt {
  margin-bottom: 6px;
  color: var(--text-muted);
  font-size: 12px;
}

.config-list dd {
  color: var(--text-primary);
  font-size: 13px;
  line-height: 1.6;
}

.config-help {
  margin-top: 16px;
}

.config-help p,
.config-help ul {
  color: var(--text-secondary);
  font-size: 13px;
}

.config-help ul {
  margin: 10px 0 0 20px;
}

.config-help li + li {
  margin-top: 6px;
}

.config-help code {
  font-family: var(--font-mono);
  color: var(--color-primary);
}

@media (max-width: 900px) {
  .config-list {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
