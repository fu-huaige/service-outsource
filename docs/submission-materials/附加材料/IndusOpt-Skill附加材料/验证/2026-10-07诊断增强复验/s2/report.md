# 工业建模数据优选与诊断报告

数据性质：synthetic。
数据版本：`f38d9388-f7dc-4cee-9a6f-2c92bdc7c6b9`。原始数据校验值：`305032b84a4f9cc7b450572ea9d72c020a9a166a97b5171f4a959544f45c4486`。

本次比较采用固定 ARX 结构与显式时滞，训练、验证、测试按时间划分为 60%、20%、20%；未查看测试段指标。
选段只在训练区间进行，模型在原始连续时间轴上取训练行，不拼接片段重新辨识。

| 策略 | 实际训练行数 | 验证自由仿真 FIT | 验证一步预测 FIT | 验证自由仿真 RMSE | 稳定 |
|---|---:|---:|---:|---:|---|
| 全量训练 | 1195 | 70.4834 | 96.9428 | 1.1125 | True |
| D-最优选段训练 | 930 | 72.3561 | 96.9608 | 1.0419 | True |

## 数据充分性与残差诊断

### 输入激励 / Input Support

以下训练支持范围来自 preprocessing.training_input_support，仅使用正权重训练回归行实际用到的输入及其历史。samples 是去重后的输入时间点数，不等于模型训练行数。

| 输入 | 全量训练范围 [min,max] | 优选训练范围 [min,max] | 全量 std / samples / status / constant | 优选 std / samples / status / constant |
|---|---|---|---|---|
| u1 | [-1.3826, 1.4911] | [-1.3826, 1.4911] | 0.8418 / 1196 / available / False | 0.8971 / 936 / available / False |
| u2 | [-1.4675, 1.4483] | [-1.4675, 1.4483] | 0.9095 / 1196 / available / False | 0.9444 / 936 / available / False |
| u3 | [-1.3774, 1.4402] | [-1.3774, 1.4402] | 0.9172 / 1196 / available / False | 0.9526 / 936 / available / False |

**全量训练：验证区间输入支持（validation.input_support）**
```json
{
  "policy_version": "known_input_support_v1",
  "start": 1201,
  "stop": 1597,
  "status": "extrapolation",
  "unsupported_constant_inputs": [],
  "extrapolated_inputs": [
    "u1",
    "u3"
  ],
  "unavailable_inputs": [],
  "evidence": {
    "u1": {
      "constant_in_train": false,
      "outside_train_range_fraction": 0.07556675062972293
    },
    "u2": {
      "constant_in_train": false,
      "outside_train_range_fraction": 0.0
    },
    "u3": {
      "constant_in_train": false,
      "outside_train_range_fraction": 0.05793450881612091
    }
  },
  "coefficient_updates": false,
  "deployment_ready": false
}
```
训练输入激励不足项（validation.excitation_shortfall，实际计算层为训练行）：{}。

**优选训练：验证区间输入支持（validation.input_support）**
```json
{
  "policy_version": "known_input_support_v1",
  "start": 1201,
  "stop": 1597,
  "status": "extrapolation",
  "unsupported_constant_inputs": [],
  "extrapolated_inputs": [
    "u1",
    "u3"
  ],
  "unavailable_inputs": [],
  "evidence": {
    "u1": {
      "constant_in_train": false,
      "outside_train_range_fraction": 0.07556675062972293
    },
    "u2": {
      "constant_in_train": false,
      "outside_train_range_fraction": 0.0
    },
    "u3": {
      "constant_in_train": false,
      "outside_train_range_fraction": 0.05793450881612091
    }
  },
  "coefficient_updates": false,
  "deployment_ready": false
}
```
训练输入激励不足项（validation.excitation_shortfall，实际计算层为训练行）：{}。

对比：上述范围、覆盖比例和状态均采用 backend 原值，不设置覆盖率阈值。空 excitation_shortfall 只表示未报告不足，ARX API 未返回完整 PE 阶次；不能从选段的全局激励结果补造两组模型的阶次。

### 残差诊断

顶层 residual_diagnostics 是训练集一步预测残差 ACF；优选训练行可能不连续，不能当作连续验证段白噪声检验。validation 中的白度、相关序列及 Holm/Bartlett 检验属于验证集一步预测残差，free_run_rmse 属于验证自由仿真。当前正式 API 未返回 Ljung–Box 结果或白度 pass/fail。

| 诊断 | 全量模型 | 优选模型 |
|---|---|---|
| 训练残差 ACF 置信带 | 0.0567 | 0.0643 |
| 验证残差白度比例（描述性） | 0.8500 | 0.8500 |
| 验证仿真状态 | succeeded | succeeded |
| 验证残差输入检验 method | holm_bartlett_v1 | holm_bartlett_v1 |
| 验证残差输入检验 status | evaluated | evaluated |
| 验证残差输入检验 alpha | 0.0500 | 0.0500 |
| 验证残差输入检验 rejected_channels | ["u1", "u2"] | ["u2"] |

对比：验证残差白度比例：0.85 → 0.85（描述性数值，无新增通过阈值）。
新增被拒绝通道：[]。无新增警告不代表已有警告消失；检验不显著也不能证明独立性或白噪声。

完整训练 ACF、验证输入残差相关序列、各滞后的检验统计量及支持结构保存在 diagnostics-comparison.json 和 manifest.json，不删减为单一布尔值。

### 综合结论

以下 summary 由 Skill 整理 backend 真实证据生成，不是 backend 新增的统计检验、硬门禁或评分。
验证指标保持或改善。优选数据的输入支持存在 backend 风险：extrapolation；不能仅凭 FIT 判断数据优选有效。 backend 残差与输入关联检验仍拒绝通道 u2；相关结构仍存在，不能仅根据 FIT 判断数据优选有效，也不能据此认定因果或确定缺失动态。建议人工复核后再作为最终建模数据。
缺失或不可比证据：[]。
manifest.status=succeeded 只表示执行与交付完成，与诊断 assessment 分开；不表示数据无风险或可投产。


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
