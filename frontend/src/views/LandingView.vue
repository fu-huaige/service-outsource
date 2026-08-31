<template>
  <div
    ref="pageRoot"
    class="landing-preview"
    :data-theme="theme"
    :data-reduced-motion="reducedMotion ? 'true' : 'false'"
  >
    <LandingHeader @explore="enterApplication" />

    <main id="landing-top">
      <!-- 01 Hero Section with Live Interactive Playground & Workflow -->
      <section class="landing-hero landing-section" data-section="hero">
        <div class="landing-container hero-grid">
          <div class="hero-copy">
            <span class="hero-eyebrow hero-anim-1">PROCESS INDUSTRY SYSTEM IDENTIFICATION</span>
            <h1 class="hero-anim-2">
              <span>让工业建模，</span>
              <span>从数据走向闭环决策</span>
            </h1>
            <p class="hero-subtitle hero-anim-3">
              面向流程工业建模工程师：导入多变量时序数据，完成质量门控、D-最优优选、ARX 辨识与可追溯验证。
            </p>

            <div class="hero-actions hero-anim-4">
              <button class="landing-button landing-button-primary" type="button" @click="enterApplication">
                进入工作台
                <span class="btn-arrow" aria-hidden="true">→</span>
              </button>
              <button class="landing-button landing-button-secondary" type="button" @click="scrollToBenchmark">
                查看实测对账
              </button>
            </div>

            <!-- 3 Hardcore Industrial Metric Highlights (Range & Evidence Based) -->
            <div class="hero-stats-banner hero-anim-5">
              <div class="hero-stat-item">
                <span class="stat-num text-cyan">14.3%</span>
                <span class="stat-desc">S6 实测下达到 89.04% Free-run 拟合优度 (FIT)</span>
              </div>
              <div class="hero-stat-divider"></div>
              <div class="hero-stat-item">
                <span class="stat-num text-green">16/20</span>
                <span class="stat-desc">敏感性扫描满秩；低预算由门控拦截</span>
              </div>
              <div class="hero-stat-divider"></div>
              <div class="hero-stat-item">
                <span class="stat-num text-amber">24×</span>
                <span class="stat-desc">阶段 8 闭环寻优实测</span>
              </div>
            </div>
          </div>

          <!-- Hero Tab / Interactive Switcher with Full Accessibility -->
          <div class="hero-interactive-zone hero-anim-right">
            <div class="hero-view-tabs" role="tablist" aria-label="沙盘与工作流切换">
              <button
                id="hero-tab-playground"
                type="button"
                role="tab"
                class="view-tab-btn"
                :class="{ active: heroTab === 'playground' }"
                :aria-selected="heroTab === 'playground'"
                aria-controls="hero-panel-playground"
                @click="heroTab = 'playground'"
              >
                <svg class="tab-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline>
                </svg>
                <span>实时算法与时序沙盘</span>
              </button>
              <button
                id="hero-tab-workflow"
                type="button"
                role="tab"
                class="view-tab-btn"
                :class="{ active: heroTab === 'workflow' }"
                :aria-selected="heroTab === 'workflow'"
                aria-controls="hero-panel-workflow"
                @click="heroTab = 'workflow'"
              >
                <svg class="tab-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <rect x="3" y="3" width="7" height="7"></rect>
                  <rect x="14" y="3" width="7" height="7"></rect>
                  <rect x="14" y="14" width="7" height="7"></rect>
                  <rect x="3" y="14" width="7" height="7"></rect>
                </svg>
                <span>组合工作流探查</span>
              </button>
            </div>

            <div
              id="hero-panel-playground"
              v-show="heroTab === 'playground'"
              role="tabpanel"
              aria-labelledby="hero-tab-playground"
            >
              <InteractivePlayground />
            </div>
            <div
              id="hero-panel-workflow"
              v-show="heroTab === 'workflow'"
              role="tabpanel"
              aria-labelledby="hero-tab-workflow"
            >
              <HeroWorkflow />
            </div>
          </div>
        </div>
      </section>

      <!-- 02 Benchmark Evidence Matrix (Moved up immediately after Hero) -->
      <section id="ablation-benchmark" class="landing-section section-benchmark" data-section="benchmark-evidence">
        <div class="landing-container">
          <div class="section-heading">
            <span class="section-eyebrow">ABLATION BENCHMARK</span>
            <h2>10 组独立随机种子消融对账：拒绝“黑盒玄学”</h2>
            <p>包含 200 个工作点敏感性扫描实测，直面算法优势与自身失效边界，全量数据公开可复现。</p>
          </div>
          <BenchmarkComparison />
        </div>
      </section>

      <!-- 03 Engineering Pipeline Architecture -->
      <section id="pipeline-architecture" class="landing-section section-pipeline" data-section="pipeline">
        <div class="landing-container">
          <div class="section-heading">
            <span class="section-eyebrow">ENGINEERING PIPELINE</span>
            <h2>工业建模闭环体系：从原始时序到可验证模型交付</h2>
            <p>每个环节均提供严谨的算法数学证明、物理防呆门控与不可变数据版本血缘。</p>
          </div>
          <PipelineArchitecture />
        </div>
      </section>

      <!-- 04 Unified Trusted Engineering & Lineage Traceability Zone -->
      <section
        id="trusted-engineering"
        class="landing-section section-trust"
        data-section="trusted-engineering"
      >
        <div class="landing-container">
          <div class="section-heading">
            <span class="section-eyebrow">CORE TRUST & LINEAGE</span>
            <h2>复杂工业建模，需要的不只是一个模型。</h2>
            <p>从数据版本到模型资产，再到最终评价，每个关键决定都保留真实来源与人为控制。</p>
          </div>
          <TrustedEngineering />
        </div>
      </section>

      <!-- 05 Final CTA -->
      <section class="landing-section landing-final" data-section="final-cta">
        <div class="landing-container final-layout">
          <div class="final-copy">
            <span class="final-tag font-mono">READY TO DEPLOY</span>
            <h2>把工业数据，<br />变成可验证的模型与决策。</h2>
            <p>进入现有工作台，从真实数据和可追溯工作流开始。</p>
            <div class="final-checkmarks font-mono">
              <span class="chk-item">
                <svg class="chk-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                  <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
                <span>全生命周期血缘</span>
              </span>
              <span class="chk-item">
                <svg class="chk-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                  <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
                <span>满秩 D-最优闭环</span>
              </span>
              <span class="chk-item">
                <svg class="chk-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                  <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
                <span>白盒机理自由仿真</span>
              </span>
            </div>
          </div>
          <div class="final-action-box">
            <button class="landing-button landing-button-primary final-button" type="button" @click="enterApplication">
              进入工作台
              <span class="btn-arrow" aria-hidden="true">→</span>
            </button>
          </div>
        </div>
      </section>
    </main>

    <footer class="landing-footer">
      <div class="landing-container">
        <span>IndusOpt 工模智优 · 2026 第十三届浙江省大学生服务外包创新应用大赛 A14</span>
        <span>流程工业数据建模与智能寻优平台</span>
      </div>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import BenchmarkComparison from "../components/landing/BenchmarkComparison.vue";
