# IndusOpt 前端颜色系统审计报告 (COLOR SYSTEM AUDIT)

> 生成时间: 2026-09-01
> 审计目标: 梳理当前前端代码库中的所有色彩定义、硬编码色彩、高饱和电蓝色系与样式不一致点，为 "WARM GRAPHITE"（暖灰石墨 + 鼠尾草灰绿）重构提供完整证据链。

---

## 1. 核心问题定位

当前前端色彩系统存在以下明显特征，导致了强烈的“廉价 AI Dashboard / 网络安全控制台 / 工业大屏 Demo”观感：
1. **纯黑与深冷黑背景 (`#08090C`, `#000000`, `#0F172A`)**：底色过于死黑、生硬冰冷，缺乏如 Cursor / Manus / Linear 等成熟 Agent 产品的自然暖调石墨灰（Warm Graphite）。
2. **高饱和电蓝色系泛滥 (`#2563EB`, `#3B82F6`, `#3E7BFA`, `#60A5FA`, `#1D4ED8`)**：品牌色、按钮、选中态、描边、外发光、标签、图表几乎全部使用生硬的科技蓝。
3. **Tailwind Slate 蓝灰文本与卡片 (`#94A3B8`, `#64748B`, `#475569`, `#1E293B`, `#334155`)**：次级文本与边框带有浓重蓝调，与深色底形成生硬对比。
4. **大量 Hard-coded Hex 与不统一透明度**：在预处理与建模实验室页面（`CleaningView`, `DelayView`, `CollinearityView` 等）及旧组件中残留大量直接写死的 `#2563EB`, `#ffffff`, `rgba(37, 99, 235, 0.15)` 等。
5. **Emoji 图标与 AI 模板感**：快捷按钮使用了 Emoji（🔬, 📈, ⚡, 📋）与黄色微光（✨），显得像玩具 Demo。

---

## 2. 详细色彩分布与审计清单

### 2.1 高饱和蓝色系 (需彻底清除/替换)

| 色值 / 格式 | 出现次数 | 主要分布文件 | 视觉角色 | 替换方案 |
| :--- | :--- | :--- | :--- | :--- |
| `#2563EB` | 62 次 | `CleaningView`, `CollinearityView`, `DelayView`, `SegmentationView`, `AppHeader`, `Landing` 组件群 | 主按钮、选中态、图表主色、Badge 边框 | 替换为 `var(--accent)` (`#B7D7A8`) 或图表独立色 `var(--chart-1)` |
| `#3B82F6` | 5 次 | `design-tokens.css`, `main.css`, `LandingView.vue` | 运行状态点、Accent 悬浮色、文字高光 | 替换为 `var(--accent)` (`#B7D7A8`) 或 `var(--accent-hover)` |
| `#3E7BFA` | 3 次 | `design-tokens.css` | 旧 Accent 主品牌色 | 替换为 Warm Sage `--accent: #B7D7A8` |
| `#60A5FA` / `#93C5FD` | 12 次 | `LandingView.vue`, `AppSidebar.vue`, `main.css` | 运行状态徽章、渐变文字、边框发光 | 替换为低饱和状态色与中性文本 |
| `#EFF6FF` / `#F0F7FF` | 21 次 | `CleaningView`, `DashboardView`, `Landing` 组件群 | 亮蓝微底色卡片 | 替换为 Surface 1/2/3 中性层级 |
| `rgba(37, 99, 235, *)` | 15 次 | `CleaningView`, `SegmentationView`, `Landing` 组件群 | 按钮微阴影、波形阴影、选区填充 | 替换为 `var(--accent-soft)` / `var(--surface-3)` |
| `rgba(62, 123, 250, *)` | 8 次 | `design-tokens.css`, `HomeView.vue`, `LandingView.vue` | 顶部环境光、聚焦光晕、Logo 背景 | 移除蓝色发光，改用极弱中性光晕与边框 |

### 2.2 背景与 Surface 层级现状

| 当前 Token / 硬编码 | 当前值 | 存在问题 | 目标新 Token | 新值 (Warm Graphite) |
| :--- | :--- | :--- | :--- | :--- |
| `--bg-app` | `#08090C` | 偏冷偏死黑 | `--bg-app` | `#111210` |
| `--bg-sidebar` | `#0C0D12` | 偏蓝黑 | `--bg-sidebar` | `#0E0F0D` |
| `--bg-surface` | `#12141A` | 冷灰 | `--surface-1` | `#171815` |
| `--bg-elevated` | `#181B23` | 偏冷 | `--surface-2` | `#1C1D19` |
| `--bg-overlay` | `#1E222D` | 蓝灰 | `--surface-3` | `#23241F` |
| Hover / Active | `rgba(255,255,255,0.06)` | 缺乏暖度 | `--surface-hover` / `--surface-active` | `#282923` / `#2D2F28` |

### 2.3 边框体系现状

