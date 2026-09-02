# IndusOpt 全局布局与空间系统重构总结报告 (LAYOUT_REFACTOR_RESULT)

> **重构目标**：建立统一的 **App Shell** + **Content Grid** + **Width System** + **Vertical Rhythm** + **Density System**，彻底解决前端“页面头重脚轻、大量无意义空白、内容宽度与节奏不统一、不同页面像拼凑”的问题，使整个系统具备现代成熟 Agent 产品（Manus / Linear / Cursor / Lovable）的工业级空间秩序感与高级呼吸感。

---

## 一、重构前后问题对照与核心收益

| 维度 | 重构前问题 | 重构后设计规范与实现 |
| :--- | :--- | :--- |
| **App Shell 容器** | 各页面随意写 `width`、`max-width: 860px/920px/100vw`，左侧侧边栏 56px 未统一计算导致水平滚动条或不对齐 | 统一 App Shell 容器：`width: calc(100vw - var(--sidebar-width)); min-width: 0;`，全站建立 `.page-container`（最大 1280px，自适应响应式 Gutter 20px / 32px / 48px） |
| **Home 首页视觉** | 顶部有冗余居中大 Logo，页面像宣传 Landing Page；下部出现大面积无意义死白；Composer 尺寸过窄或过宽 | 统一单中心轴设计：移除中央冗余 Logo，顶部统一 Eyebrow `A14 · INDUSTRIAL AI AGENT WORKSPACE` + Headline（36px）+ 核心 **860px** Composer；下方提供快捷 Suggestion Row + 3 张高价值 **Suggested Workflows** 卡片，彻底填补空间并建立首屏专业功能感 |
| **Workspace 工作区** | 双栏/三栏断裂，Agent Stream 缺乏宽度收敛，Artifact Workbench 尺寸僵硬 | 采用 Pane-based 分栏：左侧 Context（240px），中间 Agent Stream 严格收敛于 `--workspace-center-max: 760px` 中心轴，右侧 Artifact Workbench 使用弹性 `clamp(460px, 38vw, 640px)`，流式日志与工件面板浑然一体 |
| **Detail 页面标准** | 各分析/建模页 padding 混乱（`padding: 24px clamp(20px, 3.5vw, 40px) 48px`），Header 高度与结构各不相同 | 全局统一 `.page-header-unified`：固定 32px 底部外边距，包含分类 Eyebrow、H1 标题与副标题；表格与参数卡片统一遵循 1280px 标准容器与 24px / 32px 垂直间距 |
| **网格与间距系统** | 随机的 margin/padding 数值（15px, 22px, 35px 等） | 严格基数倍数网格（4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80, 96px）与标准 CSS 变量 tokens |

---

## 二、空间系统规范 (Layout Design Tokens)

在 `src/styles/layout.css` 中建立了全套响应式空间与网格变量：

```css
:root {
  /* Sidebar & Shell */
  --sidebar-width: 56px;
  --sidebar-expanded-width: 232px;

  /* Page Gutters */
  --page-gutter-sm: 20px;
  --page-gutter-md: 32px;
  --page-gutter-lg: 48px;

  /* Max Width System */
  --content-max: 1280px;            /* Standard: Dataset, Model, Benchmark, Deliverables */
  --content-wide: 1440px;           /* Wide: Large Tables & Multi-charts */
  --reading-max: 760px;             /* Reading: Report texts, long descriptions */
  --agent-home-max: 920px;          /* Home Hero column */
  --workspace-center-max: 760px;    /* Agent conversation stream */
  --composer-max: 860px;            /* Agent input card */

  /* Section Gaps (Vertical Rhythm) */
  --section-gap-xs: 16px;
  --section-gap-sm: 24px;
  --section-gap-md: 32px;
  --section-gap-lg: 48px;
  --section-gap-xl: 64px;
  --section-gap-2xl: 88px;
}
```

### 1. 四层宽度标准 (Width Tiers)
1. **READING (`760px`)**: 用于交付报告正文、详细分析文档、Agent 思考过程流。
2. **FOCUSED (`860px ~ 920px`)**: 用于 Home 首页 Agent Composer、表单录入与任务执行入口。
3. **STANDARD (`1280px`)**: 全局统一的标准业务内容宽度，用于数据集列表、ARX 系统辨识、Optuna 寻优、消融基准与系统设置。
4. **WIDE (`100% - Gutters`, 最大 1440px)**: 用于 Workspace 三栏工作台与预处理全流程实验室。