import HeroWorkflow from "../components/landing/HeroWorkflow.vue";
import InteractivePlayground from "../components/landing/InteractivePlayground.vue";
import LandingHeader from "../components/landing/LandingHeader.vue";
import PipelineArchitecture from "../components/landing/PipelineArchitecture.vue";
import TrustedEngineering from "../components/landing/TrustedEngineering.vue";
import { enterFromLanding } from "../router/landingEntry";

defineOptions({ name: "LandingView" });

defineProps<{
  theme: "dark" | "light";
}>();

const router = useRouter();
const route = useRoute();
const pageRoot = ref<HTMLElement | null>(null);
const reducedMotion = ref(false);
const heroTab = ref<"playground" | "workflow">("playground");

let mediaQuery: MediaQueryList | null = null;
let sectionObserver: IntersectionObserver | null = null;
let revealFrame: number | null = null;
let directionFrame: number | null = null;
let lastScrollY = 0;
let scrollDirection: "down" | "up" = "down";
const pendingReveal = new Set<HTMLElement>();
const SCROLL_DIRECTION_DEAD_ZONE = 4;

function enterApplication() {
  void enterFromLanding(router, route.query.next);
}

function scrollToBenchmark() {
  document.getElementById("ablation-benchmark")?.scrollIntoView({
    behavior: reducedMotion.value ? "auto" : "smooth",
    block: "start",
  });
}

