# A14 IndusOpt / ProcessPilot 增量项目交接文档

> 交接日期：2026-08-25（Asia/Shanghai）
>
> 交接对象：项目负责人及后续开发、测试人员
>
> 交接范围：在 `A14_TEAM_HANDOFF_2026-08-21.md` 之后完成的验收、修复、前端调整与 Agent 大模型接入
>
> 安全说明：本文不包含任何 API Key、密码或个人敏感信息

## 1. 一句话结论

本轮负责范围已经完成并合并到远端团队开发分支 `feat/versioned-preprocessing-pipeline`；本文编写时最新功能合并提交为 `d26903f`（PR #5），文档 PR 的后续合并提交以 GitHub 为准。本轮没有修改或推送 `main`。

当前可以进入“负责人整体审查 → 收尾人工材料 → 决定是否向 `main` 发起 PR”的阶段，但不能把公开数据集验证、Docker Compose 首次实机部署、演示录屏等团队任务描述为已经完成。

## 2. 接手时先读哪些文件

请按以下顺序阅读，避免只看旧交接得出过时结论：

1. `README.md`：当前功能、启动方式、质量门禁和大模型配置。
2. 本文：2026-08-21 之后的增量工作与当前 GitHub 状态。
3. `A14_TEAM_HANDOFF_2026-08-21.md`：版本化预处理、正式数据、历史验收步骤和安全边界。
4. `PHASE_STATUS.md`：阶段 4–11、实验和交付材料状态；其中部分测试数量是旧快照，最新数量以本文和 PR #5 为准。
5. `docs/PROJECT_HANDOFF_ANALYSIS.md`：项目定位、架构和早期缺口分析；其中“Agent 部分实现”等描述已经被后续提交推进，不能视为当前最终状态。

特别注意：旧交接文档第 5、38、39 节曾写“暂不接真实 LLM”。该描述适用于当时的阶段安排；现在真实 OpenAI-compatible LLM 已接入，同时仍保留离线规则回退。

## 3. 当前 Git 与 GitHub 状态

### 3.1 集成分支

- 仓库：`fu-huaige/service-outsource`（private）。
- 当前远端默认分支：`feat/versioned-preprocessing-pipeline`。
- 本文编写时该分支最新功能合并提交：`d26903f`，即 PR #5 的 merge commit。
- 本轮始终以该分支作为 PR base，没有向 `main` 直接推送。

负责人接手后建议先执行：

```bash
git fetch origin
git switch feat/versioned-preprocessing-pipeline
git pull --ff-only origin feat/versioned-preprocessing-pipeline
git log --oneline -8
```

功能提交历史中应能看到：

```text
d26903f Merge pull request #5 from fu-huaige/test/agent-runtime-settings
e3992c1 feat(agent): add runtime LLM configuration
1bdca1f Merge pull request #4 from fu-huaige/test/sidebar-toggle-alignment
881e55e Merge pull request #3 from fu-huaige/test/ui-form-layout-acceptance
```

### 3.2 PR 状态

