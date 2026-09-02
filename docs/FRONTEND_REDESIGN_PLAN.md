# Frontend Redesign Plan — Industrial AI Agent Workspace

> Version: v1.0
> Date: 2026-09-01
> Status: PENDING USER APPROVAL — Do NOT begin execution until approved
> Companion: [FRONTEND_REDESIGN_AUDIT.md](./FRONTEND_REDESIGN_AUDIT.md)

---

## 目标摘要

将当前 IndusOpt 工模智优前端从「传统工业数据分析后台」重构为「Industrial AI Agent Workspace」。

参考产品的设计思想：Manus（任务委托 + Artifact）× Cursor（专业工具 + 紧凑 Agent 流）× Replit（任务状态 + Workbench）× v0（Prompt-first Home）× Lovable（克制精致的视觉层级）。

最终形成属于本项目自己的工业智能 Agent 工作台。

---

## 核心约束（执行前必读）

> [!CAUTION]
> 以下内容在整个重构过程中严禁破坏：
> 1. 所有 `data-test="*"` 属性（E2E 测试依赖）
> 2. 所有 API 调用语义（endpoint URL、request/response schema）
> 3. HITL 确认机制的三种流程（lag / feature / arx）
> 4. Dataset Version Lineage 语义
> 5. ComplianceProof 可见性
> 6. 测试集隔离（SplitIndices 不可视觉混淆）
> 7. 路由 `/simulation`, `/preprocessing/segmentation`, `/benchmark`, `/copilot` 必须继续存在

---

## 新信息架构 (New IA)

### 一级导航（重新定义）

```
Home          /           ← Prompt-first 入口（全新设计）
Workspace     /workspace  ← Agent Workspace（三栏，核心页面）
Projects      /runs       ← 历史 Execution 列表
Assets        /assets     ← 数据集 / 模型 / 优化研究 / 报告（聚合页）
Settings      /settings   ← 保留原有功能
```

### 路由映射（旧 → 新）

| 旧路由 | 新路由 | 处理方式 |
|--------|--------|---------|
| `/` (LandingView) | `/` (HomeView) | **重设计**：替换为 Prompt-first Home |
| `/dashboard` | `/` 或 `/runs` | **降级**：内容整合进 Home Recent Tasks |
| `/copilot` | `/workspace` 或 `/workspace/:executionId` | **升级**：成为主界面三栏 Workspace |
| `/datasets` | `/assets/datasets` | **迁移**：移入 Assets |
| `/datasets/:id` | `/assets/datasets/:id` | **保留 + 重组件化**：作为 Asset Detail |
| `/simulation` | `/assets/simulation` 或保留 | **保留**（E2E 依赖 `/simulation`，需重定向） |
| `/preprocessing/*` | `/assets/preprocessing/*` 或保留 | **保留原路由**（E2E 依赖） + 重设计页面 |
| `/modeling/*` | `/assets/modeling/*` | **迁移 + 重设计** |
| `/modeling/optimization` | `/assets/optimization` | **迁移** |
| `/benchmark` | `/assets/benchmark` 或保留 | **保留**（E2E 依赖） |
| `/deliverables` | `/assets/reports` | **迁移 + 重设计** |
| `/settings` | `/settings` | **保留** |

> [!IMPORTANT]
> E2E 测试中使用了 `/simulation`, `/preprocessing/segmentation`, `/benchmark`, `/copilot` 这四个路由。
> 必须保留这些路由（或添加重定向）。推荐在新路由体系中添加向后兼容的 redirect。

---

## PHASE 1 — Audit + IA（当前阶段：已完成）

- [x] 完整扫描 frontend/src
- [x] 生成 FRONTEND_REDESIGN_AUDIT.md
- [x] 生成 FRONTEND_REDESIGN_PLAN.md（本文档）
- [ ] 用户批准计划后进入 Phase 2

---

## PHASE 2 — Design System

### 目标
建立统一 design tokens，替换碎片化的 CSS 变量。

### 文件变更

#### [MODIFY] `src/assets/main.css`
清除 Vite 模板残留（`.hero`, `#center`, `#next-steps` 等），保留 `body`, `html`, `*` 基础重置。

#### [NEW] `src/assets/design-tokens.css`
定义完整 token 体系：

