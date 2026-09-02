<template>
  <div class="landing" ref="pageRoot">
    <!-- ── Header ─────────────────────────────────────────── -->
    <header class="landing-header">
      <div class="landing-container landing-header__inner">
        <div class="landing-logo">
          <div class="landing-logo__mark">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 2L2 7l10 5 10-5-10-5z"/>
              <path d="M2 17l10 5 10-5"/>
              <path d="M2 12l10 5 10-5"/>
            </svg>
          </div>
          <span class="landing-logo__name">IndusOpt</span>
          <span class="landing-logo__tag font-mono">A14</span>
        </div>
        <nav class="landing-nav">
          <button type="button" class="landing-nav__item" @click="scrollToSection('features')">功能</button>
          <button type="button" class="landing-nav__item" @click="scrollToSection('workflow')">流程</button>
          <button type="button" class="landing-nav__item" @click="scrollToSection('benchmark')">基准</button>
          <button type="button" class="landing-nav__cta" @click="enterApp">进入工作台</button>
        </nav>
      </div>
    </header>

    <!-- ── Hero ───────────────────────────────────────────── -->
    <section class="landing-hero">
      <div class="landing-container">
        <div class="hero-eyebrow font-mono">INDUSTRIAL AI AGENT WORKSPACE</div>
        <h1 class="hero-title">
          <span>让工业建模，</span>
          <span class="hero-title__accent">从数据走向闭环决策</span>
        </h1>
        <p class="hero-subtitle">
          面向流程工业建模工程师。导入多变量时序数据，Agent 自动完成质量门控、D-最优优选、
          ARX 辨识与 Optuna 寻优，全程可追溯、可审核。
        </p>
        <div class="hero-actions">
          <button type="button" class="btn-primary" @click="enterApp">
            进入工作台
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="14" height="14" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg>
          </button>
          <button type="button" class="btn-ghost" @click="scrollToSection('benchmark')">查看实测基准</button>
        </div>

        <!-- Stats strip -->
        <div class="hero-stats">
          <div class="hero-stat">
            <div class="hero-stat__num font-mono">89.0%</div>
            <div class="hero-stat__desc">S6 Free-run FIT</div>
          </div>
          <div class="hero-stat-div"></div>
          <div class="hero-stat">
            <div class="hero-stat__num font-mono">8</div>
            <div class="hero-stat__desc">自动化建模阶段</div>
          </div>
          <div class="hero-stat-div"></div>
          <div class="hero-stat">
            <div class="hero-stat__num font-mono">24×</div>
            <div class="hero-stat__desc">闭环寻优实测</div>
          </div>
          <div class="hero-stat-div"></div>
          <div class="hero-stat">
            <div class="hero-stat__num font-mono">S1~S6</div>
            <div class="hero-stat__desc">标准工况覆盖</div>
          </div>
        </div>
      </div>

      <!-- Agent preview terminal -->
      <div class="landing-container">
        <div class="hero-terminal">
          <div class="hero-terminal__bar">
            <div class="hero-terminal__dots">
              <span /><span /><span />
            </div>
            <span class="hero-terminal__title font-mono">IndusOpt Agent Workspace</span>
            <span class="hero-terminal__status font-mono">
              <span class="status-dot running" style="display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--color-success);margin-right:5px" />
              Backend Ready
            </span>
          </div>
          <div class="hero-terminal__body">
            <!-- User prompt -->
            <div class="ht-msg ht-msg--user">
              <div class="ht-msg__avatar">U</div>
              <div class="ht-msg__text">分析 S3 工况时序数据，建立 ARX 动态模型，寻找最优参数</div>
            </div>
            <!-- Agent plan -->
            <div class="ht-msg ht-msg--agent">
              <div class="ht-msg__avatar ht-msg__avatar--agent">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="12" height="12" stroke-linecap="round" stroke-linejoin="round"><rect width="18" height="10" x="3" y="11" rx="2"/><circle cx="12" cy="5" r="2"/><path d="M12 7v4"/></svg>
              </div>
              <div class="ht-plan">
                <div class="ht-plan__label font-mono">AGENT PLAN · 8 STEPS</div>
                <div class="ht-steps">
                  <div class="ht-step ht-step--done">
                    <span class="ht-step__dot done" />
                    <span class="ht-step__name">data_profile</span>
                    <span class="ht-step__time font-mono">0.3s</span>
                  </div>
                  <div class="ht-step ht-step--done">
                    <span class="ht-step__dot done" />
                    <span class="ht-step__name">clean</span>
                    <span class="ht-step__time font-mono">1.1s</span>
                  </div>
                  <div class="ht-step ht-step--done">
                    <span class="ht-step__dot done" />
                    <span class="ht-step__name">segment</span>
                    <span class="ht-step__time font-mono">2.4s</span>
                  </div>
                  <div class="ht-step ht-step--running">
                    <span class="ht-step__dot running" />
                    <span class="ht-step__name">delay_analyze</span>
                    <span class="ht-step__spinner font-mono">…</span>
                  </div>
                  <div class="ht-step ht-step--pending">
                    <span class="ht-step__dot pending" />
                    <span class="ht-step__name font-mono" style="color:var(--text-faint)">arx_fit</span>
                  </div>
                  <div class="ht-step ht-step--pending">
                    <span class="ht-step__dot pending" />
                    <span class="ht-step__name font-mono" style="color:var(--text-faint)">evaluate_model</span>
                  </div>
                  <div class="ht-step ht-step--pending">
                    <span class="ht-step__dot pending" />
                    <span class="ht-step__name font-mono" style="color:var(--text-faint)">optimize_pipeline</span>
                  </div>
                  <div class="ht-step ht-step--pending">
                    <span class="ht-step__dot pending" />
                    <span class="ht-step__name font-mono" style="color:var(--text-faint)">generate_report</span>
                  </div>
                </div>
              </div>
            </div>
            <!-- Tool event -->
            <div class="ht-event">
              <span class="ht-event__icon">🔬</span>
              <span class="ht-event__tool font-mono">delay_analyze</span>
              <span class="ht-event__desc">估计 u1→y 互相关时滞，预白化处理中…</span>
              <div class="agent-working-dot" />
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- ── Features ────────────────────────────────────────── -->
    <section class="landing-section" id="features">
      <div class="landing-container">
        <div class="section-label font-mono">CAPABILITIES</div>
        <h2 class="section-title">专为流程工业建模设计</h2>
        <p class="section-subtitle">从原始时序数据到经过验证的 ARX 动态模型，全自动 8 阶段流程</p>

        <div class="features-grid">
          <div v-for="f in features" :key="f.title" class="feature-card">
            <div class="feature-card__icon">{{ f.icon }}</div>
            <div class="feature-card__title">{{ f.title }}</div>
            <div class="feature-card__desc">{{ f.desc }}</div>
          </div>
        </div>
      </div>
    </section>

    <!-- ── Workflow ─────────────────────────────────────────── -->
    <section class="landing-section" id="workflow">
      <div class="landing-container">
        <div class="section-label font-mono">8-STAGE PIPELINE</div>
        <h2 class="section-title">Agent 自动执行完整建模闭环</h2>

        <div class="workflow-steps">
          <div v-for="(step, i) in workflowSteps" :key="step.name" class="workflow-step">
            <div class="workflow-step__num font-mono">{{ String(i + 1).padStart(2, '0') }}</div>
            <div class="workflow-step__body">
              <div class="workflow-step__name">{{ step.name }}</div>
              <div class="workflow-step__desc">{{ step.desc }}</div>
            </div>
            <div class="workflow-step__badge" :class="step.type">{{ step.label }}</div>
          </div>
        </div>
      </div>
    </section>

    <!-- ── Benchmark ────────────────────────────────────────── -->
    <section class="landing-section" id="benchmark">
      <div class="landing-container">
        <div class="section-label font-mono">ABLATION RESULTS</div>
        <h2 class="section-title">消融对照实测基准</h2>
        <p class="section-subtitle">S3 工况下四种策略对照，所有指标均来自保留测试集</p>

        <div class="benchmark-table">
          <div class="bm-header">
            <div class="bm-cell">策略</div>
            <div class="bm-cell bm-cell--num">FIT (%)</div>
            <div class="bm-cell bm-cell--num">R²</div>
            <div class="bm-cell bm-cell--num">RMSE</div>
            <div class="bm-cell bm-cell--num">Free-FIT (%)</div>
          </div>
          <div
            v-for="row in benchmarkRows"
            :key="row.strategy"
            class="bm-row"
            :class="{ 'bm-row--highlight': row.highlight }"
          >
            <div class="bm-cell">
              <span class="bm-strategy">{{ row.strategy }}</span>
              <span v-if="row.highlight" class="bm-badge font-mono">BEST</span>
            </div>
            <div class="bm-cell bm-cell--num font-mono">{{ row.fit }}</div>
            <div class="bm-cell bm-cell--num font-mono">{{ row.r2 }}</div>
            <div class="bm-cell bm-cell--num font-mono">{{ row.rmse }}</div>
            <div class="bm-cell bm-cell--num font-mono">{{ row.freeFit }}</div>
          </div>
        </div>
      </div>
    </section>

    <!-- ── HITL Section ─────────────────────────────────────── -->
    <section class="landing-section">
      <div class="landing-container">
        <div class="section-label font-mono">HUMAN-IN-THE-LOOP</div>
        <h2 class="section-title">高影响操作，人工审核确认</h2>
        <p class="section-subtitle">Agent 在时滞补偿、特征筛选、ARX 结构三个节点触发人工确认，而不是静默执行</p>

        <div class="hitl-demo">
          <div class="hitl-card">
            <div class="hitl-card__header">
              <div class="hitl-card__icon">⚠</div>
              <div>
                <div class="hitl-card__title">需要你的确认</div>
                <div class="hitl-card__sub font-mono">时滞补偿</div>
              </div>
            </div>
            <div class="hitl-card__body">
              <p class="hitl-card__desc">Agent 估计了以下变量的时滞量，请审查后确认：</p>
              <div class="hitl-lag-row">
                <span class="font-mono">u1</span>
                <span class="font-mono hitl-lag-val">推荐: 4 采样点</span>
              </div>
              <div class="hitl-lag-row">
                <span class="font-mono">u2</span>
                <span class="font-mono hitl-lag-val">推荐: 2 采样点</span>
              </div>
            </div>
            <div class="hitl-card__actions">
              <button type="button" class="hitl-btn-reject">拒绝</button>
              <button type="button" class="hitl-btn-approve">批准并继续 ✓</button>
            </div>
          </div>
          <div class="hitl-desc">
            <div class="hitl-desc__item">
              <div class="hitl-desc__num font-mono">01</div>
              <div>
                <div class="hitl-desc__title">时滞补偿确认</div>
                <div class="hitl-desc__text">Agent 预白化互相关估计多输入时滞，提供推荐值并允许手动覆盖</div>
              </div>
            </div>
            <div class="hitl-desc__item">
              <div class="hitl-desc__num font-mono">02</div>
              <div>
                <div class="hitl-desc__title">ARX 结构确认</div>
                <div class="hitl-desc__text">推荐 na/nb/nk 阶次，工程师审查后可调整，附模型验证结果</div>
              </div>
            </div>
            <div class="hitl-desc__item">
              <div class="hitl-desc__num font-mono">03</div>
              <div>
                <div class="hitl-desc__title">特征筛选确认</div>
                <div class="hitl-desc__text">VIF + Spearman 共线性分析后推荐删除列，工程师可取消勾选保留</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- ── CTA ─────────────────────────────────────────────── -->
    <section class="landing-cta">
      <div class="landing-container">
        <h2 class="cta-title">准备好开始了吗？</h2>
        <p class="cta-sub">导入你的时序数据，让 Agent 完成从原始数据到经过验证的动态模型的全过程</p>
        <button type="button" class="btn-primary btn-primary--lg" @click="enterApp">
          进入 IndusOpt 工作台
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg>
        </button>
      </div>
    </section>

    <!-- ── Footer ──────────────────────────────────────────── -->
    <footer class="landing-footer">
      <div class="landing-container landing-footer__inner">
        <div class="landing-footer__brand">
          <div class="landing-logo__mark" style="width:22px;height:22px">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 2L2 7l10 5 10-5-10-5z"/>
              <path d="M2 17l10 5 10-5"/>
              <path d="M2 12l10 5 10-5"/>
            </svg>
          </div>
          <span class="font-mono" style="font-size:12px;color:var(--text-muted)">IndusOpt 工模智优 A14</span>
        </div>
        <div class="landing-footer__text">Industrial AI Agent Workspace · 面向流程工业系统辨识</div>
      </div>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { useRouter } from 'vue-router';
