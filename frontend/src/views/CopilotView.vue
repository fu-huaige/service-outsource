<template>
  <div class="copilot-view">
    <div class="page-header">
      <span class="page-eyebrow">智能协作</span>
      <h2>Agent 工作台</h2>
      <p class="subtitle copilot-flow" aria-label="Agent 执行流程">
        <span v-for="step in FLOW_STEPS" :key="step" class="flow-step">{{ step }}</span>
      </p>
    </div>

    <div class="copilot-layout">
      <div class="industrial-card">
        <div class="industrial-card-header">
          <div class="industrial-card-title">
            <el-icon><ChatDotRound /></el-icon> 指令输入
          </div>
        </div>

        <el-form :model="form" class="copilot-command-form">
          <el-form-item label="数据版本 ID">
            <el-input
              v-model="form.active_version_id"
              placeholder="留空则只生成计划，不执行"
            />
          </el-form-item>

          <el-form-item label="任务描述">
            <el-input
              v-model="prompt"
              type="textarea"
              :rows="4"
              resize="vertical"
              placeholder="例如：清洗数据并估计时滞，然后做 ARX 辨识"
            />
          </el-form-item>

          <el-form-item label="示例指令" class="examples-form-item">
            <div class="examples-grid">
              <button
                v-for="example in EXAMPLES"
                :key="example.title"
                type="button"
                class="example-card"
                @click="prompt = example.prompt"
              >
                <span class="example-title">{{ example.title }}</span>
                <span class="example-description">{{ example.description }}</span>
              </button>
            </div>
          </el-form-item>

          <div class="copilot-action-row">
            <div class="copilot-action-content">
              <el-button
                type="primary"
                :loading="sending"
                icon="Promotion"
                @click="handleSend"
              >
                提交给 Agent
              </el-button>
            </div>
          </div>
        </el-form>

        <el-alert v-if="errorMessage" type="error" :closable="false" show-icon class="alert-gap">
          <template #title>执行失败：{{ errorMessage }}</template>
        </el-alert>
      </div>

      <template v-if="result">
        <div class="industrial-card">
          <div class="industrial-card-header">
            <div class="industrial-card-title">
              <el-icon><CircleCheck /></el-icon> 合规证明
              <span class="proof-id">{{ result.compliance?.proof_id }}</span>
            </div>
            <el-tag :type="result.compliance?.passed ? 'success' : 'danger'">
              {{ result.compliance?.passed ? "校验通过" : "校验未通过，已阻止执行" }}
            </el-tag>
          </div>

          <ul class="proof-list">
            <li v-for="check in result.compliance?.checks ?? []" :key="check.name">
              <el-icon :class="check.passed ? 'ok' : 'bad'">
                <CircleCheck v-if="check.passed" />
                <CircleClose v-else />
              </el-icon>
              <span class="check-name">{{ check.name }}</span>
              <span class="check-detail">{{ check.detail }}</span>
            </li>
          </ul>

          <p class="signature">
            签名 {{ result.compliance?.signature }} · 代码版本
            {{ result.compliance?.code_version }} · 生成于
            {{ result.compliance?.generated_at }}
          </p>
        </div>

        <div class="industrial-card">
          <div class="industrial-card-header">
            <div class="industrial-card-title">
              <el-icon><Share /></el-icon> Agent 编排计划
            </div>
            <div class="header-tags">
              <el-tag :type="result.plan_source === 'llm' ? 'success' : 'info'">
                {{
                  result.plan_source === "llm"
                    ? `大模型编排 · ${result.llm_provider}/${result.llm_model}`
                    : "确定性规则编排"
                }}
              </el-tag>
              <el-tag :type="result.executed ? 'success' : 'info'">
                {{ result.executed ? "已执行" : "仅生成计划" }}
              </el-tag>
            </div>
          </div>

          <el-alert
            v-if="result.llm_fallback_reason"
            type="info"
            :closable="false"
            show-icon
            class="alert-gap"
          >
            <template #title>
              未采用大模型计划，已回退到确定性规则编排：{{ result.llm_fallback_reason }}
              （无论计划由谁生成，都要通过同一套白名单与合规校验）
            </template>
          </el-alert>

          <el-steps direction="vertical" :active="activeStep" finish-status="success">
            <el-step
              v-for="step in result.plan.steps"
              :key="step.step_id"
              :status="stepStatus(step.status)"
            >
              <template #title>
                <span class="step-title">{{ step.step_id }} · {{ step.tool }}</span>
                <el-tag v-if="step.requires_confirmation" size="small" type="warning">
                  需人工确认
                </el-tag>
                <el-tag :type="statusType(step.status)" size="small" class="status-tag">
                  {{ statusLabel(step.status) }}
                </el-tag>
              </template>
              <template #description>
                <div class="step-body">
                  <p v-if="Object.keys(step.parameters).length" class="step-params">
                    参数：<span class="code-inline">{{ JSON.stringify(step.parameters) }}</span>
                  </p>
                  <p v-if="runFor(step.step_id)" class="step-summary">
                    {{ runFor(step.step_id)?.summary }}
                  </p>
                  <p v-if="runFor(step.step_id)?.error_code" class="step-error">
                    错误码：{{ runFor(step.step_id)?.error_code }}
                  </p>
                  <p v-if="runFor(step.step_id)" class="step-timing">
                    耗时 {{ (runFor(step.step_id)?.duration_ms ?? 0).toFixed(1) }} ms
                  </p>
                </div>
              </template>
            </el-step>
          </el-steps>
        </div>

        <div class="industrial-card" v-if="result.step_runs.length">
          <div class="industrial-card-header">
            <div class="industrial-card-title">
              <el-icon><Document /></el-icon> 工具真实输出
            </div>
          </div>
          <el-table :data="result.step_runs" stripe style="width: 100%">
            <el-table-column prop="step_id" label="步骤" width="90" />
            <el-table-column prop="tool" label="工具" width="200" />
            <el-table-column label="状态" width="120">
              <template #default="{ row }">
                <el-tag :type="statusType(row.status)" size="small">
                  {{ statusLabel(row.status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="算法返回值">
              <template #default="{ row }">
                <span class="code-inline result-cell">{{ JSON.stringify(row.result) }}</span>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <div class="industrial-card">
          <div class="industrial-card-header">
            <div class="industrial-card-title">
              <el-icon><InfoFilled /></el-icon> 结论与假设
            </div>
          </div>
          <p class="conclusion">{{ result.conclusion }}</p>
          <ul class="assumption-list">
            <li v-for="note in result.plan.assumptions" :key="note">{{ note }}</li>
          </ul>
          <p class="stop-conditions">
            停止条件：{{ result.plan.stop_conditions.join("；") }}
          </p>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from "vue";
import {
  ChatDotRound,
  CircleCheck,
  CircleClose,
  Document,
  InfoFilled,
  Promotion,
  Share,
} from "@element-plus/icons-vue";
import { chatWithCopilot } from "../api/copilot";
import type { AgentStepStatus, CopilotChatRequest, CopilotChatResponse } from "../types/api";
import { ApiError } from "../api/client";
import { ElMessage } from "element-plus";

const FLOW_STEPS = ["自然语言", "意图解析", "白名单计划", "静态合规校验", "真实算法执行", "结论"];

const EXAMPLES = [
  {
    title: "完整建模流程",
    description: "筛选高信噪比动态数据，处理共线性并进行闭环寻优",
    prompt: "提取 1 号塔高信噪比的动态数据，处理共线性后，通过闭环寻优找出最佳模型数据",
  },
  {
    title: "清洗与系统辨识",
    description: "清洗异常数据，估计时滞并完成 ARX 辨识",
    prompt: "清洗数据并估计时滞，然后做 ARX 辨识",
  },
  {
    title: "区间优选与导出",
    description: "使用窗口 90 优选动态区间并导出数据集",
    prompt: "用窗口 90 做动态区间优选并导出优选数据集",
  },
];

const STATUS_LABELS: Record<string, string> = {
  pending: "待执行",
  running: "执行中",
  waiting_confirmation: "待确认",
  completed: "已完成",
  failed: "失败",
};

const prompt = ref("");
const sending = ref(false);
const errorMessage = ref("");
const result = ref<CopilotChatResponse | null>(null);

const form = reactive<CopilotChatRequest>({
  message: "",
  active_version_id: "",
});

const handleSend = async () => {
  errorMessage.value = "";
  if (!prompt.value.trim()) {
    errorMessage.value = "请输入指令。";
    return;
  }
  sending.value = true;
  try {
    // No mock plan: a fabricated workflow would misrepresent what the agent decided.
    result.value = await chatWithCopilot({
      message: prompt.value.trim(),
      active_version_id: form.active_version_id || null,
    });
    ElMessage.success(result.value.conclusion);
  } catch (err) {
    result.value = null;
    errorMessage.value = err instanceof ApiError ? err.message : String(err);
  } finally {
    sending.value = false;
  }
};

const runFor = (stepId: string) =>
  result.value?.step_runs.find((run) => run.step_id === stepId) ?? null;

const activeStep = computed(() => {
  if (!result.value) return 0;
  const steps = result.value.plan.steps;
  const firstUnfinished = steps.findIndex((step) => step.status !== "completed");
  return firstUnfinished === -1 ? steps.length : firstUnfinished;
});

const statusLabel = (status: string) => STATUS_LABELS[status] ?? status;

const statusType = (status: AgentStepStatus) =>
  status === "completed"
    ? "success"
    : status === "failed"
      ? "danger"
      : status === "waiting_confirmation"
        ? "warning"
        : "info";

const stepStatus = (status: AgentStepStatus) =>
  status === "completed"
    ? "success"
    : status === "failed"
      ? "error"
      : status === "waiting_confirmation"
        ? "warning"
        : "wait";
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

.copilot-flow {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 0;
}

.flow-step {
  display: inline-flex;
  align-items: center;
  white-space: nowrap;
}

.flow-step + .flow-step::before {
  content: "→";
  margin: 0 7px;
  color: var(--text-muted);
}

.copilot-layout {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.copilot-command-form {
  --copilot-label-width: 136px;
  container-type: inline-size;
  display: grid;
  gap: 16px;
  width: min(100%, 1120px);
  margin: 0 auto;
}

.copilot-command-form :deep(.el-form-item) {
  display: grid;
  grid-template-columns: var(--copilot-label-width) minmax(0, 1fr);
  align-items: start;
  min-width: 0;
  margin: 0;
}

.copilot-command-form :deep(.el-form-item__label) {
  width: auto !important;
  height: auto;
  min-height: 32px;
  padding: 0 16px 0 0;
  line-height: 32px;
  text-align: right;
  justify-content: flex-end;
}

.copilot-command-form :deep(.el-form-item__content) {
  display: block;
  min-width: 0;
  width: 100%;
  line-height: 1.5;
}

.copilot-command-form :deep(.el-input),
.copilot-command-form :deep(.el-textarea) {
  width: 100%;
}

.examples-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  width: 100%;
  min-width: 0;
}

.example-card {
  appearance: none;
  display: block;
  min-width: 0;
  max-width: 100%;
  padding: 11px 12px;
  overflow: hidden;
  color: inherit;
  font: inherit;
  text-align: left;
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
  border-radius: 6px;
  cursor: pointer;
  transition:
    border-color 0.15s ease,
    background-color 0.15s ease,
    box-shadow 0.15s ease;
}

.example-card:hover {
  background: var(--color-primary-light);
  border-color: var(--color-primary);
}

.example-card:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}

.example-title,
.example-description {
  display: block;
  max-width: 100%;
  overflow-wrap: anywhere;
  white-space: normal;
}

.example-title {
  color: var(--color-primary);
  font-size: 13px;
  font-weight: 600;
}

.example-description {
  margin-top: 3px;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.45;
}

.copilot-action-row {
  display: grid;
  grid-template-columns: var(--copilot-label-width) minmax(0, 1fr);
  min-width: 0;
}

.copilot-action-content {
  display: flex;
  grid-column: 2;
  justify-content: flex-end;
}

.copilot-action-content :deep(.el-button) {
  min-width: 160px;
}

.alert-gap {
  margin-top: 12px;
}

.header-tags {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.proof-id {
  margin-left: 10px;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-secondary);
}

.proof-list {
  list-style: none;
  padding: 0;
  margin: 8px 0 0;
}

.proof-list li {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 5px 0;
  font-size: 13px;
  border-bottom: 1px dashed var(--border-color, #e4e7ed);
}

.ok {
  color: #2a9d8f;
}

.bad {
  color: #e63946;
}

.check-name {
  font-family: var(--font-mono);
  min-width: 220px;
}

.check-detail {
  color: var(--text-secondary);
}

.signature {
  margin-top: 10px;
  font-size: 12px;
  color: var(--text-secondary);
  font-family: var(--font-mono);
  word-break: break-all;
}

.step-title {
  font-weight: 600;
  margin-right: 8px;
}

.status-tag {
  margin-left: 6px;
}

.step-body {
  padding: 4px 0 10px;
  font-size: 13px;
}

.step-params,
.step-timing {
  color: var(--text-secondary);
  margin: 2px 0;
  font-size: 12px;
}

.step-summary {
  margin: 4px 0;
}

.step-error {
  color: #e63946;
  margin: 2px 0;
}

.result-cell {
  font-size: 12px;
  word-break: break-all;
}

.conclusion {
  font-weight: 600;
  margin-bottom: 10px;
}

.assumption-list {
  margin: 0 0 10px;
  padding-left: 20px;
  font-size: 13px;
  color: var(--text-secondary);
}

.stop-conditions {
  font-size: 12px;
  color: var(--text-secondary);
}

@container (max-width: 900px) {
  .examples-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@container (max-width: 680px) {
  .copilot-command-form :deep(.el-form-item),
  .copilot-action-row {
    grid-template-columns: minmax(0, 1fr);
    gap: 6px;
  }

  .copilot-command-form :deep(.el-form-item__label) {
    min-height: 0;
    padding: 0;
    line-height: 1.5;
    text-align: left;
    justify-content: flex-start;
  }

  .examples-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .copilot-action-content {
    grid-column: 1;
  }

  .copilot-action-content :deep(.el-button) {
    min-width: 0;
    width: 100%;
  }
}

@media (max-width: 600px) {
  .copilot-view .industrial-card {
    padding: 16px;
  }
}
</style>