```css
/* Color — Dark Default */
--color-bg-app:      #0B0D10;
--color-bg-surface:  #111419;
--color-bg-elevated: #15191F;
--color-bg-overlay:  #1C2028;

/* Border */
--color-border:      rgba(255,255,255,0.07);
--color-border-strong: rgba(255,255,255,0.12);

/* Text */
--color-text-primary:   #F5F7FA;
--color-text-secondary: #9AA4B2;
--color-text-muted:     #667085;

/* Accent — 唯一品牌色（工业蓝） */
--color-accent:       #2B7BE9;
--color-accent-dim:   rgba(43,123,233,0.15);
--color-accent-border: rgba(43,123,233,0.35);

/* Status */
--color-success:  #10B981;
--color-warning:  #F59E0B;
--color-error:    #EF4444;
--color-info:     #6B8EAD;

/* Spacing */
--space-1: 4px;   --space-2: 8px;   --space-3: 12px;
--space-4: 16px;  --space-5: 20px;  --space-6: 24px;
--space-8: 32px;

/* Radius */
--radius-sm: 6px;  --radius-md: 10px;  --radius-lg: 14px;

/* Font */
--font-sans: 'PingFang SC', 'Noto Sans SC', system-ui, sans-serif;
--font-mono: 'JetBrains Mono', ui-monospace, monospace;
--font-size-sm:   12px;
--font-size-base: 13px;
--font-size-md:   14px;

/* Transition */
--transition-fast: 160ms ease-out;
--transition-base: 200ms ease-out;
```

---

## PHASE 3 — App Shell

### 目标
重建整个应用壳（AppShell），采用新 IA。

### 文件变更

#### [MODIFY] `src/layouts/DefaultLayout.vue`
- 移除旧的 AppHeader + AppSidebar 引用
- 引入新的 `AppShell` 组件
- 保留 CommandPalette + bounce 效果

#### [NEW] `src/components/shell/AppShell.vue`
全新应用壳：
```
┌────────────────────────────────────────────────┐
│ PrimaryNav (左侧, 56px icon strip)              │
│  Home | Workspace | Runs | Assets | Settings   │
│                                                │
│  ┌──────────────────────────────────────────┐  │
│  │ ProjectSwitcher (顶部，当前数据集指示器) │  │
│  │ + System Health Dot                      │  │
│  └──────────────────────────────────────────┘  │
│                                                │
│  <router-view />                               │
└────────────────────────────────────────────────┘
```

#### [NEW] `src/components/shell/PrimaryNav.vue`
- 纯 Icon + label 导航（宽 56px，hover 展开到 220px）
- 图标：Home / Bot / History / Archive / Settings
- 当前路由高亮
- 底部：系统健康状态点

#### [NEW] `src/components/shell/ProjectSwitcher.vue`
- 显示当前活跃数据集名称 + version short ID
- 点击可切换数据集

---

## PHASE 4 — Home Prompt-first Redesign

### 目标
新 Home（原 LandingView 的 app 入口），完全替换旧 DashboardView。

### 文件变更

#### [NEW] `src/views/HomeView.vue`

布局结构：
```
┌──────────────────────────────────────────────────────┐
│  (空白区) 品牌名 + 副标题                             │
│                                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │   AgentComposer（大型输入区）                 │   │
│  │   [Dataset 附件] [Mode] [Run]                │   │
│  └──────────────────────────────────────────────┘   │
│                                                      │
│  Quick Actions:                                      │
│  [诊断数据质量] [建立动态模型] [运行参数优化] [生成报告] │
│                                                      │
│  ─── Recent Tasks ───────────────────────────────   │
│  [Running] 分析 dataset_A · 2 min ago               │
│  [Completed] ARX 建模 dataset_B · 1h ago             │
│  [Needs Review] Feature Selection · 3h ago           │
└──────────────────────────────────────────────────────┘
```

#### [NEW] `src/components/composer/AgentComposer.vue`
- 大型文本输入区（min-height: 80px）
- 左下：DatasetAttachment 附件选择器
- 右下：Run 按钮（→ POST /copilot/chat）
- 支持 Cmd+Enter 快速提交
- Focus 状态：轻微 border highlight + glow

---

## PHASE 5 — Agent Workspace（核心）

### 目标
构建三栏 Agent Workspace，取代旧 CopilotView。

### 路由
```
/workspace                → 新建任务或空状态
/workspace/:executionId   → 具体的 Execution
```

旧路由 `/copilot` → redirect to `/workspace`（保持 E2E 兼容）

### 文件变更

#### [NEW] `src/views/WorkspaceView.vue`
三栏结构：
```
┌─────────────┬──────────────────────┬──────────────────────┐
│ LEFT (220px) │ CENTER (Agent Stream) │ RIGHT (Artifact Bench)│
│ 可折叠       │ 弹性宽度              │ 固定 380px，可折叠    │
└─────────────┴──────────────────────┴──────────────────────┘
```