| 边框类型 | 当前值 | 存在问题 | 目标新 Token |
| :--- | :--- | :--- | :--- |
| Subtle Border | `rgba(255,255,255,0.08)` | 冷白色系 | `--border-subtle: rgba(242, 240, 232, 0.06)` |
| Default Border | `rgba(255,255,255,0.14)` | 对比度偏生硬 | `--border-default: rgba(242, 240, 232, 0.10)` |
| Strong Border | `rgba(255,255,255,0.22)` | 过亮 | `--border-strong: rgba(242, 240, 232, 0.16)` |
| Accent Border | `rgba(62,123,250,0.32)` | 蓝色描边 | `--accent-border: rgba(183, 215, 168, 0.28)` |

### 2.4 文本颜色体系现状

| 文本层级 | 当前值 | 存在问题 | 目标新 Token | 新值 |
| :--- | :--- | :--- | :--- | :--- |
| Primary Text | `#F8FAFC` | 偏冷白 | `--text-primary` | `#F1EFE8` (柔和暖米白) |
| Secondary Text | `#94A3B8` | 明显 Slate 蓝灰 | `--text-secondary` | `#B3B0A6` (暖灰) |
| Tertiary / Label | `#64748B` | 明显 Slate 蓝灰 | `--text-tertiary` | `#858279` (中性暖灰) |
| Muted / Auxiliary | `#475569` | 灰暗蓝调 | `--text-muted` | `#65635D` |
| Disabled | N/A | 缺失统一 token | `--text-disabled` | `#4C4B46` |

### 2.5 状态与 Agent 运行色彩现状

| 语义状态 | 当前值 | 当前问题 | 目标新 Token 与值 |
| :--- | :--- | :--- | :--- |
| **RUNNING (Agent)** | `#3E7BFA` (电蓝) | 误将电蓝作为执行状态 | `--accent: #B7D7A8` (低饱和 Sage 绿微脉冲) |
| **COMPLETED** | `#10B981` (高亮绿) | 过亮 | `--success: #86B895` / `--success-soft` |
| **WAITING (HITL)** | `#F59E0B` (亮橙) | 刺眼 | `--warning: #D2B36F` / `--warning-soft` |
| **FAILED / ERROR** | `#F43F5E` (洋红/玫瑰红)| 偏粉红 | `--danger: #D27D78` / `--danger-soft` |
| **INFO** | `#38BDF8` (高亮天蓝) | 泛滥天蓝 | `--info: #9BAEC8` / `--info-soft` |

### 2.6 数据可视化 / 图表调色盘 (ECharts)

当前图表直接硬编码了 `#2563eb`, `#E76F51`, `#2A9D8F`, `#f43f5e`, `#d97706`。需建立独立且克制低饱和的图表色板：
- `--chart-1: #A9C99B` (柔和鼠尾草绿)
- `--chart-2: #A6B5C5` (素雅灰蓝)
- `--chart-3: #C5A977` (柔暖土黄)
- `--chart-4: #B59BBE` (低饱和粉紫)
- `--chart-5: #C08E89` (素陶红)
- 网格线：`rgba(242, 240, 232, 0.06)`
- 坐标轴文字：`#77756E`
- Tooltip 背景：`#20211D` (边框 `rgba(242, 240, 232, 0.10)`)

---

## 3. 重构执行路线

1. **第 1 步**: 重塑 `frontend/src/assets/design-tokens.css` 与 `main.css`，注入 WARM GRAPHITE 完整变量架构，覆盖 Element Plus 暗黑体系。
2. **第 2 步**: 重构 App 容器与导航 (`AppShell.vue`, `PrimaryNav.vue`, `NavItem.vue`)，实现克制 2px Accent 指示条与纯暖灰表面。
3. **第 3 步**: 重构 `HomeView.vue` 与 `AgentComposer.vue`：
   - 彻底移除 Emoji，引入 Lucide / 极简 SVG 轮廓图标。
   - 替换 Logo、A14 徽标、标题字体色彩为柔和暖白 `#F1EFE8`。
   - Composer 采用 `#171815` 底色 + `#23241F` 发送按钮 (输入有效时渐变为 `#B7D7A8`)。
   - Empty State 采用 `#77756E` 极简 Sparkle 轮廓。
4. **第 4 步**: 重构 `WorkspaceView.vue`, `AgentStream.vue`, `AgentPlan.vue`, `ToolExecution.vue`, `ApprovalCard.vue`, `ArtifactWorkbench.vue`，消除所有蓝光、蓝黑底色与生硬 Badge。
5. **第 5 步**: 全面覆盖其余 Views (`LandingView`, `DatasetsView`, `DatasetDetailView`, `CleaningView`, `SegmentationView`, `DelayView`, `CollinearityView`, `ARXModelingView`, `OptunaView`, `BenchmarkView`, `SimulationView`, `DeliverablesView`, `SettingsView`, `RunsView`, `AssetsView`)，消灭所有写死的高饱和蓝与 `#ffffff`。
6. **第 6 步**: 验证构建、单元测试、E2E 兼容性，生成 `docs/COLOR_REFACTOR_RESULT.md`。
