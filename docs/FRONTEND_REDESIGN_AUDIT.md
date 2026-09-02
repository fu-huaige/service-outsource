# Frontend Redesign Audit — IndusOpt 工模智优

> Generated: 2026-09-01
> Scope: `frontend/src` complete scan before any redesign modification
> Purpose: Ground truth for the Agent-first redesign. Do NOT modify existing behavior without reading this document first.

---

## 1. 当前页面地图 (Page Map)

| Route | Component | Title | Role in Flow |
|-------|-----------|-------|--------------|
| `/` | `LandingView.vue` | 产品首页 | 营销 Landing，内含 Hero / Benchmark / Workflow 介绍 |
| `/dashboard` | `DashboardView.vue` | 工作台总览 | 主工作区入口，Leaderboard + Pipeline 导引 + Telemetry |
| `/simulation` | `SimulationView.vue` | 仿真生成器 | 生成 S1~S6 标准工况仿真数据集 |
| `/datasets` | `DatasetsView.vue` | 数据资产 | 数据集列表管理、上传入口 |
| `/datasets/:id` | `DatasetDetailView.vue` | 数据集详情 | 版本谱系 / 数据 Profile / 时序预览 / 列配置 |
| `/preprocessing/cleaning` | `CleaningView.vue` | 时间规整与清洗 | Hampel/IQR 异常清洗 + 降采样 |
| `/preprocessing/segmentation` | `SegmentationView.vue` | 动态响应区间优选 | D-最优 + 门控 + 信息增益优选 |
| `/preprocessing/delay` | `DelayView.vue` | 多变量时滞分析 | 预白化互相关 + 时滞估计 |
| `/preprocessing/collinearity` | `CollinearityView.vue` | 共线性与变量筛选 | VIF + Spearman 共线性分析 |
| `/modeling/arx` | `ARXModelingView.vue` | ARX 系统辨识 | OLS/Ridge ARX 参数辨识 + 验证 |
| `/modeling/optimization` | `OptunaView.vue` | Optuna 闭环寻优 | Optuna 超参数优化 |
| `/copilot` | `CopilotView.vue` | Agent 工作台 | **核心**：LLM/规则编排 Agent 全流程 |
| `/benchmark` | `BenchmarkView.vue` | 一键自评测基准 | 4 策略消融对照（自评测） |
| `/deliverables` | `DeliverablesView.vue` | 报告与交付中心 | LLM 报告生成 + 数据导出 |
| `/settings` | `SettingsView.vue` | 系统设置 | LLM API Key / 健康状态 / Agent 规划方式 |
| `/403` `/404` `/500` | error views | 错误页 | 标准错误页面 |

**总计：15 个主要页面（含 3 个错误页）**

---

## 2. 当前信息架构 (IA)

```
Landing (/)
└── 产品介绍、进入工作台

App Shell (DefaultLayout)
├── Header
│   ├── Logo (IndusOpt 工模智优 A14)
│   ├── 当前数据集显示
│   ├── 快捷指令 Cmd+K
│   ├── 产品首页链接
│   └── 系统健康状态指示
│
├── Sidebar (232px, 可折叠到 64px)
│   ├── 工作台总览 → /dashboard
│   ├── [数据准备]
│   │   ├── 生成仿真数据 → /simulation
│   │   └── 数据资产管理 → /datasets
│   ├── [分析与建模]
│   │   ├── [预处理与优选]
│   │   │   ├── 时间规整与清洗
│   │   │   ├── D-最优动态区间优选
│   │   │   ├── 多变量时滞对齐
│   │   │   └── VIF 共线性与筛选
│   │   └── [辨识与寻优]
│   │       ├── ARX 系统辨识
│   │       └── Optuna 闭环寻优
│   └── [协作与交付]
│       ├── AI 智能工模 Copilot → /copilot  ← 被放在最后
│       ├── 消融对账评测 → /benchmark
│       ├── 工程报告与交付 → /deliverables
│       └── 系统环境设置 → /settings
│
└── Main Content Area (overflow-y: auto, 带网格背景)
```

