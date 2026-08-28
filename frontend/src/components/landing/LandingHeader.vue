<template>
  <header class="landing-header">
    <a class="landing-brand" href="#landing-top" aria-label="IndusOpt 工模智优首页">
      <span class="landing-brand-mark" aria-hidden="true">
        <span></span>
        <span></span>
        <span></span>
      </span>
      <span>IndusOpt 工模智优</span>
    </a>

    <nav class="landing-nav" aria-label="Landing 页面导航">
      <a href="#trusted-engineering">系统能力</a>
      <a href="#agent-workflow">工作流程</a>
      <a href="#dataset-lineage">数据血缘</a>
    </nav>

    <button class="landing-header-cta" type="button" @click="emit('explore')">
      开始探索
      <span aria-hidden="true">→</span>
    </button>
  </header>
</template>

<script setup lang="ts">
const emit = defineEmits<{
  explore: [];
}>();
</script>

<style scoped>
.landing-header {
  position: sticky;
  top: 0;
  z-index: 20;
  display: grid;
  grid-template-columns: minmax(220px, 1fr) auto minmax(220px, 1fr);
  align-items: center;
  width: 100%;
  height: 72px;
  margin: 0 auto;
  padding: 0 max(22px, calc((100vw - 1320px) / 2));
  border-bottom: 1px solid var(--landing-border);
  background: var(--landing-header-bg);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
}

.landing-brand,
.landing-nav a {
  color: var(--landing-text);
  text-decoration: none;
}

.landing-brand {
  display: inline-flex;
  align-items: center;
  justify-self: start;
  gap: 12px;
  font-size: 15px;
  font-weight: 700;
  letter-spacing: -0.01em;
}

.landing-brand-mark {
  display: grid;
  grid-template-columns: repeat(3, 4px);
  align-items: end;
  gap: 3px;
  width: 18px;
  height: 18px;
}

.landing-brand-mark span {
  display: block;
  background: var(--landing-accent);
}

.landing-brand-mark span:nth-child(1) {
  height: 8px;
}

.landing-brand-mark span:nth-child(2) {
  height: 18px;
}

.landing-brand-mark span:nth-child(3) {
  height: 12px;
}

.landing-nav {
  display: flex;
  align-items: center;
  gap: clamp(22px, 3vw, 42px);
  white-space: nowrap;
}

.landing-nav a {
  position: relative;
  padding: 8px 0;
  color: var(--landing-muted);
  font-size: 13px;
  transition: color 320ms ease;
}

.landing-nav a::after {
  position: absolute;
  right: 0;
  bottom: 2px;
  left: 0;
  height: 1px;
  background: var(--landing-accent);
  content: "";
  opacity: 0;
  transform: scaleX(0.3);
  transition: opacity 320ms ease, transform 320ms ease;
}

.landing-nav a:hover,
.landing-nav a:focus-visible {
  color: var(--landing-text);
}

.landing-nav a:hover::after,
.landing-nav a:focus-visible::after {
  opacity: 1;
  transform: scaleX(1);
}

.landing-header-cta {
  display: inline-flex;
  align-items: center;
  justify-self: end;
  gap: 12px;
  min-height: 40px;
  padding: 0 17px;
  border: 1px solid var(--landing-accent);
  border-radius: var(--landing-radius);
  background: var(--landing-accent);
  color: var(--landing-accent-contrast);
  cursor: pointer;
  font-size: 13px;
  font-weight: 700;
  white-space: nowrap;
  transition: background-color 300ms ease, border-color 300ms ease, transform 180ms ease;
}

.landing-header-cta:hover {
  border-color: var(--landing-accent-strong);
  background: var(--landing-accent-strong);
}

.landing-header-cta:active {
  transform: translateY(1px);
}

.landing-brand:focus-visible,
.landing-nav a:focus-visible,
.landing-header-cta:focus-visible {
  outline: 2px solid var(--landing-accent);
  outline-offset: 4px;
}

@media (max-width: 860px) {
  .landing-header {
    grid-template-columns: 1fr auto;
  }

  .landing-nav {
    display: none;
  }
}

@media (max-width: 520px) {
  .landing-header {
    height: 64px;
    padding-inline: 16px;
  }

  .landing-brand {
    font-size: 14px;
  }

  .landing-header-cta {
    min-height: 36px;
    padding-inline: 12px;
  }
}

@media (prefers-reduced-transparency: reduce) {
  .landing-header {
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
  }
}
</style>
