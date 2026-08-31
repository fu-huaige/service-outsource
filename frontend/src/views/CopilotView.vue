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

        <el-alert
          v-if="hydratingExecution"
          type="info"
          :closable="false"
          show-icon
          class="alert-gap"
          data-test="hydrating-execution"
        >
          <template #title>正在从 Backend 恢复 Agent Execution…</template>
        </el-alert>

        <el-alert
          v-if="resumeNotice"
          type="warning"
          :closable="false"
          show-icon
          class="alert-gap"
          data-test="resume-notice"
        >
          <template #title>{{ resumeNotice }}</template>
        </el-alert>

        <el-alert v-if="errorMessage" type="error" :closable="false" show-icon class="alert-gap">
          <template #title>执行失败：{{ errorMessage }}</template>
        </el-alert>
      </div>

      <template v-if="result">
        <div v-if="result.compliance" class="industrial-card">
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
                    ? result.llm_provider && result.llm_model
                      ? `大模型编排 · ${result.llm_provider}/${result.llm_model}`
                      : "大模型编排"
                    : "确定性规则编排"
                }}
              </el-tag>
              <el-tag :type="result.executed ? 'success' : 'info'">
                {{ result.executed ? "已执行" : "仅生成计划" }}
              </el-tag>
            </div>
          </div>

          <div v-if="result.execution_id" class="execution-state">
            <span data-test="execution-id">Execution {{ result.execution_id }}</span>
            <span data-test="workflow-status">Workflow {{ result.workflow_status }}</span>
            <span data-test="current-version-id">Version {{ result.current_version_id }}</span>
          </div>

          <el-alert
            v-if="historicalConfirmationUnavailable"
            type="warning"
            :closable="false"
            show-icon
            class="alert-gap"
            data-test="historical-confirmation-unavailable"
          >
            <template #title>
              这是历史 Agent Execution，缺少继续确认所需的 Copilot run 关联；可以查看结果，但不能提交确认。
            </template>
            <button
              type="button"
              disabled
              class="historical-confirmation-disabled"
              data-test="historical-confirmation-disabled"
            >
              历史确认不可用
            </button>
          </el-alert>

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
                  <p v-if="isArxFitStep(step.step_id) && arxModelId(step.step_id)" :data-test="'arx-model-id-' + step.step_id">
                    ARX 建模完成 · Model {{ arxModelId(step.step_id) }}
                  </p>
                  <p v-if="runFor(step.step_id)?.duration_ms != null" class="step-timing">
                    耗时 {{ (runFor(step.step_id)?.duration_ms ?? 0).toFixed(1) }} ms
                  </p>
                  <p
                    v-if="confirmationMessage(step.step_id)"
                    class="confirmation-message"
                    :data-test="'confirmation-status-' + step.step_id"
                  >
                    {{ confirmationMessage(step.step_id) }}
                  </p>
                  <div
                    v-if="canConfirm(step.step_id)"
                    class="confirmation-actions"
                    :data-test="'confirm-actions-' + step.step_id"
                  >
                    <template v-if="isLagApplyStep(step.step_id)">
                      <el-button
                        size="small"
                        :data-test="'edit-lag-' + step.step_id"
                        @click="openLagOverrides(step.step_id)"
                      >
                        修改参数
                      </el-button>
                      <el-dialog
                        v-if="editingLagStepId === step.step_id"
                        v-model="lagDialogVisible"
                        width="600px"
                        :close-on-click-modal="false"
                        :data-test="'lag-overrides-' + step.step_id"
                        @closed="closeLagOverrides"
                      >
                        <template #header>
                          <div class="lag-dialog-header">
                            <h3>修改时滞补偿参数</h3>
                            <p>调整 Agent 推荐的输入时滞，确认执行前可先验证参数。</p>
                          </div>
                        </template>
                        <div class="lag-dialog-body">
                          <el-alert type="info" :closable="false" show-icon class="lag-recommendation" :data-test="'lag-recommendation-' + step.step_id">
                            <template #title>
                              Delay Analyze 建议： {{ formattedLagRecommendation(step.step_id) }}
                            </template>
                          </el-alert>
                          <div class="lag-override-heading">人工覆盖参数</div>
                          <div class="lag-override-labels" aria-hidden="true">
                            <span>参数</span>
                            <span>时滞 nk</span>
                            <span>操作</span>
                          </div>
                          <div
                            v-for="(override, index) in lagOverrideDraftRows"
                            :key="`${index}-${override.variable}`"
                            class="lag-override-row"
                          >
                            <el-select
                              v-model="override.variable"
                              :data-test="'lag-variable-' + index"
                              @change="syncLagOverrideValue(index, step.step_id)"
                            >
                              <el-option
                                v-for="variable in lagVariables(step.step_id)"
                                :key="variable"
                                :label="variable"
                                :value="variable"
                                :disabled="isLagVariableDisabled(variable, index)"
                              />
                            </el-select>
                            <el-input-number
                              v-model="override.value"
                              :min="0"
                              :precision="0"
                              :step="1"
                              :data-test="'lag-value-' + index"
                            />
                            <el-button size="small" :data-test="'remove-lag-override-' + index" @click="removeLagOverride(index)">
                              删除
                            </el-button>
                          </div>
                          <el-button
                            size="small"
                            :disabled="lagOverrideDraftRows.length >= lagVariables(step.step_id).length"
                            :data-test="'add-lag-override-' + step.step_id"
                            @click="addLagOverride(step.step_id)"
                          >
                            添加参数
                          </el-button>
                          <el-alert
                            v-if="lagDraftValidation"
                            :type="lagDraftValidation.overall_status === 'INVALID' ? 'error' : lagDraftValidation.overall_status === 'WARNING' ? 'warning' : 'success'"
                            :closable="false"
                            show-icon
                            class="lag-validation"
                            :data-test="'lag-validation-' + step.step_id"
                          >
                            <template #title>
                              校验：{{ lagDraftValidation.overall_status }} {{ lagDraftValidation.issues.join("；") }}
                            </template>
                          </el-alert>
                        </div>
                        <template #footer>
                          <div class="lag-dialog-footer">
                            <el-button :data-test="'cancel-lag-' + step.step_id" @click="closeLagOverrides">取消</el-button>
                            <el-button
                              type="primary"
                              :loading="validatingLagStepId === step.step_id"
                              :data-test="'validate-lag-' + step.step_id"
                              @click="validateLagOverrideDraftRows(step.step_id)"
                            >
                              验证参数
                            </el-button>
                          </div>
                        </template>
                      </el-dialog>
                      <el-button
                        type="primary"
                        size="small"
                        :loading="confirmingStepId === step.step_id"
                        :data-test="'approve-' + step.step_id"
                        @click="handleLagApproval(step.step_id)"
                      >
                        Approve
                      </el-button>
                      <el-button
                        v-if="lagValidation?.overall_status === 'WARNING'"
                        type="warning"
                        size="small"
                        :loading="confirmingStepId === step.step_id"
                        :data-test="'ack-lag-warning-' + step.step_id"
                        @click="handleLagApproval(step.step_id, true)"
                      >
                        确认警告并执行
                      </el-button>
                    </template>
                    <template v-else-if="isArxFitStep(step.step_id)">
                      <div class="arx-recommendation" :data-test="'arx-recommendation-' + step.step_id">
                        <p>ARX 结构推荐</p>
                        <p :data-test="'arx-na-' + step.step_id">na：{{ arxRecommendation(step.step_id).recommended_na }}</p>
                        <p v-for="(value, variable) in arxRecommendedNb(step.step_id)" :key="variable" :data-test="'arx-nb-' + variable">
                          nb · {{ variable }}：{{ value }}
                        </p>
                        <p v-for="(value, variable) in arxRecommendedDelays(step.step_id)" :key="'delay-' + variable" :data-test="'arx-delay-' + variable">
                          delay · {{ variable }}：{{ value }}（只读）
                        </p>
                        <p :data-test="'arx-delay-provenance-' + step.step_id">
                          delay 来源：{{ arxRecommendation(step.step_id).delay_source }}
                        </p>
                        <p :data-test="'arx-evidence-' + step.step_id">
                          推荐依据：{{ JSON.stringify(arxRecommendation(step.step_id).selection_evidence) }}
                        </p>
                      </div>
                      <el-button
                        type="primary"
                        size="small"
                        :loading="confirmingStepId === step.step_id"
                        :data-test="'adopt-arx-' + step.step_id"
                        @click="adoptArxRecommendation(step.step_id)"
                      >
                        采用推荐参数
                      </el-button>
                      <el-button size="small" :data-test="'edit-arx-' + step.step_id" @click="openArxOverrides(step.step_id)">
                        修改参数
                      </el-button>
                      <el-dialog v-if="editingArxStepId === step.step_id" v-model="arxDialogVisible" title="修改 ARX 参数" :data-test="'arx-overrides-' + step.step_id">
                        <label>
                          na
                          <input v-model.number="arxNa" type="number" min="1" step="1" :data-test="'arx-na-input-' + step.step_id" />
                        </label>
                        <label v-for="variable in arxInputColumns(step.step_id)" :key="variable">
                          nb · {{ variable }}
                          <input v-model.number="arxNb[variable]" type="number" min="1" step="1" :data-test="'arx-nb-input-' + variable" />
                        </label>
                        <el-button size="small" :loading="validatingArxStepId === step.step_id" :data-test="'validate-arx-' + step.step_id" @click="validateArxOverrides(step.step_id)">
                          验证参数
                        </el-button>
                        <p v-if="arxValidation" :data-test="'arx-validation-' + step.step_id">
                          校验：{{ arxValidation.overall_status }} {{ arxValidation.issues.join("；") }}
                        </p>
                        <el-button
                          v-if="arxValidation?.overall_status === 'VALID'"
                          type="primary"
                          size="small"
                          :loading="confirmingStepId === step.step_id"
                          :data-test="'confirm-arx-' + step.step_id"
                          @click="confirmArxOverrides(step.step_id)"
                        >
                          确认并建模
                        </el-button>
                      </el-dialog>
                    </template>
                    <template v-else-if="isFeatureApplyStep(step.step_id)">
                      <p class="feature-recommendation" :data-test="'feature-recommendation-' + step.step_id">
                        系统 Feature selection recommendation
                      </p>
                      <div class="feature-recommendation-list">
                        <p
                          v-for="item in featureRecommendationRows(step.step_id)"
                          :key="item.variable"
                          :data-test="'feature-variable-' + item.variable"
                        >
                          {{ item.variable }} · {{ item.action }} · {{ item.reason }}
                        </p>
                      </div>
                      <el-button
                        size="small"
                        :data-test="'edit-feature-' + step.step_id"
                        @click="openFeatureSelection(step.step_id)"
                      >
                        调整变量
                      </el-button>
                      <div
                        v-if="editingFeatureStepId === step.step_id"
                        class="feature-selection-options"
                        :data-test="'feature-selection-' + step.step_id"
                      >
                        <label
                          v-for="item in featureRecommendationRows(step.step_id)"
                          :key="item.variable"
                        >
                          <input
                            v-model="featureDropColumns"
                            type="checkbox"
                            :value="item.variable"
                            :data-test="'feature-drop-' + item.variable"
                          />
                          删除 {{ item.variable }}
                        </label>
                        <p v-if="featureValidation" class="feature-validation">
                          校验：{{ featureValidation.overall_status }}
                          {{ featureValidation.issues.join("；") }}
                        </p>
                      </div>
                      <el-button
                        type="primary"
                        size="small"
                        :loading="confirmingStepId === step.step_id"
                        :data-test="'approve-' + step.step_id"
                        @click="handleFeatureApproval(step.step_id)"
                      >
                        {{ editingFeatureStepId === step.step_id ? "应用调整" : "批准建议" }}
                      </el-button>
                    </template>
                    <el-button
                      v-else
                      type="primary"
                      size="small"
                      :loading="confirmingStepId === step.step_id"
                      :data-test="'approve-' + step.step_id"
                      @click="handleConfirmation(step.step_id, true)"
                    >
                      Approve
                    </el-button>
                    <el-button
                      size="small"
                      :disabled="confirmingStepId === step.step_id"
                      :data-test="'reject-' + step.step_id"
                      @click="handleConfirmation(step.step_id, false)"
                    >
                      Reject
                    </el-button>
                  </div>
                </div>
                <div v-if="canExecutePipelineOptimization(step.step_id)" class="optimization-actions">
                  <el-button
                    type="primary"
                    size="small"
                    :loading="executingOptimizationStepId === step.step_id"
                    :disabled="executingOptimizationStepId !== null"
                    :data-test="'execute-optimization-' + step.step_id"
                    @click="executePipelineOptimizationStep(step.step_id)"
                  >
                    执行模型优化
                  </el-button>
                </div>
                <p
                  v-if="isOptimizationStep(step.step_id) && step.status === 'failed' && optimizationFailure(step.step_id)"
                  class="step-error"
                  :data-test="'optimization-error-' + step.step_id"
                >
                  模型优化失败：{{ optimizationFailure(step.step_id) }}
                </p>
                <div
                  v-if="isOptimizationStep(step.step_id) && step.status === 'completed' && optimizationResult(step.step_id)"
                  class="optimization-results"
                  :data-test="'optimization-results-' + step.step_id"
                >
                  <p class="optimization-title">模型优化结果</p>
                  <div class="optimization-summary">
                    <div class="optimization-item">
                      <span>最佳综合目标值</span>
                      <strong>{{ formatOptimizationObjective(optimizationResult(step.step_id)?.best_value) }}</strong>
                    </div>
                    <div class="optimization-item">
                      <span>优化模型 ID</span>
                      <strong class="code-inline">{{ optimizationResult(step.step_id)?.optimized_model_id }}</strong>
                    </div>
                  </div>
                  <p class="optimization-params-title">最优参数</p>
                  <div class="optimization-params-grid">
                    <div
                      v-for="(value, key) in optimizationResult(step.step_id)?.best_params"
                      :key="String(key)"
                      class="optimization-item"
                    >
                      <span>{{ String(key) }}</span>
                      <strong class="code-inline">{{ formatOptimizationParameter(value) }}</strong>
                    </div>
                  </div>
                </div>
                <div v-if="canExecuteModelEvaluation(step.step_id)" class="evaluation-actions">
                  <el-button
                    type="primary"
                    size="small"
                    :loading="executingEvaluationStepId === step.step_id"
                    :disabled="executingEvaluationStepId !== null"
                    :data-test="'execute-evaluation-' + step.step_id"
                    @click="executeModelEvaluationStep(step.step_id)"
                  >
                    执行模型评价
                  </el-button>
                </div>
                <p
                  v-if="isEvaluationStep(step.step_id) && step.status === 'failed' && evaluationFailure(step.step_id)"
                  class="step-error"
                  :data-test="'evaluation-error-' + step.step_id"
                >
                  模型评价失败：{{ evaluationFailure(step.step_id) }}
                </p>
                <div
                  v-if="isEvaluationStep(step.step_id) && step.status === 'completed' && evaluationResult(step.step_id)"
                  class="evaluation-results"
                  :data-test="'evaluation-results-' + step.step_id"
                >
                  <p class="evaluation-title">模型评价结果</p>
                  <div class="evaluation-groups">
                    <section class="evaluation-group" :data-test="'evaluation-one-step-' + step.step_id">
                      <h4>Test 一步预测</h4>
                      <div class="evaluation-metrics-grid">
                        <div class="evaluation-metric"><span>FIT</span><strong>{{ pct(evaluationResult(step.step_id)?.test.one_step.fit) }}</strong></div>
                        <div class="evaluation-metric"><span>R²</span><strong>{{ num(evaluationResult(step.step_id)?.test.one_step.r2) }}</strong></div>
                        <div class="evaluation-metric"><span>RMSE</span><strong>{{ num(evaluationResult(step.step_id)?.test.one_step.rmse) }}</strong></div>
                        <div class="evaluation-metric"><span>MAE</span><strong>{{ num(evaluationResult(step.step_id)?.test.one_step.mae) }}</strong></div>
                        <div class="evaluation-metric"><span>NRMSE</span><strong>{{ num(evaluationResult(step.step_id)?.test.one_step.nrmse) }}</strong></div>
                      </div>
                    </section>
                    <section class="evaluation-group" :data-test="'evaluation-free-run-' + step.step_id">
                      <h4>Test 自由仿真</h4>
                      <div class="evaluation-metrics-grid">
                        <div class="evaluation-metric"><span>FIT</span><strong>{{ pct(evaluationResult(step.step_id)?.test.free_run.fit) }}</strong></div>
                        <div class="evaluation-metric"><span>R²</span><strong>{{ num(evaluationResult(step.step_id)?.test.free_run.r2) }}</strong></div>
                        <div class="evaluation-metric"><span>RMSE</span><strong>{{ num(evaluationResult(step.step_id)?.test.free_run.rmse) }}</strong></div>
                        <div class="evaluation-metric"><span>MAE</span><strong>{{ num(evaluationResult(step.step_id)?.test.free_run.mae) }}</strong></div>
                        <div class="evaluation-metric"><span>NRMSE</span><strong>{{ num(evaluationResult(step.step_id)?.test.free_run.nrmse) }}</strong></div>
                      </div>
                    </section>
                  </div>
                </div>              </template>
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
import { computed, onMounted, reactive, ref, watch } from "vue";
import {
  ChatDotRound,
  CircleCheck,
  CircleClose,
  Document,
  InfoFilled,
  Promotion,
  Share,
} from "@element-plus/icons-vue";
import {
  chatWithCopilot,
  confirmCopilotStep,
  executePipelineOptimization,
  executeModelEvaluation,
  getCopilotExecution,
  validateArxStructure,
  validateFeatureSelection,
  validateLagOverrides,
} from "../api/copilot";
import type {
  ArxStructureManualOverrides,
  ArxStructureValidationResponse,
  AgentConfirmationStatus,
  AgentOptimizationResult,
  AgentStepStatus,
  CopilotChatRequest,
  CopilotChatResponse,
  CopilotExecutionSnapshot,
  PredictionMetrics,
  SavedArxEvaluationResult,
  FeatureSelectionAction,
  FeatureSelectionValidationResponse,
  LagManualOverride,
  LagOverrideValidationResponse,
} from "../types/api";
import { ApiError } from "../api/client";
import { useRoute, useRouter, type LocationQueryRaw } from "vue-router";
import { useCopilotExecutionStore } from "../stores/copilotExecution";
import { ElMessage } from "element-plus";

