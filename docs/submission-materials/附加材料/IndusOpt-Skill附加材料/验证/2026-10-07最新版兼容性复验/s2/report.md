# 工业建模数据优选与诊断报告

数据性质：synthetic。
数据版本：`d3c0e68e-f4ab-4ac3-837a-d61128421d28`。原始数据校验值：`305032b84a4f9cc7b450572ea9d72c020a9a166a97b5171f4a959544f45c4486`。

本次比较采用固定 ARX 结构与显式时滞，训练、验证、测试按时间划分为 60%、20%、20%；未查看测试段指标。
选段只在训练区间进行，模型在原始连续时间轴上取训练行，不拼接片段重新辨识。

| 策略 | 实际训练行数 | 验证自由仿真 FIT | 验证一步预测 FIT | 稳定 |
|---|---:|---:|---:|---|
| 全量训练 | 1195 | 70.4834 | 96.9428 | True |
| D-最优选段训练 | 930 | 72.3561 | 96.9608 | True |

## 执行参数

选段请求与候选范围（stop_index_exclusive 不含端点；窗口为自适应基准长度）：
```json
{
  "selection_parameters": {
    "window": 60,
    "budget": 8,
    "window_size": 60,
    "max_segments": 8,
    "na": 2,
    "nb": 2,
    "nk": 0,
    "train_ratio": 0.6,
    "selection_mode": "ensemble",
    "standardize": true,
    "quality_weighting": true,
    "adaptive_windows": true,
    "temporal_coverage_bins": 0,
    "history_guard": 4
  },
  "selection_training_range": {
    "start_index": 4,
    "stop_index_exclusive": 1195
  }
}
```
ARX 请求参数：
```json
{
  "model_type": "ARX",
  "na": 2,
  "nb": {
    "u1": 2,
    "u2": 2,
    "u3": 2
  },
  "delays": {
    "u1": 0,
    "u2": 0,
    "u3": 0
  },
  "train_ratio": 0.6,
  "validation_ratio": 0.2,
  "evaluate_test": false,
  "estimator": "ols",
  "fit_intercept": true,
  "standardize": true,
  "initialization_policy": "fixed",
  "history_guard": 2,
  "require_stable": true
}
```
后端返回的有效模型结构与实际截距（未返回的字段保留 null，不根据请求补造）：
```json
[
  {
    "strategy": "全量训练",
    "model_structure": {
      "model_type": "ARX",
      "simulation_horizons": [
        1,
        16,
        64,
        0
      ],
      "simulation_max_nfev": 150,
      "regularization_kernel": "identity",
      "kernel_decay": 0.9,
      "initialization_policy": "fixed",
      "initialization_window": 32,
      "input_columns": [
        "u1",
        "u2",
        "u3"
      ],
      "output_column": "y",
      "na": 2,
      "nb": {
        "u1": 2,
        "u2": 2,
        "u3": 2
      },
      "delays": {
        "u1": 0,
        "u2": 0,
        "u3": 0
      },
      "estimator": "ols",
      "fit_intercept": true,
      "standardize": true,
      "history_guard": 2,
      "ridge_alpha": null,
      "parameter_count": 8
    },
    "intercept": 0.0028799127176075824
  },
  {
    "strategy": "D-最优选段训练",
    "model_structure": {
      "model_type": "ARX",
      "simulation_horizons": [
        1,
        16,
        64,
        0
      ],
      "simulation_max_nfev": 150,
      "regularization_kernel": "identity",
      "kernel_decay": 0.9,
      "initialization_policy": "fixed",
      "initialization_window": 32,
      "input_columns": [
        "u1",
        "u2",
        "u3"
      ],
      "output_column": "y",
      "na": 2,
      "nb": {
        "u1": 2,
        "u2": 2,
        "u3": 2
      },
      "delays": {
        "u1": 0,
        "u2": 0,
        "u3": 0
      },
      "estimator": "ols",
      "fit_intercept": true,
      "standardize": true,
      "history_guard": 2,
      "ridge_alpha": null,
      "parameter_count": 8
    },
    "intercept": 0.00169503744294176
  }
]
```
模型 preprocessing 原始结果保存在 comparison.json 与 manifest.json 的 comparison 中。
本流程接口未提供可靠的后端部署版本或 commit，未推断运行实例版本。

## 诊断依据

```json
{
  "candidate_count": 574,
  "gated_count": 570,
  "selected_count": 8,
  "selected_rows": 930,
  "coverage_ratio": 0.7808564231738035,
  "baseline_log_det": 44.562764665147114,
  "selected_log_det": 43.4598961207433,
  "information_retention": 0.9928887036483188,
  "evaluated_candidates": 1970,
  "naive_candidate_evaluations": 4532,
  "lazy_speedup": 2.300507614213198,
  "stopped_reason": "budget_reached",
  "budget_advisory": null,
  "condition_number": 1371.939039704202,
  "excitation_satisfied": true,
  "persistent_excitation_order": {
    "u1": 6,
    "u2": 6,
    "u3": 6
  },
  "required_excitation_order": {
    "u1": 4,
    "u2": 4,
    "u3": 4
  },
  "rejection_counts": {
    "steady_state_segment": 4
  },
  "noise_sigma": 0.04511900256771131,
  "model_count": 3,
  "criterion": "mean_dimension_normalized_logdet",
  "retention_definition": "regularized_logdet_gain_ratio"
}
```

共线性诊断见 04_collinearity.json（单输入时不调用）；质量画像见 03_profile.json。
以上表格字段直接来自 06_baseline.json 与 07_selected_model.json 的 data.validation 和 data.training_rows，完整标识见 comparison.json。

## 使用边界

本次按用户明确参数执行时滞补偿，随后以 nk=0 建模，避免重复补偿；未执行清洗、变量删除或 Optuna 闭环寻优。给定时滞不是本次恢复的真值。
质量加权参与数据选段；两组 ARX 均采用等权 OLS，不将选段权重只用于优选模型。
selected.csv 为交付子集，非连续片段不能当作连续时间序列拼接训练；复现实验请使用 model-source.csv 与 manifest.json 内的原始行下标。
稳定或高 FIT 不等于可直接投入生产。低分、不利结果与预算提示均保留；真实应用还需工艺先验和外部验证。
本报告由确定性脚本生成，未调用语言模型生成指标。