function updateMotionPreference(event: MediaQueryListEvent | MediaQueryList) {
  reducedMotion.value = event.matches;
}

function setRevealOrigin(section: HTMLElement, direction: "down" | "up") {
  section.classList.toggle("reveal-from-bottom", direction === "down");
  section.classList.toggle("reveal-from-top", direction === "up");
}

function updateScrollDirection() {
  directionFrame = null;
  const currentScrollY = window.scrollY;
  const delta = currentScrollY - lastScrollY;
  if (Math.abs(delta) < SCROLL_DIRECTION_DEAD_ZONE) return;

  scrollDirection = delta > 0 ? "down" : "up";
  lastScrollY = currentScrollY;
}

function trackScrollDirection() {
  if (directionFrame !== null) return;
  directionFrame = window.requestAnimationFrame(updateScrollDirection);
}

function queueSectionReveal(section: HTMLElement) {
  pendingReveal.add(section);
  if (revealFrame !== null) return;
  revealFrame = window.requestAnimationFrame(() => {
    pendingReveal.forEach((pendingSection) => pendingSection.classList.add("is-visible"));
    pendingReveal.clear();
    revealFrame = null;
  });
}

function revealSections() {
  const sections = pageRoot.value?.querySelectorAll<HTMLElement>(".landing-section");
  if (!sections) return;

  sections.forEach((section) => setRevealOrigin(section, "down"));

  if (reducedMotion.value || typeof IntersectionObserver === "undefined") {
    sections.forEach((section) => section.classList.add("is-visible"));
    return;
  }

  sectionObserver = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        const section = entry.target as HTMLElement;
        if (entry.isIntersecting) {
          setRevealOrigin(section, scrollDirection);
          queueSectionReveal(section);
          sectionObserver?.unobserve(section);
        }
      });
    },
    { threshold: 0, rootMargin: "-12% 0px -12%" }
  );
  sections.forEach((section) => sectionObserver?.observe(section));
}

onMounted(() => {
  if (typeof window.matchMedia === "function") {
    mediaQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    updateMotionPreference(mediaQuery);
    mediaQuery.addEventListener("change", updateMotionPreference);
  }
  if (!reducedMotion.value) {
    lastScrollY = window.scrollY;
    window.addEventListener("scroll", trackScrollDirection, { passive: true });
  }
  revealSections();
});

onBeforeUnmount(() => {
  mediaQuery?.removeEventListener("change", updateMotionPreference);
  window.removeEventListener("scroll", trackScrollDirection);
  sectionObserver?.disconnect();
  if (directionFrame !== null) window.cancelAnimationFrame(directionFrame);
  if (revealFrame !== null) window.cancelAnimationFrame(revealFrame);
  pendingReveal.clear();
});
</script>

<style scoped>
.landing-preview {
  position: relative;
  --landing-radius: 6px;
  min-width: 320px;
  min-height: 100dvh;
  overflow-x: hidden;
  background: var(--landing-bg);
  color: var(--landing-text);
  font-family: var(--font-sans);
}

.landing-preview::before {
  position: absolute;
  inset: 0;
  pointer-events: none;
  content: "";
  background-image:
    linear-gradient(var(--landing-grid) 1px, transparent 1px),
    linear-gradient(90deg, var(--landing-grid) 1px, transparent 1px);
  background-size: 44px 44px;
  opacity: 0.65;
  z-index: 0;
}