const route = useRoute();
const router = useRouter();
const executionStore = useCopilotExecutionStore();

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
  cancelled: "已取消",
};

const prompt = ref("");
const sending = ref(false);
const confirmingStepId = ref<string | null>(null);
const executingOptimizationStepId = ref<string | null>(null);
const executingEvaluationStepId = ref<string | null>(null);
const validatingLagStepId = ref<string | null>(null);
const editingLagStepId = ref<string | null>(null);
const lagDialogVisible = ref(false);
const lagOverrideRows = ref<LagManualOverride[]>([]);
const lagOverrideDraftRows = ref<LagManualOverride[]>([]);
const lagValidation = ref<LagOverrideValidationResponse | null>(null);
const lagDraftValidation = ref<LagOverrideValidationResponse | null>(null);
const editingFeatureStepId = ref<string | null>(null);
const featureDropColumns = ref<string[]>([]);
const featureValidation = ref<FeatureSelectionValidationResponse | null>(null);
const validatingArxStepId = ref<string | null>(null);
const editingArxStepId = ref<string | null>(null);
const arxDialogVisible = ref(false);
const arxNa = ref<number | null>(null);
const arxNb = ref<Record<string, number>>({});
const arxValidation = ref<ArxStructureValidationResponse | null>(null);
const errorMessage = ref("");
const resumeNotice = ref("");
const hydratingExecution = ref(false);
const result = ref<CopilotChatResponse | null>(null);
const confirmationStatuses = reactive<Record<string, AgentConfirmationStatus>>({});

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
    const response = await chatWithCopilot({
      message: prompt.value.trim(),
      active_version_id: form.active_version_id || null,
    });
    for (const stepId of Object.keys(confirmationStatuses)) {
      delete confirmationStatuses[stepId];
    }
    editingLagStepId.value = null;
    lagDialogVisible.value = false;
    lagOverrideRows.value = [];
    lagOverrideDraftRows.value = [];
    lagValidation.value = null;
    lagDraftValidation.value = null;
    editingFeatureStepId.value = null;
    featureDropColumns.value = [];
    featureValidation.value = null;
    validatingArxStepId.value = null;
    editingArxStepId.value = null;
    arxDialogVisible.value = false;
    arxNa.value = null;
    arxNb.value = {};
    arxValidation.value = null;
    result.value = response;
    resumeNotice.value = "";
    if (response.execution_id) {
      await activateExecution(response.execution_id);
    } else {
      executionStore.clearActiveExecutionId();
      await replaceExecutionQuery(null);
    }
    ElMessage.success(response.conclusion);
  } catch (err) {
    result.value = null;
    errorMessage.value = err instanceof ApiError ? err.message : String(err);
  } finally {
    sending.value = false;
  }
};

