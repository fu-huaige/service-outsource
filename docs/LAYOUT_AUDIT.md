# IndusOpt 全局布局与空间系统审计报告 (LAYOUT AUDIT)

> 审计范围: `App.vue`, `AppShell.vue`, `PrimaryNav.vue`, `HomeView.vue`, `WorkspaceView.vue`, `DatasetsView.vue`, `DatasetDetailView.vue`, `ARXModelingView.vue`, `OptunaView.vue`, `CleaningView.vue`, `SegmentationView.vue`, `DelayView.vue`, `CollinearityView.vue`, `BenchmarkView.vue`, `SimulationView.vue`, `DeliverablesView.vue`, `SettingsView.vue`, `RunsView.vue`, `AssetsView.vue`
> 审计时间: 2026-09-01

---

## 1. 现状度量与空间尺寸扫描

### 1.1 侧边栏与 App Shell
- **当前侧边栏宽度**:
  - 折叠态: `--sidebar-width-collapsed: 56px;`
  - 展开态: `--sidebar-width-expanded: 220px;` (规范要求: `232px`)
- **主内容区宽度**:
  - `app-shell__content`: `flex: 1; min-width: 0; width: calc(100vw - 56px); overflow-y: auto;`
  - 结构基本正确，但子页面缺少统一的 Container 规范层，各个页面自行设定 `padding` 与 `max-width`。

### 1.2 页面容器与最大宽度 (Max-Width) 混乱现状
| 页面 / 视图 | 当前容器最大宽度 | 当前内边距 (Padding) | 存在问题 |
| :--- | :--- | :--- | :--- |
| **HomeView** | `760px` | `80px var(--space-6) var(--space-10)` | 宽度过窄，在 1920×1080 下显得拘谨；顶部硬编码 80px，下方空状态导致严重头重脚轻 |
| **WorkspaceView** | 无限制 (100%) | 无外边距，内嵌 Panel 分栏 | 右侧栏 `--artifact-panel-width: 380px` 偏窄，在宽屏下 Artifact 显示空间受限 |
| **RunsView** | `860px` | `var(--space-6)` (24px) | 随机宽度 860px，与其它详情页 1280px 不统一 |
| **AssetsView** | `920px` | `var(--space-6)` (24px) | 随机宽度 920px，缺少统一标准 |
| **DatasetsView** | 100% (未设 max-width) | `var(--space-6) clamp(20px, 3.5vw, 40px) var(--space-12)` | 宽屏下表格横向无限拉伸，与左对齐表头脱节 |
| **DatasetDetailView**| 100% | `var(--space-6) clamp(20px, 3.5vw, 40px) var(--space-12)` | 宽屏下无 max-width 约束 |
| **CleaningView** | 100% | `var(--space-6) clamp(20px, 3.5vw, 40px) var(--space-12)` | 无统一 1280px 约束 |
| **ARXModelingView** | 100% | `var(--space-6) clamp(20px, 3.5vw, 40px) var(--space-12)` | 左右表单与图表未采用标准 12 列网格 |
| **OptunaView** | 100% | `var(--space-6) clamp(20px, 3.5vw, 40px) var(--space-12)` | 缺乏标准网格 |
| **SettingsView** | 100% | `var(--space-6) clamp(20px, 3.5vw, 40px) var(--space-12)` | 宽度过宽，表单与卡片失去紧凑感 |

### 1.3 垂直节奏与硬编码间距 (Vertical Rhythm)
1. **页面 Header 垂直节奏脱节**:
   - `DatasetsView`, `SettingsView`, `RunsView`, `AssetsView` 等页面虽然有 `.page-header`，但其 `margin-bottom` 为 `20px`，缺少统一标准 (`32px`)。
   - `HomeView` 顶部硬编码 `padding-top: 80px`，缺乏 `clamp(72px, 9vh, 112px)` 的视口自适应能力。
