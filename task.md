# LIGHT-FIRST VISUAL THEME REFACTOR PROGRESS
主题: INDUSOPT — WARM LIGHT (柔暖明亮米白 + 鼠尾草 Sage 绿)

---

## 阶段规划与执行进度

### Stage 1: Design Tokens & Global Styles (Light Default) 🟡
- [ ] 重构 `src/assets/design-tokens.css`（`:root` 默认设为 Warm Light，`[data-theme="dark"]` 作为备用）
  - App 背景：`--bg-app: #F6F7F3`, `--bg-subtle: #F1F3EE`, `--bg-sidebar: #F8F9F6`
  - Surface：`--surface-1: #FFFFFF`, `--surface-2: #FAFBF8`, `--surface-3: #F3F5F0`, `--surface-hover: #EEF1EB`, `--surface-active: #E8EDE5`
  - 边框：`--border-subtle: #ECEEE9`, `--border-default: #E2E5DE`, `--border-strong: #D4D9D1`
  - 文本：`--text-primary: #20231F`, `--text-secondary: #626860`, `--text-tertiary: #81877E`, `--text-muted: #9CA19A`, `--text-disabled: #BEC2BC`
  - 品牌：`--accent: #82A978`, `--accent-hover: #719967`, `--accent-active: #638B59`, `--accent-dark: #52735A`, `--accent-soft: #EDF4E9`, `--accent-medium: #DDEBD7`, `--accent-border: #C9DEC2`
  - 状态：`--success: #66956E`, `--warning: #B48A47`, `--danger: #B96560`, `--info: #70899E`
  - 图表：`--chart-1: #6E9B69`, `--chart-2: #7995A8`, `--chart-3: #B28B50`, `--chart-4: #96799F`, `--chart-5: #B8746E`
  - 暗色终端专用：`--dark-panel: #20231F`, `--dark-panel-secondary: #292D28`, `--dark-text: #F4F5F1`
- [ ] 重构 `src/assets/main.css`（全局浅色底色、浅色滚动条、Element Plus 浅色覆盖层、暖光微投影）

### Stage 2: Navigation & Shell (Light Warm Minimalist) ⚪
- [ ] `PrimaryNav.vue` & `NavItem.vue`：
  - 侧栏底色 `#F8F9F6`，右边框 `#ECEEE9`
  - 普通图标 `#7E847B`，hover `#EFF1EC`，选中项 `#E8F0E5` (文字 `#354234`, 图标 `#557651`, 左侧 2px `#82A978`)
- [ ] `AppShell.vue`：浅色主视窗背景 `#F6F7F3`

### Stage 3: Landing Page & Home View (Airy, Calm, Premium) ⚪
- [ ] `LandingView.vue`：
  - 顶部 Header：`rgba(246,247,243,0.88)` + blur(12px) + `#E8EAE5` 边框，白色 Logo 方块 `#FFFFFF` (边框 `#DFE4DB`，图标 `#698F64`)
  - Hero 区域：Eyebrow `#EDF4E9`/`#5D7E58`，主标题 `#20231F`，副行 `#52735A` (彻底删除亮蓝)
  - CTA：Primary `#82A978` (白字，微阴影)，Secondary `#FFFFFF` (边框 `#DDE1DA`，字 `#444A43`)
  - Stats Strip：`#FFFFFF` 卡片，边框 `#E3E6DF`，数字 `#282C27`
  - Workspace Preview：外层 `#FFFFFF`，顶栏 `#F2F4EF`，内层 `#FAFBF8`，中性灰圆点
  - Features / Workflow / Benchmark / HITL / CTA 区域全面转为 Warm Light
- [ ] `HomeView.vue`：
  - 浅色留白主页，Logo 方块 `#FFFFFF`，A14 徽标 `#EDF4E9`/`#52735A`
  - 主标题 `#20231F`，副标题 `#81877E`
  - Quick Actions：`#FFFFFF` 底色，边框 `#E2E5DE`，hover `#FAFBF8`
  - Recent Tasks：`#FFFFFF` 卡片，中性轻边框
- [ ] `AgentComposer.vue`：
  - 主体 `#FFFFFF`，边框 `#DDE1DA`，轻柔投影 `0 4px 18px rgba(30,40,28,0.045)`
  - 聚焦边框 `#AFC8A8` + `0 0 0 3px rgba(130,169,120,0.10)`
  - 文字 `#20231F`，placeholder `#989D96`，底栏 `#F8F9F6`
  - 发送按钮 `#82A978` (白字/白色图标)

### Stage 4: Workspace, Stream, Approval & Artifacts (Light Workspace) ⚪
- [ ] `WorkspaceView.vue`：左栏 `#F8F9F6`，中栏 `#FFFFFF`/`#F6F7F3`，右栏 `#FAFBF8`
- [ ] `AgentStream.vue`：用户气泡 `#F0F4ED`，Agent 执行块 `#F7F8F5`，状态提示浅色化
- [ ] `AgentPlan.vue` & `ToolExecution.vue`：白色/暖灰技术面板，浅色进度线
- [ ] `ApprovalCard.vue`：`#FFFDF7` 浅暖黄背景，`#B48A47` 左指示条，`#82A978` 确认按钮
- [ ] `ArtifactWorkbench.vue` & `MetricStrip.vue`：`#FAFBF8` 表面，`#FFFFFF` 内嵌面板，暗色仅用于 Code/Terminal

### Stage 5: Secondary Data & Modeling Views Migration ⚪
- [ ] `CleaningView.vue`, `SegmentationView.vue`, `DelayView.vue`, `CollinearityView.vue`
- [ ] `ARXModelingView.vue`, `OptunaView.vue`, `BenchmarkView.vue`, `SimulationView.vue`
- [ ] `DatasetsView.vue`, `DatasetDetailView.vue`, `DeliverablesView.vue`, `SettingsView.vue`, `RunsView.vue`, `AssetsView.vue`, `CommandPalette.vue`
- [ ] 表格、输入框、表头与 ECharts 曲线浅色化

### Stage 6: Validation, Build, Screenshots & Documentation ⚪
- [ ] 自动化单元测试 (`npm test`)
- [ ] 生产构建 (`npm run build`)
- [ ] 输出 `docs/LIGHT_THEME_REFACTOR.md`
