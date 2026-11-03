#!/usr/bin/env python3
"""Local IndusOpt API adapter. Python 3.11+, standard library only."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


TRAIN_RATIO = 0.6


class SkillError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SkillError("API 重定向已停止；请检查本地服务地址。")


def save(path, value):
    Path(path).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_selection(data):
    indices = data.get("selected_indices", [])
    expected = (data.get("selection") or {}).get("selected_rows")
    if not indices or len(indices) != expected or len(set(indices)) != len(indices):
        raise SkillError(
            "EMPTY_OR_TRUNCATED_SELECTION：选段为空或下标不完整，停止建模与导出；不要把空列表传给 ARX。"
        )
    if any(type(i) is not int or i < 0 for i in indices):
        raise SkillError("INVALID_SELECTION：下标必须为非负整数。")
    return sorted(indices)


def contained(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise SkillError("导出产物不存在或越出指定 artifact-root。")
    return path


class API:
    def __init__(self, base, timeout, out):
        parsed = urlparse(base)
        if parsed.scheme not in ("http", "https") or parsed.hostname not in (
            "localhost",
            "127.0.0.1",
            "::1",
        ):
            raise SkillError(
                "此适配器仅连接本机 IndusOpt；base-url 必须为 loopback HTTP(S) 地址。"
            )
        if (
            parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path.rstrip("/") != "/api/v1"
        ):
            raise SkillError(
                "base-url 格式应为 http://127.0.0.1:端口/api/v1，不含凭据。"
            )
        self.base, self.timeout, self.out = base.rstrip("/"), timeout, out
        self.opener = build_opener(NoRedirect())
        self.log = []

    def request(self, name, path, payload=None, raw=None, content_type=None):
        body = (
            raw
            if raw is not None
            else (json.dumps(payload).encode() if payload is not None else None)
        )
        headers = (
            {"Content-Type": content_type or "application/json"}
            if body is not None
            else {}
        )
        entry = {
            "step": name,
            "method": "POST" if body is not None else "GET",
            "path": path,
            "parameters": payload,
            "at_utc": datetime.now(timezone.utc).isoformat(),
        }
        self.log.append(entry)
        save(self.out / "requests.json", self.log)
        try:
            with self.opener.open(
                Request(self.base + path, data=body, headers=headers),
                timeout=self.timeout,
            ) as response:
                value = json.load(response)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            (self.out / f"{name}.error.txt").write_text(detail, encoding="utf-8")
            raise SkillError(
                f"{name}: HTTP {exc.code}；服务端错误已保存。不自动重试写请求。"
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise SkillError(
                f"{name}: 连接失败或超时；服务端可能仍在执行，请核查运行记录后再决定是否重试。{exc}"
            ) from exc
        save(self.out / f"{name}.json", value)
        if value.get("success") is not True or not isinstance(value.get("data"), dict):
            raise SkillError(f"{name}: 非预期响应，详见原始 JSON。")
        data = value["data"]
        task = data.get("task") or data.get("parse_task")
        if task and task.get("status") != "succeeded":
            raise SkillError(
                f"{name}: 状态 {task.get('status')}，本同步适配器停止，保留任务 ID 供后续查询。"
            )
        return data

    def download(self, dataset, version, destination):
        path = f"/datasets/{uuid.UUID(dataset)}/download?" + urlencode(
            {"version_id": str(uuid.UUID(version))}
        )
        try:
            with self.opener.open(self.base + path, timeout=self.timeout) as response:
                destination.write_bytes(response.read())
        except (HTTPError, URLError, OSError) as exc:
            raise SkillError(f"下载指定版本失败：{exc}") from exc


def validate_csv(path, time_column, inputs, output):
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        if len(fields) != len(set(fields)):
            raise SkillError("CSV 存在重复列名。")
        roles = [time_column, *inputs, output]
        if len(roles) != len(set(roles)) or not set(roles) <= set(fields):
            raise SkillError("时间、输入、输出列必须存在且互不重复。")
        previous = None
        count = 0
        for row in reader:
            if None in row or any(v is None for v in row.values()):
                raise SkillError("CSV 行列数不一致。")
            try:
                instant = datetime.fromisoformat(
                    row[time_column].replace("Z", "+00:00")
                )
                if previous is not None and instant <= previous:
                    raise SkillError(
                        "时间戳必须严格递增；先在主项目规整重复或乱序记录。"
                    )
                previous = instant
            except (ValueError, TypeError) as exc:
                raise SkillError("需要一致的 ISO 时间戳；先在主项目规整数据。") from exc
            count += 1
        if count < 100:
            raise SkillError(
                "当前快捷流程至少需要 100 行；不足时停止，不放宽质量阈值。"
            )
    return count


def selection_training_range(n_rows, na, nb, window):
    """Match the backend's nk=0 ensemble, including (1, 1) and (4, 3)."""
    history = max(na, nb - 1, 4)
    train_stop = int(n_rows * TRAIN_RATIO) - history
    if n_rows < 100 or train_stop <= history + window:
        raise SkillError(
            "INSUFFICIENT_ROWS：补偿后样本或 ensemble 训练区间不足；"
            f"样本={n_rows}，历史/guard={history}，可用回归行上限={train_stop - history}，"
            f"要求严格大于窗口={window}。请核对时滞、阶次与窗口。"
        )
    return {"start_index": history, "stop_index_exclusive": train_stop}


