"""Contract tests plus checks against the included real API execution evidence."""

import csv
import hashlib
import importlib.util
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "adapter", ROOT / "indusopt-data-selection/scripts/indusopt_skill.py"
)
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


EVIDENCE = ROOT / "示例与实测/S2完整结果"


def example_args(**overrides):
    values = {
        "csv": str(EVIDENCE / "source.csv"), "time_column": "timestamp",
        "inputs": "u1,u2,u3", "output_column": "y", "delays": "1,1,1",
        "confirm_lags": True, "na": 2, "nb": 2, "window": 60, "budget": 8,
        "artifact_root": str(EVIDENCE), "data_kind": "synthetic",
    }
    values.update(overrides)
    return Namespace(**values)


class EvidenceAPI:
    """Replay fixtures to test client file handling, not backend computation."""

    def request(self, name, path, payload=None, **kwargs):
        data = json.loads((EVIDENCE / f"{name}.json").read_text(encoding="utf-8"))["data"]
        if name == "08_export":
            data.update(csv_uri="selected.csv", manifest_uri="server-manifest.json")
        return data

    def download(self, dataset, version, destination):
        destination.write_bytes((EVIDENCE / destination.name).read_bytes())


class AdapterContracts(unittest.TestCase):
    def test_success_requires_report_and_utf8_server_manifest(self):
        original = Path.read_text

        def read_utf8(path, *args, **kwargs):
            if path.name == "server-manifest.json":
                self.assertEqual(kwargs.get("encoding"), "utf-8")
            return original(path, *args, **kwargs)

        with tempfile.TemporaryDirectory() as tmp, patch.object(Path, "read_text", read_utf8):
            out = Path(tmp)
            self.assertEqual(adapter.analyze(example_args(), EvidenceAPI(), out), "succeeded")
            self.assertTrue((out / "report.md").is_file())
            self.assertEqual(json.loads((out / "manifest.json").read_text(encoding="utf-8"))["status"], "succeeded")
            self.assertFalse((out / "manifest.pending.json").exists())

    def test_invalid_parameters_stop_before_api_requests(self):
        for overrides in ({"na": 0}, {"nb": 21}, {"window": 4}, {"budget": 101}, {"window": 2000}, {"delays": "1001,1001,1001"}):
            args = example_args(**overrides)
            api = Mock()
            with self.subTest(overrides=overrides), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(adapter.SkillError):
                    adapter.analyze(args, api, Path(tmp))
                api.request.assert_not_called()

    def test_short_ensemble_training_range_stops_before_api_requests(self):
        source_lines = (EVIDENCE / "source.csv").read_text(encoding="utf-8").splitlines()
        for source_rows in (111, 115):
            with self.subTest(source_rows=source_rows), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "input.csv"
                path.write_text("\n".join(source_lines[:source_rows + 1]) + "\n", encoding="utf-8")
                api = Mock()
                api.request.side_effect = AssertionError("Insufficient data reached the API")
                with self.assertRaisesRegex(adapter.SkillError, "INSUFFICIENT_ROWS"):
                    adapter.analyze(example_args(csv=str(path)), api, Path(tmp))
                api.request.assert_not_called()

    def test_ensemble_training_range_matches_backend_boundary(self):
        for rows in (110, 114):
            with self.subTest(rows=rows), self.assertRaisesRegex(adapter.SkillError, "INSUFFICIENT_ROWS"):
                adapter.selection_training_range(rows, 2, 2, 60)
        for rows, na, nb, history, stop in (
            (115, 2, 2, 4, 65),
            (1999, 2, 2, 4, 1195),
            (1999, 20, 20, 20, 1179),
            (1999, 2, 20, 19, 1180),
        ):
            with self.subTest(rows=rows, na=na, nb=nb):
                interval = adapter.selection_training_range(rows, na, nb, 60)
                self.assertEqual(interval["start_index"], history)
                self.assertEqual(interval["stop_index_exclusive"], stop)
                self.assertLessEqual(stop, int(rows * 0.6) - max(na, nb - 1))

    def test_explicit_policies_and_returned_model_parameters_are_recorded(self):
        evidence_api = EvidenceAPI()
        model_structure = {
            "model_type": "ARX", "estimator": "ols", "na": 2,
            "nb": {"u1": 2, "u2": 2, "u3": 2},
            "delays": {"u1": 0, "u2": 0, "u3": 0},
            "fit_intercept": True, "standardize": True, "history_guard": 2,
        }
        preprocessing = {"feature_center": [1.0, 2.0], "feature_scale": [3.0, 4.0]}

        def request(name, path, payload=None, **kwargs):
            data = evidence_api.request(name, path, payload, **kwargs)
            if name in ("06_baseline", "07_selected_model"):
                data.update(model_structure=model_structure, intercept=0.125, preprocessing=preprocessing)
            return data

        api = Mock(wraps=evidence_api)
        api.request.side_effect = request
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.assertEqual(adapter.analyze(example_args(), api, out), "succeeded")
            calls = {call.args[0]: call.args[2] for call in api.request.call_args_list if len(call.args) > 2}
            selection = calls["05_selection"]
            self.assertEqual(selection["train_ratio"], 0.6)
            self.assertEqual(selection["selection_mode"], "ensemble")
            self.assertEqual(selection["history_guard"], 4)
            for key in ("standardize", "quality_weighting", "adaptive_windows"):
                self.assertIs(selection[key], True)
            for name in ("06_baseline", "07_selected_model"):
                model = calls[name]
                self.assertEqual(model["model_type"], "ARX")
                self.assertEqual(model["estimator"], "ols")
                self.assertIs(model["fit_intercept"], True)
                self.assertIs(model["standardize"], True)
                self.assertIs(model["evaluate_test"], False)
                self.assertNotIn("sample_weights", model)
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["selection_parameters"]["train_ratio"], 0.6)
            self.assertEqual(manifest["selection_parameters"]["window"], 60)
            self.assertEqual(manifest["selection_parameters"]["budget"], 8)
            self.assertEqual(manifest["selection_training_range"], {
                "start_index": 4, "stop_index_exclusive": 1195,
            })
            for model in manifest["comparison"]:
                self.assertEqual(model["model_structure"], model_structure)
                self.assertEqual(model["intercept"], 0.125)
                self.assertEqual(model["preprocessing"], preprocessing)
            report = (out / "report.md").read_text(encoding="utf-8")
            self.assertIn('"selection_mode": "ensemble"', report)
            self.assertIn('"intercept": 0.125', report)

    def test_report_failure_does_not_leave_success_manifest(self):
        original = Path.write_text

        def fail_report(path, *args, **kwargs):
            if path.name == "report.md":
                raise OSError("Simulated report write failure")
            return original(path, *args, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with patch.object(Path, "write_text", fail_report), self.assertRaisesRegex(OSError, "Simulated report"):
                adapter.analyze(example_args(), EvidenceAPI(), out)
            self.assertFalse((out / "manifest.json").exists())

    def test_complete_selection(self):
        self.assertEqual(
            adapter.validate_selection(
                {"selection": {"selected_rows": 2}, "selected_indices": [5, 3]}
            ),
            [3, 5],
        )

    def test_empty_does_not_fall_back_to_all_training_rows(self):
        with self.assertRaises(adapter.SkillError):
            adapter.validate_selection(
                {"selection": {"selected_rows": 0}, "selected_indices": []}
            )

    def test_truncated_selection_stops(self):
        with self.assertRaises(adapter.SkillError):
            adapter.validate_selection(
                {
                    "selection": {"selected_rows": 4001},
                    "selected_indices": list(range(4000)),
                }
            )

    def test_duplicates_and_negative_indices_stop(self):
        for indices in ([1, 1], [1, -1]):
            with self.assertRaises(adapter.SkillError):
                adapter.validate_selection(
                    {"selection": {"selected_rows": 2}, "selected_indices": indices}
                )

    def test_artifact_path_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "artifacts"
            root.mkdir()
            outside = Path(tmp) / "other.txt"
            outside.write_text("not an artifact", encoding="utf-8")
            with self.assertRaises(adapter.SkillError):
                adapter.contained(root, "../other.txt")

    def test_symlink_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "artifacts"
            root.mkdir()
            outside = Path(tmp) / "other.txt"
            outside.write_text("not an artifact", encoding="utf-8")
            try:
                (root / "link").symlink_to(outside)
            except (OSError, NotImplementedError) as exc:
                if isinstance(exc, NotImplementedError) or getattr(exc, "winerror", None) == 1314:
                    self.skipTest("Symbolic links are unavailable without OS permission")
                raise
            with self.assertRaises(adapter.SkillError):
                adapter.contained(root, "link")

    def test_client_rejects_remote_host(self):
        with self.assertRaises(adapter.SkillError):
            adapter.API("https://example.com/api/v1", 1, Path("."))

    def test_duplicate_time_stops_before_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.csv"
            path.write_text("t,u,y\n2026-01-01T00:00:00,1,2\n2026-01-01T00:00:00,2,3\n", encoding="utf-8")
            with self.assertRaises(adapter.SkillError):
                adapter.validate_csv(path, "t", ["u"], "y")


class RealExecutionEvidence(unittest.TestCase):
    def test_real_export_and_metric_sources(self):
        root = ROOT / "示例与实测/S2完整结果"
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "succeeded")
        self.assertEqual(
            manifest["selected_sha256"],
            hashlib.sha256((root / "selected.csv").read_bytes()).hexdigest(),
        )
        with (root / "selected.csv").open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), len(manifest["selected_sample_indices"]))
        selection = json.loads((root / "05_selection.json").read_text(encoding="utf-8"))["data"]
        self.assertEqual(len(rows), selection["selection"]["selected_rows"])
        comparison = json.loads((root / "comparison.json").read_text(encoding="utf-8"))
        for name, result in zip(["06_baseline", "07_selected_model"], comparison):
            raw = json.loads((root / f"{name}.json").read_text(encoding="utf-8"))["data"]
            self.assertEqual(
                result["validation_free_run_fit"], raw["validation"]["free_run_fit"]
            )
            self.assertEqual(result["processing_run_id"], raw["processing_run_id"])
            self.assertIsNone(raw["metrics"]["test_free_run_fit"])
        self.assertEqual(comparison[1]["training_rows"], len(rows))
        with (root / "model-source.csv").open(encoding="utf-8", newline="") as f:
            continuous = list(csv.DictReader(f))
        guard = max(
            manifest["model_parameters"]["na"],
            max(manifest["model_parameters"]["nb"].values()) - 1,
        )
        self.assertLess(
            max(manifest["selected_sample_indices"]), int(len(continuous) * 0.6) - guard
        )

    def test_pending_confirmation_has_no_apply_or_model_request(self):
        root = ROOT / "示例与实测/未确认停止"
        self.assertEqual(
            json.loads((root / "pending-confirmation.json").read_text(encoding="utf-8"))["status"],
            "waiting_confirmation",
        )
        requests = json.loads((root / "requests.json").read_text(encoding="utf-8"))
        self.assertFalse(
            any("/apply" in r["path"] or "/modeling/" in r["path"] for r in requests)
        )
        self.assertFalse((root / "selected.csv").exists())

    def test_rank_deficient_run_not_presented_as_success(self):
        root = ROOT / "示例与实测/S6失败停止"
        self.assertEqual(
            json.loads((root / "failure.json").read_text(encoding="utf-8"))["status"], "failed"
        )
        error = json.loads((root / "07_selected_model.error.txt").read_text(encoding="utf-8"))
        self.assertEqual(error["error"]["code"], "DESIGN_MATRIX_RANK_DEFICIENT")
        self.assertFalse((root / "manifest.json").exists())
        self.assertFalse((root / "selected.csv").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