const persistentStepStatus = (status: string): AgentStepStatus => {
  const statuses: Record<string, AgentStepStatus> = {
    PENDING: "pending",
    RUNNING: "running",
    WAITING_CONFIRMATION: "waiting_confirmation",
    SUCCEEDED: "completed",
    FAILED: "failed",
    CANCELLED: "cancelled",
  };
  return statuses[status] ?? "pending";
};


const queryExecutionId = (): string | null => {
  const value = route.query.execution_id;
  const raw = Array.isArray(value) ? value[0] : value;
  return typeof raw === "string" && raw.trim() ? raw.trim() : null;
};

const replaceExecutionQuery = async (executionId: string | null) => {
  const query: LocationQueryRaw = { ...route.query };
  if (executionId) query.execution_id = executionId;
  else delete query.execution_id;
  await router.replace({ query });
};

const snapshotToChatResponse = (snapshot: CopilotExecutionSnapshot): CopilotChatResponse => {
  const stepRuns = new Map(snapshot.step_runs.map((step) => [step.step_id, step]));
  const plan = {
    ...snapshot.plan,
    steps: snapshot.plan.steps.map((step) => ({
      ...step,
      status: persistentStepStatus(stepRuns.get(step.step_id)?.status ?? step.status),
    })),
  };
  return {
    copilot_run_id: snapshot.copilot_run_id,
    execution_id: snapshot.execution_id,
    workflow_status: snapshot.workflow_status,
    current_version_id: snapshot.current_version_id,
    pending_confirmation_step_id: snapshot.pending_confirmation_step_id,
    plan,
    task: null,
    compliance: null,
    step_runs: snapshot.step_runs.map((step) => ({
      step_id: step.step_id,
      tool: step.tool,
      status: persistentStepStatus(step.status),
      parameters:
        typeof step.input_payload.parameters === "object" && step.input_payload.parameters !== null
          ? step.input_payload.parameters as Record<string, any>
          : {},
      summary: "",
      result: step.result_payload,
      duration_ms: null,
      error_code: step.error_code,
      error_message: step.error_message,
      processing_run_ids: step.processing_run_ids,
      input_payload: step.input_payload,
      source_version_id: step.source_version_id,
      result_version_id: step.result_version_id,
      confirmation_status: step.confirmation_status as AgentConfirmationStatus,
      attempt_count: step.attempt_count,
      started_at: step.started_at,
      finished_at: step.finished_at,
    })),
    conclusion: snapshot.error_message ?? "",
    executed: snapshot.step_runs.some((step) => step.status !== "PENDING"),
    plan_source: snapshot.planner_source === "llm" ? "llm" : "rule_based",
    llm_provider: "",
    llm_model: "",
    llm_fallback_reason: null,
  };
};

