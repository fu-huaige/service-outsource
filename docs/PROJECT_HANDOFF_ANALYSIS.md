# ProcessPilot / A14 项目接管分析

> 分析日期：2026-08-20。范围：整个仓库、`docs/reference` 赛题资料、运行中的后端 API 和前端构建结果。本轮不修改业务代码、数据库、依赖或配置，仅新增本文档。

## 1. 项目总体说明

当前系统是 Vue + FastAPI 的本地工业时序数据优选平台：可生成/接收多变量时序数据，执行质量画像、动态区段 D-最优优选、时滞分析、共线性诊断、ARX 辨识和 Optuna 闭环寻优，并导出可追溯结果。核心算法和独立数值闭环是真实执行的；但仿真数据没有进入统一数据库生命周期，Agent 的清洗/确认续跑/报告/导出仍不完整，报告和前端交付也有缺口。

## 2. 当前技术栈

| 层次 | 当前实现 | 关键位置 |
| --- | --- | --- |
| 前端 | Vue 3、TypeScript、Vite、Vue Router、Pinia、Element Plus、ECharts、Axios | `frontend/package.json`、`frontend/src` |
| 后端 | Python 3.11+、FastAPI、Pydantic、Uvicorn | `backend/pyproject.toml`、`backend/app` |
| 数据库/ORM | PostgreSQL 16、SQLAlchemy Async、Alembic；测试支持 SQLite | `backend/app/models`、`backend/alembic` |
| 队列 | Redis 7、RQ worker；不可用时同步回退 | `docker-compose.yml`、`app/services/job_queue.py` |
| Agent | 规则 Planner + 可选 OpenAI-compatible LLM；白名单、Schema、DAG、合规证明 | `backend/algorithms/agent` |
| 算法/优化 | NumPy、质量门控、Fisher/D-最优、预白化互相关、VIF、ARX、Optuna | `backend/algorithms`、`optimization_service.py` |
| 部署 | Compose 启动 backend、worker、PostgreSQL、Redis；前端单独启动 | `docker-compose.yml` |

## 3. 项目目录结构

```text
E:\服外\A14
├── README.md / PHASE_STATUS.md / CHANGELOG.md
├── docker-compose.yml
├── backend
│   ├── app/api/routes.py       API
│   ├── app/services            数据、清洗、分析、建模、Agent、交付
│   ├── app/models / schemas    ORM 表和 Pydantic 契约
│   ├── algorithms              工业算法和报告溯源
│   ├── alembic                 迁移 0001 -> 0003
│   ├── tests / scripts
│   └── data                    运行时 CSV、报告、导出、仿真产物
├── frontend
│   ├── src/api、router、stores、views、components、types
│   ├── tests/unit
│   └── e2e/closed-loop.spec.ts
└── docs
    ├── reference              A14 官方资料和内部基线
    ├── algorithms、experiments、architecture、manual
    └── PROJECT_HANDOFF_ANALYSIS.md
```

## 4. 当前启动方式

后端依赖：

```powershell
cd "E:\服外\A14"
docker compose up -d --build
docker compose exec backend alembic upgrade head
docker compose ps
```

后端地址为 `http://localhost:18000`，文档为 `/docs`，探针为 `/api/v1/health/live` 和 `/api/v1/health/ready`。前端不在 Compose 中：

```powershell
cd "E:\服外\A14\frontend"
npm.cmd ci
npm.cmd run dev
```

Vite 代理 `/api` 到 `http://127.0.0.1:18000`。本轮 HTTP live/ready 和 OpenAPI 均成功；前端 build 成功。Vitest 因 Windows 写 `node_modules/.vite-temp` 遇到 EPERM，未得到业务断言结果。Python 90 个文件语法扫描通过。当前沙箱无法读取 Docker named pipe，故不把 Docker CLI 状态作为本轮证据。

## 5. 当前功能清单

### 已完整实现

- 上传 CSV 的编码/分隔符识别、列元数据、删除、质量画像和版本血缘（上传数据）。
- S1–S6 仿真：稳态、阶跃、污染、缺失、冻结、漂移、不规则采样、重复时间戳、高共线性、异构激励，并保存 ground truth/manifest。
- 真实清洗 API：时间规整、重采样、缺失插值、Hampel/IQR/Z-score、局部中位数/clip、移动平均/Savitzky-Golay。
- 动态窗口质量门控 + D-最优选段；真实时滞预白化互相关和验证精炼；Pearson/Spearman/VIF/条件数。
- 时间顺序 ARX（OLS/Ridge）、MAE/RMSE/R²/FIT/AIC/BIC、自由仿真、稳定性和残差白度。
- Optuna 多轮真实闭环、试验记录、最佳参数、收敛曲线、缓存和策略记忆。
- 选中行 CSV + provenance manifest 导出；实时自评测基准。