import { markLandingEntered } from '../router/landingEntry';

const router = useRouter();
const pageRoot = ref<HTMLElement | null>(null);

function enterApp() {
  markLandingEntered();
  router.push('/home');
}

function scrollToSection(id: string) {
  const el = document.getElementById(id);
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

const features = [
  {
    icon: '🤖',
    title: 'Agent 自动编排',
    desc: 'LLM 规划 + 规则兜底双引擎，自然语言描述目标即可触发完整 8 阶段建模流程',
  },
  {
    icon: '📐',
    title: 'D-最优动态区间优选',
    desc: '基于 D-最优准则与信息增益，自动识别并保留动态响应最丰富的时间区间',
  },
  {
    icon: '⏱',
    title: '多变量时滞估计',
    desc: '预白化互相关算法估计各输入通道对输出的动态延迟，支持人工审核确认',
  },
  {
    icon: '🔬',
    title: 'ARX 系统辨识',
    desc: 'OLS/Ridge ARX 参数辨识，三段（训练/验证/测试）严格隔离，One-step + Free-run 双轨验证',
  },
  {
    icon: '⚡',
    title: 'Optuna 闭环寻优',
    desc: '基于 Optuna 的超参数寻优，100+ Trials 搜索最优参数组合，FIT 提升可达 14%+',
  },
  {
    icon: '🛡',
    title: '合规证明可追溯',
    desc: '每次 Agent 执行生成 proof_id + 数字签名，数据处理全链路可审计',
  },
  {
    icon: '👤',
    title: '三点 HITL 确认',
    desc: '时滞补偿、ARX 结构、特征筛选三个关键节点触发人工审核，不静默执行高影响操作',
  },
  {
    icon: '📋',
    title: 'LLM 工程报告',
    desc: '自动生成包含模型参数、验证指标和建议的完整 Markdown 工程分析报告',
  },
];

const workflowSteps = [
  { name: '数据质量诊断', desc: '缺失值、异常检测、采样一致性检查', type: 'auto', label: '自动' },
  { name: '时间规整与清洗', desc: 'Hampel 滤波 + IQR 异常替换 + 降采样对齐', type: 'auto', label: '自动' },
  { name: '动态区间优选', desc: 'D-最优 + 门控 + 信息增益优选覆盖率', type: 'auto', label: '自动' },
  { name: '多变量时滞分析', desc: '预白化互相关估计各输入时滞', type: 'hitl', label: '需确认' },
  { name: '共线性与特征筛选', desc: 'VIF + Spearman 分析，推荐移除冗余列', type: 'hitl', label: '需确认' },
  { name: 'ARX 系统辨识', desc: 'OLS/Ridge ARX 拟合，推荐 na/nb/nk 结构', type: 'hitl', label: '需确认' },
  { name: '模型评价验证', desc: '测试集 One-step + Free-run 指标评估', type: 'auto', label: '自动' },
  { name: 'Optuna 参数寻优', desc: '闭环多目标超参数优化，生成工程报告', type: 'auto', label: '自动' },
];

const benchmarkRows = [
  { strategy: '全量特征 · 无区间优选', fit: '74.2', r2: '0.847', rmse: '0.081', freeFit: '71.5', highlight: false },
  { strategy: '能量门控优选', fit: '81.6', r2: '0.901', rmse: '0.063', freeFit: '79.1', highlight: false },
  { strategy: '质量门控优选', fit: '83.9', r2: '0.921', rmse: '0.057', freeFit: '81.4', highlight: false },
  { strategy: 'D-最优 + VIF 筛选 + Optuna', fit: '89.0', r2: '0.962', rmse: '0.031', freeFit: '86.9', highlight: true },
];
</script>

<style scoped>
/* ── Base ──────────────────────────────────────────────────── */
.landing {
  width: 100%;
  height: 100vh;
  overflow-y: auto;
  overflow-x: hidden;
  -webkit-overflow-scrolling: touch;
  scroll-behavior: smooth;
  background: var(--bg-app);
  color: var(--text-primary);
  position: relative;
}

.landing-container {
  max-width: 1120px;
  margin: 0 auto;
  padding: 0 var(--space-6);
}

/* ── Header ────────────────────────────────────────────────── */
.landing-header {
  position: sticky;
  top: 0;
  z-index: var(--z-header);
  background: rgba(246, 247, 243, 0.88);
  border-bottom: 1px solid #E8EAE5;
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
}

.landing-header__inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 58px;
}

