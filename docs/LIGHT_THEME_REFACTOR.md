# IndusOpt 浅色主题重构交付报告 (LIGHT-FIRST VISUAL THEME REFACTOR)

> 主题名称: **INDUSOPT — WARM LIGHT**
> 核心关键词: **LIGHT, WARM, CALM, PREMIUM, NEUTRAL, AIRY, PROFESSIONAL, AGENT-NATIVE, INDUSTRIAL**
> 视觉参考: **Manus × Lovable × v0 × Linear × Cursor Light Workspace**
> 交付时间: 2026-09-01

---

## 1. 重构目标与核心设计哲学转变

本次重构彻底终结了“Dark AI Console / 黑色工业控制台”带来的沉重、玩具感与廉价 AI 模板印象，全面转向以 **Warm Light（柔暖米白 + 鼠尾草 Sage 绿）** 为默认视觉基础的现代工业 Agent 工作台。

### 核心转变对比表

| 维度 | 旧版 (Dark Console) | 新版 (Warm Light Workspace) |
| :--- | :--- | :--- |
| **默认主题** | 纯黑/深灰暗黑模式为主 | **默认 Warm Light 浅色模式**（Dark Mode 可在设置中按需开启） |
| **主背景 (App Background)** | `#111210` / `#08090C` 黑色死沉 | `--bg-app: #F6F7F3`（温润米白，顶部 0.08 弱浅绿微晕，极具呼吸感） |
| **工作台表面 (Surface)** | `#171815` / `#1C1D19` 深色 Panel | `--surface-1: #FFFFFF`, `--surface-2: #FAFBF8`, `--surface-3: #F3F5F0` |
| **主边框系统** | 深色细线 | `--border-subtle: #ECEEE9`, `--border-default: #E2E5DE`, `--border-strong: #D4D9D1` |
| **主视觉排印 (Typography)** | 高亮冷白 + 蓝灰 | 标题 `--text-primary: #20231F` (深石墨暖黑) + 正文 `--text-secondary: #626860` |
| **品牌与强调色 (Accent)** | 容易泛滥的电蓝 / 霓虹绿 | `--accent: #82A978` (精炼鼠尾草绿，白字高对比)，全屏占比严格 < 5% |
| **标题二行文案** | 曾存在亮蓝科技渐变 | 采用自然深绿 `--accent-dark: #52735A`，纯靠字重排版产生冲击力 |
| **Composer** | 深黑输入框 | `#FFFFFF` 高级卡片 + `#DDE1DA` 边框 + `0 4px 18px rgba(30,40,28,0.045)` 柔光投影 |
| **Dark Utility 用途** | 全屏到处黑底 | **严格限定**：仅用于 Terminal / Logs / Code 等原生代码执行窗口 |

---

## 2. 全局 Design Tokens 架构

```css
:root {
  /* ── APP BACKGROUND (WARM NEUTRAL OFF-WHITE) ── */
  --bg-app:        #F6F7F3;   /* 页面主底色 */
  --bg-subtle:     #F1F3EE;   /* 次级底色 */
  --bg-sidebar:    #F8F9F6;   /* 侧边栏 */

  /* ── SURFACES ── */
  --surface-1:     #FFFFFF;   /* 主卡片 / 核心工作区 */
  --surface-2:     #FAFBF8;   /* 次级卡片 / 嵌套背景 */
  --surface-3:     #F3F5F0;   /* 浮层 / 按钮底色 / 下拉面板 */
  --surface-hover: #EEF1EB;   /* 交互悬浮态 */
  --surface-active:#E8EDE5;   /* 选中态 */
  --bg-footer:     #F8F9F6;   /* 输入底栏 */

  /* ── BORDER ── */
  --border-subtle: #ECEEE9;  /* 结构分割线 */
  --border-default:#E2E5DE;  /* 默认卡片与输入边框 */
  --border-strong: #D4D9D1;  /* 强调/高亮边框 */
  --border-focus:  #AFC8A8;  /* 聚焦 Sage 绿 */

  /* ── TEXT ── */
  --text-primary:  #20231F;  /* 标题与核心信息 (深石墨暖黑) */
  --text-secondary:#626860;  /* 正文说明 */
  --text-tertiary: #81877E;  /* 标签与元数据 */
  --text-muted:    #9CA19A;  /* 弱提示与占位 */
  --text-disabled: #BEC2BC;  /* 禁用态 */

  /* ── BRAND / ACCENT (Sage Green) ── */
  --accent:        #82A978;  /* 鼠尾草灰绿 */
  --accent-hover:  #719967;
  --accent-active: #638B59;
  --accent-dark:   #52735A;
  --accent-soft:   #EDF4E9;
  --accent-medium: #DDEBD7;
  --accent-border: #C9DEC2;

  /* ── STATUS ── */
  --success:       #66956E;  --success-soft: #EDF5EF;
  --warning:       #B48A47;  --warning-soft: #FBF4E7;
  --danger:        #B96560;  --danger-soft:  #FAECEB;
  --info:          #70899E;  --info-soft:    #EDF2F5;

  /* ── DARK UTILITY (仅限 Terminal/Code) ── */
  --dark-panel:    #20231F;
  --dark-panel-secondary: #292D28;
  --dark-text:     #F4F5F1;

  /* ── CHARTS (LIGHT PALETTE) ── */
  --chart-1: #6E9B69;
  --chart-2: #7995A8;
  --chart-3: #B28B50;
  --chart-4: #96799F;
  --chart-5: #B8746E;
  --chart-grid: #ECEEE9;
  --chart-axis: #858B82;
  --chart-tooltip-bg: #FFFFFF;
  --chart-tooltip-border: #E1E4DE;
}
```

