<template>
  <div class="agent-stream" ref="streamRef">
    <!-- User Request Bubble -->
    <div class="stream-section">
      <div class="stream-user-request">
        <div class="stream-user-request__avatar">U</div>
        <div class="stream-user-request__body">
          <div class="stream-user-request__text">{{ execution.plan?.goal || '用户请求' }}</div>
        </div>
      </div>
    </div>

    <!-- Compliance Proof (compact) -->
    <div v-if="execution.artifacts?.compliance" class="stream-compliance">
      <span
        class="compliance-badge"
        :class="execution.artifacts.compliance.passed ? 'ok' : 'fail'"
      >
        {{ execution.artifacts.compliance.passed ? '✓ 合规证明通过' : '✗ 合规校验未通过' }}
      </span>
      <span class="compliance-id font-mono" :title="execution.artifacts?.compliance?.proof_id">
        {{ (execution.artifacts?.compliance?.proof_id ?? '').slice(0, 8) }}
      </span>
    </div>

    <!-- Plan Overview / Execution Timeline -->
    <AgentPlan
      v-if="execution.plan?.steps?.length"
      :steps="execution.plan.steps"
      :step-runs="execution.step_runs"
      :current-step-id="execution.current_step_id"
      @step-click="$emit('artifact-select', $event)"
    />

    <!-- Step Events Stream -->
    <div class="stream-events">
      <template v-for="stepRun in execution.step_runs" :key="execution.execution_id + ':' + stepRun.step_id">
        <!-- Tool Execution Event -->
        <ToolExecution
          :step-run="stepRun"
          :plan-step="getPlanStep(stepRun.step_id)"
          @click="$emit('artifact-select', stepRun.step_id)"
        />

        <!-- Approval Card (if waiting) -->
        <div
          v-if="specGate?.step_id === stepRun.step_id"
          class="stream-action-card"
          data-test="agent-model-spec"
        >
          <div class="stream-action-card__body">
            <div class="stream-action-card__title">{{ needsRowOrder ? '确认原始记录顺序' : '补充建模配置' }}</div>
            <p>当前数据版本 {{ execution.current_version_id }}</p>
            <p v-if="versionError" role="alert">{{ versionError }}</p>
            <p v-else-if="needsRowOrder">当前 CSV 没有时间戳。请核对 CSV 行序是否与原始采集顺序一致。</p>
            <p v-else-if="specVersion && specRequirementMessage">{{ specRequirementMessage }}</p>
            <button
              v-if="versionError"
              type="button"
              class="stream-action-card__btn"
              @click="loadSpecVersion"
            >重新读取版本</button>
            <button
              v-else-if="needsRowOrder"
              type="button"
              class="stream-action-card__btn"
              data-test="confirm-model-row-order"
              :disabled="isConfirming || !specVersion?.sha256"
              @click="submitRowOrder"
            >确认原始行序并推荐</button>
            <details v-else-if="specVersion" :key="specVersion.id" data-test="model-spec-fallback">
              <summary>补充实验配置</summary>
              <ExperimentSpecFields
                :dataset-id="execution.dataset_id"
                :version="specVersion"
                :disabled="isConfirming"
                @change="specDraft = $event"
              />
              <button
                type="button"
                class="stream-action-card__btn"
                :disabled="isConfirming || !specDraft"
                @click="submitSpec"
              >确认配置并推荐</button>
            </details>
          </div>
        </div>
        <ApprovalCard
          v-else-if="needsApproval(stepRun.step_id) || lockedSelection(stepRun)"
          :step-run="stepRun"
          :plan-step="getPlanStep(stepRun.step_id)"
          :execution-id="execution.execution_id"
          :copilot-run-id="execution.copilot_run_id"
          :submitting="isConfirming || (stepRun.tool === 'confirm_model_selection' && trainingPending)"
          :recommendation="recommendationFor(stepRun)"
          :recommendation-step-id="recommendationStepId(stepRun)"
          :locked-selection="lockedSelection(stepRun)"
          @confirm="$emit('confirm', $event)"
        />
        <p
          v-if="stepRun.tool === 'confirm_model_selection' && stepRun.confirmation_status === 'REJECTED'"
          class="stream-notice"
          data-test="model-selection-rejected"
        >模型选择已拒绝</p>
      </template>

      <section v-if="lockedStep || trainingPending || modelExecution" class="training-card" data-test="agent-model-training">
        <header class="training-card__header">
          <div>
            <h3>正式模型训练</h3>
            <p v-if="trainingModelName" class="training-card__model">{{ trainingModelName }}</p>
          </div>
          <span class="training-badge" :data-state="trainingOverview.state" role="status">{{ trainingOverview.label }}</span>
        </header>

        <ol class="training-steps" aria-label="训练执行步骤">
          <li v-for="step in trainingSteps" :key="step.name" class="training-step" :data-state="step.state">
            <span class="training-step__icon" aria-hidden="true">
              <component :is="trainingIcons[step.state]" />
            </span>
            <span class="training-step__name">{{ step.name }}</span>
            <span class="training-badge" :data-state="step.state">{{ step.label }}</span>
          </li>
        </ol>

        <p v-if="modelExecution?.manifest_status === 'failed'" class="training-card__notice">模型清单发布失败，Validation 评价未执行。</p>
        <p v-if="modelExecution?.manifest_status === 'unconfirmed'" class="training-card__notice">模型清单状态待核验。</p>
        <p v-if="trainingLookupFailed" class="training-card__notice">暂时无法读取最新状态，可刷新查询。</p>
        <p v-if="trainingFailureMessage" class="training-card__notice">{{ trainingFailureMessage }}</p>

        <details v-if="modelExecution" class="training-details" data-test="training-details">
          <summary>执行详情</summary>
          <dl>
            <dt>训练执行 ID</dt><dd><code>{{ modelExecution.execution_id }}</code></dd>
            <template v-if="modelExecution.model_id">
              <dt>模型 ID</dt><dd><code>{{ modelExecution.model_id }}</code></dd>
            </template>
            <template v-if="modelExecution.training_run_id">
              <dt>训练 Run ID</dt><dd><code>{{ modelExecution.training_run_id }}</code></dd>
            </template>
            <template v-if="modelExecution.evaluation_run_id">
              <dt>评价 Run ID</dt><dd><code>{{ modelExecution.evaluation_run_id }}</code></dd>
            </template>
            <template v-if="modelExecution.training_error">
              <dt>训练诊断</dt><dd><code>{{ modelExecution.training_error }}</code></dd>
            </template>
            <template v-if="modelExecution.evaluation_error">
              <dt>评价诊断</dt><dd><code>{{ modelExecution.evaluation_error }}</code></dd>
            </template>
            <template v-if="modelExecution.comparison_reason">
              <dt>比较诊断</dt><dd><code>{{ modelExecution.comparison_reason }}</code></dd>
            </template>
          </dl>
        </details>
        <button
          v-if="(trainingPending || trainingLookupFailed || modelExecution?.execution_status === 'unconfirmed') && !isConfirming"
          :disabled="trainingLoading"
          type="button"
          class="stream-action-card__btn"
          @click="$emit('refresh-model-training')"
        >刷新训练状态</button>
      </section>

      <!-- Currently running step indicator -->
      <div v-if="isRunning" class="stream-running" data-test="stream-running">
        <div class="stream-running__indicator">
          <span class="agent-working-dot" />
        </div>
        <div class="stream-running__text">
          <span class="stream-running__tool">{{ currentToolName }}</span>
          <span class="stream-running__desc">Agent 正在执行…</span>
        </div>
      </div>

      <!-- Manual execute triggers -->
      <div
        v-if="canExecuteEvaluation"
        class="stream-action-card"
        data-test="stream-evaluate-action"
      >
        <div class="stream-action-card__body">
          <div class="stream-action-card__title">模型评价</div>
          <div class="stream-action-card__desc">ARX 建模完成，点击在测试集上执行模型评价</div>
        </div>
        <button
          type="button"
          class="stream-action-card__btn"
          @click="$emit('execute-evaluation')"
        >
          执行评价
        </button>
      </div>

      <div
        v-if="canExecuteOptimization"
        class="stream-action-card"
        data-test="stream-optimize-action"
      >
        <div class="stream-action-card__body">
          <div class="stream-action-card__title">管道优化</div>
          <div class="stream-action-card__desc">点击启动 Optuna 闭环寻优（预计 2~10 分钟）</div>
        </div>
        <button
          type="button"
          class="stream-action-card__btn"
          @click="$emit('execute-optimization')"
        >
          启动优化
        </button>
      </div>
    </div>

    <div v-if="execution.workflow_status === 'SUCCEEDED' && !isModelSelectionWorkflow" class="stream-conclusion" data-test="execution-completed">
      <div class="stream-conclusion__label">任务已完成</div>
      <div>所有步骤执行成功，可在右侧成果展示区查看和下载结果。</div>
    </div>
    <div v-else-if="execution.workflow_status === 'FAILED'" class="stream-notice warning" role="alert">
      {{ execution.error_message || '任务执行失败，请查看失败步骤。' }}
    </div>

    <!-- Conclusion -->
    <div v-if="execution.artifacts?.conclusion" class="stream-conclusion">
      <div class="stream-conclusion__label">CONCLUSION · 执行结论</div>
      <div class="stream-conclusion__text">{{ execution.artifacts.conclusion }}</div>
      <div v-if="execution.artifacts?.assumptions?.length" class="stream-conclusion__assumptions">
        <div class="stream-conclusion__assumptions-label">ASSUMPTIONS · 建模假设</div>
        <ul>
          <li v-for="(a, i) in execution.artifacts.assumptions" :key="i">{{ a }}</li>
        </ul>
      </div>
    </div>

    <!-- Hydrating / resume notice (for E2E data-test compat) -->
    <div v-if="isHydrating" class="stream-notice info" data-test="hydrating-execution">
      正在从后端恢复 Agent Execution…
    </div>
    <div v-if="resumeNotice" class="stream-notice warning" data-test="resume-notice">
      {{ resumeNotice }}
    </div>
    <div v-if="execution.execution_id" class="stream-meta font-mono" style="display:none">
      <span data-test="execution-id">{{ execution.execution_id }}</span>
      <span data-test="workflow-status">{{ execution.workflow_status }}</span>
      <span data-test="current-version-id">{{ execution.current_version_id }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { Check, Close, Loading, Minus, MoreFilled, Warning } from '@element-plus/icons-vue';
import { ref, computed, watch, nextTick } from 'vue';
import AgentPlan from './AgentPlan.vue';
import ToolExecution from './ToolExecution.vue';
import ApprovalCard from './ApprovalCard.vue';
import ExperimentSpecFields from '../composer/ExperimentSpecFields.vue';
import { getDatasetVersions } from '../../api/datasets';
import type {
  ConfirmedModelSelection, CopilotExecutionSnapshot, CopilotExecutionStepSnapshot,
  ExecutionPlanStep, CopilotConfirmRequest, ModelRecommendationResult,
  CopilotModelExecutionData, DatasetVersionNode, ModelRecommendationRequest,
} from '../../types/api';

const props = defineProps<{
  execution: CopilotExecutionSnapshot;
  isSending: boolean;
  isConfirming?: boolean;
  modelExecution?: CopilotModelExecutionData | null;
  trainingPending?: boolean;
  trainingLoading?: boolean;
  trainingLookupFailed?: boolean;
  chatRecommendation?: { stepId: string; result: ModelRecommendationResult };
}>();

const emit = defineEmits<{
  confirm: [req: CopilotConfirmRequest];
  'execute-evaluation': [];
  'refresh-model-training': [];
  'execute-optimization': [];
  'artifact-select': [stepId: string];
}>();

const streamRef = ref<HTMLElement | null>(null);
const isHydrating = ref(false);
const resumeNotice = ref('');

const isRunning = computed(() =>
  props.execution.workflow_status === 'RUNNING' ||
  props.execution.workflow_status === 'WAITING_ASYNC_TASK'
);

const currentToolName = computed(() => {
  const step = props.execution.step_runs.find(
    s => s.step_id === props.execution.current_step_id
  );
  return step?.tool ?? '';
});

function getPlanStep(stepId: string): ExecutionPlanStep | undefined {
  return props.execution.plan?.steps?.find(s => s.step_id === stepId);
}

const isModelSelectionWorkflow = computed(() =>
  props.execution.step_runs.some(step => step.tool === 'confirm_model_selection'),
);

function recommendationStepId(step: CopilotExecutionStepSnapshot): string | undefined {
  if (step.tool !== 'confirm_model_selection') return undefined;
  const reference = step.input_payload?.recommendation_step_id;
  return typeof reference === 'string' ? reference : undefined;
}

function recommendationFor(step: CopilotExecutionStepSnapshot): ModelRecommendationResult | undefined {
  const reference = recommendationStepId(step);
  if (!reference) return undefined;
  const recommendationStep = props.execution.step_runs.find(run =>
    run.tool === 'recommend_models' && run.step_id === reference && run.status === 'SUCCEEDED',
  );
  if (!recommendationStep) return undefined;
  return recommendationStep.result_payload?.recommendation ??
    (props.chatRecommendation?.stepId === reference ? props.chatRecommendation.result : undefined);
}

function lockedSelection(step: CopilotExecutionStepSnapshot): ConfirmedModelSelection | undefined {
  if (step.tool !== 'confirm_model_selection' || step.status !== 'SUCCEEDED' ||
      step.confirmation_status !== 'APPROVED') return undefined;
  return step.result_payload?.model_selection;
}

const lockedStep = computed(() => props.execution.step_runs.find(step => lockedSelection(step)));
const specGate = computed(() => props.execution.step_runs.find(step =>
  step.tool === 'recommend_models' && step.requires_confirmation && needsApproval(step.step_id),
));
const specRequirementMessage = computed(() => specGate.value?.result_payload?.spec_requirement?.message);
const needsRowOrder = computed(() => specGate.value?.result_payload?.spec_requirement?.field === 'row_order');
const specVersion = ref<DatasetVersionNode>();
const specDraft = ref<ModelRecommendationRequest | null>(null);
const versionError = ref('');
let versionRequest = 0;

async function loadSpecVersion() {
  const id = ++versionRequest;
  specVersion.value = undefined;
  specDraft.value = null;
  versionError.value = '';
  if (!specGate.value) return;
  const { dataset_id, current_version_id } = props.execution;
  try {
    const result = await getDatasetVersions(dataset_id);
    if (id !== versionRequest) return;
    if (result.dataset_id === dataset_id) {
      specVersion.value = result.nodes.find(version => version.id === current_version_id);
    }
    if (!specVersion.value) versionError.value = '无法找到当前处理后的数据版本。';
  } catch {
    if (id === versionRequest) versionError.value = '读取当前数据版本失败。';
  }
}
watch(
  [() => props.execution.execution_id, () => props.execution.current_version_id, () => specGate.value?.step_id],
  loadSpecVersion,
  { immediate: true },
);

function submitRowOrder() {
  const step = specGate.value;
  const version = specVersion.value;
  const execution = props.execution;
  if (props.isConfirming || !step || !needsRowOrder.value || !execution.copilot_run_id ||
      !version?.sha256 || version.id !== execution.current_version_id) return;
  emit('confirm', {
    execution_id: execution.execution_id, copilot_run_id: execution.copilot_run_id,
    confirmation_id: step.step_id, step_id: step.step_id, approved: true,
    row_order_confirmation: { dataset_version_id: version.id, csv_sha256: version.sha256 },
  });
}

function submitSpec() {
  const step = specGate.value;
  const request = specDraft.value;
  const execution = props.execution;
  if (props.isConfirming || !step || !execution.copilot_run_id || !request ||
      request.experiment_spec.dataset_version_id !== execution.current_version_id ||
      request.experiment_spec.dataset_id !== execution.dataset_id) return;
  emit('confirm', {
    execution_id: execution.execution_id, copilot_run_id: execution.copilot_run_id,
    confirmation_id: step.step_id, step_id: step.step_id, approved: true,
    recommendation_request: request,
  });
}

type TrainingStage = 'pending' | 'running' | 'succeeded' | 'failed' | 'skipped' | 'unconfirmed';
const trainingIcons = { pending: MoreFilled, running: Loading, succeeded: Check, failed: Close, skipped: Minus, unconfirmed: Warning };
const trainingModelName = computed(() => {
  const step = lockedStep.value;
  if (!step) return;
  const model = lockedSelection(step)?.model_type_id;
  return recommendationFor(step)?.candidates.find(candidate => candidate.model_type_id === model)?.model_name ?? model;
});
const trainingOverview = computed<{ state: TrainingStage; label: string }>(() => {
  const status = props.modelExecution;
  if (!status) {
    if (props.isConfirming) return { state: 'pending', label: '正在提交确认' };
    if (props.trainingPending || props.trainingLookupFailed) return { state: 'unconfirmed', label: '训练状态待核验' };
    return { state: 'pending', label: props.trainingLoading ? '正在读取训练状态' : '模型已确认，暂无训练任务' };
  }
  if (status.execution_status === 'pending') {
    return { state: 'pending', label: status.dispatch_status === 'queued' ? '已派发' : '等待派发' };
  }
  if (status.execution_status === 'unconfirmed' || status.training_status === 'unconfirmed' ||
      status.manifest_status === 'unconfirmed' || status.evaluation_status === 'unconfirmed' ||
      status.comparison_status === 'unconfirmed') {
    return { state: 'unconfirmed', label: '待人工核验' };
  }
  if (status.execution_status === 'failed' || status.training_status === 'failed' ||
      status.manifest_status === 'failed' || status.evaluation_status === 'failed' ||
      status.comparison_status === 'failed') {
    return { state: 'failed', label: '执行失败' };
  }
  return status.execution_status === 'succeeded'
    ? { state: 'succeeded', label: '执行完成' }
    : { state: 'running', label: '执行中' };
});
const trainingSteps = computed(() => {
  const status = props.modelExecution;
  const dispatch = status?.dispatch_status;
  const dispatched = dispatch === 'queued' || dispatch === 'started' ||
    (!!status && !dispatch && status.training_status !== 'pending');
  const training = status?.training_status ?? 'pending';
  const evaluation = status?.evaluation_status ?? 'pending';
  const comparison = status?.comparison_status ?? 'pending';
  const trainingLabels = { pending: '待开始', running: '正在训练', succeeded: '训练成功', failed: '训练失败', unconfirmed: '待人工核验' };
  const evaluationLabels = { pending: '待开始', running: '进行中', succeeded: '评价成功', failed: '评价失败', skipped: '已跳过', unconfirmed: '待人工核验' };
  const comparisonLabels = { pending: '待开始', succeeded: '比较完成', failed: '比较失败', skipped: '已跳过', unconfirmed: '待人工核验', not_comparable: '无可比结果' };
  return [
    { name: '任务派发', state: dispatched ? 'succeeded' : 'pending', label: dispatched ? '已派发' : dispatch === 'pending' ? '等待派发' : '待开始' },
    { name: '模型训练', state: training, label: trainingLabels[training] },
    { name: 'Validation 评价', state: evaluation, label: evaluationLabels[evaluation] },
    { name: '模型比较', state: comparison === 'not_comparable' ? 'skipped' : comparison, label: comparisonLabels[comparison] },
  ] satisfies Array<{ name: string; state: TrainingStage; label: string }>;
});
const trainingFailureMessage = computed(() => {
  const status = props.modelExecution;
  if (status?.training_status === 'failed') {
    if (status.training_error === 'PLATFORM_TRAINING_REJECTED') return '训练服务拒绝了本次输入，请核对建模配置和数据。';
    if (status.training_error === 'MODEL_EXECUTION_SELECTION_INVALID') return '已确认的模型或数据来源无法通过校验，请重新推荐。';
    return '模型训练失败，相关诊断见执行详情。';
  }
  if (status?.evaluation_status === 'failed') return 'Validation 评价失败，已训练的模型仍保留。';
  if (status?.comparison_status === 'failed') return '模型比较失败，训练和评价结果仍保留。';
});

function needsApproval(stepId: string): boolean {
  if (props.execution.pending_confirmation_step_id !== stepId) return false;
  const run = props.execution.step_runs.find(s => s.step_id === stepId);
  return run?.confirmation_status === 'PENDING';
}

const canExecuteEvaluation = computed(() => {
  const pending = props.execution.plan?.steps?.find(
    s => s.tool === 'evaluate_model' && props.execution.step_runs.find(r => r.step_id === s.step_id)?.status === 'PENDING'
  );
  return !!pending && props.execution.current_step_id === pending.step_id && props.execution.workflow_status === 'PLANNED';
});

const canExecuteOptimization = computed(() => {
  const pending = props.execution.plan?.steps?.find(
    s => s.tool === 'optimize_pipeline' && props.execution.step_runs.find(r => r.step_id === s.step_id)?.status === 'PENDING'
  );
  return !!pending && props.execution.current_step_id === pending.step_id && props.execution.workflow_status === 'PLANNED';
});

// Auto-scroll to bottom when new events arrive
watch(() => props.execution.step_runs.length, async () => {
  await nextTick();
  if (streamRef.value) {
    streamRef.value.scrollTop = streamRef.value.scrollHeight;
  }
});
</script>

<style scoped>
.agent-stream {
  flex: 1;
  overflow-y: auto;
  padding: 24px 28px 32px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  scroll-behavior: smooth;
  max-width: 760px;
  width: 100%;
  margin: 0 auto;
}

/* User Request */
.stream-user-request {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  background: #FFFFFF;
  border: 1px solid #E5E5E8;
  border-radius: 10px;
  padding: 14px 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
}

.stream-user-request__avatar {
  width: 26px;
  height: 26px;
  border-radius: 6px;
  background: #EDF4E9;
  border: 1px solid #D6E5D1;
  color: #426340;
  font-size: 11px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.stream-user-request__text {
  font-size: 14px;
  color: #171717;
  line-height: 1.55;
}

/* Compliance Badge */
.stream-compliance {
  display: flex;
  align-items: center;
  gap: 8px;
}

.compliance-badge {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 9999px;
  font-weight: 500;
}

.compliance-badge.ok {
  color: var(--success);
  background: var(--success-soft);
  border: 1px solid var(--color-success-border);
}

.compliance-badge.fail {
  color: var(--danger);
  background: var(--danger-soft);
  border: 1px solid var(--color-error-border);
}

.compliance-id {
  font-size: 11px;
  color: #8E8E93;
}

/* Events stream */
.stream-events {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* Running indicator */
.stream-running {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: #FFFFFF;
  border: 1px solid #E5E5E8;
  border-left: 2.5px solid var(--accent);
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
}

.stream-running__indicator {
  flex-shrink: 0;
}

.stream-running__text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.stream-running__tool {
  font-size: 12px;
  color: var(--accent);
  font-weight: 600;
}

.stream-running__desc {
  font-size: 12px;
  color: #8E8E93;
}

/* Action cards (manual trigger) */
.training-card {
  --training-ink: #56645d;
  --training-surface: #f0f3f1;
  padding: 16px;
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  background: var(--bg-card, white);
}
.training-card__header { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.training-card h3 { margin: 0; font-size: 14px; font-weight: 650; }
.training-card__model { margin: 4px 0 0; color: var(--text-secondary); font-size: 13px; }
.training-badge {
  flex-shrink: 0;
  padding: 2px 7px;
  border-radius: 5px;
  color: var(--training-ink);
  background: var(--training-surface);
  font-size: 12px;
  line-height: 1.6;
}
.training-card [data-state="succeeded"] { --training-ink: #24633f; --training-surface: #e9f4ec; }
.training-card [data-state="running"] { --training-ink: #17666b; --training-surface: #e6f3f2; }
.training-card [data-state="failed"] { --training-ink: #9c3c3a; --training-surface: #fceeed; }
.training-card [data-state="unconfirmed"] { --training-ink: #805616; --training-surface: #fff2db; }
.training-steps { list-style: none; margin: 14px 0 0; padding: 0; }
.training-step {
  position: relative;
  display: grid;
  grid-template-columns: 22px minmax(0, 1fr) auto;
  align-items: center;
  gap: 9px;
  min-height: 35px;
  font-size: 13px;
}
.training-step:not(:last-child)::after {
  content: '';
  position: absolute;
  left: 10px;
  top: calc(50% + 11px);
  bottom: calc(-50% + 11px);
  width: 1px;
  background: var(--border-subtle, #dfe6e1);
}
.training-step__icon {
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--training-surface);
  color: var(--training-ink);
}
.training-step__icon svg { width: 13px; height: 13px; }
.training-step[data-state="pending"] .training-step__name,
.training-step[data-state="skipped"] .training-step__name { color: var(--text-secondary); }
.training-step[data-state="running"] .training-step__name { font-weight: 650; }
.training-card__notice { margin: 10px 0 0; font-size: 12px; color: var(--text-secondary); }
.training-details { margin-top: 10px; border-top: 1px solid var(--border-subtle); padding-top: 10px; font-size: 12px; }
.training-details summary { cursor: pointer; color: var(--text-secondary); }
.training-details dl { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 5px 12px; margin: 8px 0 0; }
.training-details dt { color: var(--text-secondary); }
.training-details dd { margin: 0; overflow-wrap: anywhere; }
.training-card > button { margin-top: 10px; }

.stream-action-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 16px;
  background: #FFFFFF;
  border: 1px solid #E5E5E8;
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
}

.stream-action-card__title {
  font-size: 13px;
  font-weight: 600;
  color: #171717;
  margin-bottom: 2px;
}

.stream-action-card__desc {
  font-size: 12px;
  color: #666666;
}

.stream-action-card__btn {
  flex-shrink: 0;
  padding: 6px 14px;
  background: #426340;
  border: none;
  border-radius: 6px;
  color: #FFFFFF;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease;
}

.stream-action-card__btn:hover {
  background: #345032;
}

/* Conclusion */
.stream-conclusion {
  padding: 16px;
  background: #FFFFFF;
  border: 1px solid #E5E5E8;
  border-radius: 8px;
  border-left: 3px solid var(--success);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
}

.stream-conclusion__label {
  font-size: 11px;
  color: var(--success);
  letter-spacing: normal;
  font-family: var(--font-sans);
  margin-bottom: 8px;
  font-weight: 600;
}

.stream-conclusion__text {
  font-size: 13px;
  color: #171717;
  line-height: 1.6;
}

.stream-conclusion__assumptions {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #ECECED;
}

.stream-conclusion__assumptions-label {
  font-size: 11px;
  color: #8E8E93;
  letter-spacing: normal;
  font-family: var(--font-sans);
  margin-bottom: 8px;
  font-weight: 600;
}

.stream-conclusion__assumptions ul {
  padding-left: 16px;
}

.stream-conclusion__assumptions li {
  font-size: 12px;
  color: #666666;
  line-height: 1.6;
}

/* Notice banners */
.stream-notice {
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 12px;
}

.stream-notice.info {
  background: var(--info-soft);
  border: 1px solid var(--color-info-border);
  color: var(--info);
}

.stream-notice.warning {
  background: var(--warning-soft);
  border: 1px solid var(--color-warning-border);
  color: var(--warning);
}
</style>