.landing-logo {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.landing-logo__mark {
  width: 28px;
  height: 28px;
  background: #FFFFFF;
  border: 1px solid #DFE4DB;
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #698F64;
  box-shadow: var(--shadow-sm);
}

.landing-logo__name {
  font-size: 15px;
  font-weight: 800;
  color: #20231F;
  letter-spacing: -0.02em;
}

.landing-logo__tag {
  font-size: 10px;
  font-weight: 600;
  color: #52735A;
  background: #EDF4E9;
  border: 1px solid #D6E5D1;
  padding: 1px 7px;
  border-radius: var(--radius-full);
}

.landing-nav {
  display: flex;
  align-items: center;
  gap: var(--space-5);
}

.landing-nav__item {
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
  font-size: var(--font-size-sm);
  color: #626860;
  font-weight: 500;
  transition: color var(--transition-fast);
}

.landing-nav__item:hover {
  color: #20231F;
}

.landing-nav__cta {
  padding: 7px 18px;
  background: #82A978;
  border: 1px solid #82A978;
  border-radius: var(--radius-full);
  color: #FFFFFF;
  font-size: var(--font-size-sm);
  font-weight: 600;
  cursor: pointer;
  box-shadow: 0 2px 8px rgba(80, 110, 75, 0.12);
  transition: all var(--transition-fast);
}

.landing-nav__cta:hover {
  background: #719967;
  border-color: #719967;
  transform: translateY(-1px);
}

/* ── Hero ──────────────────────────────────────────────────── */
.landing-hero {
  position: relative;
  padding: 96px 0 72px;
  text-align: center;
  background: radial-gradient(circle at 50% 0%, rgba(130, 169, 120, 0.08), transparent 35%);
}

.hero-eyebrow {
  display: inline-block;
  font-size: 11px;
  font-weight: 700;
  color: #5D7E58;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  margin-bottom: var(--space-4);
  padding: 4px 12px;
  background: #EDF4E9;
  border: 1px solid #D3E4CD;
  border-radius: var(--radius-full);
}

.hero-title {
  font-size: clamp(34px, 5.5vw, 60px);
  font-weight: 800;
  color: #20231F;
  letter-spacing: -0.04em;
  line-height: 1.12;
  margin-bottom: var(--space-5);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}

.hero-title__accent {
  color: #52735A;
}

.hero-subtitle {
  font-size: var(--font-size-md);
  color: #626860;
  max-width: 620px;
  margin: 0 auto var(--space-6);
  line-height: 1.7;
}

.hero-actions {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
  margin-bottom: var(--space-10);
}

/* ── Buttons ───────────────────────────────────────────────── */
.btn-primary {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: 12px 24px;
  background: #82A978;
  border: none;
  border-radius: var(--radius-full);
  color: #FFFFFF;
  font-size: var(--font-size-md);
  font-weight: 600;
  cursor: pointer;
  box-shadow: 0 4px 14px rgba(80, 110, 75, 0.12);
  transition: all var(--transition-fast);
}

.btn-primary:hover {
  background: #719967;
  transform: translateY(-1px);
}

.btn-primary--lg {
  padding: 14px 32px;
  font-size: var(--font-size-lg);
}

.btn-ghost {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: 11px 22px;
  background: #FFFFFF;
  border: 1px solid #DDE1DA;
  border-radius: var(--radius-full);
  color: #444A43;
  font-size: var(--font-size-md);
  font-weight: 500;
  text-decoration: none;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.btn-ghost:hover {
  background: #F5F7F2;
  border-color: #C8CEC5;
  transform: translateY(-1px);
}

/* ── Stats ─────────────────────────────────────────────────── */
.hero-stats {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-8);
  margin-bottom: var(--space-10);
  padding: var(--space-4) var(--space-6);
  background: #FFFFFF;
  border: 1px solid #E3E6DF;
  border-radius: var(--radius-lg);
  max-width: 640px;
  margin-left: auto;
  margin-right: auto;
  box-shadow: 0 6px 24px rgba(30, 40, 28, 0.035);
}

.hero-stat { text-align: center; }

.hero-stat__num {
  font-size: 26px;
  font-weight: 800;
  color: #282C27;
  letter-spacing: -0.03em;
}

.hero-stat:first-child .hero-stat__num {
  color: #5E8259;
}

.hero-stat__desc {
  font-size: 11px;
  color: #8B9188;
  margin-top: 2px;
}

.hero-stat-div {
  width: 1px;
  height: 32px;
  background: #E8EAE5;
}

/* ── Terminal / Workspace Preview ──────────────────────────── */
.hero-terminal {
  border: 1px solid #E1E4DE;
  border-radius: var(--radius-lg);
  overflow: hidden;
  max-width: 780px;
  margin: 0 auto;
  text-align: left;
  background: #FFFFFF;
  box-shadow: 0 18px 50px rgba(30, 40, 28, 0.06);
}

.hero-terminal__bar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  background: #F2F4EF;
  border-bottom: 1px solid #E1E4DE;
}