**核心问题**：Agent（Copilot）被放在导航的倒数第二位，与"协作与交付"同组。
实际上 Agent 应该是整个产品的主入口。

---

## 3. 当前组件体系 (Component Inventory)

### 3.1 布局组件
| 组件 | 文件 | 功能 |
|------|------|------|
| `DefaultLayout` | `layouts/DefaultLayout.vue` | 主壳：Header + Sidebar + Main + CommandPalette |
| `AppHeader` | `components/AppHeader.vue` | 顶部栏：Logo / 数据集 / Cmd+K / 健康状态 |
| `AppSidebar` | `components/AppSidebar.vue` | 左侧导航（Element Plus `el-menu`，可折叠） |

### 3.2 功能组件
| 组件 | 文件 | 功能 |
|------|------|------|
| `CommandPalette` | `components/CommandPalette.vue` | Cmd+K 指令面板，支持导航/执行 |
| `StateView` | `components/StateView.vue` | 多态状态组件：empty/loading/hitl_wait/failure |
| `ChartContainer` | `components/ChartContainer.vue` | ECharts 图表容器 |
| `HelloWorld` | `components/HelloWorld.vue` | 遗留模板组件（可删除） |

### 3.3 Landing 专属组件
```
components/landing/
  LandingHeader.vue  (及其他 Landing 子组件)
```

### 3.4 Stores
| Store | 文件 | 状态 |
|-------|------|------|
| `useCopilotExecutionStore` | `stores/copilotExecution.ts` | 当前活跃 `executionId`（localStorage 持久化） |
| `useDatasetStore` | `stores/datasetStore.ts` | 当前选中的数据集（`activeDataset`） |
| `useSystemStore` | `stores/systemStore.ts` | 系统健康状态（5s 轮询 liveness + readiness） |

### 3.5 API 客户端层
| 文件 | 覆盖接口 |
|------|---------|
| `api/client.ts` | Axios 实例 + ApiResponse 拦截器（统一 `{ success, data, error }` 格式） |
| `api/copilot.ts` | `/copilot/chat`, `/copilot/executions/:id`, `/copilot/confirm`, lag/feature/arx validate, evaluate, optimize |
| `api/datasets.ts` | 数据集 CRUD + profile + versions + config |
| `api/preprocessing.ts` | clean / segment / delay / collinearity / feature-apply / lag-apply |
| `api/modeling.ts` | `/modeling/arx/fit` |
| `api/simulation.ts` | `/simulation/generate` |
| `api/delivery.ts` | `/delivery/report`, `/delivery/export` |
| `api/dashboard.ts` | `/dashboard/leaderboard` |
| `api/agentSettings.ts` | `/agent-settings/llm-config`, `/agent-settings/test-connection` |
| `api/health.ts` | `/health/live`, `/health/ready`, `/system/info` |

---

## 4. 页面间功能重复

| 重复功能 | 页面 A | 页面 B | 说明 |
|---------|--------|--------|------|
| version_id 输入框 | 每个预处理页面 | CopilotView | 用户需要手动复制粘贴 version_id，体验差 |
| 数据集选择 | DashboardView | CopilotView | 两处都有数据集选择逻辑但方式不同 |
| 错误 Alert | 所有页面各自实现 | StateView | StateView 存在但各页面绕过它自己做 |
| 加载状态 | 所有页面各自实现 | StateView | 同上 |
| 指标格式化函数 | CopilotView.pct()/num() | ARXModelingView | 同类函数重复实现 |
| ARX 结构输入 | ARXModelingView | CopilotView (Approval Dialog) | 两处 ARX na/nb 输入，样式不一致 |
| 时滞输入 | DelayView | CopilotView (Lag Override Dialog) | 同上 |

---

## 5. 当前 Agent (Copilot) 与其他模块关系

