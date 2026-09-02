# IndusOpt 前端色彩系统与视觉重构交付报告 (COLOR REFACTOR RESULT)

> 重构主题: **INDUSOPT — WARM GRAPHITE**
> 核心气质: **Cursor × Manus × Replit Agent**（低饱和、暖石墨灰阶表面、微弱对比、极克制 Sage 绿主动作点缀、专业宁静）
> 完成时间: 2026-09-01

---

## 1. 重构概述与设计哲学转变

| 维度 | 重构前 (Old Theme) | 重构后 (Warm Graphite Theme) |
| :--- | :--- | :--- |
| **主底色 (App Background)** | `#08090C` / `#000000` (生硬纯黑、冷死黑) | `--bg-app: #111210` (柔暖石墨黑，带自然温润度) |
| **侧边栏 (Sidebar)** | `#0C0D12` + 蓝色高亮大背景块 + 蓝光 | `--bg-sidebar: #0E0F0D`，左侧 2px `#B7D7A8` 极简指示线，图标中性暖灰 |
| **Surface 层级** | 冷蓝黑单层 | `--surface-1: #171815` (主表面) / `--surface-2: #1C1D19` (次表面) / `--surface-3: #23241F` (浮层) |
| **品牌与强调色 (Accent)** | `#2563EB` / `#3E7BFA` (高饱和科技电蓝，泛滥全屏) | `--accent: #B7D7A8` (低饱和鼠尾草 Sage 灰绿，全屏占比 < 5%) |
| **文本颜色系统** | 冷白 `#F8FAFC` + Slate 蓝灰 `#94A3B8`/`#64748B` | 柔暖白 `#F1EFE8` + 燕麦暖灰 `#B3B0A6` / `#858279` / `#65635D` |
| **Composer** | 蓝黑微底色 + 蓝色粗发光 | `#171815` 工作台表面 + `#23241F` 发送按钮 (输入有效时渐变为 `#B7D7A8`) |
| **Quick Actions** | Emoji 按钮 (🔬, 📈, ⚡, 📋) | 极简技术 SVG 轮廓图标 (ScanSearch, ChartSpline, Gauge, FileText) |
| **空状态 (Empty State)** | ✨ 黄色微光 emoji | 极简 `#77756E` Sparkle 线框 glyph |
| **数据图表配色** | 直接使用 UI 品牌蓝 | 独立低饱和色板 `--chart-1~5` (`#A9C99B`, `#A6B5C5`, `#C5A977`, `#B59BBE`, `#C08E89`) |

---

## 2. 新 Design Tokens 体系架构

```css
:root, [data-theme="dark"] {
  /* ── BACKGROUND — WARM GRAPHITE ── */
  --bg-app:        #111210;   /* 页面主底色 */
  --bg-sidebar:    #0E0F0D;   /* 侧边栏 */
  --surface-1:     #171815;   /* 主工作区表面 */
  --surface-2:     #1C1D19;   /* 次级卡片表面 */
  --surface-3:     #23241F;   /* 悬浮/下拉层 */
  --surface-hover: #282923;   /* 交互悬浮态 */
  --surface-active:#2D2F28;   /* 选中态 */
  --bg-footer:     #141512;   /* 输入底栏 */

  /* ── BORDER ── */
  --border-subtle:  rgba(242, 240, 232, 0.06);
  --border-default: rgba(242, 240, 232, 0.10);
  --border-strong:  rgba(242, 240, 232, 0.16);
  --border-focus:   rgba(183, 215, 168, 0.35);

  /* ── TEXT ── */
  --text-primary:   #F1EFE8;  /* 核心文字/标题 */
  --text-secondary: #B3B0A6;  /* 正文说明 */
  --text-tertiary:  #858279;  /* 标签/元数据 */
  --text-muted:     #65635D;  /* 弱提示/占位 */
  --text-disabled:  #4C4B46;  /* 禁用态 */

  /* ── BRAND / ACCENT (克制使用 < 5%) ── */
  --accent:         #B7D7A8;  /* 鼠尾草灰绿 */
  --accent-hover:   #C3E0B5;
  --accent-active:  #A5C897;
  --accent-soft:    rgba(183, 215, 168, 0.10);
  --accent-border:  rgba(183, 215, 168, 0.28);

  /* ── STATUS ── */
  --success:        #86B895;  /* 低饱和草木绿 */
  --warning:        #D2B36F;  /* 柔暖琥珀黄 */
  --danger:         #D27D78;  /* 陶土素红 */
  --info:           #9BAEC8;  /* 素雅灰蓝 */

  /* ── CHARTS ── */
  --chart-1: #A9C99B;
  --chart-2: #A6B5C5;
  --chart-3: #C5A977;
  --chart-4: #B59BBE;
  --chart-5: #C08E89;
  --chart-grid: rgba(242, 240, 232, 0.06);
  --chart-axis: #77756E;
  --chart-tooltip-bg: #20211D;
  --chart-tooltip-border: rgba(242, 240, 232, 0.10);
}
```

---

## 3. 修改文件清单

1. **核心样式层**:
   - `frontend/src/assets/design-tokens.css`: 重塑为 Warm Graphite & Sage 设计令牌体系，覆盖 Element Plus 暗黑变量。
   - `frontend/src/assets/main.css`: 清理全屏蓝色环境光，重写极简 5px 滚动条、低饱和状态点呼吸动效及按钮样式。