#### [NEW] `src/components/workspace/AgentStream.vue`
中心区域内容：
```
[User Request]
用户意图文本

[Agent Plan]
✓ 检查数据集
✓ 数据质量分析
● 估计时滞          ← 当前执行（带 spinner）
○ 特征筛选
○ ARX 建模
○ 验证
○ 参数优化
○ 生成报告

[Working State]
Tool: delay_analyze
"正在估计 u1 → y 的动态时滞…"

[Tool Event]
Delay Analysis · Completed · 1.8s
Detected delay: 4 samples

[Approval Required]  ← ApprovalCard
...
```

#### [NEW] `src/components/workspace/AgentMessage.vue`
单条消息组件：
- `type`: `user_request | plan | tool_event | result | approval | conclusion`
- 紧凑样式，非大气泡

#### [NEW] `src/components/workspace/AgentPlan.vue`
任务计划组件：
- 可折叠的步骤列表
- 三态视觉：completed（弱化）/ running（高亮 + 动画）/ pending（虚化）
- 每步：icon + 工具名 + 状态 + 耗时

#### [NEW] `src/components/workspace/TaskStep.vue`
单个步骤组件（从 AgentPlan 拆出）

#### [NEW] `src/components/workspace/ToolExecution.vue`
工具执行事件卡：
```
┌───────────────────────────────┐
│ 🔧 Delay Analysis             │
│ Completed · 1.8s              │
│                               │
│ delay u1 → 4  delay u2 → 2   │
└───────────────────────────────┘
```

---

## PHASE 6 — Artifact Workbench

### 目标
右侧面板，展示 Agent 工作产生的结构化结果。

### 文件变更

#### [NEW] `src/components/artifact/ArtifactWorkbench.vue`
容器组件：
- Tab 切换：Preview / Data / Model / Metrics / Report / Logs
- 展开/折叠/全屏/Pin 按钮
- Drawer 模式（小屏）

#### [NEW] `src/components/artifact/ArtifactHeader.vue`
```
┌────────────────────────────────────────────────┐
│  [图标] ARX Model   version: v3  [↗ 全屏]  [✕] │
│  ────────────────────────────────────────────  │
│  Preview | Data | Metrics | Logs               │
└────────────────────────────────────────────────┘
```

#### [NEW] `src/components/artifact/MetricStrip.vue`
紧凑指标条（替换多 KPI Card）：
```
R²     FIT      Free-FIT  RMSE
0.962  88.4%    86.9%     0.031
```

#### [NEW] `src/components/artifact/DatasetArtifact.vue`
展示：质量分 / 行列数 / 缺失率 / 时序预览图 / 冻结段 / Lineage Tab

#### [NEW] `src/components/artifact/ModelArtifact.vue`
展示：ARX 结构（na/nb/nk）/ 系数 / 指标 / 一步预测图 / 自由仿真图

#### [NEW] `src/components/artifact/OptimizationArtifact.vue`
展示：best_params / best_value / Optuna 收敛曲线 / 参数重要性

#### [NEW] `src/components/artifact/ReportArtifact.vue`
展示：Markdown 渲染 / 章节导航 / 绑定数值列表

---

## PHASE 7 — Approval / Human-in-the-loop

### 目标
将三种 HITL 确认统一为 Agent-native ApprovalCard 设计。

### 保留的业务逻辑
- lag validate API 调用
- feature selection validate API 调用
- arx structure validate API 调用
- 所有 `data-test` 属性

### 文件变更

#### [NEW] `src/components/workspace/ApprovalCard.vue`
统一确认卡组件：
```
┌─────────────────────────────────────────────┐
│  ⚠  Agent needs your approval               │
│                                             │
│  Feature Selection                          │
│                                             │
│  Agent recommends removing:                 │
│  x3 · x7                                   │
│                                             │
│  Reason:                                    │
│  High multicollinearity (VIF > threshold)   │
│                                             │
│  Impact: Dataset shrinks from 5 → 3 inputs  │
│                                             │
│  [Reject]  [Review Details]  [Approve]      │
└─────────────────────────────────────────────┘
```

内部处理三种类型：
- `lag_apply`: 时滞推荐 + 手动覆盖表单
- `arx_fit`: ARX 结构推荐 + 手动覆盖
- `feature_apply`: 删除列列表 + checkbox

ApprovalCard 内嵌覆盖表单（展开/收起），不再用 `el-dialog`。

#### [MODIFY] `src/views/WorkspaceView.vue`（或 AgentStream）
- 移除所有 `el-dialog` 用于确认的部分
- 改用 inline ApprovalCard
- 保留所有 `data-test` 属性

---

## PHASE 8 — Asset Detail Refactor

### 目标
将各独立预处理/建模页面重定位为 Asset Detail View，通过 AgentWorkspace 的"Open Full View"进入。

### 各页面处理方式

#### Dataset Detail (`/datasets/:id` → `/assets/datasets/:id`)
- 保留现有 4 个 Tab：概览/质量/版本谱系/列配置
- 重设计为 Asset Detail 样式（去 Card everywhere）
- 版本谱系图改用专业 DAG 显示