| PR | 状态 | Base | 内容 | 处理建议 |
| --- | --- | --- | --- | --- |
| [#1](https://github.com/fu-huaige/service-outsource/pull/1) | Open | `feat/versioned-preprocessing-pipeline` | S6 pipeline acceptance | 不要直接重复合并；核心修改已由 `39fa648` 汇总进入 PR #3，负责人核对后关闭为 superseded |
| [#2](https://github.com/fu-huaige/service-outsource/pull/2) | Open | `feat/versioned-preprocessing-pipeline` | S2 delay refinement | 不要直接重复合并；`±2` 修复与回归已由 `39fa648` 汇总进入 PR #3，负责人核对后关闭为 superseded |
| [#3](https://github.com/fu-huaige/service-outsource/pull/3) | Merged | `feat/versioned-preprocessing-pipeline` | 前端整体优化 + 最终 pipeline acceptance/report lineage | 已进入集成分支，merge commit `881e55e` |
| [#4](https://github.com/fu-huaige/service-outsource/pull/4) | Merged | `feat/versioned-preprocessing-pipeline` | 折叠侧边栏顶部图标对齐 | 已进入集成分支，merge commit `1bdca1f` |
| [#5](https://github.com/fu-huaige/service-outsource/pull/5) | Merged | `feat/versioned-preprocessing-pipeline` | Agent 运行时 LLM 配置与超时修复 | 已进入集成分支，merge commit `d26903f` |

## 4. 本轮完成了什么

### 4.1 项目接管与边界确认

- 完整阅读了项目入口、交接文档、后端、前端、配置、测试和主要需求资料。
- 确认产品定位为工业时序数据优选、动态建模与模型健康工作台，不是直接控制工厂的实时控制系统。
- 固定 Git 边界：测试分支从 `feat/versioned-preprocessing-pipeline` 建立，PR 回到该分支，不直接操作 `main`。

### 4.2 S2、S5、S6 与版本化流水线验收

主要增量提交包括：

- `f2f2a70`：统一仿真数据集生命周期与 Dashboard。
- `54dd224`：加入严格 Baseline 与 held-out 泛化评价。
- `3a30f14`：审计模型评价指标与诊断。
- `e7cc8cd`：版本化预处理流水线与验收修复 checkpoint。
- `39fa648`：汇总 pipeline acceptance、S2/S6 修复与报告血缘。

验收口径与结果：

- **S2 Delay**：候选峰邻域由 `±1` 扩到 `±2`；冻结场景 `seed=9002`、`n=1200` 恢复 `u1=3`、`u2=8`。未确认 Apply 必须返回 `CONFIRMATION_REQUIRED`，且不能创建半成品版本。
- **S5 Collinearity**：验证 Pearson、Spearman、VIF、Condition Number 的真实诊断；确认剔除冗余变量后生成新不可变版本，源版本不被覆盖。
- **S6 ARX + Optuna**：只允许在 `DESIGN_MATRIX_RANK_DEFICIENT` 时从 OLS 确定性回退到 Ridge `alpha=0.1`，并记录回退原因；评价主口径为验证/测试集 free-run FIT，禁止用 Test 调参。
- **版本与血缘**：清洗、特征选择、建模、寻优和报告持续传播 `current_version_id`，保留源版本、参数、运行记录和派生关系。

算法和正式验收的细节仍以 `A14_TEAM_HANDOFF_2026-08-21.md`、`docs/algorithms/`、`docs/experiments/` 与 Git diff 为准，本文不重复完整数学推导和数据表。

### 4.3 前端 UI 与交互调整

相关提交：`55656f6`、`7cba17c`、`435b2d7`、`6b90b73`、`298803c`，集中在 PR #3、#4。

完成内容：

- 保留产品名 `IndusOpt 工模智优`，统一页面标题、留白、卡片和工业工作台层级。
- 统一清洗、时滞、共线性、ARX、Optuna 等参数表单的标签宽度、输入框宽度和纵向对齐。
- 修复长标签不自然断行，包括清洗算法、Hampel 滑窗、ARX `u1` 阶数等。
- 重做 Agent 工作台的字段、示例指令卡片、按钮和响应式布局，避免窄屏横向溢出。
- Agent 抽屉与侧边栏支持内容滚动，展开菜单后底部项目不再被遮挡。
- 加入克制的页面顶部/底部回弹，并支持 reduced-motion。
- 修复清洗页面源数据版本说明排版与折叠侧边栏首个图标中心线。
- 保留真实错误、加载和空状态，不用 mock 成功掩盖后端问题。

### 4.4 真实大模型 Agent

相关功能提交：`e3992c1`，通过 PR #5 合并。

完成内容：

- 新增 `/api/v1/system/agent-config` 的读取、更新、恢复部署配置接口。
- 新增 `/api/v1/system/agent-config/test` 真实连接测试。
- 系统设置页支持 Provider、OpenAI-compatible base URL、模型、API Key 和请求超时。
- 选择 DeepSeek 时自动填写：
  - Base URL：`https://api.deepseek.com`
  - 默认模型：`deepseek-v4-flash`
- API Key 仅写入当前后端进程内存；读取接口只返回 `has_api_key`，不回显密钥，不写浏览器存储或 Git。
- Agent 规划与报告结论共用当前有效 Provider。
- 模型未配置、不可达、输出非法或计划未通过白名单/合规校验时，自动回退 `RuleBasedPlanner`；核心清洗、时滞、ARX、Optuna 不依赖 LLM。
- Agent 前端规划请求单独使用 120 秒超时，修复后端约 33 秒成功返回、前端在 30 秒误报失败的问题。

真实联调证据：

- `deepseek-v4-flash` 连接测试成功，单次测试约 1.98 秒。
- 完整 Agent 指令约 33.52 秒返回 HTTP 200。
- 返回 `plan_source=llm`，生成 12 步计划并通过合规校验。
- 未填写数据版本时只生成计划，结论为“请指定数据版本后执行”，不会误执行算法。

重要运行特性：后端重启会清除页面运行时配置。正式演示可重新填写，或使用 README 中的 `INDUSOPT_LLM_*` 环境变量。任何情况下都不要把真实 Key 写进文档、源码、截图或提交记录。

## 5. 最近一次完整验证证据

PR #5 提交前实际执行：

- Backend Pytest：`273 passed, 2 skipped`。
- Ruff：通过。
- Mypy：当前 Python 3.13 环境检查 52 个应用源文件通过。
- Frontend Vitest：`35 passed`。
- `vue-tsc --noEmit`：通过。
- Vite production build：通过。
- 真实 DeepSeek 连接与真实 LLM 规划：通过。

PR #3 的独立前端验证还包括：

- Vitest：`32/32 passed`。
- Playwright + Chrome：`11/11 passed`。
- `git diff --check`：通过。

注意：`PHASE_STATUS.md` 同时保留了更早阶段的 `23`、`237` 等测试快照。后续对外写材料时应说明证据日期，不要把不同快照的数字混成一次测试结果。

## 6. 启动、检查与演示

完整命令以 `README.md` 的“本地开发”“Docker Compose”“质量门禁”为准。

最小本地开发流程：

```bash
# 后端
cd backend
pip install -e ".[dev]"
PYTHONPATH=. uvicorn app.main:app --reload --port 18000

# 前端（另一个终端）
cd frontend
npm ci
npm run dev
```

建议演示顺序：

1. 打开系统设置，确认 PostgreSQL、Redis 与系统状态。
2. 选择 DeepSeek，填写 Key，点击“保存并立即生效”。
3. 点击“测试当前连接”，确认成功。
4. 打开 Agent 工作台，不填版本 ID，先演示真实 LLM 只生成合规计划。
5. 再选择真实数据版本，演示白名单、确认门和真实算法执行。
6. 展示模型不可用时的规则回退，证明核心算法不依赖外部模型。
7. 展示版本 DAG、报告血缘和优选数据导出。

## 7. 尚未完成与已知限制

以下不属于本轮已经完成的技术任务，负责人需要继续安排：

1. **PR #1、#2 收尾**：确认其核心补丁已由 `39fa648` 覆盖后，关闭为 superseded，避免重复合并。
2. **向 main 集成**：本轮没有推 main。应先整体审查 `feat/versioned-preprocessing-pipeline`，需要时创建以 `main` 为 base 的 PR，由负责人决定合并。
3. **Docker Compose 首次实机验证**：本环境缺少可用 Docker daemon；需在有 Docker 的机器验证 build、迁移、health、worker 与持久卷。
4. **公开数据集外部验证**：当前已有仿真和内部实验，但 README 明确标记公开数据集验证未完成。
5. **竞赛人工材料**：PowerPoint 最终视觉复核、演示视频/交互录屏、成员分工与身份字段需要团队人工完成。
6. **生产安全**：当前没有管理员登录、RBAC/SSO 或加密密钥存储；运行时 Agent 设置页只适合可信本地/内网环境。
7. **模型配置持久性**：页面配置随进程重启丢失；正式部署应使用环境变量或后续增加受控的服务端密钥管理。
8. **产品边界**：当前是离散时间 MISO ARX 为主的工业建模工作台，不应宣传为成熟 DCS/SCADA、PI/Seeq/MATLAB 的直接替代品。

## 8. 负责人建议的收尾清单

- [ ] 拉取并检查集成分支（功能基线至少应包含 `d26903f`）。
- [ ] 审查 PR #3、#4、#5 的合并内容。
- [ ] 核对后关闭 PR #1、#2，避免重复合并。
- [ ] 在负责人环境重新执行 README 质量门禁。
- [ ] 使用演示 Key 重测连接、真实 LLM 规划和规则回退。
- [ ] 在 Docker 机器完成 Compose、迁移、Worker 与数据卷验证。
- [ ] 复核 PPT、录屏、分工表和知识产权待填字段。
- [ ] 决定是否创建 `feat/versioned-preprocessing-pipeline → main` 的最终 PR。

## 9. 建议后续使用的技能

后续 Codex/Agent 会话建议按任务选择：

- `review`：整体审查 `feat/versioned-preprocessing-pipeline` 相对 `main` 的标准符合性与目标达成度。
- `gh-fix-ci`：若最终 PR 的 GitHub Actions 失败，读取检查日志并定位修复。
- `diagnose` 或 `superpowers:systematic-debugging`：复现并修复真实运行问题。
- `webapp-testing`：用 Playwright 验证前端、Agent、错误路径和响应式布局。
- `document-skills:pptx` / `presentations:Presentations`：复核或修改答辩 PPT。
- `document-skills:pdf`：对最终 PDF 材料做逐页视觉检查。
- `superpowers:verification-before-completion`：在宣布最终交付前重新运行证据链。

## 10. 交接结论

可对团队表述为：

> 本轮负责的 S2/S5/S6 验收、流水线修复、前端 UI 收敛与真实 DeepSeek Agent 接入已经完成，并通过 PR #3、#4、#5 合并到 `feat/versioned-preprocessing-pipeline`。当前应由负责人统一审查该分支、处理两个旧 PR、完成 Docker/公开数据/竞赛人工材料，再决定是否合并到 main。