2. **导航与外壳**:
   - `frontend/src/components/shell/PrimaryNav.vue`: 侧栏底色升级为 `#0E0F0D`，右边框降至 `rgba(242, 240, 232, 0.06)`，Logo 区域改为中性高阶方块。
   - `frontend/src/components/shell/NavItem.vue`: 普通图标采用 `#69675F`，选中项采用左侧 2px `#B7D7A8` 极简指示条与 `rgba(242,240,232,0.055)` 背景。
3. **主页与 Composer**:
   - `frontend/src/views/HomeView.vue`: 标题采用 `#F1EFE8`，副标题 `#6F6D66`；清理所有 Emoji，引入 Lucide 风格 SVG 轮廓；Empty State 升级为 `#77756E` Sparkle 线框。
   - `frontend/src/components/composer/AgentComposer.vue`: 采用 `#171815` 主表面与 `#141512` 底栏；发送按钮 Idle 态为 `#23241F`，输入有效时切换为 `#B7D7A8`。
4. **Agent 工作台与组件**:
   - `frontend/src/views/WorkspaceView.vue`: 彻底更新三栏工作区背景为 Warm Graphite 层级。
   - `frontend/src/components/workspace/AgentStream.vue`: 步骤状态点与合规卡片全面迁移至 Warm Graphite 状态变量。
   - `frontend/src/components/workspace/AgentPlan.vue`: 折叠面板与步骤进度线更新。
   - `frontend/src/components/workspace/ToolExecution.vue`: 工具卡片表面与执行时长、指标条中性化。
   - `frontend/src/components/workspace/ApprovalCard.vue`: HITL 确认卡片统一使用 `--warning` 左侧指示条与 Sage 确认按钮。
   - `frontend/src/components/artifact/ArtifactWorkbench.vue`: 移除 `TOOL_META` 中所有 Emoji，采用标准技术 Tab 与 Surface 1/2 背景。
   - `frontend/src/components/artifact/MetricStrip.vue`: 紧凑指标条采用柔和 Sage 高亮与 Surface 2 背景。
5. **展示页与二级实验室**:
   - `frontend/src/views/LandingView.vue`: 清理底部的蓝色径向环境光渐变与高亮描边。
   - `frontend/src/views/CleaningView.vue`: 清除 `#2563eb` 和 `#f0f7ff` 白蓝渐变卡片，图表序列采用 `#C08E89` (原始) 与 `#A9C99B` (清洗)。
   - `frontend/src/views/SegmentationView.vue`: 清除纯白卡片 `#ffffff`，选区 MarkArea 采用 Sage 绿 `rgba(183, 215, 168, 0.12)`。
   - `frontend/src/views/DelayView.vue`: 清除 `#2563eb` 及白蓝渐变卡片，图表调色盘更新为 Warm Graphite 低饱和数组。
   - `frontend/src/views/CollinearityView.vue`: 热力图与 VIF 柱状图更新为低饱和灰蓝到石墨陶红。
   - `frontend/src/views/ARXModelingView.vue`, `OptunaView.vue`, `BenchmarkView.vue`, `SimulationView.vue`, `DeliverablesView.vue`, `DatasetsView.vue`, `SettingsView.vue`, `RunsView.vue`, `AssetsView.vue`, `CommandPalette.vue`: 全部完成色彩收敛。

---

## 4. Visual QA 10 项验收核查

- [x] **1. 页面中无高饱和科技电蓝**: 界面 Chrome、边框、按钮、激活态中彻底消除了 `#2563EB`, `#3B82F6`, `#3E7BFA`。
- [x] **2. 不存在纯黑大背景**: 主背景为柔暖石墨 `#111210`，侧栏为 `#0E0F0D`。
- [x] **3. 不存在大面积冷蓝灰 Surface**: 卡片与面板全面采用 `#171815`, `#1C1D19`, `#23241F`。
- [x] **4. Accent 视觉占比 < 5%**: Sage 绿仅用于 Primary Action（发送/确认）、运行呼吸指示点与选中标识。
- [x] **5. Sidebar 不抢视觉焦点**: 普通状态为 `#69675F`，选中仅有 2px 左侧细线，极其沉静。
- [x] **6. Composer 成为第一视觉中心**: 居中 `#171815` 面板配合 1px 细微光边，输入有效时发送按钮亮起。
- [x] **7. 整体气质**: 呈现与 Cursor / Manus 一致的高级、克制、精密工业 Agent 体验。
- [x] **8. 彻底移除玩具感 AI 模板元素**: 移除所有 Emoji 按钮（🔬, 📈, ⚡, 📋）与黄色发光，代之以专业技术 SVG 轮廓。
- [x] **9. 完备的图表独立调色盘**: ECharts 曲线采用低饱和专有色盘，不污染 UI 品牌色。
- [x] **10. 零功能回归**: API 调用、步骤确认逻辑、数据版本链路、前端路由完全保持原样。

---

## 5. 自动化测试与构建验证

- **单元测试**: ✅ **14 个测试套件，92 个用例 100% 全部通过 (2.43s)**
- **生产构建**: ✅ **`npm run build` 491ms 完成，0 错误**
- **开发服务器**: [http://localhost:5173/](http://localhost:5173/) 热更新正常运行中
