# IndusOpt 工业建模数据优选与诊断 Skill

ProcessPilot / IndusOpt 项目的竞赛附加材料与演示版 Skill：调用本机后端，完成工业 CSV 诊断、人工确认后的时滞补偿、D-最优数据优选、ARX 对照评价及可追溯数据交付。

**需要配套后端。安装 Skill 不会安装或启动 IndusOpt，也不能脱离后端独立计算。** 本包导出的是 D-最优选段数据，不是 Optuna Best 结果。

## 能力与边界

| 支持 | 暂不支持 |
|---|---|
| 质量画像、显式时滞补偿、共线性诊断 | 自动清洗、自动估计时滞、自动删列 |
| 训练段 D-最优选段、同结构 ARX 对照 | Optuna 闭环寻优、测试集最终评价 |
| 优选 CSV、连续建模源、下标和来源清单 | 远程产物下载、异步任务轮询 |
| 确定性 Markdown 报告 | 自动图文 HTML 报告、大模型生成指标 |

数据优选效果对照同时参考样本量、验证 FIT/RMSE、稳定性、训练输入支持与验证残差诊断。诊断来自 backend 正式 ARX 响应；已有风险、缺失字段和不可比条件均保留，不因 FIT 改善而无条件宣称数据优选有效。

Input Support 采样点数采用 backend 的支持度诊断口径，不等同于 ARX 最终有效训练行数。

客户端仅使用 Python 3.11+ 标准库。自然语言触发由宿主智能体负责，独立触发准确率尚未评测。

ARX 是当前 Skill 的正式对照模型；主系统新增的 OE 能力尚未接入本 Skill。

## 后端依赖与验证版本

**IndusOpt 主系统及后端目前不公开，也不随本仓库分发。** 本仓库公开的是 Skill 客户端、文档、已获授权的合成示例及验证材料；仅下载本仓库**不能独立运行在线诊断、时滞补偿、D-最优数据优选或 ARX 建模**。已获主系统使用授权的团队成员可在自己的 `<项目根目录>/backend` 中按[运行约定](indusopt-data-selection/references/runtime.md)部署。其他使用者可以阅读源码及示例，并执行不启动后端的本地验证。

- 原始 macOS 演示对应后端提交：`5bcc51c1469e6451d4a1980c71d37663498ce172`。
- 原始证据：`示例与实测/` 与 `验证/环境与验收.json`；保留历史记录，不改写成新版验收。
- 最新验收：2026-10-07 在用户重建的 backend `5d2a3de68e24863f91b9785bbef89f8727a5de11` 上，S2 完整在线链通过；见 [最新证据](验证/2026-10-07最新版兼容性复验/verification.json) 与 [发布验收说明](验证/发布验收说明.md)。9 月的 S2/S6/未确认停止记录继续作为历史证据保留。
- 同日诊断增强 S2 单次在线复验也通过，见 [诊断增强证据](验证/2026-10-07诊断增强复验/verification.json)：输入支持范围保持，但已有验证外推与残差关联风险仍保留，综合结论为人工复核。
- 在线验收继续复用用户以 `5d2a3de68e24863f91b9785bbef89f8727a5de11` 构建的 Docker backend；API 未返回部署 commit。只读核对时主项目 HEAD 为 `8fd4f37a59974cbeefc58ecbcab1d58cb25f5849`，相关 Input Support / Residual Diagnostics 实现与上述运行来源一致；此源码比较不表示 `8fd4f37` 已在线验收。

## 安装与运行

1. 将 `indusopt-data-selection/` 复制到宿主智能体的技能目录，不覆盖已有个人修改。
2. 使用已有且获授权的 IndusOpt backend；独立演示环境的启动方式见 [运行约定](indusopt-data-selection/references/runtime.md)。
3. 使用 Python 命令验证固定流程，或向宿主智能体提出：

> 使用 $indusopt-data-selection 分析这份工业 CSV，先核对变量和时滞，完成诊断、数据优选和模型对照，输出可复核的结果。

### 最短示例（仅限已获后端使用授权的用户；本包根目录，端口 18143）

将下列产物根目录替换为演示后端实际使用的目录。`1,1,1` 是复现附件的固定假设，不是推荐时滞或估计真值。

```text
python indusopt-data-selection/scripts/indusopt_skill.py --base-url http://127.0.0.1:18143/api/v1 analyze --csv 示例与实测/S2输入/input.csv --time-column timestamp --inputs u1,u2,u3 --output-column y --delays 1,1,1 --data-kind synthetic --artifact-root C:/Temp/indusopt-skill-demo/artifacts --out runs/diagnosis
```

首次仅画像并保存 `pending-confirmation.json`，状态为 `waiting_confirmation`。确认具体补偿值和来源后，加 `--confirm-lags` 并改用全新目录 `--out runs/result`，才会补偿、建模和导出。macOS/Linux 使用 `python3`，产物根目录可采用 `/tmp/indusopt-skill-demo/artifacts`。

## 交付文件

- `report.md`：验证集模型对照与使用边界。
- `selected.csv`：D-最优选中样本；不能把断续片段直接拼成连续序列训练。
- `model-source.csv`：完整连续建模源，配合 manifest 中的行下标复现。
- `manifest.json`：完整成功标记，最后写入；含版本、模型、样本下标及 SHA-256。
- `diagnostics-comparison.json`：两组真实输入支持、激励不足及残差诊断；summary 明确标为 Skill 整理的描述性结论。成功 manifest 表示交付完成，不代表诊断无风险。
- `source.csv`：上传数据副本。真实业务运行目录可能含敏感数据，不应直接公开。
- `failure.json` / `pending-confirmation.json`：失败或待确认状态，不是成功交付。

## 本地验证

```text
python -B 验证/test_adapter.py
```

此命令检查客户端约束与历史证据，不启动后端。Windows 不支持符号链接时仅跳过相应测试，其余路径保护仍检查。最新在线验收结果及历史复验脚本的适用范围见发布验收说明。

## 开源许可证

本仓库中由团队拥有或已获得适当授权、且未另行注明许可的 Skill 源码、文档和团队自建合成示例，采用 [Apache License 2.0](LICENSE)（SPDX：`Apache-2.0`）发布。授权范围及第三方内容说明见 [许可证状态](LICENSE_STATUS.md)。该许可证不自动覆盖未包含在本仓库中的 IndusOpt 主系统或后端。

## 开源维护说明

- 主系统及后端暂不公开，不提供或虚构后端下载地址；若将来调整公开范围，应先取得团队授权并核对兼容版本。
- 本仓库已采用 Apache-2.0；新增第三方作品或材料前，应核对相应许可、署名及授权范围，详见 [许可证状态](LICENSE_STATUS.md)。
- 仅上传已审阅的合成示例，不上传本机数据库、密钥、缓存或业务数据。
- 修改文件后重新生成并检查 `SHA256SUMS.txt`。

本包不自动执行 Git 提交、推送或部署。正式 DOCX 保留当前格式修改版本，其正文数据属于 9 月原始竞赛材料；最新修订及运行状态以 README、附加材料说明.md 和发布验收说明为准。