### 部分实现

- Agent 可解析自然语言、生成结构化计划、白名单执行并产生合规证明；但 Agent 清洗只做诊断摘要，变量选择只是建议。
- 报告服务有 Markdown 模板和数值绑定；仿真版本实际返回 500，且没有嵌入 ECharts 图片。
- 时滞“分析”已实现；独立补偿后的派生版本没有清晰公开 API。
- 共线性只输出 drop/keep/review 建议，不自动删除、合并或 PCA。
- RQ 有后台 worker，但取消接口只返回取消状态。

### 只有页面/写死数据

- Dashboard KPI/榜单/数据集名/FIT 是常量。
- Settings 健康描述和保存逻辑主要是本地 UI，失败时有 `(Mock)` 提示。
- Cleaning 请求失败时构造正弦波 raw/cleaned 数据，掩盖真实错误。
- Simulation 下载按钮生成固定 50 行正弦波 CSV，不是后端仿真文件。
- Deliverables 显示 artifact URI，但没有完整下载体验。

### 尚未实现

- 仿真生成后写入 `datasets/dataset_versions/dataset_profiles` 的统一资产流程。
- Agent 确认后恢复执行；Agent 直接调用报告/导出的完整路径。
- Agent 根据模型反馈自主改写下一轮计划的 Level 4 控制器。

## 6. 前端分析

路由覆盖 Dashboard、数据中心、仿真、数据详情、清洗、动态区段、时滞、共线性、ARX、Optuna、Copilot、Benchmark、Deliverables、Settings 和错误页。Axios 模块位于 `frontend/src/api`，Pinia 只有 dataset/system 两个 store，没有统一 pipeline/study/report store。Segmentation、Delay、Collinearity、ARX、Optuna、Copilot、Benchmark、Deliverables 消费真实 API；Dashboard、Settings、Cleaning 错误态和 Simulation 下载存在固定数据。

ECharts 页面能展示 API 返回的图表/窗口结果，但报告没有复用这些图片。类型文件仍把仿真场景联合类型写到 S1–S5，任务资源也有旧字段形态。build 成功但 ECharts chunk 约 1MB。

## 7. 后端分析

Router 集中在 `backend/app/api/routes.py`，统一 success/error envelope。Service 划分为 dataset、simulation、cleaning、segment、preprocessing analysis、modeling、optimization、agent、report、benchmark。上传数据通过不可变版本 DAG 管理；仿真通过文件和 manifest 管理，算法由 `version_data.py`读取，形成两个不完全统一的数据世界。

## 8. Agent 分析

Planner 关键词解析中英文意图和参数；可选 LLM 输出 JSON，随后走同一套 Pydantic、白名单、DAG 和合规检查。白名单覆盖 profile、align/resample、anomaly、clean、segment、delay、collinearity、select variables、ARX、evaluate、optimize、report、export。

- 真实执行：profile、动态区段、时滞、共线性、ARX、optimize。
- 诊断而非变更：Agent 的 align/clean/anomaly 分支没有调用 `clean_dataset_version`。
- 咨询/延迟：select_variables 只给建议；report/export 返回 deferred。
- 确认问题：`/copilot/confirm` 只返回 approved/rejected，不恢复工作流。

等级判断：**Level 3（受限/混合实现）**。它有结构化 Planner、白名单工具和真实算法，超过 Level 1；但没有 Agent 反馈控制和可恢复确认，因此不是 Level 4。真正的闭环目前由独立 Optuna 服务负责。

## 9. 工业算法分析