---

## 3. 重点模块改造详解

### 1. Landing Page (`LandingView.vue`)
- **Header**: `rgba(246,247,243,0.88)` + `blur(12px)`，边框 `#E8EAE5`。Logo 方块为纯白 `#FFFFFF` + `#698F64` 图标，A14 徽标为轻盈的 `#EDF4E9` / `#52735A`。
- **Hero**:
  - 主标题：“让工业建模，”采用 `#20231F`；第二行“从数据走向闭环决策”采用自然深绿 `#52735A`（彻底去除科技电蓝）。
  - Eyebrow 胶囊：“INDUSTRIAL AI AGENT WORKSPACE”采用 `#EDF4E9` 底色 + `#5D7E58` 文字。
  - Primary CTA：`#82A978`（白字，轻投影 `0 4px 14px rgba(80,110,75,0.12)`）。
  - Secondary CTA：“查看实测基准”采用 `#FFFFFF` + `#DDE1DA` 边框 + `#444A43` 深灰字。
- **Metrics Strip**: 纯白高阶卡片 `#FFFFFF` + `#E3E6DF` 边框，数字 `#282C27`，89.0% 采用 `#5E8259` 强调。
- **Workspace Preview**: 外层纯白 `#FFFFFF`（带 `0 18px 50px rgba(30,40,28,0.06)` 弥散阴影），顶部 Bar 为 `#F2F4EF`，中性圆点 `#D0D4CD`，内部为 `#FAFBF8` 浅色流。
- **Features / Pipeline / Benchmark / HITL**: 全部转化为白底面板、浅色标头与中性暖灰排版。

### 2. Home View (`HomeView.vue`)
- **留白与呼吸感**: 居中 `#20231F` 大标题 + `#5D7E58` 技术副标。
- **Composer**: 采用纯白高质感表面 `#FFFFFF`、`#DDE1DA` 浅边框与聚焦 Sage 绿光晕。发送按钮为 `#E8EDE5` (Idle) 与 `#82A978` (Active，白箭头)。
- **Quick Actions**: 纯白卡片 `#FFFFFF` + `#E2E5DE` 边框，移除玩具感 Emoji，引入标准 Lucide 风格矢量图标。
- **Recent Tasks**: `#FFFFFF` 面板，轻柔悬浮与低饱和状态标签。

### 3. Agent Workspace & Stream (`WorkspaceView.vue`, `AgentStream.vue`, `ApprovalCard.vue`, `ArtifactWorkbench.vue`)
- **左侧边栏**: `#F8F9F6` 背景 + `#ECEEE9` 分割线。
- **中栏对话流**: 用户请求气泡为 `#F0F4ED`（带 `#E2E8DE` 边框与 `#20231F` 文字），Agent 消息为纯白/透明。
- **HITL 确认卡片**: `#FFFDF7` 浅琥珀黄底色，左侧 `3px #B48A47` 指示线，批准按钮为 `#82A978` 白字。
- **右侧 Artifact Workbench**: `#FAFBF8` 表面，`#FFFFFF` 内嵌面板与指标条。

### 4. 设置中心主题切换 (`SettingsView.vue`)
- 在系统设置中增加了 **界面主题** 模块，提供可视化的主题卡片切换（默认 **Warm Light**，保留 **Warm Graphite** 备用），并自动同步 `localStorage`。

---

## 4. Visual QA 10 项验证

- [x] **1. 浅色占比 > 80%**: 全屏 75~80% 浅色 Neutral，15% 纯白 Surface，暗色面仅限代码/日志终端 (< 5%)。
- [x] **2. 彻底清除电蓝色系**: Chrome 边框、标题、CTA、选中态中无任何高饱和电蓝。
- [x] **3. 柔和高对比可读性**: `#20231F` 在 `#F6F7F3` / `#FFFFFF` 上对比度超过 14:1，极易阅读。
- [x] **4. 极克制的 Sage 绿 Accent**: 占比 < 5%，仅用于 Primary Action、运行脉冲与选中态。
- [x] **5. 页面呼吸留白充足**: Hero 上下具有大面积呼吸空间，组件不拥挤。
- [x] **6. 移除 Emoji 玩具感**: 替换为一致的 1.8px 细线技术 SVG 轮廓。
- [x] **7. 现代工作台视觉感知**: 呈现 Manus / Lovable / v0 的专业轻盈感，非传统粗糙 Admin。
- [x] **8. 完备的 Light 图表色板**: ECharts 曲线与热力图在白底上优雅清晰。
- [x] **9. 主题切换与持久化**: 设置页切换顺畅，Dark Mode 完好保留。
- [x] **10. 业务与自动化测试 100% 通过**: 14 套测试、92 个用例全部 PASS，构建 0 错误。

---

## 5. 验证状态
- **单元测试**: `npm test` ✅ **14 passed, 92 passed (2.33s)**
- **生产构建**: `npm run build` ✅ **470ms 成功打包**
- **开发服务**: [http://localhost:5173/](http://localhost:5173/) 热更新正常运行中
