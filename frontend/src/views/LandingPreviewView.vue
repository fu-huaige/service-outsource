<template>
  <div
    ref="pageRoot"
    class="landing-preview"
    :data-theme="theme"
    :data-reduced-motion="reducedMotion ? 'true' : 'false'"
  >
    <LandingHeader @explore="navigateToDashboard" />

    <main id="landing-top">
      <section class="landing-hero landing-section" data-section="hero">
        <div class="landing-container hero-grid">
          <div class="hero-copy">
            <span class="hero-eyebrow">INDUSTRIAL INTELLIGENCE</span>
            <h1>
              <span>让工业建模，</span>
              <span>从数据走向闭环决策</span>
            </h1>
            <p class="hero-subtitle">Agent 驱动的流程工业数据建模与智能寻优平台</p>
            <div class="hero-actions">
              <button class="landing-button landing-button-primary" type="button" @click="navigateToDashboard">
                开始探索
                <span aria-hidden="true">→</span>
              </button>
              <button class="landing-button landing-button-secondary" type="button" @click="scrollToWorkflow">
                查看工作流程
              </button>
            </div>
          </div>
          <HeroWorkflow />
        </div>
      </section>

      <section
        id="trusted-engineering"
        class="landing-section section-trust"
        data-section="trusted-engineering"
      >
        <div class="landing-container">
          <div class="section-heading">
            <h2>复杂工业建模，需要的不只是一个模型。</h2>
            <p>从数据版本到模型资产，再到最终评价，每个关键决定都保留真实来源与人为控制。</p>
          </div>
          <TrustedEngineering />
        </div>
      </section>

      <section id="agent-workflow" class="landing-section section-agent" data-section="agent-workflow">
        <div class="landing-container">
          <div class="section-heading section-heading-narrow">
            <h2>从一句工程目标，到一条可确认的执行路径。</h2>
            <p>Agent 负责组织正式工具与依赖关系，确认门控仍由工程人员掌握。</p>
          </div>
          <AgentWorkflowShowcase />
        </div>
      </section>

      <section id="dataset-lineage" class="landing-section section-lineage" data-section="dataset-lineage">
        <div class="landing-container">
          <div class="section-heading section-heading-narrow">
            <h2>数据不会被覆盖，每一步都有来路。</h2>
            <p>不可变派生版本把数据处理、建模来源与最终结果连接成可审计的证据链。</p>
          </div>
          <LineageDiagram />
        </div>
      </section>

      <section class="landing-section section-model" data-section="model-lifecycle">
        <div class="landing-container">
          <div class="section-heading">
            <h2>模型、寻优与评价，保持清晰边界。</h2>
            <p>ARX 结构、Validation 搜索、Saved Model 与 held-out Test 各自承担明确职责。</p>
          </div>
          <ModelLifecycle />
        </div>
      </section>

      <section class="landing-section landing-final" data-section="final-cta">
        <div class="landing-container final-layout">
          <div>
            <h2>把工业数据，<br />变成可验证的模型与决策。</h2>
            <p>进入现有工作台，从真实数据和可追溯工作流开始。</p>
          </div>
          <button class="landing-button landing-button-primary final-button" type="button" @click="navigateToDashboard">
            开始探索
            <span aria-hidden="true">→</span>
          </button>
        </div>
      </section>
    </main>

    <footer class="landing-footer">
      <div class="landing-container">
        <span>IndusOpt 工模智优</span>
        <span>流程工业数据建模与智能寻优平台</span>
      </div>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import AgentWorkflowShowcase from "../components/landing/AgentWorkflowShowcase.vue";
import HeroWorkflow from "../components/landing/HeroWorkflow.vue";
import LandingHeader from "../components/landing/LandingHeader.vue";
import LineageDiagram from "../components/landing/LineageDiagram.vue";
import ModelLifecycle from "../components/landing/ModelLifecycle.vue";
import TrustedEngineering from "../components/landing/TrustedEngineering.vue";

defineProps<{
  theme: "dark" | "light";
}>();

const router = useRouter();
const pageRoot = ref<HTMLElement | null>(null);
const reducedMotion = ref(false);
let mediaQuery: MediaQueryList | null = null;
let sectionObserver: IntersectionObserver | null = null;
let revealFrame: number | null = null;
let directionFrame: number | null = null;
let lastScrollY = 0;
let scrollDirection: "down" | "up" = "down";
const visibleSections = new WeakSet<HTMLElement>();
const pendingReveal = new Set<HTMLElement>();
const SCROLL_DIRECTION_DEAD_ZONE = 4;

function navigateToDashboard() {
  void router.push("/dashboard");
}