.hero-terminal__dots {
  display: flex;
  gap: 6px;
}

.hero-terminal__dots span {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #D0D4CD;
}

.hero-terminal__title {
  font-size: var(--font-size-xs);
  color: #868C83;
  flex: 1;
  text-align: center;
}

.hero-terminal__status {
  font-size: 11px;
  color: #67936C;
  display: flex;
  align-items: center;
}

.hero-terminal__body {
  background: #FAFBF8;
  padding: var(--space-5);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  min-height: 190px;
}

.ht-msg {
  display: flex;
  gap: var(--space-3);
  align-items: flex-start;
}

.ht-msg__avatar {
  width: 26px;
  height: 26px;
  border-radius: var(--radius-xs);
  background: #E8EDE5;
  border: 1px solid #D8DFD5;
  color: #5D7E58;
  font-size: 11px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.ht-msg__avatar--agent {
  background: #EDF4E9;
  border-color: #D3E4CD;
  color: #52735A;
}

.ht-msg--user {
  background: #F0F4ED;
  border: 1px solid #E2E8DE;
  border-radius: var(--radius-sm);
  padding: var(--space-2) var(--space-3);
}

.ht-msg__text {
  font-size: var(--font-size-sm);
  color: #20231F;
  line-height: 1.5;
  padding: 3px 0;
}

.ht-plan {
  flex: 1;
  background: #FFFFFF;
  border: 1px solid #E2E5DE;
  border-radius: var(--radius-sm);
  padding: var(--space-3);
}

.ht-plan__label {
  font-size: 10px;
  color: #81877E;
  letter-spacing: 0.08em;
  margin-bottom: var(--space-2);
}

.ht-steps {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.ht-step {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--font-size-xs);
}

.ht-step__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.ht-step__dot.done { background: #66956E; }
.ht-step__dot.running {
  background: #82A978;
  box-shadow: 0 0 0 3px #EDF4E9;
  animation: agent-breathe 1.5s ease-in-out infinite;
}
.ht-step__dot.pending { background: #BEC2BC; }

.ht-step__name { color: #626860; }
.ht-step--done .ht-step__name { color: #81877E; }
.ht-step--running .ht-step__name { color: #20231F; font-weight: 600; }

.ht-step__time {
  margin-left: auto;
  color: #9CA19A;
  font-size: 10px;
}

.ht-step__spinner {
  margin-left: auto;
  color: #82A978;
  font-size: 10px;
}

.ht-event {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  background: #F2F5EF;
  border: 1px solid #E2E5DE;
  border-radius: var(--radius-xs);
  font-size: var(--font-size-xs);
}

.ht-event__tool {
  color: #52735A;
  font-weight: 600;
}

.ht-event__desc {
  color: #626860;
  flex: 1;
}

/* ── Sections ──────────────────────────────────────────────── */
.landing-section {
  padding: 80px 0;
  border-top: 1px solid #EAECE6;
}

.section-label {
  font-size: var(--font-size-xs);
  color: #5D7E58;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  margin-bottom: var(--space-2);
  font-weight: 700;
}

.section-title {
  font-size: clamp(26px, 3.2vw, 38px);
  font-weight: 800;
  color: #20231F;
  letter-spacing: -0.03em;
  margin-bottom: var(--space-2);
}

.section-subtitle {
  font-size: var(--font-size-md);
  color: #626860;
  margin-bottom: var(--space-8);
  max-width: 560px;
  line-height: 1.6;
}

/* ── Features Grid ─────────────────────────────────────────── */
.features-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
  gap: var(--space-4);
}

.feature-card {
  padding: var(--space-5);
  background: #FFFFFF;
  border: 1px solid #E2E5DE;
  border-radius: var(--radius-md);
  box-shadow: 0 2px 8px rgba(30, 40, 28, 0.03);
  transition: all var(--transition-fast);
}

.feature-card:hover {
  background: #FAFBF8;
  border-color: #D4D9D1;
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
}

.feature-card__icon {
  font-size: 24px;
  margin-bottom: var(--space-3);
}

.feature-card__title {
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: #20231F;
  margin-bottom: var(--space-2);
}

.feature-card__desc {
  font-size: var(--font-size-xs);
  color: #626860;
  line-height: 1.6;
}

/* ── Workflow Steps ────────────────────────────────────────── */
.workflow-steps {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.workflow-step {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-3) var(--space-5);
  background: #FFFFFF;
  border: 1px solid #E2E5DE;
  border-radius: var(--radius-sm);
  transition: all var(--transition-fast);
}

.workflow-step:hover {
  background: #FAFBF8;
  border-color: #D4D9D1;
}

.workflow-step__num {
  width: 28px;
  font-size: var(--font-size-xs);
  color: #9CA19A;
  flex-shrink: 0;
  font-weight: 700;
}

.workflow-step__body {
  flex: 1;
}

.workflow-step__name {
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: #20231F;
}

.workflow-step__desc {
  font-size: var(--font-size-xs);
  color: #626860;
  margin-top: 2px;
}

.workflow-step__badge {
  font-size: 10px;
  font-weight: 700;
  padding: 3px 9px;
  border-radius: var(--radius-full);
  font-family: var(--font-mono);
}

.workflow-step__badge.auto {
  color: #557651;
  background: #EDF4E9;
  border: 1px solid #D3E4CD;
}

.workflow-step__badge.hitl {
  color: #8C6826;
  background: #FBF4E7;
  border: 1px solid #EFE0C2;
}

/* ── Benchmark Table ───────────────────────────────────────── */
.benchmark-table {
  border: 1px solid #E2E5DE;
  border-radius: var(--radius-md);
  overflow: hidden;
  box-shadow: var(--shadow-sm);
  background: #FFFFFF;
}

.bm-header {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr 1fr 1fr;
  gap: 0;
  background: #F7F8F5;
  border-bottom: 1px solid #E2E5DE;
}

.bm-row {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr 1fr 1fr;
  background: #FFFFFF;
  border-bottom: 1px solid #ECEEE9;
}

.bm-row:last-child { border-bottom: none; }

.bm-row--highlight {
  background: #FAFBF8;
}

.bm-cell {
  padding: var(--space-3) var(--space-4);
  font-size: var(--font-size-sm);
  color: #20231F;
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.bm-header .bm-cell {
  font-size: var(--font-size-xs);
  color: #6B7168;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.bm-cell--num {
  justify-content: flex-end;
}

.bm-strategy {
  font-size: var(--font-size-sm);
  color: #20231F;
  font-weight: 500;
}

.bm-badge {
  font-size: 10px;
  font-weight: 600;
  color: #52735A;
  background: #EDF4E9;
  border: 1px solid #D6E5D1;
  padding: 1px 7px;
  border-radius: var(--radius-full);
}

/* ── HITL Demo ─────────────────────────────────────────────── */
.hitl-demo {
  display: grid;
  grid-template-columns: 380px 1fr;
  gap: var(--space-8);
  align-items: start;
}

.hitl-card {
  border: 1px solid #E2E5DE;
  border-left: 3px solid #B48A47;
  background: #FFFDF7;
  border-radius: var(--radius-md);
  overflow: hidden;
  box-shadow: var(--shadow-sm);
}

.hitl-card__header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid #EFE0C2;
}

.hitl-card__icon {
  width: 26px;
  height: 26px;
  background: #FBF4E7;
  border-radius: var(--radius-xs);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #B48A47;
  font-size: 13px;
}

.hitl-card__title {
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: #20231F;
}

.hitl-card__sub {
  font-size: var(--font-size-xs);
  color: #81877E;
}

.hitl-card__body {
  padding: var(--space-4);
  background: #FFFFFF;
}

.hitl-card__desc {
  font-size: var(--font-size-xs);
  color: #626860;
  margin-bottom: var(--space-3);
}

.hitl-lag-row {
  display: flex;
  justify-content: space-between;
  padding: var(--space-2) var(--space-3);
  background: #FAFBF8;
  border: 1px solid #ECEEE9;
  border-radius: var(--radius-xs);
  margin-bottom: 4px;
  font-size: var(--font-size-xs);
  color: #20231F;
}

.hitl-lag-val {
  color: #81877E;
}

.hitl-card__actions {
  display: flex;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  border-top: 1px solid #ECEEE9;
  background: #FAFBF8;
  justify-content: flex-end;
}

.hitl-btn-reject {
  padding: 6px 14px;
  background: #FFFFFF;
  border: 1px solid #DDE1DA;
  border-radius: var(--radius-sm);
  color: #626860;
  font-size: var(--font-size-xs);
  cursor: pointer;
}

.hitl-btn-reject:hover {
  background: #F3F5F0;
  color: #20231F;
}

.hitl-btn-approve {
  padding: 6px 14px;
  background: #82A978;
  border: 1px solid #82A978;
  border-radius: var(--radius-sm);
  color: #FFFFFF;
  font-size: var(--font-size-xs);
  font-weight: 600;
  cursor: pointer;
}

.hitl-btn-approve:hover {
  background: #719967;
}

.hitl-desc {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

.hitl-desc__item {
  display: flex;
  gap: var(--space-4);
}

.hitl-desc__num {
  font-size: 20px;
  font-weight: 800;
  color: #BEC2BC;
  flex-shrink: 0;
  line-height: 1.2;
}

.hitl-desc__title {
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: #20231F;
  margin-bottom: 4px;
}

.hitl-desc__text {
  font-size: var(--font-size-xs);
  color: #626860;
  line-height: 1.6;
}

/* ── CTA ───────────────────────────────────────────────────── */
.landing-cta {
  padding: 96px 0;
  border-top: 1px solid #EAECE6;
  text-align: center;
  background: var(--surface-2);
}

.cta-title {
  font-size: clamp(28px, 4vw, 44px);
  font-weight: 800;
  color: #20231F;
  letter-spacing: -0.03em;
  margin-bottom: var(--space-3);
}

.cta-sub {
  font-size: var(--font-size-md);
  color: #626860;
  margin-bottom: var(--space-6);
  max-width: 480px;
  margin-left: auto;
  margin-right: auto;
  line-height: 1.6;
}

/* ── Footer ────────────────────────────────────────────────── */
.landing-footer {
  border-top: 1px solid #EAECE6;
  padding: var(--space-5) 0;
  background: var(--bg-sidebar);
}

.landing-footer__inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.landing-footer__brand {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.landing-footer__text {
  font-size: var(--font-size-xs);
  color: var(--text-muted);
}
</style>