const syncConfirmationStatuses = (snapshot: CopilotExecutionSnapshot) => {
  for (const stepId of Object.keys(confirmationStatuses)) delete confirmationStatuses[stepId];
  for (const step of snapshot.step_runs) {
    if (["NOT_REQUIRED", "PENDING", "APPROVED", "REJECTED"].includes(step.confirmation_status)) {
      confirmationStatuses[step.step_id] = step.confirmation_status as AgentConfirmationStatus;
    }
  }
};

const isInvalidExecutionReference = (error: unknown) =>
  error instanceof ApiError &&
  ["AGENT_EXECUTION_NOT_FOUND", "HTTP_404", "HTTP_422"].includes(error.code);

let hydrationRequest = 0;
const hydrateExecution = async (executionId: string) => {
  const request = ++hydrationRequest;
  hydratingExecution.value = true;
  errorMessage.value = "";
  try {
    const snapshot = await getCopilotExecution(executionId);
    if (request !== hydrationRequest) return;
    result.value = snapshotToChatResponse(snapshot);
    syncConfirmationStatuses(snapshot);
    form.active_version_id = snapshot.current_version_id;
    executionStore.setActiveExecutionId(snapshot.execution_id);
    resumeNotice.value = "";
  } catch (error) {
    if (request !== hydrationRequest) return;
    if (isInvalidExecutionReference(error)) {
      result.value = null;
      executionStore.clearActiveExecutionId();
      await replaceExecutionQuery(null);
      resumeNotice.value = "未找到指定的 Agent Execution，已清除失效的恢复标识，可以创建新任务。";
    } else {
      errorMessage.value = error instanceof ApiError ? error.message : String(error);
    }
  } finally {
    if (request === hydrationRequest) hydratingExecution.value = false;
  }
};

