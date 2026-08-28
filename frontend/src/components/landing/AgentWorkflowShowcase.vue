<template>
  <div class="agent-showcase">
    <blockquote class="engineering-intent">
      <span>工程目标</span>
      <p>完成 ARX 模型辨识，使用 Optuna 对模型进行优化，并评价优化后的模型。</p>
    </blockquote>

    <div class="agent-path" aria-label="Agent 执行路径">
      <template v-for="(step, index) in steps" :key="step.name">
        <button
          class="agent-step"
          :class="{ active: activeIndex === index }"
          type="button"
          @focus="activeIndex = index"
          @pointerenter="activeIndex = index"
          @click="activeIndex = index"
        >
          <span class="agent-step-name">{{ step.name }}</span>
          <span class="agent-step-control">{{ step.control }}</span>
        </button>
        <span
          v-if="index < steps.length - 1"
          class="agent-connector"
          :class="{ active: activeIndex === index || activeIndex === index + 1 }"
          aria-hidden="true"
        ></span>
      </template>
    </div>

    <div class="agent-detail" aria-live="polite">
      <span class="detail-type">{{ activeStep.type }}</span>
      <strong>{{ activeStep.name }}</strong>
      <p>{{ activeStep.detail }}</p>
      <span class="detail-boundary">{{ activeStep.boundary }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";

interface AgentStep {
  name: string;
  control: string;
  type: string;
  detail: string;
  boundary: string;
}

const steps: AgentStep[] = [
  {
    name: "Profile",
    control: "Inspect",
    type: "DATA CONTEXT",
    detail: "读取数据画像，为后续结构决策建立可追溯上下文。",
    boundary: "Read-only analysis",
  },
  {
    name: "Dynamic Segment",
    control: "Select",
    type: "SIGNAL WINDOW",
    detail: "定位能够表达过程动态特性的高信噪比区间。",
    boundary: "Traceable source segment",
  },
  {
    name: "Fit ARX",
    control: "Human Approval",
    type: "MODEL STRUCTURE",
    detail: "用户确认结构后执行系统辨识，并保存可重放的模型资产。",
    boundary: "Confirmation required",
  },
  {
    name: "Optimize",
    control: "Human Approval",
    type: "VALIDATION SEARCH",
    detail: "在验证边界内运行 Optuna 搜索，生成新的正式优化模型。",
    boundary: "No Test tuning",
  },
  {
    name: "Evaluate",
    control: "User Trigger",
    type: "HELD-OUT TEST",
    detail: "用户显式触发保存模型评价，读取 held-out Test 生成真实结果。",
    boundary: "No refit",
  },
];

const activeIndex = ref(2);
const activeStep = computed(() => steps[activeIndex.value]);
</script>

<style scoped>
.agent-showcase {
  border: 1px solid var(--landing-border-strong);
  border-radius: var(--landing-radius);
  background: var(--landing-surface);
}

.engineering-intent {
  display: grid;
  grid-template-columns: 120px minmax(0, 1fr);
  gap: 30px;
  margin: 0;
  padding: clamp(24px, 4vw, 44px);
  border-bottom: 1px solid var(--landing-border);
}

.engineering-intent span {
  padding-top: 5px;
  color: var(--landing-accent);
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.12em;
}

.engineering-intent p {
  max-width: 780px;
  margin: 0;
  color: var(--landing-text);
  font-size: clamp(19px, 2.2vw, 29px);
  font-weight: 520;
  line-height: 1.55;
  letter-spacing: -0.025em;
}

.agent-path {
  display: flex;
  align-items: stretch;
  padding: clamp(30px, 5vw, 58px) clamp(24px, 4vw, 44px);
  overflow-x: auto;
}

.agent-step {
  display: flex;
  flex: 1 0 138px;
  flex-direction: column;
  align-items: flex-start;
  justify-content: space-between;
  min-height: 126px;
  padding: 18px;
  border: 1px solid var(--landing-border);
  border-radius: var(--landing-radius);
  background: var(--landing-node-bg);
  color: var(--landing-muted);
  cursor: pointer;
  text-align: left;
  transition: border-color 380ms ease, background-color 380ms ease, color 380ms ease, transform 380ms ease;
}

.agent-step.active {
  border-color: var(--landing-accent);
  background: var(--landing-accent-soft);
  color: var(--landing-text);
  transform: translateY(-3px);
}

.agent-step:focus-visible {
  outline: 2px solid var(--landing-accent);
  outline-offset: 3px;
}

.agent-step-name {
  font-size: 14px;
  font-weight: 700;
}

.agent-step-control {
  color: var(--landing-accent);
  font-family: var(--font-mono);
  font-size: 9px;
  line-height: 1.45;
}

.agent-connector {
  position: relative;
  flex: 0 0 clamp(18px, 3vw, 42px);
  align-self: center;
  height: 1px;
  overflow: hidden;
  background: var(--landing-border-strong);
}

.agent-connector::after {
  position: absolute;
  inset: 0;
  background: var(--landing-accent);
  content: "";
  transform: scaleX(0);
  transform-origin: left;
  transition: transform 620ms cubic-bezier(0.16, 1, 0.3, 1);
}

.agent-connector.active::after {
  transform: scaleX(1);
}

.agent-detail {
  display: grid;
  grid-template-columns: 130px minmax(120px, 0.7fr) minmax(260px, 1.5fr) minmax(130px, 0.6fr);
  align-items: center;
  gap: 24px;
  min-height: 98px;
  padding: 24px clamp(24px, 4vw, 44px);
  border-top: 1px solid var(--landing-border);
  background: var(--landing-surface-tinted);
}

.detail-type,
.detail-boundary {
  color: var(--landing-accent);
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.1em;
}

.agent-detail strong {
  color: var(--landing-text);
  font-size: 15px;
}

.agent-detail p {
  margin: 0;
  color: var(--landing-muted);
  font-size: 13px;
  line-height: 1.65;
}

.detail-boundary {
  justify-self: end;
  color: var(--landing-muted);
  text-align: right;
}

@media (max-width: 760px) {
  .engineering-intent {
    grid-template-columns: 1fr;
    gap: 10px;
  }

  .agent-detail {
    grid-template-columns: 1fr;
    gap: 7px;
  }

  .detail-boundary {
    justify-self: start;
    text-align: left;
  }
}

@media (pointer: coarse) {
  .agent-step {
    min-height: 118px;
  }

  .agent-step-control {
    color: var(--landing-text);
  }
}

@media (prefers-reduced-motion: reduce) {
  .agent-step,
  .agent-connector::after {
    transition: none !important;
    transform: none !important;
  }
}
</style>