#### Cleaning View (`/preprocessing/cleaning`)
- 路由保留（E2E 可能访问）
- 重设计去除 Card everywhere
- 增加"从 Agent Workspace 中查看" 提示

#### Segmentation / Delay / Collinearity
- 同 Cleaning 处理原则

#### ARX Modeling (`/modeling/arx`)
- 保留路由
- 重设计 MetricStrip 替换多 KPI Card
- 图表专业化（去多余背景，弱化网格）

#### Optimization (`/modeling/optimization`)
- 保留路由
- 重设计 Optuna 结果为 OptimizationArtifact 样式

#### Deliverables (`/deliverables`)
- 路由迁移到 `/assets/reports`
- 保留 `/deliverables` redirect
- 重设计为 ReportArtifact 样式

---

## PHASE 9 — Loading / Empty / Error

### 目标
统一全局 Empty / Loading / Error 状态，彻底消除白屏。

### 文件变更

#### [MODIFY] `src/components/StateView.vue`
- 新增 `skeleton` 变体（骨架屏）
- 优化 `failure` 状态加入 "Ask Agent to fix" 操作
- 统一动画：160ms ease-out

#### [NEW] `src/components/common/LoadingSkeleton.vue`
各场景骨架屏预设：
- `list`: 表格行骨架
- `agent-stream`: Agent 流内容骨架
- `artifact`: 右侧 Artifact 骨架
- `metric-strip`: 指标行骨架

#### [NEW] `src/components/common/EmptyState.vue`
统一空状态：
- `icon` + `title` + `description`
- 可选的 primary action 和 secondary action

#### [NEW] `src/components/common/InlineError.vue`
行内错误：
- 非模态（不用 alert()）
- 带 Retry + 上报建议

---

## PHASE 10 — Responsive + Animation + Polish

### 目标
- 主要目标：1440×900, 1920×1080
- 保证：1280px MacBook viewport
- 小屏：右侧 Artifact 降级为 Drawer

### 动画规范
```css
/* 所有交互动画 */
transition: all var(--transition-fast);   /* 160ms */
transition: all var(--transition-base);   /* 200ms */

/* Agent Working indicator */
@keyframes breathing {
  0%, 100% { opacity: 0.7; }
  50%       { opacity: 1; }
}
animation: breathing 2s ease-in-out infinite;

/* 禁止 */
/* bounce / rotate / glow / gradient-animation / page-transition-flash */
```

---

## PHASE 11 — Regression Tests

执行顺序：
1. `npm run test`（Vitest 全量单测）
2. `npm run build`（TypeScript + Vite 构建）
3. `npm run test:e2e`（Playwright 全量 E2E）

如有测试失败，必须修复后才能继续。

---

## PHASE 12 — Visual QA

每个关键页面在 1440×900 和 1920×1080 下截图，检查：
- alignment, hierarchy, typography, overflow
- spacing, contrast, empty state, loading, error
- chart layout, long content

截图保存至 `docs/screenshots/before/` 和 `docs/screenshots/after/`。

生成 `docs/FRONTEND_REDESIGN_RESULT.md`。

---

## 新组件清单

### Shell
- `AppShell.vue`
- `PrimaryNav.vue`
- `ProjectSwitcher.vue`

### Composer
- `AgentComposer.vue`

### Workspace
- `AgentStream.vue`
- `AgentMessage.vue`
- `AgentPlan.vue`
- `TaskStep.vue`
- `ToolExecution.vue`
- `ApprovalCard.vue`
- `RunStatus.vue`

### Artifact
- `ArtifactWorkbench.vue`
- `ArtifactHeader.vue`
- `ArtifactTabs.vue`
- `MetricStrip.vue`
- `DatasetArtifact.vue`
- `ModelArtifact.vue`
- `OptimizationArtifact.vue`
- `ReportArtifact.vue`

### Common
- `LoadingSkeleton.vue`
- `EmptyState.vue`
- `InlineError.vue`
- `InspectorPanel.vue`
- `CommandPalette.vue`（已存在，需更新内容）

---

## 验收标准

1. 第一次打开，3 秒内理解：「这是一个工业智能 Agent」
2. 最多 2 次操作创建新 Agent Task
3. Agent 执行过程中同一页面看到 Goal / Plan / Step / Tool / Result / Artifact / Approval
4. 不需要跳 6~10 个页面完成一次分析
5. Artifact 是一等公民
6. 所有 Vitest 单测通过
7. 所有 Playwright E2E 测试通过
8. TypeScript 无类型错误
9. Vite build 无错误
10. 无明显 Card everywhere / gradient everywhere / oversized typography