.landing-preview[data-theme="light"] {
  --landing-bg: #f8fafc;
  --landing-surface: #ffffff;
  --landing-surface-active: #ffffff;
  --landing-surface-tinted: #f1f5f9;
  --landing-node-bg: #f8fafc;
  --landing-text: #0f172a;
  --landing-muted: #64748b;
  --landing-faint: #64748b;
  --landing-accent: #2563eb;
  --landing-accent-strong: #1d4ed8;
  --landing-accent-contrast: #ffffff;
  --landing-accent-soft: rgba(37, 99, 235, 0.08);
  --landing-border: #e2e8f0;
  --landing-border-strong: #cbd5e1;
  --landing-border-active: #2563eb;
  --landing-grid: rgba(203, 213, 225, 0.55);
  --landing-highlight: rgba(37, 99, 235, 0.06);
  --landing-header-bg: rgba(248, 250, 252, 0.92);
  --landing-shadow: 0 16px 40px rgba(15, 23, 42, 0.06);
  color-scheme: light;
}

.landing-preview[data-theme="dark"] {
  --landing-bg: #f8fafc;
  --landing-surface: #ffffff;
  --landing-surface-active: #ffffff;
  --landing-surface-tinted: #f1f5f9;
  --landing-node-bg: #f8fafc;
  --landing-text: #0f172a;
  --landing-muted: #64748b;
  --landing-faint: #64748b;
  --landing-accent: #2563eb;
  --landing-accent-strong: #1d4ed8;
  --landing-accent-contrast: #ffffff;
  --landing-accent-soft: rgba(37, 99, 235, 0.08);
  --landing-border: #e2e8f0;
  --landing-border-strong: #cbd5e1;
  --landing-border-active: #2563eb;
  --landing-grid: rgba(203, 213, 225, 0.55);
  --landing-highlight: rgba(37, 99, 235, 0.06);
  --landing-header-bg: rgba(248, 250, 252, 0.92);
  --landing-shadow: 0 16px 40px rgba(15, 23, 42, 0.06);
  color-scheme: light;
}

.landing-container {
  position: relative;
  z-index: 1;
  width: min(100% - 44px, 1380px);
  margin-inline: auto;
}

/* Scroll Triggered Smooth Slide-in / Slide-out Animation */
.landing-section {
  position: relative;
  padding: clamp(48px, 6vw, 84px) 0;
  scroll-margin-top: 72px;
  opacity: 0;
  transform: translateY(28px) scale(0.992);
  transition:
    opacity 560ms cubic-bezier(0.16, 1, 0.3, 1),
    transform 560ms cubic-bezier(0.16, 1, 0.3, 1);
  will-change: opacity, transform;
}

.landing-section.reveal-from-bottom {
  transform: translateY(28px) scale(0.992);
}

.landing-section.reveal-from-top {
  transform: translateY(-24px) scale(0.992);
}

.landing-section.is-visible {
  opacity: 1;
  transform: translateY(0) scale(1);
}