def model_diagnostics(model):
    """Copy exposed backend evidence; absent fields remain null, never a pass."""
    preprocessing = model.get("preprocessing") or {}
    validation = model.get("validation") or {}
    return {
        "model_id": model.get("model_id"),
        "processing_run_id": model.get("processing_run_id"),
        "training_input_support": preprocessing.get("training_input_support"),
        "input_support_provenance": preprocessing.get("input_support_provenance"),
        "residual_diagnostics": model.get("residual_diagnostics"),
        "validation": {
            key: validation.get(key) for key in (
                "partition", "n_samples", "input_support", "excitation_shortfall",
                "residual_whiteness_ratio", "input_residual_correlations",
                "input_residual_test", "simulation_status", "simulation_error_code",
            )
        },
    }


def diagnostic_summary(comparison, full, selected):
    """Describe backend judgments and numeric changes without new acceptance gates."""
    missing = []
    for name, diagnostics in (("full", full), ("selected", selected)):
        validation = diagnostics["validation"]
        support = validation["input_support"] or {}
        test = validation["input_residual_test"] or {}
        if not diagnostics["training_input_support"]:
            missing.append(f"{name}.preprocessing.training_input_support")
        if not diagnostics["residual_diagnostics"]:
            missing.append(f"{name}.residual_diagnostics")
        for key in ("excitation_shortfall", "residual_whiteness_ratio", "input_residual_correlations", "simulation_status"):
            if validation[key] is None:
                missing.append(f"{name}.validation.{key}")
        if support.get("status") not in (
            "within_observed_input_ranges", "extrapolation", "unsupported", "unavailable",
        ):
            missing.append(f"{name}.validation.input_support.status")
        if test.get("status") != "evaluated" or not isinstance(test.get("rejected_channels"), list):
            missing.append(f"{name}.validation.input_residual_test (not evaluated)")

    full_validation, selected_validation = full["validation"], selected["validation"]
    full_support = full_validation["input_support"] or {}
    selected_support = selected_validation["input_support"] or {}
    full_test = full_validation["input_residual_test"] or {}
    selected_test = selected_validation["input_residual_test"] or {}
    full_interval = (full_validation["partition"], full_validation["n_samples"], full_support.get("start"), full_support.get("stop"))
    selected_interval = (selected_validation["partition"], selected_validation["n_samples"], selected_support.get("start"), selected_support.get("stop"))
    same_interval = all(value is not None for value in (*full_interval, *selected_interval)) and full_interval == selected_interval
    same_test_policy = all(full_test.get(key) is not None and full_test.get(key) == selected_test.get(key) for key in ("method", "alpha"))
    if not same_interval:
        missing.append("matching validation interval")
    if not same_test_policy:
        missing.append("matching residual-input test method/alpha")

    changes, review = [], []
    metrics_nonworse = True
    metric_values = {}
    for key, label, larger_better in (
        ("validation_one_step_fit", "验证一步预测 FIT", True),
        ("validation_free_run_fit", "验证自由仿真 FIT", True),
        ("validation_free_run_rmse", "验证自由仿真 RMSE", False),
    ):
        left, right = comparison[0][key], comparison[1][key]
        metric_values[key] = {"full": left, "selected": right}
        if not all(type(value) in (int, float) and math.isfinite(value) for value in (left, right)):
            missing.append(key)
            metrics_nonworse = False
        elif (right < left if larger_better else right > left):
            metrics_nonworse = False
            review.append(f"{label}向不利方向变化（描述性对照，未做显著性判断）。")

    rows_reduced = comparison[1]["training_rows"] < comparison[0]["training_rows"]
    stable = comparison[0]["stable"] is True and comparison[1]["stable"] is True
    if comparison[1]["stable"] is False:
        review.append("优选模型的 backend 稳定性判断为 false。")
    elif not stable:
        missing.append("both model stability judgments")
    status = selected_support.get("status")
    if status in ("extrapolation", "unsupported", "unavailable"):
        review.append(f"优选数据的输入支持存在 backend 风险：{status}；不能仅凭 FIT 判断数据优选有效。")
    if selected_validation["excitation_shortfall"]:
        review.append("backend 报告优选训练输入的持续激励阶次不足；这是诊断提示，不新增阻断门禁。")
    if selected_validation["simulation_status"] not in (None, "succeeded"):
        review.append("优选模型的验证仿真未成功。")
    rejected = selected_test.get("rejected_channels") or []
    if rejected:
        review.append("backend 残差与输入关联检验仍拒绝通道 " + ", ".join(rejected) + "；相关结构仍存在，不能仅根据 FIT 判断数据优选有效，也不能据此认定因果或确定缺失动态。")
    left, right = full_validation["residual_whiteness_ratio"], selected_validation["residual_whiteness_ratio"]
    if same_interval and all(type(value) in (int, float) and math.isfinite(value) for value in (left, right)):
        changes.append(f"验证残差白度比例：{left} → {right}（描述性数值，无新增通过阈值）。")
        if right < left:
            review.append("验证残差白度比例下降（描述性变化，不是新增统计失败门槛）。")
    if not rows_reduced:
        review.append("本次未减少实际训练样本，不能声称以更少数据保持性能。")

    if review:
        assessment = "manual_review"
        conclusion = "验证指标" + ("保持或改善。" if metrics_nonworse and same_interval else "需结合原始数值复核。") + " ".join(review) + "建议人工复核后再作为最终建模数据。"
    elif missing:
        assessment = "insufficient_evidence"
        conclusion = "诊断证据未返回、未形成正式判断或评价条件不可比，不能仅凭 FIT 宣称输入信息保持或残差未恶化；需人工复核。"
    else:
        assessment = "no_new_backend_warnings"
        conclusion = "本次减少训练样本，模型稳定，验证指标保持或改善；backend 未报告优选输入支持或残差输入检验风险。白度与 ACF 仅作描述性对照，不能证明全部工业信息保留或模型可投产。"
    if missing and assessment == "manual_review":
        conclusion += "同时有部分诊断证据缺失或不可比。"
    return {
        "generated_by": "skill",
        "assessment": assessment,
        "samples": {"full": comparison[0]["training_rows"], "selected": comparison[1]["training_rows"], "reduced": rows_reduced},
        "validation_metrics": metric_values,
        "both_models_stable": stable,
        "same_validation_interval": same_interval,
        "same_residual_test_policy": same_test_policy,
        "input_support_status": {"full": full_support.get("status"), "selected": status},
        "new_input_support_warning_channels": {
            key: sorted(set(selected_support.get(key) or []) - set(full_support.get(key) or []))
            if same_interval and isinstance(full_support.get(key), list) and isinstance(selected_support.get(key), list) else None
            for key in ("unsupported_constant_inputs", "extrapolated_inputs", "unavailable_inputs")
        },
        "new_excitation_shortfall_channels": sorted(set(selected_validation["excitation_shortfall"]) - set(full_validation["excitation_shortfall"]))
        if isinstance(full_validation["excitation_shortfall"], dict) and isinstance(selected_validation["excitation_shortfall"], dict) else None,
        "new_residual_rejected_channels": sorted(set(rejected) - set(full_test.get("rejected_channels") or [])) if same_interval and same_test_policy else None,
        "descriptive_changes": changes,
        "review_reasons": review,
        "missing_or_incomparable_evidence": missing,
        "conclusion": conclusion,
    }


