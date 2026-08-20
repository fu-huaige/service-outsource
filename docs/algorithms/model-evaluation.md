# ProcessPilot 模型评价口径

## 目标

本规范定义闭环寻优的正式比较口径，避免将 Optuna 的首个随机 trial 误称为“优化前基线”，并防止测试集泄漏进寻优过程。

## 时间顺序切分

同一 DatasetVersion 的时序数据按原始时间顺序连续切分：

```text
0 ───────── Train ───────── Validation ───────── Test ───────── N
              60%               20%                20%
```

- Train：ARX 参数拟合，动态区段门控与 D-最优选段也只读取这一段；
- Validation：计算 free-run FIT，作为 Optuna 的唯一选择依据；
- Test：在 best trial 已固定后，只执行一次最终评价。

比例由 `OptimizationStartRequest.train_ratio` 和 `validation_ratio` 记录；余量为 Test。任何 `train_ratio + validation_ratio >= 1` 的请求均被拒绝。系统不随机打乱时序样本。

## 正式 Baseline

每次 Study 在 Optuna 前执行一次确定性的工程默认流程，配置唯一来源为 `app/services/evaluation_policy.py` 的 `DEFAULT_BASELINE_CONFIG`：

| 参数 | 默认值 |
| --- | --- |
| window_size / max_segments | 60 / 10 |
| max_missing_ratio / max_anomaly_ratio | 0.20 / 0.10 |
| min_input_activity_ratio | 0.05 |
| 选段 ARX 结构 na / nb / nk | 2 / 2 / 0 |
| 辨识 ARX 结构 na / nb / nk | 2 / 2 / 0 |
| estimator | OLS |
| train / validation / test | 0.60 / 0.20 / 0.20 |

Baseline 同样执行质量门控、D-最优选段和 ARX，不调用 Optuna。它的参数、validation/test 指标、开始/结束时间、耗时、错误码与 `ProcessingRun` ID 保存于 `optimization_studies.statistics.evaluations.baseline`，并以 `optimization.baseline` 写入 `processing_runs`。

## 寻优与独立 Test

1. 每个 Optuna trial 仅评估 Train 与 Validation，`evaluate_test=false`，不生成 Test 指标、曲线或残差；
2. objective 为稳定模型的 validation free-run FIT 及既有工程惩罚项；Test 从不参与 objective、trial 排名、search space 调整或 warm start；
3. 以最大 objective 选定 `best_trial_number`；
4. 用该 trial 的固定参数重放一次门控、选段和 ARX，开启 Test 评价；
5. 保存 `test_free_run_fit`、Test one-step MAE/RMSE/R²，以及下述泛化差距到 `statistics.evaluations.final_test` 和 `optimization.final_test` ProcessingRun。

最终 Test evaluation 失败不会伪造数值：Study 的寻优结果仍可查询，但 Test 字段为空并带错误状态。

## 指标定义

- Baseline validation FIT：正式 Baseline 的 validation free-run FIT；
- Optimized validation FIT：validation objective 选出的 best trial 的 validation free-run FIT；
- Optimized test FIT：best trial 固定后得到的 held-out Test free-run FIT；
- Improvement：`optimized_validation_fit - baseline_validation_fit`；
- Generalization gap：`optimized_validation_fit - optimized_test_fit`。

MAE、RMSE、R²来自最终 Test 的 one-step 诊断；FIT 的正式主口径始终是 free-run FIT。

## Dashboard

Dashboard 仅以真实数据库记录显示上述指标。历史 Study 没有正式 Baseline 或 final Test evaluation 时：

- baseline / improvement 显示 `—`；
- Test FIT / gap 显示“暂无测试集评价”；
- 禁止用第一个 trial、固定值或前端计算补充缺失值。

泛化风险为系统工程提示，不是行业标准或“模型必然失效”的结论：gap ≤ 10 个百分点为正常，10–25 为注意，>25 为高风险。阈值统一位于 `evaluation_policy.py`。
