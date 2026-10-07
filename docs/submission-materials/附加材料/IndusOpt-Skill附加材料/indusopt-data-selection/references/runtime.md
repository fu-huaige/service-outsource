# 运行与接口约定

## 环境

客户端：Python 3.11+，仅标准库，无 API Key、无独立 pip 依赖。
服务端：仅供已获主系统使用授权的成员部署，需自行提供非公开 IndusOpt 主项目根目录下的 `backend/`，使用 Python 3.11+，按 `pyproject.toml` 安装。本仓库不提供后端源码、公开下载入口或可独立运行的替代服务。生产目标为 PostgreSQL；可选 Redis/RQ。客户端不会修改语言模型配置。生成报告采用本地确定性模板，无外部大模型请求。

正式后端沿用项目部署说明。本地演示可使用项目已有 `scripts/serve_e2e.py`：

```bash
cd /path/to/IndusOpt/backend
# 已有可用虚拟环境可直接复用；否则：
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
# 使用新建的专用目录，--keep 防止已有目录被该辅助脚本清空。
INDUSOPT_LLM_PROVIDER=none INDUSOPT_BACKGROUND_OPTIMIZATION=false \
  .venv/bin/python scripts/serve_e2e.py --port 18143 --state-dir /tmp/indusopt-skill-demo --keep
```

对应 `--base-url http://127.0.0.1:18143/api/v1`，`--artifact-root /tmp/indusopt-skill-demo/artifacts`。该演示使用 SQLite 与 `create_all`，不验证 PostgreSQL 迁移、Docker、RQ 或生产部署。确认路径属于本次演示；不要用生产目录。

### Windows（CMD）

仅限已获后端使用授权的成员：先把下面的示例目录替换成自己的主项目后端路径。使用已有且安装了后端依赖的 Python 3.11+；若需新环境，经用户授权后执行：

```bat
cd /d "C:\path\to\IndusOpt\backend"
python -m venv .venv-skill
.venv-skill\Scripts\python.exe -m pip install -e ".[dev]"
set INDUSOPT_LLM_PROVIDER=none
set INDUSOPT_BACKGROUND_OPTIMIZATION=false
.venv-skill\Scripts\python.exe scripts/serve_e2e.py --port 18143 --state-dir C:/Temp/indusopt-skill-demo --keep
```

`.venv-skill` 应为新目录，已有解释器可直接复用并替换命令路径。对应 `--artifact-root C:/Temp/indusopt-skill-demo/artifacts`。演示目录应属于本次工作；保留 `--keep`，避免辅助脚本清空已有目录。

在另一个 CMD 窗口进入附件根目录，执行 README 的客户端命令。客户端仅需标准库，Windows 使用 `python`，macOS/Linux 使用 `python3`。

## 命令

全局参数必须在子命令之前。输出目录不得已存在。

```bash
# 生成演示数据，原始响应中的 ground_truth 仅供事后审计
python3 "$SKILL_DIR/scripts/indusopt_skill.py" --base-url http://127.0.0.1:18143/api/v1 \
  generate-example --scenario S2 --samples 2000 --seed 20260913 --out ./example

# 仅用于复现本包的固定假设演示：三个通道均人为指定 1 个采样点。
# 这些参数不来自真值，也不表示已经估计到最佳时滞。不得用于真实数据的默认配置。
python3 "$SKILL_DIR/scripts/indusopt_skill.py" --base-url http://127.0.0.1:18143/api/v1 analyze \
  --csv ./example/input.csv --time-column timestamp --inputs u1,u2,u3 --output-column y \
  --delays 1,1,1 --confirm-lags --data-kind synthetic \
  --artifact-root /tmp/indusopt-skill-demo/artifacts --out ./result

# 产品自带 S3/S6 基准，独立于前一条 CSV 流程
python3 "$SKILL_DIR/scripts/indusopt_skill.py" --base-url http://127.0.0.1:18143/api/v1 \
  benchmark --samples 2000 --seed 20260913 --out ./benchmark
```

`analyze` 默认 na=2、各输入 nb=2、window=60、budget=8；可明确修改 `--na`、`--nb`、`--window`、`--budget`。这些是可复现起点，不保证最优；`--delays` 没有默认值。客户端显式采用 ensemble 选段、标准化、质量加权、自适应窗口及训练比例 0.6；window 是自适应窗口的基准长度，budget 是最大窗口数，不是固定行数。两组模型均显式采用 ARX、OLS、标准化、截距和固定预测初始化，要求模型稳定，不隐式改用正则化。

完整结果中含原始输入和连续建模数据。用户数据的运行目录可能含业务信息，只有示例合成数据结果适合直接作为公开竞赛附件。

请求前校验 `na/nb` 为 1–20、窗口至少 5、预算 1–100，并按 `N=原始行数-max(lag_map)` 预估补偿后长度。N 至少为 100，且必须满足下述 ensemble 历史与训练边界；可以确定不足时，在任何 API 请求前停止。下载实际补偿版本后再次核对长度。该预检只判断确定的长度不足，不保证质量门控、有限值回归行数或 OLS 秩检验一定通过；服务端仍执行完整业务校验。报告及其他必要文件写入后，才以临时文件替换方式发布成功 manifest。