/* Hero Staggered Entrance Animations */
@keyframes heroFadeInUp {
  from {
    opacity: 0;
    transform: translateY(24px) scale(0.985);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

.hero-anim-1 {
  animation: heroFadeInUp 0.6s cubic-bezier(0.16, 1, 0.3, 1) 0.05s backwards;
}

.hero-anim-2 {
  animation: heroFadeInUp 0.65s cubic-bezier(0.16, 1, 0.3, 1) 0.12s backwards;
}

.hero-anim-3 {
  animation: heroFadeInUp 0.7s cubic-bezier(0.16, 1, 0.3, 1) 0.2s backwards;
}

.hero-anim-4 {
  animation: heroFadeInUp 0.75s cubic-bezier(0.16, 1, 0.3, 1) 0.28s backwards;
}

.hero-anim-5 {
  animation: heroFadeInUp 0.8s cubic-bezier(0.16, 1, 0.3, 1) 0.36s backwards;
}

.hero-anim-right {
  animation: heroFadeInUp 0.85s cubic-bezier(0.16, 1, 0.3, 1) 0.18s backwards;
}

/* Hero Section */
.landing-hero {
  position: relative;
  display: flex;
  align-items: center;
  min-height: calc(100dvh - 72px);
  padding: clamp(24px, 4vw, 56px) 0;
}

.hero-grid {
  display: grid;
  grid-template-columns: minmax(360px, 1.15fr) minmax(420px, 1.35fr);
  gap: clamp(32px, 4vw, 56px);
  align-items: center;
}

.hero-copy {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.hero-eyebrow {
  display: inline-block;
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 700;
  color: var(--landing-accent);
  letter-spacing: 0.1em;
}

.hero-copy h1 {
  margin: 0;
  display: flex;
  flex-direction: column;
  font-size: clamp(34px, 3.8vw, 50px);
  font-weight: 800;
  line-height: 1.18;
  letter-spacing: -0.035em;
  color: var(--landing-text);
}

.hero-subtitle {
  margin: 0;
  color: var(--landing-muted);
  font-size: 14px;
  line-height: 1.65;
  max-width: 580px;
}

.hero-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 4px;
}

.landing-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 42px;
  padding: 0 20px;
  border-radius: var(--landing-radius);
  border: 1px solid transparent;
  cursor: pointer;
  font-size: 14px;
  font-weight: 700;
  white-space: nowrap;
  transition: all 0.22s cubic-bezier(0.16, 1, 0.3, 1);
}

.landing-button-primary {
  border-color: var(--landing-accent);
  background: var(--landing-accent);
  color: var(--landing-accent-contrast);
  box-shadow: 0 4px 14px rgba(37, 99, 235, 0.22);
}

.landing-button-primary:hover {
  border-color: var(--landing-accent-strong);
  background: var(--landing-accent-strong);
  box-shadow: 0 8px 24px rgba(37, 99, 235, 0.38);
  transform: translateY(-2px);
}

.btn-arrow {
  display: inline-block;
  transition: transform 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}

.landing-button-primary:hover .btn-arrow {
  transform: translateX(4px);
}

.landing-button-secondary {
  border-color: var(--landing-border-strong);
  background: #ffffff;
  color: var(--landing-text);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
}

.landing-button-secondary:hover {
  border-color: var(--landing-accent);
  background: var(--landing-accent-soft);
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
}

/* 3 Hardcore Metric Highlights */
.hero-stats-banner {
  display: grid;
  grid-template-columns: 1fr auto 1fr auto 1fr;
  align-items: center;
  gap: 14px;
  margin-top: 14px;
  padding: 14px 18px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.03);
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

.hero-stats-banner:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);
  border-color: #cbd5e1;
}

.hero-stat-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.stat-num {
  font-family: var(--font-mono);
  font-size: 18px;
  font-weight: 800;
  line-height: 1.1;
}