def diagnostics_report(full, selected, summary):
    def cell(value):
        if value is None:
            return "未返回"
        if type(value) is float:
            return f"{value:.4f}" if math.isfinite(value) else "不可用"
        return json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)

    full_support, selected_support = full["training_input_support"] or {}, selected["training_input_support"] or {}
    lines = [
        "", "## 数据充分性与残差诊断", "", "### 输入激励 / Input Support", "",
        "以下训练支持范围来自 preprocessing.training_input_support，仅使用正权重训练回归行实际用到的输入及其历史。samples 是去重后的输入时间点数，不等于模型训练行数。", "",
        "| 输入 | 全量训练范围 [min,max] | 优选训练范围 [min,max] | 全量 std / samples / status / constant | 优选 std / samples / status / constant |",
        "|---|---|---|---|---|",
    ]
    for column in sorted(set(full_support) | set(selected_support)):
        left, right = full_support.get(column) or {}, selected_support.get(column) or {}
        ranges = [f"[{cell(item.get('minimum'))}, {cell(item.get('maximum'))}]" for item in (left, right)]
        details = [" / ".join(cell(item.get(key)) for key in ("std", "samples", "status", "constant")) for item in (left, right)]
        lines.append(f"| {column} | {ranges[0]} | {ranges[1]} | {details[0]} | {details[1]} |")
    for label, diagnostics in (("全量训练", full), ("优选训练", selected)):
        validation = diagnostics["validation"]
        lines += ["", f"**{label}：验证区间输入支持（validation.input_support）**", "```json", json.dumps(validation["input_support"], ensure_ascii=False, indent=2), "```", f"训练输入激励不足项（validation.excitation_shortfall，实际计算层为训练行）：{cell(validation['excitation_shortfall'])}。"]
    lines += [
        "", "对比：上述范围、覆盖比例和状态均采用 backend 原值，不设置覆盖率阈值。空 excitation_shortfall 只表示未报告不足，ARX API 未返回完整 PE 阶次；不能从选段的全局激励结果补造两组模型的阶次。", "",
        "### 残差诊断", "",
        "顶层 residual_diagnostics 是训练集一步预测残差 ACF；优选训练行可能不连续，不能当作连续验证段白噪声检验。validation 中的白度、相关序列及 Holm/Bartlett 检验属于验证集一步预测残差，free_run_rmse 属于验证自由仿真。当前正式 API 未返回 Ljung–Box 结果或白度 pass/fail。", "",
        "| 诊断 | 全量模型 | 优选模型 |", "|---|---|---|",
        f"| 训练残差 ACF 置信带 | {cell((full['residual_diagnostics'] or {}).get('confidence_interval'))} | {cell((selected['residual_diagnostics'] or {}).get('confidence_interval'))} |",
    ]
    for key, label in (("residual_whiteness_ratio", "验证残差白度比例（描述性）"), ("simulation_status", "验证仿真状态")):
        lines.append(f"| {label} | {cell(full['validation'][key])} | {cell(selected['validation'][key])} |")
    for key in ("method", "status", "alpha", "rejected_channels"):
        lines.append(f"| 验证残差输入检验 {key} | {cell((full['validation']['input_residual_test'] or {}).get(key))} | {cell((selected['validation']['input_residual_test'] or {}).get(key))} |")
    lines += [
        "", "对比：" + " ".join(summary["descriptive_changes"]),
        "新增被拒绝通道：" + cell(summary["new_residual_rejected_channels"]) + "。无新增警告不代表已有警告消失；检验不显著也不能证明独立性或白噪声。", "",
        "完整训练 ACF、验证输入残差相关序列、各滞后的检验统计量及支持结构保存在 diagnostics-comparison.json 和 manifest.json，不删减为单一布尔值。", "",
        "### 综合结论", "",
        "以下 summary 由 Skill 整理 backend 真实证据生成，不是 backend 新增的统计检验、硬门禁或评分。",
        summary["conclusion"],
        "缺失或不可比证据：" + cell(summary["missing_or_incomparable_evidence"]) + "。",
        "manifest.status=succeeded 只表示执行与交付完成，与诊断 assessment 分开；不表示数据无风险或可投产。", "",
    ]
    return lines


