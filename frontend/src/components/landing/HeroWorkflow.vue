<template>
  <div
    ref="zone"
    class="hero-workflow"
    :class="{ 'has-pointer': pointerInside }"
    aria-label="可组合工业建模工作流"
    @pointerenter="pointerInside = true"
    @pointerleave="resetPointer"
    @pointermove="handlePointerMove"
  >
    <div class="workflow-coordinate" aria-hidden="true">
      <span>X / PROCESS</span>
      <span>Y / TRACE</span>
    </div>

    <div class="workflow-track">
      <template v-for="(step, index) in steps" :key="step.name">
        <button
          :ref="(element) => setNodeRef(element, index)"
          class="workflow-node"
          :class="{
            active: activeIndex === index,
            adjacent: Math.abs(activeIndex - index) === 1,
          }"
          type="button"
          @focus="activeIndex = index"
          @pointerenter="activeIndex = index"
        >
          <span class="node-index">{{ String(index + 1).padStart(2, "0") }}</span>
          <span class="node-name">{{ step.name }}</span>
        </button>
        <span
          v-if="index < steps.length - 1"
          class="workflow-connector"
          :class="{ active: activeIndex === index || activeIndex === index + 1 }"
          aria-hidden="true"
        ></span>
      </template>
    </div>

    <div class="workflow-inspector" aria-live="polite">
      <span class="inspector-label">{{ activeStep.label }}</span>
      <strong>{{ activeStep.name }}</strong>
      <span>{{ activeStep.detail }}</span>
    </div>

    <p class="workflow-note">按工程目标组合步骤，并非每个任务固定执行全部流程。</p>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from "vue";

interface WorkflowStep {
  name: string;
  label: string;
  detail: string;
}

const steps: WorkflowStep[] = [
  { name: "Raw Data", label: "DATA SOURCE", detail: "原始过程数据与采样信息" },
  { name: "Cleaning", label: "QUALITY", detail: "异常、缺失与时间规整" },
  { name: "Segmentation", label: "DYNAMICS", detail: "识别高信噪比动态区间" },
  { name: "Delay", label: "LAG", detail: "建立输入与输出的时滞关系" },
  { name: "Feature", label: "VARIABLES", detail: "控制共线性并保留有效变量" },
  { name: "ARX", label: "STRUCTURE", detail: "辨识模型结构并保存真实模型" },
  { name: "Optimize", label: "SEARCH", detail: "在验证集上完成 Optuna 寻优" },
  { name: "Evaluate", label: "HOLD-OUT", detail: "用户触发保存模型的 Test 评价" },
];

const defaultStep: WorkflowStep = {
  name: "Composable Workflow",
  label: "ENGINEERING PATH",
  detail: "移动指针，检查每个工程环节",
};

const zone = ref<HTMLElement | null>(null);
const nodeRefs: HTMLElement[] = [];
const activeIndex = ref(-1);
const pointerInside = ref(false);
let animationFrame: number | null = null;
let pendingPointer: PointerEvent | null = null;

const activeStep = computed(() => steps[activeIndex.value] ?? defaultStep);

function setNodeRef(element: unknown, index: number) {
  if (element instanceof HTMLElement) {
    nodeRefs[index] = element;
  }
}

function applyPointerPosition(event: PointerEvent) {
  if (!zone.value) return;
  const bounds = zone.value.getBoundingClientRect();
  const x = event.clientX - bounds.left;
  const y = event.clientY - bounds.top;
  zone.value.style.setProperty("--pointer-x", `${x}px`);
  zone.value.style.setProperty("--pointer-y", `${y}px`);

  let nearestIndex = -1;
  let nearestDistance = Number.POSITIVE_INFINITY;
  nodeRefs.forEach((node, index) => {
    const rect = node.getBoundingClientRect();
    const nodeX = rect.left + rect.width / 2;
    const nodeY = rect.top + rect.height / 2;
    const distance = Math.hypot(event.clientX - nodeX, event.clientY - nodeY);
    if (distance < nearestDistance) {
      nearestDistance = distance;
      nearestIndex = index;
    }
  });
  activeIndex.value = nearestIndex;
}

function handlePointerMove(event: PointerEvent) {
  if (event.pointerType === "touch") return;
  pendingPointer = event;
  if (animationFrame !== null) return;
  animationFrame = window.requestAnimationFrame(() => {
    if (pendingPointer) applyPointerPosition(pendingPointer);
    animationFrame = null;
  });
}

function resetPointer() {
  pointerInside.value = false;
  activeIndex.value = -1;
  pendingPointer = null;
}

onBeforeUnmount(() => {
  if (animationFrame !== null) window.cancelAnimationFrame(animationFrame);
});
</script>