## 已核对接口

| 方法与路径（相对于 /api/v1） | 作用 |
|---|---|
| GET /health/live | 检查 API 存活；不代替完整依赖就绪检查 |
| POST /simulation/generate | 持久化仿真 CSV 及真值 |
| POST /datasets/upload | multipart 字段 file，返回 dataset 与 parse_task |
| GET /datasets/{id} | 读取已有列角色 |
| GET /datasets/{id}/versions | 读取版本血缘，定位唯一原始版本 |
| POST /datasets/{id}/config | time_column、input_columns、output_column |
| GET /datasets/{id}/download?version_id=... | 下载指定版本，避免 active 指针漂移 |
| GET /datasets/{id}/profile?version_id=... | 指定版本质量画像 |
| POST /preprocessing/delay/apply | lag_map、user_confirmed，返回 result_version_id |
| POST /preprocessing/collinearity | 只给出诊断，不删除变量 |
| POST /preprocessing/segment | 返回 selection、selected_indices |
| POST /modeling/arx/fit | training_sample_indices 限制训练行；evaluate_test=false |
| POST /delivery/export | 显式 sample_indices，返回 csv_uri、manifest_uri |
| POST /benchmark/run | 重算产品内基准 |

成功响应为 `success=true, data=...`。HTTP 202 不代表完成，脚本检查 task/parse_task.status。服务端 csv_uri 是产物根下的相对文件路径，不是下载 URL；脚本仅从明确指定的本机 artifact-root 复制文件，并检查路径包含关系、版本标识、行列数与每条时间/数值。

## 模型切分细节

以下契约根据主项目提交 `5d2a3de` 的 SegmentRequest、segment_service、regressor 与 selection 源码核对。2026-10-07 用户按该提交重新构建 Docker backend，health/live、Schema 检查及 S2 完整在线链通过；见 [最新验收](../../验证/2026-10-07最新版兼容性复验/verification.json)。接口自身未返回部署 commit，未将本地 HEAD 冒充接口返回的版本。

N 为补偿后连续版本的原始时间轴行数。模型取 `train_end=floor(N*0.6)`，模型 guard 为 `g=max(na,nb-1)`（补偿后 nk=0），训练下标小于 `train_end-g`。选段同样直接在原始 N 行时间轴上使用 `train_ratio=0.6`，不再换算为回归矩阵行比例。

当前 ensemble 使用用户结构以及辅助结构 `(na,nb)=(1,1)`、`(4,3)`，因此共同历史长度为 `H=max(na,nb-1,4)`。客户端显式传 `history_guard=H`，选段服务得到 `train_stop=floor(N*0.6)-H`；候选回归行下标处于 `[H, train_stop)`。当前服务严格要求 `train_stop > H+window_size`，相等也会拒绝。默认 na=nb=2、window=60 时，补偿后 N=114 不足，N=115 才通过长度条件；原始数据还需加上最大补偿时滞所裁掉的行数。自适应短窗口不会放宽这个服务门槛。

H 至少为模型 guard，所以选段候选范围不会进入验证或测试区间。模型仍使用完整连续时间轴与选中下标，实际训练行数必须等于完整 selected_indices 数量，否则停止导出。质量加权用于选段，两组 ARX 均等权训练，不单独给优选模型传选段权重。

当前响应返回完整 `selected_indices`；4,000 点限制用于图表时间与序列投影，不用于裁截训练下标。实际 `selection.selected_rows` 与返回下标长度不一致、为空或重复时仍停止，不根据图表投影推断训练样本。

manifest 的 `selection_parameters` 保留 window/budget 字段，同时记录显式选择策略、训练比例、阶次和 guard；`selection_training_range` 记录候选范围的起点与不含端点的终点。`model_parameters` 记录 ARX 请求，`comparison` 保留后端返回的 model_structure、实际 intercept 和 preprocessing，报告区分请求参数与有效返回值。未返回的字段为 null，不从请求推造结果。当前调用接口没有可靠的后端部署版本或 commit，不将文档核对版本或本地 Git HEAD 填作运行版本。

本包 2026-09-13 与 2026-09-18 的 S2/S6、指标和在线记录继续作为历史证据保留。2026-10-07 最新 S2 验收选中 930 行，全量/优选验证自由仿真 FIT 分别为 70.4834% / 72.3561%；不要求与历史数值一致。本轮未重跑 S6、未确认停止或在线长度边界。ARX 仍为当前 Skill 正式模型，主系统新增的 OE 尚未接入。

此 Skill 不支持远程服务导出、认证配置、自动清洗/删列、自动时滞估计、任意自定义流水线或长任务轮询。需要这些能力时使用项目主体，不伪造完成结果。