const activateExecution = async (executionId: string) => {
  executionStore.setActiveExecutionId(executionId);
  await replaceExecutionQuery(executionId);
};

const refreshCurrentExecution = async () => {
  const executionId = result.value?.execution_id ?? executionStore.activeExecutionId;
  if (executionId) await hydrateExecution(executionId);
};

let mounted = false;
onMounted(async () => {
  const routeExecutionId = queryExecutionId();
  const executionId = routeExecutionId ?? executionStore.activeExecutionId;
  if (executionId) {
    executionStore.setActiveExecutionId(executionId);
    if (!routeExecutionId) await replaceExecutionQuery(executionId);
    await hydrateExecution(executionId);
  }
  mounted = true;
});

watch(
  () => route.query.execution_id,
  async () => {
    if (!mounted) return;
    const routeExecutionId = queryExecutionId();
    const executionId = routeExecutionId ?? executionStore.activeExecutionId;
    if (!executionId) return;
    executionStore.setActiveExecutionId(executionId);
    if (!routeExecutionId) await replaceExecutionQuery(executionId);
    await hydrateExecution(executionId);
  }
);

const historicalConfirmationUnavailable = computed(
  () => result.value?.workflow_status === "WAITING_CONFIRMATION" && !result.value.copilot_run_id
);

const canConfirm = (stepId: string) =>
  Boolean(
    result.value?.execution_id &&
      result.value.copilot_run_id &&
      result.value.workflow_status === "WAITING_CONFIRMATION" &&
      result.value.pending_confirmation_step_id === stepId
  );

const confirmationMessage = (stepId: string) => {
  const status = confirmationStatuses[stepId];
  if (status === "APPROVED") {
    return result.value?.plan.steps.find((step) => step.step_id === stepId)?.status === "completed"
      ? "已批准并执行完成"
      : "已批准，等待执行";
  }
  if (status === "REJECTED") return "已拒绝";
  return "";
};

const isLagApplyStep = (stepId: string) =>
  result.value?.plan.steps.find((step) => step.step_id === stepId)?.tool === "apply_lag_compensation";

const isFeatureApplyStep = (stepId: string) =>
  result.value?.plan.steps.find((step) => step.step_id === stepId)?.tool === "select_variables";

const isArxFitStep = (stepId: string) =>
  result.value?.plan.steps.find((step) => step.step_id === stepId)?.tool === "fit_arx";

const preparedStepValue = (stepId: string, key: string): unknown => {
  const run = runFor(stepId);
  return run?.result?.[key] ?? run?.input_payload?.[key];
};
const arxRecommendation = (stepId: string): Record<string, any> => {
  const recommendation = preparedStepValue(stepId, "arx_structure_recommendation");
  return recommendation && typeof recommendation === "object" && !Array.isArray(recommendation)
    ? recommendation as Record<string, any>
    : {};
};

const arxRecommendedNb = (stepId: string): Record<string, number> => {
  const values = arxRecommendation(stepId).recommended_nb;
  return values && typeof values === "object" && !Array.isArray(values)
    ? values as Record<string, number>
    : {};
};

const arxRecommendedDelays = (stepId: string): Record<string, number> => {
  const values = arxRecommendation(stepId).recommended_delays;
  return values && typeof values === "object" && !Array.isArray(values)
    ? values as Record<string, number>
    : {};
};

const arxInputColumns = (stepId: string) => Object.keys(arxRecommendedNb(stepId));

const arxModelId = (stepId: string) => {
  const modelId = runFor(stepId)?.result?.model_id;
  return typeof modelId === "string" ? modelId : null;
};

const openArxOverrides = (stepId: string) => {
  const recommendation = arxRecommendation(stepId);
  editingArxStepId.value = stepId;
  arxDialogVisible.value = true;
  arxNa.value = Number(recommendation.recommended_na);
  arxNb.value = { ...arxRecommendedNb(stepId) };
  arxValidation.value = null;
};

const selectedArxOverrides = (stepId: string): ArxStructureManualOverrides => {
  const recommendation = arxRecommendation(stepId);
  const recommendedNb = arxRecommendedNb(stepId);
  const overrides: ArxStructureManualOverrides = {};
  if (arxNa.value !== null && arxNa.value !== Number(recommendation.recommended_na)) {
    overrides.na = arxNa.value;
  }
  const changedNb = Object.fromEntries(
    Object.entries(arxNb.value).filter(([column, value]) => value !== recommendedNb[column])
  );
  if (Object.keys(changedNb).length) overrides.nb = changedNb;
  return overrides;
};

const validateArxOverrides = async (stepId: string) => {
  const current = result.value;
  if (!current?.execution_id || !canConfirm(stepId) || validatingArxStepId.value) return null;

  errorMessage.value = "";
  validatingArxStepId.value = stepId;
  try {
    const validation = await validateArxStructure({
      execution_id: current.execution_id,
      step_id: stepId,
      manual_overrides: selectedArxOverrides(stepId),
    });
    arxValidation.value = validation;
    return validation;
  } catch (err) {
    errorMessage.value = err instanceof ApiError ? err.message : String(err);
    return null;
  } finally {
    validatingArxStepId.value = null;
  }
};

const adoptArxRecommendation = async (stepId: string) => {
  await submitConfirmation(stepId, true, [], false, undefined, {});
};