<style scoped>
.hero-workflow {
  --pointer-x: 50%;
  --pointer-y: 50%;
  position: relative;
  min-width: 0;
  padding: clamp(24px, 4vw, 42px);
  overflow-x: auto;
  overflow-y: hidden;
  border: 1px solid var(--landing-border-strong);
  border-radius: var(--landing-radius);
  background:
    radial-gradient(circle 220px at var(--pointer-x) var(--pointer-y), var(--landing-highlight), transparent 72%),
    var(--landing-surface);
  box-shadow: var(--landing-shadow);
  isolation: isolate;
}

.hero-workflow::before {
  position: absolute;
  inset: 0;
  z-index: -1;
  background-image:
    linear-gradient(var(--landing-grid) 1px, transparent 1px),
    linear-gradient(90deg, var(--landing-grid) 1px, transparent 1px);
  background-size: 32px 32px;
  content: "";
  opacity: 0.58;
}

.workflow-coordinate {
  display: flex;
  justify-content: space-between;
  margin-bottom: 40px;
  color: var(--landing-faint);
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.13em;
}

.workflow-track {
  display: flex;
  align-items: center;
  min-width: 600px;
  padding: 22px 0 28px;
}

.workflow-node {
  position: relative;
  display: grid;
  flex: 0 0 66px;
  place-items: center;
  min-height: 82px;
  padding: 10px 6px;
  border: 1px solid var(--landing-border-strong);
  border-radius: var(--landing-radius);
  background: var(--landing-node-bg);
  color: var(--landing-muted);
  cursor: crosshair;
  transition: border-color 360ms ease, background-color 360ms ease, color 360ms ease, transform 360ms ease;
}

.workflow-node.active {
  border-color: var(--landing-accent);
  background: var(--landing-accent-soft);
  color: var(--landing-text);
  transform: translateY(-3px);
}

.workflow-node.adjacent {
  border-color: var(--landing-border-active);
  color: var(--landing-text);
}

.workflow-node:focus-visible {
  outline: 2px solid var(--landing-accent);
  outline-offset: 3px;
}

.node-index {
  color: var(--landing-accent);
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.08em;
}

.node-name {
  font-size: 11px;
  font-weight: 650;
  white-space: nowrap;
}

.workflow-connector {
  position: relative;
  flex: 1 1 12px;
  min-width: 10px;
  height: 1px;
  overflow: hidden;
  background: var(--landing-border-strong);
}

.workflow-connector::after {
  position: absolute;
  inset: 0;
  background: var(--landing-accent);
  content: "";
  opacity: 0;
  transform: translateX(-100%);
}

.workflow-connector.active::after {
  animation: connector-pass 720ms cubic-bezier(0.16, 1, 0.3, 1) both;
}

.workflow-inspector {
  display: grid;
  grid-template-columns: 110px minmax(110px, 0.7fr) minmax(180px, 1.3fr);
  align-items: center;
  gap: 14px;
  min-height: 64px;
  padding-top: 18px;
  border-top: 1px solid var(--landing-border);
  color: var(--landing-muted);
  font-size: 12px;
}

.workflow-inspector strong {
  color: var(--landing-text);
  font-size: 13px;
  font-weight: 650;
}

.inspector-label {
  color: var(--landing-accent);
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.12em;
}

.workflow-note {
  margin: 20px 0 0;
  color: var(--landing-faint);
  font-size: 11px;
  line-height: 1.6;
}

@keyframes connector-pass {
  0% {
    opacity: 0;
    transform: translateX(-100%);
  }
  28% {
    opacity: 1;
  }
  100% {
    opacity: 0;
    transform: translateX(100%);
  }
}

@media (max-width: 1120px) {
  .workflow-coordinate,
  .workflow-inspector,
  .workflow-note {
    position: sticky;
    left: 0;
    width: min(100%, 700px);
  }
}

@media (max-width: 700px) {
  .hero-workflow {
    padding: 22px 18px;
  }

  .workflow-coordinate {
    margin-bottom: 18px;
  }

  .workflow-track {
    min-width: 600px;
  }

  .workflow-node {
    flex-basis: 62px;
    min-height: 72px;
  }

  .workflow-inspector {
    grid-template-columns: 1fr;
    gap: 4px;
  }
}

@media (pointer: coarse) {
  .hero-workflow {
    background: var(--landing-surface);
  }

  .workflow-node {
    cursor: default;
  }
}

@media (prefers-reduced-motion: reduce) {
  .workflow-node,
  .workflow-connector::after {
    animation: none !important;
    transition: none !important;
    transform: none !important;
  }
}
</style>
