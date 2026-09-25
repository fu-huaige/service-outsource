# 工业建模数据优选与诊断报告

数据性质：synthetic。
数据版本：`5eb06366-cdf0-412f-a62f-452eb8578979`。原始数据校验值：`305032b84a4f9cc7b450572ea9d72c020a9a166a97b5171f4a959544f45c4486`。

本次比较采用固定 ARX 结构与显式时滞，训练、验证、测试按时间划分为 60%、20%、20%；未查看测试段指标。
选段只在训练区间进行，模型在原始连续时间轴上取训练行，不拼接片段重新辨识。

| 策略 | 实际训练行数 | 验证自由仿真 FIT | 验证一步预测 FIT | 稳定 |
|---|---:|---:|---:|---|
| 全量训练 | 1195 | 71.3998 | 96.9447 | True |
| D-最优选段训练 | 360 | 73.6591 | 96.9476 | True |

## 诊断依据

```json
{
  "candidate_count": 38,
  "gated_count": 38,
  "selected_count": 8,
  "selected_rows": 360,
  "coverage_ratio": 0.18027040560841262,
  "baseline_log_det": 53.77341344344394,
  "selected_log_det": 42.73240991519332,
  "information_retention": 0.7946754200407424,
  "evaluated_candidates": 195,
  "naive_candidate_evaluations": 276,
  "lazy_speedup": 1.4153846153846155,
  "stopped_reason": "budget_reached",
  "budget_advisory": null,
  "condition_number": 1254.5477718019683,
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
  "rejection_counts": {},
  "noise_sigma": 0.044125916728208876
}
```

共线性诊断见 04_collinearity.json（单输入时不调用）；质量画像见 03_profile.json。
以上表格字段直接来自 06_baseline.json 与 07_selected_model.json 的 data.validation 和 data.training_rows，完整标识见 comparison.json。

## 使用边界

本次按用户明确参数执行时滞补偿，随后以 nk=0 建模，避免重复补偿；未执行清洗、变量删除或 Optuna 闭环寻优。给定时滞不是本次恢复的真值。
selected.csv 为交付子集，非连续片段不能当作连续时间序列拼接训练；复现实验请使用 model-source.csv 与 manifest.json 内的原始行下标。
稳定或高 FIT 不等于可直接投入生产。低分、不利结果与预算提示均保留；真实应用还需工艺先验和外部验证。
本报告由确定性脚本生成，未调用语言模型生成指标。