```
CopilotView.vue（1980 行）
├── 输入层
│   ├── 自然语言 prompt
│   ├── active_version_id（手动输入）
│   └── dataset_id（通过 header 的 datasetStore 间接获取）
│
├── API 调用
│   ├── POST /copilot/chat → 生成执行计划
│   └── GET /copilot/executions/:id → 恢复历史 Execution
│
├── 计划显示（Element Plus el-steps 竖版）
│   ├── 步骤状态（pending/running/waiting_confirmation/completed/failed）
│   ├── 工具名称 + 参数
│   └── Summary 文本
│
├── 人工确认 (HITL) — 3 种类型
│   ├── 时滞补偿 (lag_apply) → Dialog + 验证 API
│   ├── ARX 结构 (arx_fit) → Dialog + 推荐/覆盖 + 验证 API
│   └── Feature Selection (feature_apply) → Inline checkbox
│
├── 手动触发执行（2 个半自动步骤）
│   ├── 模型评价 (evaluate_model) → 手动点击执行
│   └── 管道优化 (optimize_pipeline) → 手动点击执行
│
└── 结果显示
    ├── 合规证明（proof_id, signature, checks[]）
    ├── 步骤运行记录（el-table，JSON 原始输出）
    ├── 工具真实输出（JSON.stringify 直接显示）
    ├── 评价指标（FIT/R²/RMSE/MAE/NRMSE 二合一表）
    ├── 优化结果（best_params + best_value）
    └── 结论与假设（conclusion + assumptions）
```

**核心问题**：
1. Agent 页面是一个 1980 行的单文件组件，所有逻辑都在里面
2. 工具真实输出用 `JSON.stringify` 直接展示，不是 Artifact
3. 没有右侧 Artifact 面板，结果都在聊天流里
4. 确认对话框用的是 `el-dialog`，不是 Agent-native Approval Card
5. 计划用 `el-steps` 展示，与现代 Agent UI 相差甚远

---

## 6. 核心流程页面 vs 可降级页面

### 核心流程（必须保留，需要重新呈现方式）
| 页面/能力 | 重要性 | 新定位 |
|---------|--------|--------|
| Agent Chat + Plan | 核心 | **主界面** → AgentStream + ArtifactWorkbench |
| HITL 确认 | 核心 | ApprovalCard（全新设计） |
| Dataset Detail / Profile | 核心 | DatasetArtifact（Artifact Tab） |
| ARX Modeling + Metrics | 核心 | ModelArtifact（Artifact Tab） |
| Optimization Results | 核心 | OptimizationArtifact（Artifact Tab） |
| Report 生成 | 重要 | ReportArtifact（Artifact Tab） |
| Version Lineage | 核心 | DatasetArtifact 内 Lineage Tab |
| Settings (LLM Config) | 重要 | Settings 页保留 |

### 可降级为 Secondary View（Asset Detail / 从 Artifact 点进）
| 页面 | 降级方式 |
|------|---------|
| `CleaningView` | Agent 产生 Cleaning Result Artifact，点击"查看完整详情"进入 |
| `SegmentationView` | Agent 产生 Segmentation Artifact |
| `DelayView` | Agent 产生 Delay Analysis Artifact |
| `CollinearityView` | Agent 产生 Feature Selection Artifact |
| `DashboardView` | 整合进新 Home 的 Recent Tasks + Quick Stats |
| `BenchmarkView` | Assets > Studies 中的 Benchmark Tab |
| `SimulationView` | Workspace 侧栏的 Quick Actions |

---

## 7. 应成为 Agent Artifact 的能力

| Artifact 类型 | 来源步骤 | 数据内容 |
|--------------|---------|---------|
| `DatasetArtifact` | 数据导入 / profile | 行数/列数/质量分/时序预览/缺失率/冻结段 |
| `CleaningArtifact` | `clean` 工具 | 清洗前后对比/替换点数/改变摘要 |
| `SegmentationArtifact` | `segment` 工具 | 门控窗口/D-最优结果/覆盖率/信息增益 |
| `DelayArtifact` | `delay_analyze` 工具 | 各输入时滞/互相关曲线/不确定变量 |
| `FeatureSelectionArtifact` | `feature_apply` 工具 | VIF 矩阵/推荐/保留/删除变量 |
| `ModelArtifact` | `arx_fit` 工具 | 模型结构/系数/FIT/R²/RMSE/自由仿真曲线 |
| `EvaluationArtifact` | `evaluate_model` 工具 | 测试集 one-step + free-run 指标 |
| `OptimizationArtifact` | `optimize_pipeline` 工具 | Optuna best_params/best_value/trial 曲线 |
| `ReportArtifact` | `generate_report` 工具 | Markdown 报告全文/章节/绑定数值 |