2. **HomeView 结构性问题**:
   - **品牌冗余**: 左侧 56px Sidebar 已有明确的 Logo Mark；Home 顶部中央重复出现 32px Logo + "IndusOpt" + A14 徽标。
   - **标题与输入框间距过紧**: `home-headline` 距离 Composer 仅 16px，缺少 28px 的视觉呼吸空间。
   - **输入框尺寸与比例偏小**: 当前 Composer 为 720px，且在 1920×1080 屏幕上无法构成绝对视觉中心。
   - **巨大无意义空白 (Empty Zone)**: 当本地无历史任务时，Quick Actions 下方仅展示 1 个 Sparkle 图标 + 简短说明，导致在 1440×900 和 1920×1080 视口下屏幕下方有超过 50% 的死白。

---

## 2. 空间设计系统规范定义 (Layout Tokens Plan)

### 2.1 容器宽度系统 (Width Tier System)
- `--reading-max: 760px;` (文本报告、长文本、帮助说明)
- `--agent-home-max: 920px;` (Home 居中聚焦容器、主输入区域)
- `--workspace-center-max: 760px;` (Workspace 对话流核心文本阅读区)
- `--content-max: 1280px;` (所有标准数据、分析与配置详情页)
- `--content-wide: 1440px;` (宽屏报表与多面板展示)
- `WIDE`: 100% 满宽，两侧仅保留 32~48px gutter (Workspace、大型数据看板)

### 2.2 间距系统与垂直节奏 (Spacing & Vertical Scale)
```css
/* 统一 Spacing 阶梯 (4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80, 96) */
--space-1:  4px;
--space-2:  8px;
--space-3:  12px;
--space-4:  16px;
--space-5:  20px;
--space-6:  24px;
--space-7:  32px;
--space-8:  40px;
--space-9:  48px;
--space-10: 64px;
--space-11: 80px;
--space-12: 96px;

/* Section 垂直节奏 */
--section-gap-xs: 16px;
--section-gap-sm: 24px;
--section-gap-md: 32px;
--section-gap-lg: 48px;
--section-gap-xl: 64px;
--section-gap-2xl: 88px;

/* 页面内边距响应式阶梯 */
--page-gutter-lg: 48px;  /* >= 1440px */
--page-gutter-md: 32px;  /* 1280px ~ 1439px */
--page-gutter-sm: 20px;  /* < 1280px */
```

### 2.3 响应式断点 (Breakpoints)
- `1600px`: Ultra-wide display
- `1440px`: Standard desktop / 1440×900 laptop
- `1280px`: Compact desktop / small laptop
- `1024px`: Tablet landscape / compact workspace
- `768px`: Mobile / tablet portrait

---

## 3. 重构执行路线图 (Action Plan)

1. **新建 `src/styles/layout.css`**:
   - 注入上述全部 Layout Tokens、标准容器类 (`.page-container`, `.page-container--reading`, `.page-container--wide`)、标准 Page Header 类、12 列网格类 (`.grid-12`, `.col-8`, `.col-4`, `.col-6`)。
2. **重构 HomeView**:
   - 移除中央冗余 Logo，建立极简 Eyebrow: `A14 · INDUSTRIAL AI AGENT`。
   - 放大主标题（36px, line-height 1.15, margin-bottom 28px）。
   - 将 Composer 强化为 860px 核心功能对象。
   - 将 Quick Actions 重构为贴合 Composer 的 Suggestion Row（18px 间距，85% 宽度）。
   - 下方彻底消除死白：提供高价值的 **Suggested Workflows**（S3 时序辨识 / 多变量质量诊断 / 闭环参数寻优）与 **Recent Runs** 唤醒区，使 1440×900 和 1920×1080 拥有完美的黄金比例视觉平衡。
3. **重构 WorkspaceView**:
   - 强化 Pane 架构：左侧 Context (240px)，中间 Agent 流 (flex 0.9fr)，右侧 Artifact Workbench (minmax 520px, flex 1.1fr)。
   - 统一细线 Divider，消除卡片漂浮感。
4. **统一所有 Detail 页面**:
   - 引入标准 `.page-container`（1280px max-width），统一 Page Header（32px bottom margin）、Section Gap（32~48px）、MetricStrip 等宽网格。
5. **Visual QA 验证**:
   - 检查 1920×1080 与 1440×900 视口下的几何对称性、中心轴线与信息密度。