### 2. 统一页面容器与页头结构
全站统一采用：
```html
<div class="page-container">
  <div class="page-header-unified">
    <div class="page-header-unified__main">
      <span class="page-header-unified__eyebrow">MODULE · 模块分类</span>
      <h1 class="page-header-unified__title">页面标题</h1>
      <p class="page-header-unified__desc">模块核心工业算法与业务功能说明</p>
    </div>
    <div class="page-header-unified__actions">
      <!-- 快捷操作按钮 -->
    </div>
  </div>

  <!-- 页面主体卡片与网格内容 -->
</div>
```

---

## 三、各页面重构实施明细

### 1. Home 首页 (`src/views/HomeView.vue`)
- **删除冗余元素**：移除居中多余的大尺寸 Logo，与侧边栏品牌区消除重复。
- **强化首屏中心轴**：
  - Eyebrow: `A14 · INDUSTRIAL AI AGENT WORKSPACE`（柔和草本绿胶囊徽章）
  - Headline: `今天想分析或优化什么？`（36~38px，清晰明快）
  - Agent Composer: 严格限定在 **860px**，内边距 `18px 20px 14px`，Footer 高度 `52px`，操作按钮自右侧对齐。
  - Suggestion Row: 4 个高频快捷词元紧跟输入框下方（`18px` 间距）。
- **彻底解决下部死白问题**：
  - 接入动态 Recent Tasks（如用户有历史记录则展示最近任务卡片）。
  - 无历史记录时展示 3 组精心设计的 **Suggested Workflows** 核心卡片：
    - `S3 动态时序辨识` (System ID)
    - `多变量数据质量诊断` (Diagnostics)
    - `闭环工况参数寻优` (Optimization)
  - 页面在 1440×900 和 1920×1080 下均具备平衡的黄金分割垂直节奏，无任何空旷感。

### 2. Workspace 沉浸工作台 (`src/views/WorkspaceView.vue`, `AgentStream.vue`)
- **Pane 结构分栏**：
  - 左侧 Context 栏：固定 240px，柔和边框分割。
  - 中间 Agent Stream：Flex 弹性自适应，内部日志流严格限制在 `760px` 中心轴阅读宽度。
  - 右侧 Artifact Workbench：使用 `clamp(460px, 38vw, 640px)` 动态宽度，保证可视化图表与数据表具备充裕展示空间。

### 3. 数据资产与分析详情 (`src/views/DatasetsView.vue`, `DatasetDetailView.vue`, `AssetsView.vue`)
- 接入 `.page-container`，消除随机 padding。
- 采用 `.page-header-unified`，统一操作区右浮动。
- 解决数据表操作列固定与单元格换行问题。

### 4. 系统辨识、寻优与实验室 (`ARXModelingView.vue`, `OptunaView.vue`, `CleaningView.vue`, `SegmentationView.vue`, `DelayView.vue`, `CollinearityView.vue`, `BenchmarkView.vue`, `SimulationView.vue`, `DeliverablesView.vue`, `SettingsView.vue`)
- 彻底移除硬编码的 `padding: var(--space-6) clamp(...) var(--space-12)` 与随机 margin。
- 统一使用 `.page-container` + `.page-header-unified` + `--section-gap-md (32px)` 垂直节奏。
- 参数卡片与图表容器统一采用网格对齐，消除不对齐与视觉抖动。

---

## 四、验证与构建质量

### 1. 单元测试套件
```bash
$ npm test
Test Files  14 passed (14)
     Tests  92 passed (92)
  Duration  2.24s
```
全部 14 个测试文件、92 项测试用例 100% 通过，无任何逻辑与路由回归。

### 2. 生产构建打包
```bash
$ npm run build
✓ built in 482ms
```
静态资源构建全部通过，无 CSS 解析错误与死链。

### 3. 多分辨率实机截图归档 (Browser Visual QA)
已通过无头浏览器在 `artifacts/layout-refactor/` 下完成多分辨率实机渲染截图验证：
- `artifacts/layout-refactor/home-1920x1080.png` (Home 首屏 1920×1080)
- `artifacts/layout-refactor/home-1440x900.png` (Home 首屏 1440×900)
- `artifacts/layout-refactor/workspace-1920x1080.png` (Workspace 1920×1080)
- `artifacts/layout-refactor/workspace-1440x900.png` (Workspace 1440×900)
- `artifacts/layout-refactor/datasets-1440x900.png` (数据资产标准 1280px 容器)
- `artifacts/layout-refactor/arx-1440x900.png` (ARX 系统辨识标准 1280px 容器)
- `artifacts/layout-refactor/optimization-1440x900.png` (Optuna 闭环寻优标准 1280px 容器)
- `artifacts/layout-refactor/deliverables-1440x900.png` (成果交付标准 1280px 容器)