---

## 8. 不能破坏的 API 契约

| API | 重要原因 |
|-----|---------|
| `POST /copilot/chat` | Agent 全流程入口，含 plan + compliance + step_runs |
| `GET /copilot/executions/:id` | Execution 恢复与历史查看 |
| `POST /copilot/confirm` | HITL 确认核心，含 lag/feature/arx override |
| `POST /copilot/lag-overrides/validate` | 确认前验证 |
| `POST /copilot/feature-selection/validate` | 确认前验证 |
| `POST /copilot/arx-structure/validate` | 确认前验证 |
| `POST /copilot/evaluate-model/execute` | 手动触发评价 |
| `POST /copilot/optimize-pipeline/execute` | 手动触发优化（6 分钟超时） |
| `GET /datasets/:id` | 数据集详情 + Preview + Profile |
| `GET /datasets/:id/versions` | 版本谱系（Lineage），是项目核心差异化能力 |
| `POST /preprocessing/clean` | 清洗，产生新 version_id |
| `POST /preprocessing/segment` | 优选，产生 TaskResource |
| `POST /preprocessing/delay-analyze` | 时滞分析 |
| `POST /preprocessing/collinearity` | 共线性分析 |
| `POST /preprocessing/lag-compensation/apply` | 时滞补偿应用（需 user_confirmed=true） |
| `POST /preprocessing/feature-selection/apply` | 特征筛选应用（需 user_confirmed=true） |
| `POST /modeling/arx/fit` | ARX 辨识 |
| `POST /optimization/optuna/start` | Optuna 优化启动 |
| `GET /optimization/optuna/:id/status` | Optuna 状态轮询 |
| `POST /delivery/report` | 报告生成（LLM + 数值绑定） |
| `POST /delivery/export` | 数据导出 |
| `GET /agent-settings/llm-config` | LLM 配置读取 |
| `PUT /agent-settings/llm-config` | LLM 配置更新 |
| `GET /health/live` + `GET /health/ready` | 5s 健康轮询 |

---

## 9. 当前测试覆盖

### E2E 测试（Playwright）

| 测试 | 路由依赖 | 关键断言 |
|------|---------|---------|
| 仿真场景完整性（S1~S6） | `/simulation` | 6 个场景 radio 可见 |
| 生成→优选闭环 | `/simulation`, `/preprocessing/segmentation` | 真实 API，覆盖率 < 1 |
| 自评测基准 4 策略 | `/benchmark` | 全量/能量/质量/D-最优 均出现 |
| Agent 计划生成 + 合规证明 | `/copilot` | 签名 + 校验通过/未通过 |
| 离线规则编排不报错 | `/copilot` | "确定性规则编排"出现，无错误 |
| 错误路径（不存在版本） | `/preprocessing/segmentation` | 可读错误消息 |
| 404 路由 | `/this-route-does-not-exist` | 404 文本可见 |
| 每个主视图无控制台错误 | 13 个路由 | h2 可见 + 无 pageerror |
| 后端场景常量一致性 | API 直接调用 | `body.data.scenario === 'S3'` |

**重构时必须保持的 data-test 属性**（否则 E2E 会失败）：
- `data-test="hydrating-execution"`, `data-test="resume-notice"`
- `data-test="execution-id"`, `data-test="workflow-status"`, `data-test="current-version-id"`
- `data-test="confirmation-status-{stepId}"`, `data-test="confirm-actions-{stepId}"`
- `data-test="approve-{stepId}"`, `data-test="reject-{stepId}"`
- `data-test="arx-model-id-{stepId}"`, `data-test="arx-recommendation-{stepId}"`
- `data-test="lag-recommendation-{stepId}"`, `data-test="lag-validation-{stepId}"`
- `data-test="feature-recommendation-{stepId}"`, `data-test="feature-variable-{variable}"`
- `data-test="evaluation-results-{stepId}"`, `data-test="optimization-results-{stepId}"`
- Routes: `/simulation`, `/preprocessing/segmentation`, `/benchmark`, `/copilot`

