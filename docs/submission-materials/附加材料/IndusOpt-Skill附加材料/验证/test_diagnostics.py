"""Replay real S2 responses to verify diagnostic consumption, not algorithms."""

import importlib.util
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "验证/2026-10-07最新版兼容性复验/s2"
spec = importlib.util.spec_from_file_location(
    "diagnostic_adapter", ROOT / "indusopt-data-selection/scripts/indusopt_skill.py"
)
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


class DiagnosticAPI:
    def __init__(self, transform=None):
        self.transform = transform
        self.models = {}

    def request(self, name, path, payload=None, **kwargs):
        data = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))["data"]
        if name in ("06_baseline", "07_selected_model"):
            if self.transform:
                self.transform(name, data)
            self.models[name] = data
        if name == "08_export":
            data.update(csv_uri="selected.csv", manifest_uri="server-manifest.json")
        return data

    def download(self, dataset, version, destination):
        destination.write_bytes((FIXTURES / destination.name).read_bytes())


def clean_diagnostics(name, model):
    support = model["validation"]["input_support"]
    support.update(status="within_observed_input_ranges", extrapolated_inputs=[])
    for evidence in support["evidence"].values():
        evidence["outside_train_range_fraction"] = 0.0
    test = model["validation"]["input_residual_test"]
    test.update(rejected_channels=[], tests=[])


class DiagnosticConsumption(unittest.TestCase):
    def run_replay(self, transform=None):
        api = DiagnosticAPI(transform)
        args = Namespace(
            csv=str(FIXTURES / "source.csv"), time_column="timestamp",
            inputs="u1,u2,u3", output_column="y", delays="1,1,1",
            confirm_lags=True, na=2, nb=2, window=60, budget=8,
            artifact_root=str(FIXTURES), data_kind="synthetic",
        )
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.assertEqual(adapter.analyze(args, api, out), "succeeded")
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            report = (out / "report.md").read_text(encoding="utf-8")
            diagnostics = json.loads((out / "diagnostics-comparison.json").read_text(encoding="utf-8"))
        return manifest, report, diagnostics, api.models

    def test_both_raw_diagnostics_are_preserved_with_correct_scopes(self):
        manifest, report, diagnostics, models = self.run_replay()
        for label, step in [("full", "06_baseline"), ("selected", "07_selected_model")]:
            actual = manifest[f"{label}_model_diagnostics"]
            raw = models[step]
            self.assertEqual(actual["training_input_support"], raw["preprocessing"]["training_input_support"])
            self.assertEqual(actual["residual_diagnostics"], raw["residual_diagnostics"])
            for key in ("input_support", "excitation_shortfall", "residual_whiteness_ratio", "input_residual_correlations", "input_residual_test", "simulation_status"):
                self.assertEqual(actual["validation"][key], raw["validation"][key])
            self.assertEqual(diagnostics[f"{label}_model_diagnostics"], actual)
        self.assertEqual(manifest["diagnostic_summary"]["generated_by"], "skill")
        self.assertEqual(diagnostics["diagnostic_summary"], manifest["diagnostic_summary"])
        self.assertIn("训练集一步预测残差", report)
        self.assertIn("验证集一步预测残差", report)

    def test_report_distinguishes_full_and_selected_support(self):
        def change(name, model):
            if name == "07_selected_model":
                model["preprocessing"]["training_input_support"]["u1"]["minimum"] = -0.4321
        _, report, _, _ = self.run_replay(change)
        self.assertIn("## 数据充分性与残差诊断", report)
        self.assertIn("全量训练", report)
        self.assertIn("优选训练", report)
        self.assertIn("-0.4321", report)
        self.assertIn("-1.3826", report)
        self.assertIn("验证自由仿真 RMSE", report)

    def test_input_warning_blocks_unconditional_positive_conclusion(self):
        def warning(name, model):
            clean_diagnostics(name, model)
            if name == "07_selected_model":
                model["validation"]["input_support"].update(status="extrapolation", extrapolated_inputs=["u1"])
        manifest, report, _, _ = self.run_replay(warning)
        summary = manifest["diagnostic_summary"]
        self.assertEqual(summary["assessment"], "manual_review")
        self.assertIn("输入支持", summary["conclusion"])
        self.assertIn("人工复核", summary["conclusion"])
        self.assertNotIn("优选成功", summary["conclusion"])
        self.assertIn(summary["conclusion"], report)

    def test_residual_warning_blocks_unconditional_positive_conclusion(self):
        def warning(name, model):
            clean_diagnostics(name, model)
            if name == "07_selected_model":
                model["validation"]["input_residual_test"].update(rejected_channels=["u3"])
        manifest, _, _, _ = self.run_replay(warning)
        summary = manifest["diagnostic_summary"]
        self.assertEqual(summary["assessment"], "manual_review")
        self.assertEqual(summary["new_residual_rejected_channels"], ["u3"])
        self.assertIn("残差", summary["conclusion"])
        self.assertNotIn("未出现明显恶化", summary["conclusion"])

    def test_existing_S2_warnings_are_not_erased_when_no_new_warning(self):
        manifest, _, _, _ = self.run_replay()
        summary = manifest["diagnostic_summary"]
        self.assertEqual(summary["assessment"], "manual_review")
        self.assertEqual(summary["new_residual_rejected_channels"], [])
        self.assertIn("人工复核", summary["conclusion"])

    def test_optional_fields_missing_produce_null_and_incomplete_evidence(self):
        def remove(name, model):
            model.pop("residual_diagnostics", None)
            model["preprocessing"].pop("training_input_support", None)
            model["validation"] = None
        manifest, report, _, _ = self.run_replay(remove)
        for name in ("full", "selected"):
            raw = manifest[f"{name}_model_diagnostics"]
            self.assertIsNone(raw["training_input_support"])
            self.assertIsNone(raw["residual_diagnostics"])
            self.assertIsNone(raw["validation"]["input_support"])
            self.assertIsNone(raw["validation"]["excitation_shortfall"])
        self.assertEqual(manifest["diagnostic_summary"]["assessment"], "insufficient_evidence")
        self.assertIn("未返回", report)

    def test_whiteness_decline_is_descriptive_not_a_new_statistical_gate(self):
        def change(name, model):
            clean_diagnostics(name, model)
            if name == "07_selected_model":
                model["validation"]["residual_whiteness_ratio"] = 0.8
        manifest, _, _, _ = self.run_replay(change)
        summary = manifest["diagnostic_summary"]
        self.assertEqual(summary["assessment"], "manual_review")
        self.assertIn("白度比例下降", summary["conclusion"])
        self.assertIn("描述性", summary["conclusion"])

    def test_clean_backend_results_allow_only_guarded_positive_summary(self):
        manifest, report, _, _ = self.run_replay(clean_diagnostics)
        summary = manifest["diagnostic_summary"]
        self.assertEqual(summary["assessment"], "no_new_backend_warnings")
        self.assertIn("保持或改善", summary["conclusion"])
        self.assertIn("不能证明", report)

    def test_different_validation_intervals_do_not_claim_fair_diagnostic_comparison(self):
        def change(name, model):
            clean_diagnostics(name, model)
            if name == "07_selected_model":
                model["validation"]["input_support"]["start"] += 1
        manifest, _, _, _ = self.run_replay(change)
        self.assertFalse(manifest["diagnostic_summary"]["same_validation_interval"])
        self.assertEqual(manifest["diagnostic_summary"]["assessment"], "insufficient_evidence")


if __name__ == "__main__":
    unittest.main(verbosity=2)