const confirmArxOverrides = async (stepId: string) => {
  if (arxValidation.value?.overall_status !== "VALID") return;
  await submitConfirmation(stepId, true, [], false, undefined, selectedArxOverrides(stepId));
};

const featureRecommendation = (stepId: string): Record<string, FeatureSelectionAction> => {
  const recommended = preparedStepValue(stepId, "recommended_selection");
  return recommended && typeof recommended === "object"
    ? recommended as Record<string, FeatureSelectionAction>
    : {};
};

const featureRecommendationEvidence = (stepId: string): Record<string, Record<string, unknown>> => {
  const evidence = preparedStepValue(stepId, "recommendation_evidence");
  return evidence && typeof evidence === "object"
    ? evidence as Record<string, Record<string, unknown>>
    : {};
};

const featureRecommendationRows = (stepId: string) =>
  Object.entries(featureRecommendation(stepId)).map(([variable, action]) => ({
    variable,
    action,
    reason: String(featureRecommendationEvidence(stepId)[variable]?.reason ?? ""),
  }));

const recommendedFeatureDrops = (stepId: string) =>
  Object.entries(featureRecommendation(stepId))
    .filter(([, action]) => action === "drop")
    .map(([variable]) => variable);

const openFeatureSelection = (stepId: string) => {
  editingFeatureStepId.value = stepId;
  featureDropColumns.value = recommendedFeatureDrops(stepId);
  featureValidation.value = null;
};

const recommendedLagMap = (stepId: string): Record<string, number> => {
  const suggested = preparedStepValue(stepId, "recommended_lag_map");
  return suggested && typeof suggested === "object" ? suggested as Record<string, number> : {};
};

const lagVariables = (stepId: string) => Object.keys(recommendedLagMap(stepId));

const formattedLagRecommendation = (stepId: string) =>
  Object.entries(recommendedLagMap(stepId))
    .map(([variable, value]) => `${variable}:${value}`)
    .join("; ");

const selectedLagOverrides = (rows: LagManualOverride[] = lagOverrideRows.value): LagManualOverride[] =>
  rows.map((row) => ({ ...row }));

const closeLagOverrides = () => {
  lagDialogVisible.value = false;
  editingLagStepId.value = null;
  lagOverrideDraftRows.value = [];
  lagDraftValidation.value = null;
};

const openLagOverrides = (stepId: string) => {
  editingLagStepId.value = stepId;
  lagOverrideDraftRows.value = selectedLagOverrides();
  lagDraftValidation.value = null;
  if (!lagOverrideDraftRows.value.length) addLagOverride(stepId);
  lagDialogVisible.value = true;
};

const isLagVariableDisabled = (variable: string, currentIndex: number) =>
  lagOverrideDraftRows.value.some(
    (row, index) => index !== currentIndex && row.variable === variable
  );

const syncLagOverrideValue = (index: number, stepId: string) => {
  const row = lagOverrideDraftRows.value[index];
  if (!row) return;
  row.value = recommendedLagMap(stepId)[row.variable];
  lagDraftValidation.value = null;
};

const addLagOverride = (stepId: string) => {
  const selected = new Set(lagOverrideDraftRows.value.map((row) => row.variable));
  const variable = lagVariables(stepId).find((candidate) => !selected.has(candidate));
  if (!variable) return;
  lagOverrideDraftRows.value.push({ variable, value: recommendedLagMap(stepId)[variable] });
  lagDraftValidation.value = null;
};

const removeLagOverride = (index: number) => {
  lagOverrideDraftRows.value.splice(index, 1);
  lagDraftValidation.value = null;
};

const validateLagOverridesForRows = async (stepId: string, rows: LagManualOverride[]) => {
  const current = result.value;
  if (!current?.execution_id || !canConfirm(stepId) || validatingLagStepId.value) return null;

  errorMessage.value = "";
  validatingLagStepId.value = stepId;
  try {
    return await validateLagOverrides({
      execution_id: current.execution_id,
      step_id: stepId,
      manual_overrides: selectedLagOverrides(rows),
    });
  } catch (err) {
    errorMessage.value = err instanceof ApiError ? err.message : String(err);
    return null;
  } finally {
    validatingLagStepId.value = null;
  }
};

const validateLagOverrideRows = async (stepId: string) => {
  const validation = await validateLagOverridesForRows(stepId, lagOverrideRows.value);
  if (validation) lagValidation.value = validation;
  return validation;
};

const validateLagOverrideDraftRows = async (stepId: string) => {
  const validation = await validateLagOverridesForRows(stepId, lagOverrideDraftRows.value);
  if (!validation) return null;

  lagDraftValidation.value = validation;
  if (validation.overall_status !== "INVALID") {
    lagOverrideRows.value = selectedLagOverrides(lagOverrideDraftRows.value);
    lagValidation.value = validation;
    closeLagOverrides();
  }
  return validation;
};
const submitConfirmation = async (
  stepId: string,
  approved: boolean,
  manualOverrides: LagManualOverride[] = [],
  warningAcknowledged = false,
  selectedFeatureDrops?: string[],
  arxStructureOverrides?: ArxStructureManualOverrides,
) => {
  const current = result.value;
  if (!current?.execution_id || !current.copilot_run_id || !canConfirm(stepId) || confirmingStepId.value) return;

  errorMessage.value = "";
  confirmingStepId.value = stepId;
  try {
    const confirmed = await confirmCopilotStep({
      copilot_run_id: current.copilot_run_id,
      confirmation_id: stepId,
      execution_id: current.execution_id,
      step_id: stepId,
      approved,
      manual_overrides: manualOverrides,
      warning_acknowledged: warningAcknowledged,
      feature_drop_columns: selectedFeatureDrops,
      arx_structure_overrides: arxStructureOverrides,
    });

    current.workflow_status = confirmed.workflow_status;
    current.current_version_id = confirmed.current_version_id ?? current.current_version_id;
    current.pending_confirmation_step_id = confirmed.pending_confirmation_step_id;
    confirmationStatuses[stepId] = confirmed.confirmation_status;

    const status = persistentStepStatus(confirmed.step_status);
    const plannedStep = current.plan.steps.find((step) => step.step_id === stepId);
    if (plannedStep) plannedStep.status = status;
    const stepRun = current.step_runs.find((run) => run.step_id === stepId);
    if (stepRun) {
      stepRun.status = status;
      if (confirmed.result_payload) stepRun.result = confirmed.result_payload;
    }
if (confirmed.lag_override_validation) lagValidation.value = confirmed.lag_override_validation;
    if (confirmed.feature_selection_validation) {
      featureValidation.value = confirmed.feature_selection_validation;
    }
    if (confirmed.arx_structure_validation) {
      arxValidation.value = confirmed.arx_structure_validation;
    }
    await refreshCurrentExecution();
    if (approved && status === "completed") {
      ElMessage.success("已批准并执行完成");
    } else {
      ElMessage.success(approved ? "已批准，等待执行" : "已拒绝该步骤");
    }
  } catch (err) {
    errorMessage.value = err instanceof ApiError ? err.message : String(err);
  } finally {
    confirmingStepId.value = null;
  }
};