| 算法 | 代码位置 | 输入/输出 | 业务调用 |
| --- | --- | --- | --- |
| 时间戳、缺失、异常、去噪、质量画像 | `algorithms/cleaning/pipeline.py`、`quality.py` | 序列和阈值 -> 清洗数据、mask、质量分 | 清洗 API；Agent 未完整复用 |
| 动态门控 | `identifiability/gating.py` | 窗口、输入/输出 -> SNR、活动、拒绝原因 | `/preprocessing/segment` |
| Fisher/D-最优选段 | `identifiability/selection.py` | ARX 矩阵、预算 -> 选中窗口/样本、log-det、条件数 | Segment/Optuna |
| 激励诊断 | `identifiability/excitation.py` | 设计矩阵 -> rank、PE、condition | Segment/Model |
| 时滞 | `identifiability/delay.py` | 多变量序列 -> 预白化候选、精炼 delay、FIT | Delay |
| 共线性 | `identifiability/collinearity.py` | 输入列 -> Pearson/Spearman/VIF/组/建议 | Collinearity |
| ARX/评价 | `identifiability/regressor.py`、`validation.py`、`app/services/modeling_service.py` | 阶次、滞后、序列 -> 系数、分区指标、稳定性 | ARX/Optuna |
| 仿真 | `app/services/simulation_service.py` | S1–S6、步数、seed -> CSV、truth、manifest | Simulation/Benchmark |

没有发现把固定 “72% -> 80% -> 89%” 作为生产闭环返回的实现。

## 10. 系统辨识分析

当前模型是 MISO ARX，含历史输出和滞后输入，按时间顺序切 train/validation/test，未随机打乱。估计器为 OLS/Ridge；秩亏会阻止不可信 OLS。指标包括 MAE、RMSE、R²、NRMSE、FIT、AIC/BIC、free-run/one-step gap、极点稳定性和残差白度。一次 S6 真实运行中验证 free-run FIT 约 92.59，而测试 free-run FIT 约 5.60，说明后段泛化风险真实存在，不能只展示训练分数。

## 11. 闭环寻优分析

**真实闭环已实现。** 每个 Optuna trial 会改变窗口长度、窗口预算、异常/缺失门限、输入活动阈值或 `nk`，重新门控/选段，重新拟合 ARX，再以验证 free-run FIT、误差、白度、复杂度评价并选最优；每轮参数、指标、错误、缓存和耗时都会保存。

本轮 S6、1200 行真实运行：3 个 trial 全部完成，study 为 `df80c3a6-08f3-4e31-a4ff-da363903cc0e`，status 返回 best params、best curve、完成/失败计数、结构评估和选择计算统计。因此闭环不是固定假数据。但它是独立 Optuna 闭环，不是 Agent 自主反馈闭环。

## 12. 数据和仿真系统

CSV 主要为 `timestamp,u*,y`；上传记录编码、分隔符、行列数、哈希和时间范围。仿真 S1 基础 ARX、S2 多输入多延迟、S3 长稳态短动态、S4 污染、S5 高共线性、S6 异构激励，写出 CSV、ground truth 和 manifest。最大问题是仿真只写文件不写 DB，所以数据详情、版本接口和报告 FK 边界不统一。

## 13. API 清单

前缀均为 `/api/v1`，成功响应统一 envelope。

| 方法 | 路径 | 作用/请求 | 前端 | 可用性 |
| --- | --- | --- | --- | --- |
| GET | `/health/live`、`/health/ready`、`/system/info` | 探针/版本 | Settings | live/ready 已实测 |
| POST | `/simulation/generate` | S1–S6、步数、seed、噪声 | Simulation | 成功；未注册 DB |
| POST | `/datasets/upload` | multipart CSV/name | Datasets | 上传路径可用 |
| GET/POST/DELETE | `/datasets`、`/datasets/{id}`、`/{id}/config`、`/{id}/profile`、`/{id}/versions` | 管理、配置、画像、版本 | Datasets/Detail | 仅 DB 数据 |
| POST | `/preprocessing/clean` | 清洗参数 | Cleaning | 后端真实 |
| POST | `/preprocessing/segment` | 输入/输出、窗口、门限、预算 | Segmentation | 已实测 |
| POST | `/preprocessing/delay` | 最大 lag、top-k | Delay | 已实测 |
| POST | `/preprocessing/collinearity` | 输入列、阈值 | Collinearity | 已实测 |
| POST | `/modeling/arx/fit` | ARX 阶次、滞后、估计器、切分 | ARX | 已实测 |
| POST/GET | `/optimization/optuna/start`、`/{study}/status` | trial/timeout/seed；查询进度 | Optuna | 已实测 |
| POST | `/tasks/{task}/cancel` | 取消任务 | Optuna/Copilot | 仅返回状态 |
| POST | `/copilot/chat`、`/copilot/confirm` | 自然语言计划；确认 | Copilot | 部分真实，确认不续跑 |
| POST | `/reports/generate` | dataset/version/study/title | Deliverables | 仿真版本本轮 500 |
| POST | `/delivery/export` | version、列、sample_indices | Deliverables | 已实测成功 |
| POST | `/benchmark/run` | S3/S6、步数、seed、窗口预算 | Benchmark | 已实测成功 |

