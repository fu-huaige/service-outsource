<template>
  <div class="trust-layout">
    <article class="trust-module trust-module-data" tabindex="0">
      <div class="module-copy">
        <span class="module-number">01</span>
        <h3>数据可信</h3>
        <p>版本血缘贯穿清洗与预处理，让每次数据变换都有来源、有依据。</p>
      </div>
      <div class="lineage-micro" aria-label="数据版本血缘示意">
        <template v-for="(version, index) in versions" :key="version">
          <span class="micro-node">{{ version }}</span>
          <span v-if="index < versions.length - 1" class="micro-line" aria-hidden="true"></span>
        </template>
      </div>
      <div class="data-labels" aria-hidden="true">
        <span>Original</span>
        <span>Cleaning</span>
        <span>Derived</span>
      </div>
    </article>

    <article class="trust-module trust-module-model" tabindex="0">
      <div class="module-copy">
        <span class="module-number">02</span>
        <h3>模型可信</h3>
        <p>模型结构、保存资产与评价结果共同形成可重放的系统辨识证据。</p>
      </div>
      <div class="model-micro" aria-label="测量值与模型响应示意">
        <svg viewBox="0 0 320 120" role="img" aria-label="测量响应与模型响应曲线">
          <polyline class="measured" points="0,84 24,81 48,65 72,35 96,22 120,38 144,62 168,73 192,58 216,39 240,46 264,64 288,70 320,61" />
          <polyline class="predicted" points="0,87 24,79 48,61 72,39 96,27 120,41 144,58 168,68 192,61 216,43 240,49 264,61 288,67 320,63" />
        </svg>
        <div class="curve-legend">
          <span>Measured</span>
          <span>Model</span>
        </div>
      </div>
    </article>

    <article class="trust-module trust-module-decision" tabindex="0">
      <div class="module-copy">
        <span class="module-number">03</span>
        <h3>决策过程可信</h3>
        <p>Agent 编排、人工确认、Optuna 与 held-out evaluation 共同约束执行路径。</p>
      </div>
      <div class="decision-micro" aria-label="决策过程步骤示意">
        <template v-for="(step, index) in decisionSteps" :key="step">
          <span class="decision-step">{{ step }}</span>
          <span v-if="index < decisionSteps.length - 1" class="decision-link" aria-hidden="true"></span>
        </template>
      </div>
    </article>
  </div>
</template>

<script setup lang="ts">
const versions = ["V0", "V1", "V2"];
const decisionSteps = ["Plan", "Approval", "Optimize", "Evaluate"];
</script>

<style scoped>
.trust-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(300px, 0.75fr);
  grid-template-rows: repeat(2, minmax(260px, auto));
  gap: 16px;
}

.trust-module {
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  min-width: 0;
  padding: clamp(24px, 3vw, 40px);
  overflow: hidden;
  border: 1px solid var(--landing-border);
  border-radius: var(--landing-radius);
  background: var(--landing-surface);
  outline: none;
  transition: border-color 380ms ease, background-color 380ms ease;
}

.trust-module:focus-visible {
  outline: 2px solid var(--landing-accent);
  outline-offset: 3px;
}

.trust-module:hover,
.trust-module:focus-visible {
  border-color: var(--landing-border-active);
  background: var(--landing-surface-active);
}

.trust-module-data {
  grid-row: 1 / 3;
  min-height: 540px;
  background:
    linear-gradient(135deg, transparent 50%, var(--landing-grid) 50%, var(--landing-grid) calc(50% + 1px), transparent calc(50% + 1px)),
    var(--landing-surface);
  background-size: 52px 52px;
}

.trust-module-decision {
  background: var(--landing-surface-tinted);
}

.module-copy {
  position: relative;
  z-index: 1;
  max-width: 430px;
}

.module-number {
  display: block;
  margin-bottom: 34px;
  color: var(--landing-accent);
  font-family: var(--font-mono);
  font-size: 11px;
}

.module-copy h3 {
  margin: 0 0 13px;
  color: var(--landing-text);
  font-size: clamp(23px, 2vw, 31px);
  font-weight: 650;
  letter-spacing: -0.035em;
}

.module-copy p {
  max-width: 38ch;
  margin: 0;
  color: var(--landing-muted);
  font-size: 14px;
  line-height: 1.75;
}

.lineage-micro {
  display: flex;
  align-items: center;
  width: 100%;
  margin: 80px 0 18px;
}

.micro-node {
  display: grid;
  flex: 0 0 62px;
  place-items: center;
  width: 62px;
  height: 62px;
  border: 1px solid var(--landing-border-strong);
  border-radius: var(--landing-radius);
  background: var(--landing-node-bg);
  color: var(--landing-text);
  font-family: var(--font-mono);
  font-size: 13px;
  transition: border-color 420ms ease, background-color 420ms ease, color 420ms ease;
}