const handleLagApproval = async (stepId: string, warningAcknowledged = false) => {
  const validation = await validateLagOverrideRows(stepId);
  if (!validation || validation.overall_status === "INVALID") return;
  if (validation.overall_status === "WARNING" && !warningAcknowledged) return;
  await submitConfirmation(
    stepId,
    true,
    selectedLagOverrides(),
    warningAcknowledged,
  );
};

const handleFeatureApproval = async (stepId: string) => {
  const current = result.value;
  if (!current?.execution_id || !canConfirm(stepId)) return;
  const adjusted = editingFeatureStepId.value === stepId;
  const dropColumns = adjusted ? [...featureDropColumns.value] : undefined;
  try {
    const validation = await validateFeatureSelection({
      execution_id: current.execution_id,
      step_id: stepId,
      drop_columns: dropColumns,
    });
    featureValidation.value = validation;
    if (validation.overall_status === "INVALID") return;
    await submitConfirmation(stepId, true, [], false, dropColumns);
  } catch (err) {
    errorMessage.value = err instanceof ApiError ? err.message : String(err);
  }
};

const handleConfirmation = async (stepId: string, approved: boolean) => {
  if (approved && isArxFitStep(stepId)) {
    await adoptArxRecommendation(stepId);
    return;
  }
  if (approved && isLagApplyStep(stepId)) {
    await handleLagApproval(stepId);
    return;
  }
  if (approved && isFeatureApplyStep(stepId)) {
    await handleFeatureApproval(stepId);
    return;
  }
  await submitConfirmation(stepId, approved);
};
const runFor = (stepId: string) =>
  result.value?.step_runs.find((run) => run.step_id === stepId) ?? null;

const isEvaluationStep = (stepId: string) =>
  result.value?.plan.steps.find((step) => step.step_id === stepId)?.tool === "evaluate_model";

const isOptimizationStep = (stepId: string) =>
  result.value?.plan.steps.find((step) => step.step_id === stepId)?.tool === "optimize_pipeline";

const directModelProducer = (stepId: string) => {
  const current = result.value;
  const target = current?.plan.steps.find((step) => step.step_id === stepId);
  if (!current || !target) return null;
  const producers = current.plan.steps.filter(
    (step) =>
      target.depends_on.includes(step.step_id) &&
      (step.tool === "fit_arx" || step.tool === "optimize_pipeline")
  );
  return producers.length === 1 ? producers[0] : null;
};

const canExecutePipelineOptimization = (stepId: string) => {
  const current = result.value;
  const optimization = current?.plan.steps.find((step) => step.step_id === stepId);
  if (
    !current?.execution_id ||
    optimization?.tool !== "optimize_pipeline" ||
    optimization.status !== "running"
  ) {
    return false;
  }
  const fits = current.plan.steps.filter(
    (step) => optimization.depends_on.includes(step.step_id) && step.tool === "fit_arx"
  );
  return fits.length === 1 && fits[0].status === "completed";
};

const canExecuteModelEvaluation = (stepId: string) => {
  const current = result.value;
  const evaluation = current?.plan.steps.find((step) => step.step_id === stepId);
  if (!current?.execution_id || evaluation?.tool !== "evaluate_model" || evaluation.status !== "pending") {
    return false;
  }
  return directModelProducer(stepId)?.status === "completed";
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const isMetricValue = (value: unknown): value is number | null =>
  value === null || typeof value === "number";

const isPredictionMetrics = (value: unknown): value is PredictionMetrics =>
  isRecord(value) && ["mae", "rmse", "r2", "fit", "nrmse"].every((key) => isMetricValue(value[key]));

const evaluationResult = (stepId: string): SavedArxEvaluationResult | null => {
  const payload = runFor(stepId)?.result;
  if (!isRecord(payload) || !isRecord(payload.test)) return null;
  if (
    typeof payload.model_id !== "string" ||
    typeof payload.source_version_id !== "string" ||
    typeof payload.processing_run_id !== "string" ||
    !isPredictionMetrics(payload.test.one_step) ||
    !isPredictionMetrics(payload.test.free_run)
  ) {
    return null;
  }
  return payload as SavedArxEvaluationResult;
};

const evaluationFailure = (stepId: string) => {
  const stepRun = runFor(stepId);
  return stepRun?.error_message || stepRun?.error_code || "";
};

const optimizationResult = (stepId: string): AgentOptimizationResult | null => {
  const payload = runFor(stepId)?.result;
  if (
    !isRecord(payload) ||
    typeof payload.study_id !== "string" ||
    typeof payload.baseline_model_id !== "string" ||
    typeof payload.model_id !== "string" ||
    typeof payload.optimized_model_id !== "string" ||
    typeof payload.source_version_id !== "string" ||
    !isRecord(payload.best_params) ||
    (payload.best_value !== null && typeof payload.best_value !== "number")
  ) {
    return null;
  }
  return payload as AgentOptimizationResult;
};

const optimizationFailure = (stepId: string) => {
  const stepRun = runFor(stepId);
  return stepRun?.error_message || stepRun?.error_code || "";
};

const pct = (value: number | null | undefined) =>
  value === null || value === undefined || !Number.isFinite(value)
    ? "—"
    : `${value.toFixed(2)}%`;

const num = (value: number | null | undefined) =>
  value === null || value === undefined || !Number.isFinite(value)
    ? "—"
    : Math.abs(value) >= 10000
      ? value.toExponential(2)
      : value.toFixed(4);

const formatOptimizationObjective = (value: number | null | undefined) =>
  value === null || value === undefined || !Number.isFinite(value) ? "—" : value.toFixed(4);

const formatOptimizationParameter = (value: unknown) => {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") {
    return Number.isFinite(value) ? (Number.isInteger(value) ? String(value) : value.toFixed(4)) : "—";
  }
  if (typeof value === "string" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value) ?? "—";
  } catch {
    return "—";
  }
};