## 14. 数据库设计

主要表：`datasets`（根资产）；`dataset_versions`（父子版本 DAG）；`dataset_columns`（列角色）；`dataset_profiles`（质量画像）；`processing_runs`（算法/Agent/交付审计）；`operation_logs`（操作日志）；`optimization_studies`、`optimization_trials`（Optuna）；`strategy_memory`（策略热启动）。迁移为 `0001_initial_schema -> 0002_processing_runs -> 0003_optimization_and_memory`。上传数据关系完整，仿真数据绕过表是主要设计缺口。

## 15. 当前项目运行验证

本轮实际链路：S6 仿真成功；26 个候选/16 个门控/3 个选中窗口的动态优选成功；时滞成功但 u2 偏差明显；共线性成功；ARX 成功；3 轮 Optuna 成功；规则 Agent 成功生成合规计划，但 ARX 因设计矩阵秩亏失败并报告该错误；导出成功写出 180/1200 行 CSV 和 manifest；S3/S6 500 行自评测成功并显示真实秩亏差异。

报告验证失败：对同一仿真 version 调用 `/reports/generate` 返回 HTTP 500 `SYSTEM_INTERNAL_ERROR`。结合 `report_service._persist` 对 `source_version_id` 的外键写入和仿真未建 DB 版本，代码层面最可能是仿真版本 FK 不存在；需在下一轮打开后端日志并加回归测试确认。后端 pytest/Playwright 本轮未重新跑，README 的历史 “237 passed” 不作为本轮证据。

## 16. A14 官方要求对应表

| A14 要求 | 当前状态 | 对应代码 | 完成度 | 主要问题 |
| --- | --- | --- | --- | --- |
| CSV 管理 | 上传数据完整 | `dataset_service.py` | 高 | 仿真不入 DB |
| 仿真数据 | S1–S6、真值真实生成 | `simulation_service.py` | 高 | 下载是假 CSV |
| 数据清洗 | API 真实，Agent 不完整 | `cleaning/pipeline.py` | 中高 | Agent 不产生派生版本 |
| 动态区段筛选 | 门控 + D-最优 + 评分 | `gating.py`、`selection.py` | 高 | 需真实工业数据验收 |
| 时滞 | 预白化、候选、验证精炼 | `delay.py` | 中高 | 补偿版本不清晰 |
| 共线性 | Pearson/Spearman/VIF/建议 | `collinearity.py` | 中高 | 无实际 drop/merge/PCA |
| 系统辨识 | 时间切分 ARX 和真实指标 | `modeling_service.py` | 高 | 测试后段泛化差 |
| Agent | 结构化计划、校验、部分工具 | `planner.py`、`agent_service.py` | 中高 | 非 Level 4 |
| 工作流 | 白名单 DAG/合规证明 | `compliance.py` | 高（校验） | 确认后不续跑 |
| 闭环寻优 | Optuna 多轮真实反馈 | `optimization_service.py` | 高 | Agent 不控制反馈 |
| 图表 | 页面有 ECharts | `frontend/src/views` | 中 | 报告无嵌图 |
| 报告 | Markdown 数值溯源 | `report_service.py` | 中 | 仿真版本 500 |
| 高质量数据导出 | CSV + manifest | `report_service.py` | 高（API） | UI 缺下载 |

## 17. Mock / 写死数据排查

- Mock API/固定指标：Dashboard、Settings；失败 Mock：Cleaning；固定下载：Simulation。
- deferred/stub 路径：Agent clean 的诊断替代、Agent report/export、copilot confirm、task cancel。
- 未发现生产 Optuna 用固定 FIT 数列模拟多轮；Optuna、segment、delay、ARX、benchmark 都返回真实计算结果。
- 前端类型遗留：S6 联合类型、旧 TaskResource；模板遗留：HelloWorld/Vite 初始资产。

## 18. 当前 Bug 与风险

### P0

本轮没有发现健康探针或核心算法 API 的代码级 P0；Docker CLI 权限限制是当前分析环境问题，不是项目运行结论。

### P1

1. 仿真版本不入数据库，统一数据生命周期断裂；报告对仿真 version 实际 500。
2. Agent 清洗未改变数据；确认不续跑；Agent report/export deferred。
3. 共线性无实际变量处理；时滞无明确补偿派生版本。

### P2

