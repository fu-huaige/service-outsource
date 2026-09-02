# IndusOpt 导航系统、页面布局与空状态打磨总结报告 (NAVIGATION_LAYOUT_POLISH)

> **目标**：全面重构与打磨 Sidebar 展开/折叠导航、统一全局 Page Header 对齐规范、建立全站标准 Empty State 组件、重构任务历史页（空状态与丰富列表双重形态），让 IndusOpt 达到现代成熟 Agent 产品（Manus / Cursor / Linear / Replit Agent / v0）的专业工作区水准。

---

## 一、重构前后对照与核心改进

| 模块 / 维度 | 重构前问题 | 重构后设计规范与实现 |
| :--- | :--- | :--- |
| **Sidebar 展开/折叠** | 处于纯图标但宽度占位大的中间状态，缺乏文字解释且无法自主折叠/展开 | 建立真展开 (`224px`，Icon + 中文 Label) 与真折叠 (`56px`，纯 Icon + 300ms 悬浮 Tooltip) 两种模式，支持顶部 Toggle 按钮切换，状态持久化至 `localStorage` |
| **Sidebar 选中与交互** | 存在蓝色边框/发光，颜色与 Warm Light 绿色系脱节 | 统一使用草本绿主题交互态：Selected `background: #E8F0E5; color: #426340; icon: #5E8358`，左侧保留 `2.5px solid #82A978` 纯净指示条，无任何蓝色溢出 |
| **Sidebar 信息架构** | 菜单混杂英文与后台术语（Workspace, Runs, Assets 等） | 一级导航精简为 4 个 Agent-first 中文核心项：`首页`、`Agent 工作台`、`任务历史`、`资产中心`；底部整合 `搜索 (⌘K)`、`设置` 与 `系统状态` |
| **Page Header 对齐** | 各页面标题居左、按钮贴紧视口最右，缺乏统一网格与层级 | 抽取全局统一 `<PageHeader>` 组件：标准 `1280px` 容器内网格排版 (`grid-template-columns: 1fr auto`)，规范 Eyebrow（如 `AGENT / HISTORY`）、30px 标题、副标题与右侧对齐 Primary Action |
| **Empty State 表现** | 仅有一个小图标和弱文案，机械居中导致页面出现大面积死白 | 抽象通用 `<AppEmptyState>` 组件（支持独立全页与列表内联两种形态），提供标准向量图标、18px 标题、清晰引导文案及主/次 CTA 按钮 |
| **任务历史 (RunsView)** | 只有简单卡片堆叠，缺乏搜索、多维过滤与产物概要 | 全面重构：顶部提供搜索框 (`280px`) + 状态多维过滤 + 排序；列表采用紧凑流式行 (`76px`)，清晰呈现目标、阶段数、时间、产物徽章（ARX / Optuna / Report）与状态色标 |

---

## 二、侧边栏导航规范 (Sidebar System)

### 1. 尺寸与状态
- **EXPANDED 模式 (`224px`)**:
  - 顶部 Brand Bar (`64px` 高度)：Logo 图标 (32px) + `IndusOpt` 标题 + `A14` 徽章 + 折叠切换按钮。
  - 主导航区：`首页`、`Agent 工作台`、`任务历史`、`资产中心`，带 18px 线性图标与 14px 中文标签。
  - 底部操作区：`搜索 (⌘K)` 快捷触发器、`设置` 入口、`系统状态`（● 系统正常 / 正在连接 / 服务未连接）。
- **COLLAPSED 模式 (`56px`)**:
  - 顶部显示 32px Logo 与展开按钮。
  - 导航项隐藏文字标签，每个图标绑定 `el-tooltip`（`placement="right"`，`show-after="300ms"`）。
  - 底部显示搜索、设置图标与系统状态指示灯。
- **持久化机制**：
  - 状态同步读写 `localStorage.getItem('indusopt.sidebar_collapsed')`，用户刷新页面或重新打开均保持偏好。