.micro-line {
  position: relative;
  flex: 1;
  height: 1px;
  overflow: hidden;
  background: var(--landing-border-strong);
}

.micro-line::after {
  position: absolute;
  inset: 0;
  background: var(--landing-accent);
  content: "";
  transform: scaleX(0);
  transform-origin: left;
  transition: transform 760ms cubic-bezier(0.16, 1, 0.3, 1);
}

.trust-module-data:hover .micro-line::after,
.trust-module-data:focus-visible .micro-line::after {
  transform: scaleX(1);
}

.trust-module-data:hover .micro-node,
.trust-module-data:focus-visible .micro-node {
  border-color: var(--landing-accent);
  background: var(--landing-accent-soft);
}

.trust-module-data:hover .micro-node:nth-of-type(2),
.trust-module-data:focus-visible .micro-node:nth-of-type(2) {
  transition-delay: 180ms;
}

.trust-module-data:hover .micro-node:nth-of-type(3),
.trust-module-data:focus-visible .micro-node:nth-of-type(3) {
  transition-delay: 360ms;
}

.data-labels {
  display: grid;
  grid-template-columns: repeat(3, 62px);
  justify-content: space-between;
  color: var(--landing-faint);
  font-family: var(--font-mono);
  font-size: 9px;
  text-align: center;
}

.model-micro {
  margin-top: 42px;
}

.model-micro svg {
  display: block;
  width: 100%;
  height: 92px;
  overflow: visible;
}

.model-micro polyline {
  fill: none;
  stroke-linecap: square;
  stroke-linejoin: round;
  stroke-width: 1.5;
}

.measured {
  stroke: var(--landing-faint);
}

.predicted {
  stroke: var(--landing-accent);
  stroke-dasharray: 500;
  stroke-dashoffset: 0;
  transition: stroke-dashoffset 820ms cubic-bezier(0.16, 1, 0.3, 1);
}

.trust-module-model:hover .predicted,
.trust-module-model:focus-visible .predicted {
  stroke-dashoffset: 500;
  animation: draw-model 820ms cubic-bezier(0.16, 1, 0.3, 1) forwards;
}

.curve-legend {
  display: flex;
  justify-content: space-between;
  color: var(--landing-faint);
  font-family: var(--font-mono);
  font-size: 9px;
}

.decision-micro {
  display: flex;
  align-items: center;
  margin-top: 38px;
}

.decision-step {
  color: var(--landing-muted);
  font-family: var(--font-mono);
  font-size: 10px;
  transition: color 380ms ease, transform 380ms ease;
}

.decision-link {
  flex: 1;
  height: 1px;
  margin: 0 8px;
  background: var(--landing-border-strong);
  transition: background-color 380ms ease;
}

.trust-module-decision:hover .decision-step,
.trust-module-decision:focus-visible .decision-step {
  color: var(--landing-text);
  transform: translateY(-2px);
}

.trust-module-decision:hover .decision-step:nth-of-type(2),
.trust-module-decision:focus-visible .decision-step:nth-of-type(2) {
  transition-delay: 100ms;
}

.trust-module-decision:hover .decision-step:nth-of-type(3),
.trust-module-decision:focus-visible .decision-step:nth-of-type(3) {
  transition-delay: 200ms;
}

.trust-module-decision:hover .decision-step:nth-of-type(4),
.trust-module-decision:focus-visible .decision-step:nth-of-type(4) {
  transition-delay: 300ms;
}

.trust-module-decision:hover .decision-link,
.trust-module-decision:focus-visible .decision-link {
  background: var(--landing-accent);
}

@keyframes draw-model {
  to {
    stroke-dashoffset: 0;
  }
}

@media (max-width: 900px) {
  .trust-layout {
    grid-template-columns: 1fr;
    grid-template-rows: auto;
  }

  .trust-module-data {
    grid-row: auto;
    min-height: 420px;
  }
}

@media (max-width: 600px) {
  .trust-module {
    min-height: 280px;
  }

  .trust-module-data {
    min-height: 390px;
  }

  .lineage-micro {
    margin-top: 54px;
  }

  .micro-node {
    flex-basis: 52px;
    width: 52px;
    height: 52px;
  }

  .data-labels {
    grid-template-columns: repeat(3, 52px);
  }

  .decision-micro {
    flex-wrap: wrap;
    gap: 10px;
  }

  .decision-link {
    flex: 0 0 16px;
    margin: 0;
  }
}

@media (pointer: coarse) {
  .predicted {
    stroke-dashoffset: 0;
  }

  .micro-line::after {
    transform: scaleX(1);
  }
}

@media (prefers-reduced-motion: reduce) {
  .trust-module,
  .micro-node,
  .micro-line::after,
  .predicted,
  .decision-step,
  .decision-link {
    animation: none !important;
    transition: none !important;
    transform: none !important;
  }

  .micro-line::after {
    transform: scaleX(1) !important;
  }
}
</style>