const executePipelineOptimizationStep = async (stepId: string) => {
  const current = result.value;
  if (!current?.execution_id || !canExecutePipelineOptimization(stepId) || executingOptimizationStepId.value) {
    return;
  }

  errorMessage.value = "";
  executingOptimizationStepId.value = stepId;
  try {
    const completed = await executePipelineOptimization(current.execution_id);
    current.workflow_status = completed.workflow_status;
    current.current_version_id = completed.current_version_id ?? current.current_version_id;

    const status = persistentStepStatus(completed.step_status);
    const plannedStep = current.plan.steps.find((step) => step.step_id === completed.step_id);
    if (plannedStep) plannedStep.status = status;
    const stepRun = current.step_runs.find((run) => run.step_id === completed.step_id);
    if (stepRun) {
      stepRun.status = status;
      stepRun.result = completed.result_payload as Record<string, any>;
      stepRun.error_code = completed.error_code;
      stepRun.error_message = completed.error_message;
      stepRun.processing_run_ids = completed.processing_run_ids;
    }

    await refreshCurrentExecution();
    if (status === "completed") {
      ElMessage.success("模型优化完成");
    } else {
      ElMessage.error(completed.error_message || completed.error_code || "模型优化失败");
    }
  } catch (err) {
    errorMessage.value = err instanceof ApiError ? err.message : String(err);
  } finally {
    executingOptimizationStepId.value = null;
  }
};

const executeModelEvaluationStep = async (stepId: string) => {
  const current = result.value;
  if (!current?.execution_id || !canExecuteModelEvaluation(stepId) || executingEvaluationStepId.value) {
    return;
  }

  errorMessage.value = "";
  executingEvaluationStepId.value = stepId;
  try {
    const completed = await executeModelEvaluation(current.execution_id);
    current.workflow_status = completed.workflow_status;
    current.current_version_id = completed.current_version_id ?? current.current_version_id;

    const status = persistentStepStatus(completed.step_status);
    const plannedStep = current.plan.steps.find((step) => step.step_id === completed.step_id);
    if (plannedStep) plannedStep.status = status;
    const stepRun = current.step_runs.find((run) => run.step_id === completed.step_id);
    if (stepRun) {
      stepRun.status = status;
      stepRun.result = completed.result_payload as Record<string, any>;
      stepRun.error_code = completed.error_code;
      stepRun.error_message = completed.error_message;
      stepRun.processing_run_ids = completed.processing_run_ids;
    }

    await refreshCurrentExecution();
    if (status === "completed") {
      ElMessage.success("模型评价完成");
    } else {
      ElMessage.error(completed.error_message || completed.error_code || "模型评价失败");
    }
  } catch (err) {
    errorMessage.value = err instanceof ApiError ? err.message : String(err);
  } finally {
    executingEvaluationStepId.value = null;
  }
};
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
    : status === "failed" || status === "cancelled"
      ? "danger"
      : status === "waiting_confirmation"
        ? "warning"
        : "info";

const stepStatus = (status: AgentStepStatus) =>
  status === "completed"
    ? "success"
    : status === "failed" || status === "cancelled"
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

.header-tags,
.execution-state,
.confirmation-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.execution-state {
  margin: 8px 0 12px;
  color: var(--text-secondary);
  font-family: var(--font-mono);
  font-size: 12px;
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

.confirmation-message {
  color: var(--text-secondary);
  margin: 6px 0;
}

.confirmation-actions {
  margin-top: 8px;
}

.lag-dialog-header h3 {
  margin: 0;
  color: var(--text-primary);
  font-size: 17px;
  font-weight: 600;
  line-height: 1.4;
}

.lag-dialog-header p {
  margin: 5px 0 0;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.5;
}

.lag-dialog-body {
  display: grid;
  gap: 16px;
}

.lag-recommendation,
.lag-validation {
  margin: 0;
}

.lag-override-heading {
  margin-bottom: -6px;
  color: var(--text-primary);
  font-size: 14px;
  font-weight: 600;
}

.lag-override-labels,
.lag-override-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(132px, 0.72fr) auto;
  align-items: center;
  gap: 12px;
}

.lag-override-labels {
  color: var(--text-secondary);
  font-size: 12px;
}

.lag-override-row + .lag-override-row {
  margin-top: 10px;
}

.lag-override-row :deep(.el-select),
.lag-override-row :deep(.el-input-number) {
  width: 100%;
}

.lag-dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

@media (max-width: 560px) {
  .lag-override-labels {
    display: none;
  }

  .lag-override-row {
    grid-template-columns: minmax(0, 1fr) minmax(112px, 0.72fr) auto;
    gap: 8px;
  }
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
.evaluation-actions,
.optimization-actions {
  margin-top: 10px;
}

.optimization-results {
  margin-top: 12px;
  padding: 12px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--surface-color);
}

.optimization-title,
.optimization-params-title {
  margin: 0 0 10px;
  font-weight: 600;
}

.optimization-params-title {
  margin-top: 12px;
}

.optimization-summary,
.optimization-params-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.optimization-item {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 4px;
  background: var(--background-color);
  font-size: 12px;
}

.optimization-item span {
  color: var(--text-secondary);
}

.evaluation-results {
  margin-top: 12px;
  padding: 12px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--surface-color);
}

.evaluation-title {
  margin: 0 0 10px;
  font-weight: 600;
}

.evaluation-groups {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.evaluation-group h4 {
  margin: 0 0 8px;
  font-size: 13px;
}

.evaluation-metrics-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.evaluation-metric {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 8px;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  font-size: 12px;
}

.evaluation-metric span {
  color: var(--text-secondary);
}

@media (max-width: 720px) {
  .evaluation-groups {
    grid-template-columns: 1fr;
  }
}
</style>