### 单元测试（Vitest，14 个文件）

| 文件 | 覆盖内容 |
|------|---------|
| `agent-entry-removal.spec.ts` | Agent 入口不被意外移除 |
| `cleaning-view-contract.spec.ts` | CleaningView API 契约 |
| `client.spec.ts` | Axios 客户端基本行为 |
| `copilot-api.spec.ts` | Copilot API 函数单测 |
| `copilot-execution-store.spec.ts` | localStorage 持久化 |
| `copilot-view-confirm.spec.ts` | 最大（51KB）：确认流程全路径 |
| `dataset-detail-freeze-segments.spec.ts` | 冻结段检测 |
| `dataset-detail-version-preview.spec.ts` | 版本预览（19KB） |
| `default-layout-bounce.spec.ts` | 边界弹性效果 |
| `landing-gate.spec.ts` | Landing Gate 重定向逻辑 |
| `landing.spec.ts` | Landing 页面组件（11KB） |
| `simulation-view.spec.ts` | 仿真视图 |
| `store.spec.ts` | 各 Store 基本行为 |
| `system-status-components.spec.ts` | 健康状态组件（10KB） |

---

## 10. 当前 Design System 分析

### 技术栈
- **Vue 3.5** + TypeScript + Vite 8
- **Element Plus 2.14**：几乎所有 UI 原语都来自 EP
- **ECharts 6.1**：图表库
- **Pinia 4**：状态管理

### 存在的设计问题
1. `style.css` 根文件仍是 Vite 模板残留（有 `.hero`, `#center`, `#next-steps` 等无关选择器）
2. 设计 token 分散在各组件 `<style scoped>` 中，缺少统一 design system 文件
3. Element Plus 组件在 scoped 中大量用 `:deep()` hack，样式耦合深
4. `industrial-card` / `industrial-card-header` / `industrial-card-title` 是全局 class pattern，但没有单独组件实现
5. 大量 card everywhere 问题：每一块内容都用 `industrial-card` 包裹
6. `CopilotView.vue` 1980 行，所有 Agent 逻辑、样式、模板混合在一起

---

## 11. 关键业务逻辑约束（禁止在重构中破坏）

### Dataset Version Lineage
- 每次处理操作产生新的 `version_id`
- `version_id` 是整个工作流的数据传递主线
- Copilot 的 `current_version_id` 随步骤推进
- 版本谱系图（DAG 结构，`nodes` + `edges`）必须保留

### HITL 确认机制（Human-in-the-loop）
三种类型需要不同的 UI 表达：
1. **时滞补偿确认**：推荐值 + 手动覆盖 + WARNING 状态 + 二次确认
2. **ARX 结构确认**：推荐 na/nb + 手动覆盖 + 验证状态
3. **Feature Selection 确认**：推荐删除列 + checkbox 修改 + 批准

### 合规证明（ComplianceProof）
- `proof_id` + `signature` + `code_version` 是机器可验证的安全标记
- 必须在 UI 中保持可见（不能隐藏）

### 测试集隔离（Test Isolation）
- 后端强制训练/验证/测试三段分离
- `SplitIndices` 中的 `train_end` / `val_end` / `test_end` 不可变
- 前端图表中不得混淆分区边界

---

## 12. 当前状态系统映射

`StateView.vue` 状态：
```
empty | loading | parsing | config_error | queued | running
partial_success | hitl_wait | success | failure | cancelled | oversized | normal
```

`AgentStepStatus`（API 类型）：
```
pending | running | waiting_confirmation | completed | failed | cancelled
```

`AgentWorkflowStatus`（API 类型）：
```
PLANNED | RUNNING | WAITING_CONFIRMATION | WAITING_ASYNC_TASK
SUCCEEDED | FAILED | CANCELLED
```

新设计的统一状态系统必须覆盖这三个维度。