def analyze(args, api, out):
    for name, value, lower, upper in (
        ("na", args.na, 1, 20),
        ("nb", args.nb, 1, 20),
        ("window", args.window, 5, None),
        ("budget", args.budget, 1, 100),
    ):
        if type(value) is not int or value < lower or (upper is not None and value > upper):
            raise SkillError(f"INVALID_PARAMETER：{name} 超出允许范围（最小 {lower}，最大 {upper}）。")
    inputs = args.inputs.split(",")
    delays = [int(v) for v in args.delays.split(",")]
    if len(delays) != len(inputs) or any(v < 0 or v > 1000 for v in delays):
        raise SkillError("每个输入需一个 0–1000 的显式时滞，顺序与 inputs 一致。")
    csv_path = Path(args.csv).resolve()
    n_rows = validate_csv(csv_path, args.time_column, inputs, args.output_column)
    aligned_rows = n_rows - max(delays)
    selection_training_range(aligned_rows, args.na, args.nb, args.window)
    source_sha = digest(csv_path)
    api.request("00_health", "/health/live")
    boundary = "IndusOptSkill" + uuid.uuid4().hex
    raw = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="skill-input.csv"\r\nContent-Type: text/csv\r\n\r\n'.encode()
        + csv_path.read_bytes()
        + f"\r\n--{boundary}--\r\n".encode()
    )
    uploaded = api.request(
        "01_upload",
        "/datasets/upload",
        raw=raw,
        content_type=f"multipart/form-data; boundary={boundary}",
    )
    dataset = uploaded["dataset"]["id"]
    if uploaded.get("deduplicated"):
        existing = api.request("02_existing", f"/datasets/{dataset}")
        if (
            existing.get("time_column") != args.time_column
            or existing.get("input_columns") != inputs
            or existing.get("output_column") != args.output_column
        ):
            raise SkillError(
                "DEDUPLICATED_ROLE_CONFLICT：已有相同文件的列角色与本次不一致；停止，不修改已有配置。"
            )
        versions = api.request("02_versions", f"/datasets/{dataset}/versions")
        roots = [
            node["id"]
            for node in versions["nodes"]
            if node.get("parent_version_id") is None
        ]
        if len(roots) != 1:
            raise SkillError("SOURCE_VERSION_AMBIGUOUS：无法唯一定位原始版本。")
        version = roots[0]
    else:
        config = api.request(
            "02_config",
            f"/datasets/{dataset}/config",
            {
                "time_column": args.time_column,
                "input_columns": inputs,
                "output_column": args.output_column,
            },
        )
        version = config["dataset"]["latest_version_id"]
    common = {
        "dataset_id": dataset,
        "version_id": version,
        "input_columns": inputs,
        "output_column": args.output_column,
    }
    api.download(dataset, version, out / "source.csv")
    if digest(out / "source.csv") != source_sha:
        raise SkillError("SOURCE_VERSION_MISMATCH：指定版本与输入文件不一致，停止。")
    profile = api.request(
        "03_profile",
        f"/datasets/{dataset}/profile?" + urlencode({"version_id": version}),
    )
    if profile.get("irregular_sampling_rate", 0) > 0:
        raise SkillError(
            "IRREGULAR_SAMPLING：先在主项目完成时间规整，再使用此快捷建模流程。"
        )
    original_version = version
    if not args.confirm_lags:
        save(
            out / "pending-confirmation.json",
            {
                "status": "waiting_confirmation",
                "source_version_id": version,
                "lag_map": dict(zip(inputs, delays)),
                "effect": "创建时滞补偿派生版本并删除无法对齐的前端边界行；不覆盖源文件。",
                "next": "用户认可具体 lag_map 后，以新 out 目录和 --confirm-lags 再运行。",
            },
        )
        return "waiting_confirmation"
    if max(delays) == 0:
        raise SkillError(
            "ZERO_LAG_BACKEND_LIMIT：当前后端拒绝全零补偿，又要求补偿血缘；不能伪造非零时滞绕过。质量画像已保存。"
        )
    aligned = api.request(
        "03b_lag_apply",
        "/preprocessing/delay/apply",
        {
            "version_id": version,
            "dataset_id": dataset,
            "lag_map": dict(zip(inputs, delays)),
            "user_confirmed": True,
            "recommendation_source": "manual",
        },
    )
    version = aligned["result_version_id"]
    common["version_id"] = version
    api.download(dataset, version, out / "model-source.csv")
    model_rows = validate_csv(
        out / "model-source.csv", args.time_column, inputs, args.output_column
    )
    selection_range = selection_training_range(model_rows, args.na, args.nb, args.window)
    selection_parameters = {
        "window_size": args.window,
        "max_segments": args.budget,
        "na": args.na,
        "nb": args.nb,
        "nk": 0,
        "train_ratio": TRAIN_RATIO,
        "selection_mode": "ensemble",
        "standardize": True,
        "quality_weighting": True,
        "adaptive_windows": True,
        "temporal_coverage_bins": 0,
        "history_guard": selection_range["start_index"],
    }
    if len(inputs) >= 2:
        api.request("04_collinearity", "/preprocessing/collinearity", common)
    segment = api.request(
        "05_selection",
        "/preprocessing/segment",
        {**common, **selection_parameters},
    )
    indices = validate_selection(segment)
    structure = {
        "model_type": "ARX",
        "na": args.na,
        "nb": dict.fromkeys(inputs, args.nb),
        "delays": dict.fromkeys(inputs, 0),
        "train_ratio": TRAIN_RATIO,
        "validation_ratio": 0.2,
        "evaluate_test": False,
        "estimator": "ols",
        "fit_intercept": True,
        "standardize": True,
        "initialization_policy": "fixed",
        "history_guard": max(args.na, args.nb - 1),
        "require_stable": True,
    }
    # Same model structure, same chronological split; only the training-row subset changes.
    baseline = api.request("06_baseline", "/modeling/arx/fit", {**common, **structure})
    selected = api.request(
        "07_selected_model",
        "/modeling/arx/fit",
        {**common, **structure, "training_sample_indices": indices},
    )
    if selected["training_rows"] != len(indices):
        raise SkillError(
            "TRAINING_ROWS_MISMATCH：模型实际训练行数与选段不符，停止导出。"
        )
    exported = api.request(
        "08_export", "/delivery/export", {**common, "sample_indices": indices}
    )
    root = Path(args.artifact_root)
    server_csv = contained(root, exported["csv_uri"])
    server_manifest = contained(root, exported["manifest_uri"])
    manifest = json.loads(server_manifest.read_text(encoding="utf-8"))
    if (
        manifest["version_id"] != version
        or manifest["exported_rows"] != len(indices)
        or exported["exported_rows"] != len(indices)
    ):
        raise SkillError("EXPORT_MISMATCH：导出来源或行数不一致。")
    csv_bytes = server_csv.read_bytes()
    reader = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8")))
    export_rows = list(reader)
    if reader.fieldnames != exported["columns"] or len(export_rows) != len(indices):
        raise SkillError("EXPORT_CONTENT_MISMATCH：导出 CSV 列名或实际行数不一致。")
    with (out / "model-source.csv").open(encoding="utf-8-sig", newline="") as source:
        model_source = list(csv.DictReader(source))
    for index, row in zip(indices, export_rows):
        expected = model_source[index]
        if datetime.fromisoformat(row["timestamp"]) != datetime.fromisoformat(
            expected[args.time_column].replace("Z", "+00:00")
        ):
            raise SkillError("EXPORT_TIME_MISMATCH：导出时间与原始下标不一致。")
        for column in [*inputs, args.output_column]:
            try:
                equal = math.isclose(
                    float(row[column]),
                    float(expected[column]),
                    rel_tol=1e-10,
                    abs_tol=1e-10,
                )
            except ValueError:
                equal = row[column] == expected[column]
            if not equal:
                raise SkillError("EXPORT_VALUE_MISMATCH：导出值与指定版本不一致。")
    (out / "selected.csv").write_bytes(csv_bytes)
    (out / "server-manifest.json").write_bytes(server_manifest.read_bytes())
    comparison = []
    for name, model in [("全量训练", baseline), ("D-最优选段训练", selected)]:
        validation = model.get("validation") or {}
        comparison.append(
            {
                "strategy": name,
                "training_rows": model["training_rows"],
                "validation_free_run_fit": validation.get("free_run_fit"),
                "validation_one_step_fit": validation.get("one_step_fit"),
                "validation_free_run_rmse": validation.get("free_run_rmse"),
                "stable": validation.get("stable"),
                "model_id": model["model_id"],
                "processing_run_id": model["processing_run_id"],
                "model_structure": model.get("model_structure"),
                "intercept": model.get("intercept"),
                "preprocessing": model.get("preprocessing"),
            }
        )
    save(out / "comparison.json", comparison)
    full_diagnostics = model_diagnostics(baseline)
    selected_diagnostics = model_diagnostics(selected)
    summary = diagnostic_summary(comparison, full_diagnostics, selected_diagnostics)
    diagnostic_comparison = {
        "full_model_diagnostics": full_diagnostics,
        "selected_model_diagnostics": selected_diagnostics,
        "diagnostic_summary": summary,
    }
    save(out / "diagnostics-comparison.json", diagnostic_comparison)
    success_manifest = {
            "status": "succeeded",
            "data_kind": args.data_kind,
            "dataset_id": dataset,
            "version_id": version,
            "original_version_id": original_version,
            "confirmed_lag_map": dict(zip(inputs, delays)),
            "model_source_sha256": digest(out / "model-source.csv"),
            "source_sha256": source_sha,
            "selected_sha256": digest(out / "selected.csv"),
            "source_rows": n_rows,
            "selected_sample_indices": indices,
            "selection_task_id": segment["task"]["id"],
            "selection_parameters": {
                "window": args.window, "budget": args.budget, **selection_parameters,
            },
            "selection_training_range": selection_range,
            "model_parameters": structure,
            "comparison": comparison,
            **diagnostic_comparison,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
        }
    lines = [
        "# 工业建模数据优选与诊断报告",
        "",
        f"数据性质：{args.data_kind}。",
        f"数据版本：`{version}`。原始数据校验值：`{source_sha}`。",
        "",
        "本次比较采用固定 ARX 结构与显式时滞，训练、验证、测试按时间划分为 60%、20%、20%；未查看测试段指标。",
        "选段只在训练区间进行，模型在原始连续时间轴上取训练行，不拼接片段重新辨识。",
        "",
        "| 策略 | 实际训练行数 | 验证自由仿真 FIT | 验证一步预测 FIT | 验证自由仿真 RMSE | 稳定 |",
        "|---|---:|---:|---:|---:|---|",
    ]

    def fmt(v):
        return (
            "不可用"
            if v is None or not isinstance(v, (int, float)) or not math.isfinite(v)
            else f"{v:.4f}"
        )

    for row in comparison:
        lines.append(
            f"| {row['strategy']} | {row['training_rows']} | {fmt(row['validation_free_run_fit'])} | {fmt(row['validation_one_step_fit'])} | {fmt(row['validation_free_run_rmse'])} | {row['stable']} |"
        )
    lines += diagnostics_report(full_diagnostics, selected_diagnostics, summary)
    lines += [
        "",
        "## 执行参数",
        "",
        "选段请求与候选范围（stop_index_exclusive 不含端点；窗口为自适应基准长度）：",
        "```json",
        json.dumps({"selection_parameters": success_manifest["selection_parameters"],
                    "selection_training_range": selection_range}, ensure_ascii=False, indent=2),
        "```",
        "ARX 请求参数：",
        "```json",
        json.dumps(structure, ensure_ascii=False, indent=2),
        "```",
        "后端返回的有效模型结构与实际截距（未返回的字段保留 null，不根据请求补造）：",
        "```json",
        json.dumps([{key: row[key] for key in ("strategy", "model_structure", "intercept")}
                    for row in comparison], ensure_ascii=False, indent=2),
        "```",
        "模型 preprocessing 原始结果保存在 comparison.json 与 manifest.json 的 comparison 中。",
        "本流程接口未提供可靠的后端部署版本或 commit，未推断运行实例版本。",
        "",
        "## 诊断依据",
        "",
        "```json",
        json.dumps(segment["selection"], ensure_ascii=False, indent=2),
        "```",
        "",
        "共线性诊断见 04_collinearity.json（单输入时不调用）；质量画像见 03_profile.json。",
        "以上表格字段直接来自 06_baseline.json 与 07_selected_model.json 的 data.validation 和 data.training_rows，完整标识见 comparison.json。",
        "",
        "## 使用边界",
        "",
        "本次按用户明确参数执行时滞补偿，随后以 nk=0 建模，避免重复补偿；未执行清洗、变量删除或 Optuna 闭环寻优。给定时滞不是本次恢复的真值。",
        "质量加权参与数据选段；两组 ARX 均采用等权 OLS，不将选段权重只用于优选模型。",
        "selected.csv 为交付子集，非连续片段不能当作连续时间序列拼接训练；复现实验请使用 model-source.csv 与 manifest.json 内的原始行下标。",
        "稳定或高 FIT 不等于可直接投入生产。低分、不利结果与预算提示均保留；真实应用还需工艺先验和外部验证。",
        "本报告由确定性脚本生成，未调用语言模型生成指标。",
        "",
    ]
    (out / "report.md").write_text("\n".join(lines), encoding="utf-8")
    # Publish success only after every required deliverable has been written.
    pending_manifest = out / "manifest.pending.json"
    save(pending_manifest, success_manifest)
    pending_manifest.replace(out / "manifest.json")
    return "succeeded"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:18000/api/v1")
    parser.add_argument("--timeout", type=int, default=120)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("analyze", help="上传 CSV 并执行固定结构诊断、优选、评价与导出")
    p.add_argument("--csv", required=True)
    p.add_argument("--time-column", required=True)
    p.add_argument("--inputs", required=True)
    p.add_argument("--output-column", required=True)
    p.add_argument(
        "--delays", required=True, help="与 inputs 同序的逗号分隔 nk，必须明确给出"
    )
    p.add_argument(
        "--confirm-lags", action="store_true", help="仅在用户已确认具体 lag_map 后使用"
    )
    p.add_argument("--artifact-root", required=True, help="同一后端使用的本机产物目录")
    p.add_argument(
        "--data-kind", choices=["synthetic", "industrial", "unknown"], default="unknown"
    )
    p.add_argument("--na", type=int, default=2)
    p.add_argument("--nb", type=int, default=2)
    p.add_argument("--window", type=int, default=60)
    p.add_argument("--budget", type=int, default=8)
    p.add_argument("--out", required=True)
    p = sub.add_parser("generate-example", help="调用项目仿真器，保存 CSV 与独立真值")
    p.add_argument(
        "--scenario", choices=["S1", "S2", "S3", "S4", "S5", "S6"], default="S6"
    )
    p.add_argument("--samples", type=int, default=2000)
    p.add_argument("--seed", type=int, default=20260913)
    p.add_argument("--out", required=True)
    p = sub.add_parser("benchmark", help="调用产品基准，保留全部有利与不利结果")
    p.add_argument("--samples", type=int, default=2000)
    p.add_argument("--seed", type=int, default=20260913)
    p.add_argument("--out", required=True)
    args = parser.parse_args()
    out = Path(args.out).resolve()
    if out.exists():
        parser.error("out 必须为尚不存在的目录，以防覆盖或混入旧结果。")
    out.mkdir(parents=True)
    try:
        api = API(args.base_url, args.timeout, out)
        status = "succeeded"
        if args.command == "analyze":
            status = analyze(args, api, out)
        elif args.command == "generate-example":
            data = api.request(
                "simulation",
                "/simulation/generate",
                {
                    "scenario": args.scenario,
                    "n_steps": args.samples,
                    "input_count": 3,
                    "seed": args.seed,
                    "name": "Skill synthetic example",
                },
            )
            api.download(data["dataset_id"], data["version_id"], out / "input.csv")
            save(
                out / "example.json",
                {
                    "data_kind": "synthetic",
                    "seed": args.seed,
                    "scenario": args.scenario,
                    "sha256": digest(out / "input.csv"),
                    "note": "真值仅用于事后审计，不作为 analyze 输入。",
                },
            )
        else:
            api.request(
                "benchmark",
                "/benchmark/run",
                {
                    "scenarios": ["S3", "S6"],
                    "n_samples": args.samples,
                    "seed": args.seed,
                },
            )
        print(json.dumps({"status": status, "output": str(out)}, ensure_ascii=False))
        return 0
    except (SkillError, ValueError, KeyError, OSError) as exc:
        save(
            out / "failure.json",
            {
                "status": "failed",
                "reason": str(exc),
                "note": "可能已有服务端记录；未回滚或自动重试。",
            },
        )
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
