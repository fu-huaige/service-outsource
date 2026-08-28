<template>
  <div class="lineage-shell">
    <div class="lineage-caption">
      <span>Example Lineage</span>
      <p>示例路径用于说明不可变派生与来源追踪，不代表每个数据集必须经历全部步骤。</p>
    </div>

    <div class="lineage-path" aria-label="数据集示例版本血缘">
      <template v-for="(version, index) in versions" :key="version.id">
        <button
          class="lineage-version"
          :class="{ active: activeIndex === index, related: index <= activeIndex }"
          type="button"
          @focus="activeIndex = index"
          @pointerenter="activeIndex = index"
          @click="activeIndex = index"
        >
          <span class="version-id">{{ version.id }}</span>
          <strong>{{ version.name }}</strong>
        </button>
        <span
          v-if="index < versions.length - 1"
          class="lineage-edge"
          :class="{ active: index < activeIndex }"
          aria-hidden="true"
        ></span>
      </template>
      <span class="lineage-edge model-edge" :class="{ active: activeIndex === versions.length - 1 }" aria-hidden="true"></span>
      <div class="model-ready">
        <span>MODEL INPUT</span>
        <strong>可建模数据版本</strong>
      </div>
    </div>

    <div class="lineage-inspector" aria-live="polite">
      <span>{{ activeVersion.operation }}</span>
      <strong>{{ activeVersion.name }}</strong>
      <p>{{ activeVersion.detail }}</p>
      <code>{{ activeVersion.lineage }}</code>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";

interface DatasetVersion {
  id: string;
  name: string;
  operation: string;
  detail: string;
  lineage: string;
}

const versions: DatasetVersion[] = [
  {
    id: "V0",
    name: "Original",
    operation: "SOURCE",
    detail: "保留原始数据资产，后续处理不会覆盖这一版本。",
    lineage: "source_version: original",
  },
  {
    id: "V1",
    name: "Cleaning",
    operation: "CLEANING",
    detail: "清洗结果形成新的派生版本，并记录其直接来源。",
    lineage: "derived_from: V0",
  },
  {
    id: "V2",
    name: "Lag Compensation",
    operation: "LAG COMPENSATION",
    detail: "确认时滞后生成不可变补偿版本，保留完整来源证据。",
    lineage: "derived_from: V1",
  },
  {
    id: "V3",
    name: "Feature Selection",
    operation: "FEATURE SELECTION",
    detail: "变量筛选生成新的数据版本，模型继续绑定其真实 source version。",
    lineage: "derived_from: V2",
  },
];

const activeIndex = ref(1);
const activeVersion = computed(() => versions[activeIndex.value]);
</script>

<style scoped>
.lineage-shell {
  padding: clamp(26px, 5vw, 58px);
  border: 1px solid var(--landing-border);
  border-radius: var(--landing-radius);
  background: var(--landing-surface);
}

.lineage-caption {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 32px;
  padding-bottom: 34px;
  border-bottom: 1px solid var(--landing-border);
}

.lineage-caption span {
  color: var(--landing-accent);
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.12em;
}

.lineage-caption p {
  max-width: 520px;
  margin: 0;
  color: var(--landing-muted);
  font-size: 13px;
  line-height: 1.7;
}

.lineage-path {
  display: flex;
  align-items: center;
  padding: clamp(44px, 7vw, 84px) 0;
  overflow-x: auto;
}

.lineage-version,
.model-ready {
  display: flex;
  flex: 0 0 132px;
  flex-direction: column;
  justify-content: space-between;
  min-height: 116px;
  padding: 17px;
  border: 1px solid var(--landing-border-strong);
  border-radius: var(--landing-radius);
  background: var(--landing-node-bg);
  color: var(--landing-muted);
  text-align: left;
}

.lineage-version {
  cursor: pointer;
  transition: border-color 400ms ease, background-color 400ms ease, color 400ms ease, transform 400ms ease;
}

.lineage-version.related {
  border-color: var(--landing-border-active);
}

.lineage-version.active {
  border-color: var(--landing-accent);
  background: var(--landing-accent-soft);
  color: var(--landing-text);
  transform: translateY(-3px);
}

.lineage-version:focus-visible {
  outline: 2px solid var(--landing-accent);
  outline-offset: 3px;
}

.version-id,
.model-ready span {
  color: var(--landing-accent);
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.1em;
}

.lineage-version strong,
.model-ready strong {
  font-size: 12px;
  line-height: 1.45;
}

.lineage-edge {
  position: relative;
  flex: 1 0 34px;
  min-width: 34px;
  height: 1px;
  overflow: hidden;
  background: var(--landing-border-strong);
}

.lineage-edge::after {
  position: absolute;
  inset: 0;
  background: var(--landing-accent);
  content: "";
  transform: scaleX(0);
  transform-origin: left;
  transition: transform 600ms cubic-bezier(0.16, 1, 0.3, 1);
}

.lineage-edge.active::after {
  transform: scaleX(1);
}

.model-edge {
  border-top: 1px dashed var(--landing-border-strong);
  background: transparent;
}

.model-ready {
  border-style: dashed;
  background: transparent;
  color: var(--landing-text);
}

.lineage-inspector {
  display: grid;
  grid-template-columns: 130px minmax(140px, 0.7fr) minmax(260px, 1.5fr) auto;
  align-items: center;
  gap: 24px;
  min-height: 82px;
  padding-top: 24px;
  border-top: 1px solid var(--landing-border);
}

.lineage-inspector > span,
.lineage-inspector code {
  color: var(--landing-accent);
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.08em;
}

.lineage-inspector strong {
  color: var(--landing-text);
  font-size: 14px;
}

.lineage-inspector p {
  margin: 0;
  color: var(--landing-muted);
  font-size: 13px;
  line-height: 1.6;
}

.lineage-inspector code {
  color: var(--landing-faint);
  white-space: nowrap;
}

@media (max-width: 820px) {
  .lineage-caption {
    flex-direction: column;
    gap: 12px;
  }

  .lineage-path {
    min-width: 830px;
  }

  .lineage-inspector {
    grid-template-columns: 1fr;
    gap: 6px;
  }
}

@media (pointer: coarse) {
  .lineage-version {
    cursor: default;
  }
}

@media (prefers-reduced-motion: reduce) {
  .lineage-version,
  .lineage-edge::after {
    transition: none !important;
    transform: none !important;
  }
}
</style>