.text-cyan { color: #0284c7; }
.text-green { color: #059669; }
.text-amber { color: #d97706; }

.stat-desc {
  font-size: 10px;
  color: #64748b;
  line-height: 1.35;
}

.hero-stat-divider {
  width: 1px;
  height: 28px;
  background: #e2e8f0;
}

/* Hero Right Interactive Zone */
.hero-interactive-zone {
  display: flex;
  flex-direction: column;
  gap: 12px;
  transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}

.hero-view-tabs {
  display: inline-flex;
  background: #e2e8f0;
  padding: 3px;
  border-radius: 8px;
  align-self: flex-start;
  gap: 2px;
}

.view-tab-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border: none;
  background: transparent;
  color: #64748b;
  font-size: 12px;
  font-weight: 600;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.18s ease;
  white-space: nowrap;
}

.view-tab-btn:hover {
  color: #0f172a;
}

.view-tab-btn.active {
  background: #ffffff;
  color: #0f172a;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
}

.tab-svg {
  width: 13px;
  height: 13px;
}

/* Section Headings */
.section-heading {
  margin-bottom: 24px;
}

.section-eyebrow {
  display: block;
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 700;
  color: var(--landing-accent);
  letter-spacing: 0.1em;
  margin-bottom: 8px;
}

.section-heading h2,
.landing-final h2 {
  margin: 0;
  color: var(--landing-text);
  font-size: clamp(26px, 3vw, 38px);
  font-weight: 700;
  line-height: 1.25;
  letter-spacing: -0.025em;
}

.section-heading p {
  max-width: 680px;
  margin: 10px 0 0;
  color: #64748b;
  font-size: 14px;
  line-height: 1.6;
}

.section-trust,
.section-pipeline,
.section-benchmark {
  border-top: 1px solid var(--landing-border);
}

/* Final CTA Section (Glacier Slate Theme) */
.landing-final {
  padding: clamp(48px, 6vw, 84px) 0;
  border-top: 1px solid var(--landing-border);
}

.final-layout {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 40px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: clamp(32px, 5vw, 48px);
  box-shadow: 0 12px 36px rgba(15, 23, 42, 0.04);
  position: relative;
  overflow: hidden;
  transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}

.final-layout::before {
  position: absolute;
  right: -40px;
  bottom: -40px;
  width: 280px;
  height: 280px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(37, 99, 235, 0.06) 0%, transparent 70%);
  pointer-events: none;
  content: "";
}

.final-layout:hover {
  transform: translateY(-2px);
  box-shadow: 0 18px 44px rgba(15, 23, 42, 0.08);
  border-color: #cbd5e1;
}

.final-copy {
  display: flex;
  flex-direction: column;
  gap: 8px;
  position: relative;
  z-index: 1;
}

.final-tag {
  font-size: 10px;
  font-weight: 700;
  color: #2563eb;
  letter-spacing: 0.1em;
}

.final-copy h2 {
  margin: 0;
  color: #0f172a;
  font-size: clamp(26px, 3vw, 36px);
  font-weight: 800;
  line-height: 1.25;
  letter-spacing: -0.025em;
}

.final-copy p {
  max-width: 580px;
  margin: 4px 0 8px;
  color: #64748b;
  font-size: 14px;
  line-height: 1.65;
}

.final-checkmarks {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  margin-top: 4px;
}

.chk-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  font-weight: 600;
  color: #475569;
}

.chk-svg {
  width: 13px;
  height: 13px;
  color: #059669;
  flex-shrink: 0;
}

.final-action-box {
  position: relative;
  z-index: 1;
}

.final-button {
  min-width: 160px;
  background: #2563eb !important;
  color: #ffffff !important;
  border-color: #2563eb !important;
  box-shadow: 0 4px 14px rgba(37, 99, 235, 0.25);
}

.final-button:hover {
  background: #1d4ed8 !important;
  border-color: #1d4ed8 !important;
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(37, 99, 235, 0.4);
}

.landing-footer {
  border-top: 1px solid var(--landing-border);
  color: #64748b;
}

.landing-footer .landing-container {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 64px;
  gap: 24px;
  font-size: 12px;
}

.font-mono {
  font-family: var(--font-mono);
}

@media (max-width: 1100px) {
  .hero-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .hero-stats-banner {
    grid-template-columns: 1fr;
    gap: 10px;
  }
  .hero-stat-divider {
    display: none;
  }
  .final-layout {
    flex-direction: column;
    align-items: flex-start;
    gap: 24px;
  }
  .landing-footer .landing-container {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
    padding: 16px 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .landing-section,
  .hero-anim-1,
  .hero-anim-2,
  .hero-anim-3,
  .hero-anim-4,
  .hero-anim-5,
  .hero-anim-right {
    animation: none !important;
    transition: none !important;
    transform: none !important;
  }
}
</style>