function scrollToWorkflow() {
  document.getElementById("agent-workflow")?.scrollIntoView({
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

function resetSection(section: HTMLElement, direction: "down" | "up") {
  pendingReveal.delete(section);
  section.classList.remove("is-visible");
  setRevealOrigin(section, direction);
  visibleSections.delete(section);
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
          visibleSections.add(section);
          queueSectionReveal(section);
        } else if (visibleSections.has(section)) {
          resetSection(section, scrollDirection);
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
  --landing-radius: 3px;
  min-width: 320px;
  min-height: 100dvh;
  overflow-x: hidden;
  background: var(--landing-bg);
  color: var(--landing-text);
  color-scheme: dark;
  font-family: var(--font-family);
  scroll-behavior: smooth;
}

.landing-preview[data-theme="dark"] {
  --landing-bg: #081118;
  --landing-surface: #0c1922;
  --landing-surface-active: #10212c;
  --landing-surface-tinted: #0a151d;
  --landing-node-bg: rgb(15 31 42 / 0.88);
  --landing-text: #eef0e8;
  --landing-muted: #9baab2;
  --landing-faint: #667983;
  --landing-accent: #63add3;
  --landing-accent-strong: #83c4e5;
  --landing-accent-contrast: #071016;
  --landing-accent-soft: rgb(99 173 211 / 0.1);
  --landing-border: rgb(156 185 199 / 0.15);
  --landing-border-strong: rgb(156 185 199 / 0.28);
  --landing-border-active: rgb(99 173 211 / 0.52);
  --landing-grid: rgb(145 175 190 / 0.055);
  --landing-highlight: rgb(78 153 191 / 0.12);
  --landing-header-bg: rgb(8 17 24 / 0.92);
  --landing-shadow: 0 28px 70px rgb(0 5 10 / 0.26);
}

.landing-preview[data-theme="light"] {
  --landing-bg: #f4f3ee;
  --landing-surface: #fbfaf6;
  --landing-surface-active: #f7f9f7;
  --landing-surface-tinted: #edf2f2;
  --landing-node-bg: rgb(248 249 246 / 0.94);
  --landing-text: #18262d;
  --landing-muted: #5d6c72;
  --landing-faint: #8b989d;
  --landing-accent: #236d98;
  --landing-accent-strong: #174f70;
  --landing-accent-contrast: #f7faf8;
  --landing-accent-soft: rgb(35 109 152 / 0.08);
  --landing-border: rgb(45 73 84 / 0.14);
  --landing-border-strong: rgb(45 73 84 / 0.25);
  --landing-border-active: rgb(35 109 152 / 0.48);
  --landing-grid: rgb(41 83 102 / 0.045);
  --landing-highlight: rgb(35 109 152 / 0.08);
  --landing-header-bg: rgb(244 243 238 / 0.92);
  --landing-shadow: 0 28px 70px rgb(42 63 71 / 0.09);
  color-scheme: light;
}

.landing-container {
  width: min(100% - 44px, 1320px);
  margin-inline: auto;
}

.landing-section {
  position: relative;
  padding: clamp(86px, 10vw, 150px) 0;
  scroll-margin-top: 72px;
}

.landing-section {
  opacity: 0;
  transition: opacity 780ms cubic-bezier(0.16, 1, 0.3, 1), transform 780ms cubic-bezier(0.16, 1, 0.3, 1);
}

.landing-section.reveal-from-bottom {
  transform: translateY(16px);
}

.landing-section.reveal-from-top {
  transform: translateY(-20px);
}

.landing-section.is-visible {
  opacity: 1;
  transform: translateY(0);
}

.landing-hero {
  display: flex;
  align-items: center;
  min-height: calc(100dvh - 72px);
  padding: clamp(46px, 7vw, 90px) 0;
}

.landing-hero::before,
.landing-hero::after {
  position: absolute;
  pointer-events: none;
  content: "";
}

.landing-hero::before {
  inset: 0;
  background-image:
    linear-gradient(var(--landing-grid) 1px, transparent 1px),
    linear-gradient(90deg, var(--landing-grid) 1px, transparent 1px);
  background-size: 56px 56px;
  mask-image: linear-gradient(to bottom, black, transparent 88%);
}

.landing-hero::after {
  top: 0;
  bottom: 0;
  left: 50%;
  width: 1px;
  background: var(--landing-border);
  opacity: 0.7;
}

.hero-grid {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: minmax(390px, 0.82fr) minmax(0, 1.18fr);
  align-items: center;
  gap: clamp(42px, 6vw, 92px);
}

.hero-copy {
  padding: 10px 0;
}

.hero-eyebrow {
  display: block;
  margin-bottom: 28px;
  color: var(--landing-accent);
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.14em;
}

.hero-copy h1 {
  max-width: 720px;
  margin: 0;
  color: var(--landing-text);
  font-size: clamp(44px, 5.2vw, 72px);
  font-weight: 650;
  line-height: 1.12;
  letter-spacing: -0.055em;
}

.hero-copy h1 span {
  display: block;
  white-space: nowrap;
}

.hero-subtitle {
  max-width: 560px;
  margin: 30px 0 0;
  color: var(--landing-muted);
  font-size: clamp(16px, 1.5vw, 20px);
  line-height: 1.65;
}

.hero-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 38px;
}

.landing-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 14px;
  min-height: 48px;
  padding: 0 22px;
  border: 1px solid transparent;
  border-radius: var(--landing-radius);
  cursor: pointer;
  font-size: 14px;
  font-weight: 700;
  white-space: nowrap;
  transition: background-color 320ms ease, border-color 320ms ease, color 320ms ease, transform 180ms ease;
}

.landing-button-primary {
  border-color: var(--landing-accent);
  background: var(--landing-accent);
  color: var(--landing-accent-contrast);
}

.landing-button-primary:hover {
  border-color: var(--landing-accent-strong);
  background: var(--landing-accent-strong);
}

.landing-button-secondary {
  border-color: var(--landing-border-strong);
  background: transparent;
  color: var(--landing-text);
}

.landing-button-secondary:hover {
  border-color: var(--landing-accent);
  background: var(--landing-accent-soft);
}

.landing-button:active {
  transform: translateY(1px);
}

.landing-button:focus-visible {
  outline: 2px solid var(--landing-accent);
  outline-offset: 4px;
}

.section-heading {
  max-width: 820px;
  margin-bottom: clamp(42px, 6vw, 76px);
}

.section-heading-narrow {
  max-width: 720px;
}

.section-heading h2,
.landing-final h2 {
  margin: 0;
  color: var(--landing-text);
  font-size: clamp(34px, 4.2vw, 58px);
  font-weight: 620;
  line-height: 1.18;
  letter-spacing: -0.05em;
}

.section-heading p {
  max-width: 620px;
  margin: 22px 0 0;
  color: var(--landing-muted);
  font-size: 15px;
  line-height: 1.8;
}

.section-trust {
  border-top: 1px solid var(--landing-border);
}

.section-agent::before,
.section-lineage::before,
.section-model::before {
  position: absolute;
  top: 0;
  right: max(22px, calc((100vw - 1320px) / 2));
  left: max(22px, calc((100vw - 1320px) / 2));
  height: 1px;
  background: var(--landing-border);
  content: "";
}

.section-lineage {
  background: var(--landing-surface-tinted);
}

.landing-final {
  padding-top: clamp(100px, 13vw, 190px);
  padding-bottom: clamp(100px, 13vw, 190px);
  border-top: 1px solid var(--landing-border-strong);
}

.final-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: end;
  gap: 48px;
}