1. Cleaning 失败显示假数据，Simulation 下载是假数据。
2. Dashboard/Settings 写死；报告无真实图片打包；交付页无下载按钮。
3. S6/任务类型过时，影响展示可信度。

### P3

Vite chunk 偏大；Node/jsdom 有 engine warning；README Compose 验证口径过时；完整测试需要干净环境重跑。

## 19. 下一阶段修改建议

### 第一优先级

统一仿真和上传数据的资产模型；修复报告仿真 FK/报告回归测试；让 Agent clean 调真实清洗服务并支持确认续跑；删除失败假图和假下载；实现真实取消或明确语义。

### 第二优先级

实现时滞补偿派生版本；实现可确认的 drop/merge/PCA；让 Agent report/export 调真实 service；补真实工业 CSV 验收；报告生成清洗前后图、动态高亮、热图和收敛图。

### 第三优先级

让 Agent 读取模型评价和失败原因，决定下一轮策略；围绕 S6 异构激励、D-最优避免秩亏、free-run FIT 目标做可复现答辩演示；加强工程解释。

### 第四优先级

在干净环境跑 pytest/ruff/mypy/Vitest/build/Playwright；加下载路由；修正类型和文档；优化分包、清理模板和 demo key-like 文本。

## 20. 修改项目之前仍需向用户确认的问题

1. 比赛主演示以 S6 仿真还是一份真实工业 CSV 为主？
2. 是否要求 Agent 自身承担“模型反馈后改写下一轮计划”，还是接受“Agent 编排 + Optuna 数值闭环”的拆分表述？
3. 报告是否必须包含可下载的 PNG/SVG/HTML/PDF 图文包，还是 Markdown/CSV 足够？
4. 是否准备接入本地 Ollama 或其他 OpenAI-compatible 模型？只需确认 provider、base URL、模型名；密钥应通过环境变量提供。

## 21. 第一轮修复记录：统一数据资产生命周期与真实 Dashboard（2026-08-20）

### 原问题与根因

- 仿真服务只写入 CSV、ground truth 和 manifest 文件，却返回了未在数据库注册的随机 ID；`datasets`、`dataset_versions` 和 `dataset_profiles` 中没有相应记录。
- Dashboard 使用 `ds_s3`、`ds_s4`、`ds_s2` 及固定 FIT/提升幅度作为排行榜行。点击后前端请求 `/datasets/ds_s3`，而后端路径参数要求 UUID，因而返回 `REQUEST_VALIDATION_FAILED`。
- 报告持久化会将来源版本写入 `processing_runs.source_version_id`。仿真 ID 不存在于 `dataset_versions`，触发外键错误并表现为 HTTP 500。
- Simulation 下载在前端重新生成固定 50 行正弦波 CSV；Cleaning 在 API 失败时也绘制正弦波假结果，均会误导展示。

### 本轮修改

- 新增仿真资产注册：生成 S1–S6 后复用现有 Dataset schema 创建 `Dataset(source=simulation)`、根 `DatasetVersion(operation=simulation_generate)`、列角色和 `DatasetProfile`。CSV SHA-256、仿真 request、场景、ground truth/manifest 路径与摘要存入已有字段，未新增数据库字段或迁移。
- `POST /simulation/generate` 现返回数据库实际存在的 `dataset_id`、`version_id`、数据集名称、场景、下载 URL、ground truth 与 manifest 信息；`GET /datasets/{id}/download` 返回该真实版本 CSV。
- 新增 `GET /dashboard/leaderboard`：只读取成功的 OptimizationStudy 和真实已完成 Trial。首轮验证自由仿真 FIT 作为 baseline，best trial 的同口径 validation FIT 作为 optimized FIT，按后者降序；测试集指标未持久化时明确返回 `null`，前端显示“暂无测试集指标”，不伪造泛化结论。
- Dashboard 删除静态数据集、固定 FIT、固定提升和伪优化步骤；“查看细节”仅使用后端返回的真实 UUID。无记录时显示引导空状态。
- 仿真下载改为后端产物 URL；Cleaning 请求失败只显示真实错误且不展示假曲线。
- 报告服务未通过 catch 伪造成功；仿真根版本存在后，原来的外键引用合法，报告可正常持久化。

### 验证结果

