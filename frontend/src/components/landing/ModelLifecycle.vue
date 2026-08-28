<template>
  <div class="lifecycle-shell">
    <div class="lifecycle-axis" aria-label="模型与寻优工程生命周期">
      <template v-for="(stage, index) in stages" :key="stage.name">
        <article class="lifecycle-stage" tabindex="0">
          <span class="stage-code">{{ stage.code }}</span>
          <h3>{{ stage.name }}</h3>
          <p>{{ stage.detail }}</p>
          <span class="stage-boundary">{{ stage.boundary }}</span>
        </article>
        <span v-if="index < stages.length - 1" class="stage-transition" aria-hidden="true">→</span>
      </template>
    </div>

    <div class="lifecycle-proof">
      <div>
        <span>MODEL ASSET</span>
        <strong>结构、参数与 source version 共同保存</strong>
      </div>
      <div>
        <span>EVALUATION</span>
        <strong>同一保存模型进入 held-out Test</strong>
      </div>
      <p>页面只呈现正式工程边界，不展示虚构性能数值。</p>
    </div>
  </div>
</template>

<script setup lang="ts">
const stages = [
  { code: "STRUCTURE", name: "ARX", detail: "定义输入输出动态结构", boundary: "System identification" },
  { code: "VALIDATE", name: "Validation", detail: "比较候选结构与参数", boundary: "Selection boundary" },
  { code: "SEARCH", name: "Optuna Search", detail: "在验证范围内执行寻优", boundary: "No Test tuning" },
  { code: "FREEZE", name: "Saved Model", detail: "固化模型资产与真实血缘", boundary: "Replayable artifact" },
  { code: "EVALUATE", name: "Held-out Evaluation", detail: "对保存模型完成最终评价", boundary: "One-step + free-run" },
];
</script>

<style scoped>
.lifecycle-shell {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(260px, 0.31fr);
  border: 1px solid var(--landing-border-strong);
  border-radius: var(--landing-radius);
  background: var(--landing-surface);
}

.lifecycle-axis {
  display: grid;
  grid-template-columns: minmax(120px, 1fr) auto minmax(120px, 1fr) auto minmax(120px, 1fr) auto minmax(120px, 1fr) auto minmax(120px, 1fr);
  align-items: stretch;
  min-width: 0;
  padding: clamp(28px, 4vw, 50px);
  overflow-x: auto;
}

.lifecycle-stage {
  display: flex;
  min-height: 272px;
  flex-direction: column;
  padding: 18px 14px;
  border-left: 1px solid var(--landing-border);
  outline: none;
  transition: border-color 380ms ease, background-color 380ms ease;
}

.lifecycle-stage:hover,
.lifecycle-stage:focus-visible {
  border-left-color: var(--landing-accent);
  background: var(--landing-accent-soft);
}

.lifecycle-stage:focus-visible {
  outline: 2px solid var(--landing-accent);
  outline-offset: 2px;
}

.stage-code {
  color: var(--landing-accent);
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.1em;
}

.lifecycle-stage h3 {
  min-height: 52px;
  margin: 34px 0 12px;
  color: var(--landing-text);
  font-size: 16px;
  line-height: 1.4;
}

.lifecycle-stage p {
  margin: 0;
  color: var(--landing-muted);
  font-size: 12px;
  line-height: 1.65;
}

.stage-boundary {
  margin-top: auto;
  color: var(--landing-faint);
  font-family: var(--font-mono);
  font-size: 9px;
  line-height: 1.5;
}

.stage-transition {
  align-self: center;
  padding: 0 8px;
  color: var(--landing-accent);
  font-family: var(--font-mono);
  font-size: 13px;
  opacity: 0.7;
}

.lifecycle-proof {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 30px;
  padding: clamp(28px, 4vw, 50px);
  border-left: 1px solid var(--landing-border-strong);
  background: var(--landing-surface-tinted);
}

.lifecycle-proof div {
  display: grid;
  gap: 12px;
}

.lifecycle-proof span {
  color: var(--landing-accent);
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.1em;
}

.lifecycle-proof strong {
  color: var(--landing-text);
  font-size: 14px;
  line-height: 1.65;
}

.lifecycle-proof p {
  margin: 0;
  padding-top: 22px;
  border-top: 1px solid var(--landing-border);
  color: var(--landing-muted);
  font-size: 12px;
  line-height: 1.65;
}

@media (max-width: 1040px) {
  .lifecycle-shell {
    grid-template-columns: 1fr;
  }

  .lifecycle-axis {
    min-width: 900px;
  }

  .lifecycle-proof {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    border-top: 1px solid var(--landing-border-strong);
    border-left: 0;
  }

  .lifecycle-proof p {
    grid-column: 1 / -1;
  }
}

@media (max-width: 620px) {
  .lifecycle-proof {
    grid-template-columns: 1fr;
  }

  .lifecycle-proof p {
    grid-column: auto;
  }
}

@media (prefers-reduced-motion: reduce) {
  .lifecycle-stage {
    transition: none !important;
  }
}
</style>