### 2. 色彩与状态样式
- **Normal 态**：文本 `#747A72`，图标 `#858B82`，高度 `40px`，边距 `2px 6px`，圆角 `8px`。
- **Hover 态**：背景 `#F0F2ED`，文本 `#30352F`，图标 `#555C53`。
- **Active 态**：背景 `#E8F0E5`，文本 `#426340`，图标 `#5E8358`，左侧 `2.5px` 浅草绿指示线 (`#82A978`)。
- **无障碍**：所有导航按钮与链接均配备完整 `aria-label` 与 Focus-Visible Ring。

---

## 三、通用页面头与空状态规范

### 1. 统一页头组件 (`src/components/common/PageHeader.vue`)
```html
<PageHeader
  eyebrow="AGENT / HISTORY"
  title="任务历史"
  description="查看 Agent 的执行阶段、审批和产物记录"
>
  <template #actions>
    <router-link to="/workspace" class="page-primary-btn">
      <svg ...> + 新建任务
    </router-link>
  </template>
</PageHeader>
```
- **Eyebrow 规则**：统一采用小号大写双层路径形式（如 `AGENT / HISTORY`、`DATA & MODEL / ASSETS`、`PREPARE DATA / DATASETS`），色值 `#63805E`，等宽字体。
- **标题与排版**：30px 粗体标题，行高 1.2；副标题 14px，行高 1.5。
- **Action 按钮**：固定高度 38px，内边距 `0 16px`，背景 `#82A978`（悬浮 `#719967`），与 Header 右侧严格对齐，不随屏幕无限拉伸分离。

### 2. 统一空状态组件 (`src/components/common/AppEmptyState.vue`)
- 支持 `history`、`dataset`、`model`、`report`、`optimization`、`search` 预设向量图标。
- **全页模式**：用于无数据主视图，最大宽度 480px，页头下方距顶 100~120px，包含 56px 柔和背景图标、18px 标题、引导说明与 CTA 动作。
- **Inline 模式 (`inline: true`)**：用于表格与列表内部空数据占位，高度 180~240px，紧凑居中。

---

## 四、任务历史页面 (RunsView) 重构落地

### 1. 空状态 (Empty State)
- 展示 History 时钟图标，文案明确引导：“还没有执行过 Agent 任务。创建任务后，这里会保存完整的执行阶段、人工审批、模型、优化结果与报告记录。”
- 提供醒目的主行动点 `[ + 创建第一个任务 ]` 直达 `/workspace`。

### 2. 丰富数据状态 (Populated State)
- **紧凑工具栏**：
  - 搜索框（280px 宽度，实时搜索目标与 Execution ID，支持一键清空）。
  - 状态筛选器下拉框（全部状态、执行中、待确认、已完成、失败、已取消）。
  - 排序选择器（最新在前 / 最早在前）。
- **任务行 (Task Row)**：
  - 高度 76px，悬浮背景 `#F7F9F5`，轻微上浮质感。
  - 左侧语义状态指示点（运行中绿光脉冲、待确认琥珀色、完成沉稳绿、失败警示红）。
  - 主信息区：加粗任务目标 + ID 短码 + 阶段步数 + 格式化时间戳。
  - 产物徽章区：自动识别并打上 `ARX Model`、`Optuna Study`、`Report` 标签。
  - 状态胶囊区：低饱和度柔和状态 Badge。
  - 右侧跳转指示箭头 `›`，点击整行无缝恢复至对应 Workspace 会话。

---

## 五、验证与构建状态

### 1. 单元测试套件
```bash
$ npm test
Test Files  14 passed (14)
     Tests  92 passed (92)
  Duration  2.71s
```
全部 14 个测试文件、92 项单元测试 100% 通过。

### 2. 生产构建打包
```bash
$ npm run build
✓ built in 599ms
```
生产环境打包构建顺利完成，无任何 TS / CSS 语法与死链错误。

### 3. Visual QA 实机截图归档清单 (`artifacts/navigation-polish/`)
- `artifacts/navigation-polish/home.png` (首页工作区与侧边栏)
- `artifacts/navigation-polish/sidebar-expanded.png` (224px 展开态侧边栏与活动项)
- `artifacts/navigation-polish/sidebar-collapsed.png` (56px 折叠态侧边栏与紧凑图标)
- `artifacts/navigation-polish/history-empty.png` (任务历史页统一 PageHeader 与精细空状态)
- `artifacts/navigation-polish/history-list.png` (任务历史页工具栏、多维过滤与流式行列表)