.landing-final p {
  max-width: 520px;
  margin: 25px 0 0;
  color: var(--landing-muted);
  font-size: 15px;
  line-height: 1.7;
}

.final-button {
  min-width: 170px;
}

.landing-footer {
  border-top: 1px solid var(--landing-border);
  color: var(--landing-faint);
}

.landing-footer .landing-container {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 88px;
  gap: 24px;
  font-size: 12px;
}

@media (max-width: 1100px) {
  .landing-hero::after {
    display: none;
  }

  .hero-grid {
    grid-template-columns: 1fr;
  }

  .hero-copy {
    max-width: 760px;
  }

  .landing-hero {
    min-height: auto;
  }
}

@media (max-width: 720px) {
  .landing-container {
    width: min(100% - 32px, 1320px);
  }

  .landing-section {
    padding: 76px 0;
    scroll-margin-top: 64px;
  }

  .landing-hero {
    padding-top: 46px;
  }

  .hero-grid {
    gap: 48px;
  }

  .hero-copy h1 {
    font-size: clamp(37px, 10.8vw, 54px);
    line-height: 1.16;
  }

  .hero-copy h1 span {
    white-space: normal;
  }

  .hero-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .landing-button {
    width: 100%;
  }

  .final-layout {
    grid-template-columns: 1fr;
    align-items: start;
  }

  .final-button {
    width: auto;
    justify-self: start;
  }

  .landing-footer .landing-container {
    align-items: flex-start;
    flex-direction: column;
    justify-content: center;
    gap: 6px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .landing-preview {
    scroll-behavior: auto;
  }

  .landing-section,
  .landing-button {
    opacity: 1 !important;
    transform: none !important;
    transition: none !important;
  }
}
</style>