- 迁移 head：`0003_optimization_and_memory`；本轮不需要 schema migration。
- 实测 S6：`dataset_id=20c184a2-faa5-491a-b04e-5315b883a329`，`version_id=a76ad733-e603-4ac2-8b04-61db125af350`，后端返回 800 行、5 列 `timestamp,u1,u2,u3,y`。详情、Profile、Versions 和真实 CSV 下载均为 HTTP 200，根版本 operation 为 `simulation_generate`。
- 对该版本实测动态区段优选、ARX、3-trial Optuna；study `2acbe923-6015-4d13-ad71-cd155cd94029` 成功。真实排行榜返回该 Dataset UUID（而非 `ds_s3`），validation baseline 为 -18.19%，best validation FIT 为 51.17%，提升 69.35%。这是小预算实测结果，不作为算法能力宣传指标。
- 同一仿真版本调用 `/reports/generate` 后返回 HTTP 200，生成报告 `731d9197-be56-4794-8c1f-42b575d90ac6`，含 14 个真实 provenance bindings。
- 自动测试：新增生命周期/报告/排行榜 3 项测试通过；既有 datasets/reporting 测试通过；optimization 测试在显式关闭后台队列的测试配置下通过；前端 `npm.cmd test` 与 `npm.cmd run build` 通过（build 仅有既有 chunk-size warning）。

### 仍未解决的问题

- 既有 Optuna trial 仅持久化 validation 指标，尚无 test FIT/generalization gap 的真实持久化与展示；本轮已明确显示缺失而非伪造。
- 同配置、同 CSV 的仿真重复生成会复用数据库资产，但已写出的重复文件产物仍待后续做受控清理策略；不能在此处自动删除用户数据。
- Agent 的真实清洗执行、确认后续跑、报告/导出工具执行及 LLM 配置仍按原分析结论暂缓。

## 22. 第二轮-A：严格 Baseline 与独立泛化评价（2026-08-20）

### 原问题

第一轮排行榜把首个 Optuna trial 的 validation free-run FIT 当作 baseline。该 trial 已属于随机/热启动搜索，不是确定性的优化前工程默认方案；同时 trial 内部虽不以 Test 为 objective，核心辨识仍会计算 Test 指标，隔离边界不够严格。

### 本轮修改

- 在 `evaluation_policy.py` 定义唯一 `DEFAULT_BASELINE_CONFIG` 与 10/25 个百分点的系统工程泛化风险阈值。每个 Study 先执行一次完整、确定性的 Baseline（门控、D-最优选段、ARX），而后才进入 Optuna。
- Baseline 与 final Test replay 的配置、validation/test 指标、耗时、时间戳、错误码和 ProcessingRun ID 保存在 `optimization_studies.statistics.evaluations`，并分别记录为 `optimization.baseline`、`optimization.final_test` 审计运行；现有 JSON 持久化字段足以可靠表达，因此未新增数据库迁移。
- Optuna 每个 trial 显式关闭 `evaluate_test`：不产生 Test 指标、图表或残差。Best Trial 按既有 validation objective 固定后，才以固定参数重放一次完整流程并产生 Test free-run FIT、Test one-step MAE/RMSE/R²。
- 统一定义 `generalization_gap = optimized_validation_fit - optimized_test_fit`；Dashboard 用真实持久化 Baseline、Best Trial validation 和 final Test 数据展示，历史 Study 则显示缺失而不补算/伪造。
- 具体口径见 `docs/algorithms/model-evaluation.md`。

### 实测验证

- 本地 S6（1200 点、seed 20260820）生成 `dataset_id=34397c5e-4597-4b37-a81e-9dec9483f514`、`version_id=1ac49157-109a-4c1c-86bc-f78d5c95a0dd`；5-trial Study 为 `25cfda1b-6451-4901-b91b-82c199482de0`。
- Baseline 使用记录的默认参数，validation free-run FIT 为 76.19%，Test free-run FIT 为 30.63%。
- Validation 选中的 best trial（窗口 140、预算 12、nk=4、na=2、nb=3、OLS）validation FIT 为 83.49%，相对 Baseline 提升 7.30 个百分点。
- 固定该 trial 后的独立 Test free-run FIT 为 13.05%，Test one-step MAE/RMSE/R² 为 0.0252 / 0.0318 / 0.9409，generalization gap 为 70.44 个百分点。Dashboard 真实显示“系统工程风险提示：泛化风险高”；没有为改善结果修改 S6、真值或切分。
- 数据集详情 API 对上述真实 UUID 返回 HTTP 200；迁移 head 仍为 `0003_optimization_and_memory`。

### 尚待后续

- 下一步应将最终 Test 评价与报告模板、导出产物和更细的泛化诊断联动；本轮未改 Agent、LLM、PCA、新模型或核心工业算法。
