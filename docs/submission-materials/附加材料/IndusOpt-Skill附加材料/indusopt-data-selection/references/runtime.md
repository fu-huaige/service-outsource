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

`analyze` 默认 na=2、各输入 nb=2、window=60、budget=8；可明确修改 `--na`、`--nb`、`--window`、`--budget`。这些是可复现起点，不保证最优；`--delays` 没有默认值。默认 OLS 且要求模型稳定，不隐式改用正则化。

完整结果中含原始输入和连续建模数据。用户数据的运行目录可能含业务信息，只有示例合成数据结果适合直接作为公开竞赛附件。

请求前校验 `na/nb` 为 1–20、窗口至少 5、预算 1–100，并检查补偿后至少 100 行、训练区间能够容纳窗口。服务端仍执行完整业务校验。报告及其他必要文件写入后，才以临时文件替换方式发布成功 manifest。

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

当前模型服务取原时间轴 `train_end=floor(N*0.6)`，在 Train 尾部额外保留 guard，`guard=max(na,nb-1)`（补偿后 nk=0）。选段服务的 train_ratio 作用在 `N-guard` 个回归行上，因此客户端使用 `(floor(N*0.6)-2*guard)/(N-guard)`，使候选窗口不进入验证边界。模型训练行数必须等于完整的 selected_indices 数量，否则停止导出。

选段响应最多给出 4,000 个下标。实际 `selection.selected_rows` 与返回长度不一致时停止；不默默只训练前 4,000 行。

此 Skill 不支持远程服务导出、认证配置、自动清洗/删列、自动时滞估计、任意自定义流水线或长任务轮询。需要这些能力时使用项目主体，不伪造完成结果。
