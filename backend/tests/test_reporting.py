"""Tests for provenance-bound reporting and optimised-dataset export (phase 10)."""

from __future__ import annotations

import asyncio
import csv
import json
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from algorithms.report.provenance import (
    render_template,
    resolve_path,
    validate_draft,
)
from app.core.config import Settings
from app.core.db import get_session
from app.main import create_app
from app.models import Base
from app.models.dataset import ProcessingRun
from app.services import report_service
from app.services.report_service import (
    RunIndex,
    _compose,
    _matches,
    _number_sections,
    _presentation_formatters,
    _report_title,
    build_execution_run_index,
)
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

RUNS = {
    "r1": {
        "run_type": "modeling.arx",
        "validation": {"free_run_fit": 97.8612, "one_step_fit": 99.1, "stable": True},
        "training_rows": 480,
        "delays": {"u1": 3, "u2": 8},
    }
}


class TestNumeralValidation:
    def test_a_bare_number_is_rejected(self) -> None:
        violations = validate_draft("验证集自由仿真 FIT 达到 97.86%。")
        assert len(violations) == 1
        assert violations[0].text == "97.86"

    def test_a_bound_number_is_accepted(self) -> None:
        draft = "验证集自由仿真 FIT 达到 {{run:r1.validation.free_run_fit}}%。"
        assert validate_draft(draft) == []

    def test_list_and_heading_numbering_is_allowed(self) -> None:
        draft = "## 1. 概述\n\n1. 第一条\n2) 第二条\n3、第三条\n"
        assert validate_draft(draft) == []

    def test_a_number_after_a_list_marker_is_still_rejected(self) -> None:
        """Structure is exempt; data on the same line is not."""

        violations = validate_draft("1. 拟合度为 88.2 分")
        assert [violation.text for violation in violations] == ["88.2"]

    def test_reports_line_and_column(self) -> None:
        violations = validate_draft("第一行没有数字\n第二行有 42")
        assert violations[0].line == 2
        assert violations[0].column > 1

    def test_a_markdown_table_separator_is_not_data(self) -> None:
        assert validate_draft("| a | b |\n|---|---:|\n") == []

    def test_catches_every_violation_not_just_the_first(self) -> None:
        violations = validate_draft("FIT 97.8，RMSE 0.12，条件数 3400")
        assert len(violations) == 3


class TestPathResolution:
    def test_reads_a_nested_path(self) -> None:
        assert resolve_path(RUNS["r1"], "validation.free_run_fit") == pytest.approx(97.8612)

    def test_reads_a_dict_leaf(self) -> None:
        assert resolve_path(RUNS["r1"], "delays.u1") == 3

    def test_reads_a_list_index(self) -> None:
        assert resolve_path({"values": [10, 20, 30]}, "values.1") == 20

    def test_missing_path_returns_none(self) -> None:
        assert resolve_path(RUNS["r1"], "validation.does_not_exist") is None

    def test_descending_through_a_scalar_returns_none(self) -> None:
        assert resolve_path(RUNS["r1"], "training_rows.deeper") is None


class TestRendering:
    def test_substitutes_from_the_run_record(self) -> None:
        result = render_template("FIT={{run:r1.validation.free_run_fit}}", runs=RUNS)
        assert "97.8612" in result.text
        assert result.fully_resolved
        assert result.bindings[0].run_id == "r1"
        assert result.bindings[0].path == "validation.free_run_fit"

    def test_booleans_render_readably(self) -> None:
        result = render_template("稳定性={{run:r1.validation.stable}}", runs=RUNS)
        assert "是" in result.text

    def test_an_unresolvable_placeholder_is_marked_not_blanked(self) -> None:
        """A silently dropped figure is more dangerous than a visibly missing one."""

        result = render_template("值={{run:r1.nope}}", runs=RUNS)
        assert "[未解析数值:r1.nope]" in result.text
        assert not result.fully_resolved
        assert result.unresolved

    def test_every_rendered_number_has_a_binding(self) -> None:
        template = (
            "{{run:r1.validation.free_run_fit}} / {{run:r1.validation.one_step_fit}}"
            " / {{run:r1.training_rows}}"
        )
        result = render_template(template, runs=RUNS)
        assert len(result.bindings) == 3
        assert all(binding.resolved for binding in result.bindings)

    def test_rendered_output_would_now_fail_numeral_validation(self) -> None:
        """The rendered document contains real numbers; only the *draft* must not."""

        result = render_template("FIT={{run:r1.validation.free_run_fit}}", runs=RUNS)
        assert validate_draft(result.text) != []

    def test_execution_step_placeholder_is_distinct_from_processing_run_evidence(self) -> None:
        result = render_template(
            "样本数={{step:s1.n_samples}}",
            runs={"s1": {"n_samples": 1500}},
        )

        assert result.text == "样本数=1500"
        assert result.bindings[0].kind == "step"
        assert result.bindings[0].run_id == "s1"


class TestExecutionScopedReportComposition:
    @staticmethod
    def _clean_only_index() -> RunIndex:
        return RunIndex(
            records={
                "s1": {
                    "tool_name": "profile_dataset",
                    "status": "SUCCEEDED",
                    "summary": "数据画像完成",
                    "n_samples": 1500,
                    "fingerprint": {
                        "values": {
                            "log_sample_count": 0.5132,
                            "missing_ratio": 0.0,
                            "anomaly_ratio": 0.2242,
                        }
                    },
                },
                "s2": {
                    "tool_name": "detect_anomalies",
                    "status": "SUCCEEDED",
                    "summary": "异常检测完成",
                    "anomaly_count": 0,
                    "anomaly_ratio": 0.0025,
                },
                "s3": {
                    "tool_name": "clean_data",
                    "status": "SUCCEEDED",
                    "summary": "数据清洗完成",
                    "total_cleaned_points": 0,
                    "summary_data": {
                        "rows_before": 1500,
                        "rows_after": 1500,
                        "changes": {
                            "unique_changed_cells": 0,
                            "missing_value_fills": 0,
                        },
                    },
                },
            },
            by_type={},
            step_by_tool={
                "profile_dataset": "s1",
                "detect_anomalies": "s2",
                "clean_data": "s3",
            },
            execution_id=uuid4(),
        )

    def test_clean_only_execution_has_scoped_title_and_no_modeling_claims(self) -> None:
        index = self._clean_only_index()
        payload = report_service.ReportRequest(
            execution_id=index.execution_id,
            dataset_id=uuid4(),
            version_id=uuid4(),
        )

        sections = _number_sections(_compose(index, payload))
        text = "\n".join(f"{section.title}\n{section.body}" for section in sections)

        assert _report_title(index, payload) == "IndusOpt 数据质量分析与清洗报告"
        assert [section.key for section in sections] == [
            "overview",
            "profile",
            "anomaly",
            "cleaning",
            "limitations",
        ]
        assert [section.title.split("、", 1)[0] for section in sections] == [
            "一",
            "二",
            "三",
            "四",
            "五",
        ]
        for forbidden in ("D-最优", "ARX", "Optuna", "模型评价"):
            assert forbidden not in text

    def test_execution_report_formats_only_explicit_fraction_metrics_as_percentages(
        self,
    ) -> None:
        index = self._clean_only_index()
        payload = report_service.ReportRequest(
            execution_id=index.execution_id,
            dataset_id=uuid4(),
            version_id=uuid4(),
        )
        sections = _number_sections(_compose(index, payload))
        template = "\n\n".join(
            f"## {section.title}\n\n{section.body}" for section in sections
        )
        template += "\n\n画像规模指纹 {{step:s1.fingerprint.values.log_sample_count}}"

        rendered = render_template(
            template,
            runs=index.records,
            formatters=_presentation_formatters(index),
        )

        assert "画像离群比例 22.42%" in rendered.text
        assert "疑似异常比例 0.25%" in rendered.text
        assert "缺失比例 0.00%" in rendered.text
        assert "画像规模指纹 0.5132" in rendered.text
        assert "51.32%" not in rendered.text
        anomaly_binding = next(
            binding
            for binding in rendered.bindings
            if binding.path == "fingerprint.values.anomaly_ratio"
        )
        assert anomaly_binding.value == "0.2242"

    def test_generate_report_returns_percentage_formatted_final_markdown(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        index = self._clean_only_index()
        dataset_id = uuid4()
        version_id = uuid4()
        payload = report_service.ReportRequest(
            execution_id=index.execution_id,
            dataset_id=dataset_id,
            version_id=version_id,
        )

        async def fake_build_execution_run_index(
            session: AsyncSession,
            *,
            execution_id: object,
            dataset_id: object,
            version_id: object,
        ) -> RunIndex:
            return index

        persisted = []

        async def fake_persist(
            session: AsyncSession,
            *,
            report_id: object,
            payload: object,
            rendered: object,
        ) -> None:
            persisted.append(rendered)

        monkeypatch.setattr(
            report_service,
            "build_execution_run_index",
            fake_build_execution_run_index,
        )
        monkeypatch.setattr(report_service, "_persist", fake_persist)

        data = asyncio.run(
            report_service.generate_report(
                SimpleNamespace(),
                payload=payload,
                artifact_root=tmp_path,
            )
        )

        assert "画像离群比例 22.42%" in data.markdown
        assert "疑似异常比例 0.25%" in data.markdown
        assert "画像异常比例 0.2242" not in data.markdown
        assert "疑似异常比例 0.0025" not in data.markdown
        assert "0.5132" not in data.markdown
        assert "51.32%" not in data.markdown

        binding_values = {
            binding.path: binding.value
            for binding in data.bindings
            if binding.path in {
                "fingerprint.values.anomaly_ratio",
                "anomaly_ratio",
            }
        }
        assert binding_values == {
            "fingerprint.values.anomaly_ratio": "0.2242",
            "anomaly_ratio": "0.0025",
        }
        assert persisted
        artifact = tmp_path / data.artifact_uri
        assert "画像离群比例 22.42%" in artifact.read_text(encoding="utf-8")
        assert "疑似异常比例 0.25%" in artifact.read_text(encoding="utf-8")

    def test_only_executed_capabilities_create_sections(self) -> None:
        segment_index = RunIndex(
            records={"s1": {"tool_name": "detect_dynamic_segments", "summary": "优选完成"}},
            by_type={},
            step_by_tool={"detect_dynamic_segments": "s1"},
            execution_id=uuid4(),
        )
        model_index = RunIndex(
            records={
                "s1": {"tool_name": "fit_arx", "summary": "辨识完成"},
                "s2": {"tool_name": "evaluate_model", "summary": "评价完成"},
            },
            by_type={},
            step_by_tool={"fit_arx": "s1", "evaluate_model": "s2"},
            execution_id=uuid4(),
        )

        segment_sections = {section.key for section in _compose(segment_index, report_service.ReportRequest(execution_id=segment_index.execution_id))}
        model_sections = {section.key for section in _compose(model_index, report_service.ReportRequest(execution_id=model_index.execution_id))}

        assert "selection" in segment_sections
        assert "model" not in segment_sections
        assert "model" in model_sections
        assert "evaluation" in model_sections
        assert _report_title(model_index, report_service.ReportRequest(execution_id=model_index.execution_id)) == "IndusOpt 动态建模与系统辨识报告"

    def test_execution_index_loads_only_explicit_processing_run_ids(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        execution_id = uuid4()
        dataset_id = uuid4()
        version_id = uuid4()
        explicit_run_id = uuid4()
        historical_segment_id = uuid4()
        execution = SimpleNamespace(
            id=execution_id,
            dataset_id=dataset_id,
            current_version_id=version_id,
            step_runs=[
                SimpleNamespace(
                    step_id="profile",
                    sequence=1,
                    tool_name="profile_dataset",
                    status="SUCCEEDED",
                    source_version_id=version_id,
                    result_version_id=None,
                    result_payload={"summary": "画像完成", "result": {"n_samples": 1500}},
                    processing_run_ids=[],
                    started_at=None,
                    finished_at=None,
                ),
                SimpleNamespace(
                    step_id="clean",
                    sequence=2,
                    tool_name="clean_data",
                    status="SUCCEEDED",
                    source_version_id=version_id,
                    result_version_id=version_id,
                    result_payload={"total_cleaned_points": 0},
                    processing_run_ids=[str(explicit_run_id)],
                    started_at=None,
                    finished_at=None,
                ),
            ],
        )
        explicit_run = SimpleNamespace(
            id=explicit_run_id,
            run_type="preprocessing.clean",
            status="succeeded",
            parameters={},
            result={"total_cleaned_points": 0},
            created_at=None,
        )

        async def fake_get_execution(session: object, *, execution_id: object) -> object:
            return execution

        class FakeSession:
            def __init__(self) -> None:
                self.requested_ids: list[object] = []

            async def get(self, model: object, identifier: object) -> object:
                self.requested_ids.append(identifier)
                return explicit_run if identifier == explicit_run_id else None

        monkeypatch.setattr(report_service, "get_execution", fake_get_execution)
        session = FakeSession()
        index = asyncio.run(
            build_execution_run_index(
                session,
                execution_id=execution_id,
                dataset_id=dataset_id,
                version_id=version_id,
            )
        )

        assert session.requested_ids == [explicit_run_id]
        assert historical_segment_id not in session.requested_ids
        assert index.by_type == {
            "preprocessing.clean": f"r{str(explicit_run_id).replace('-', '')[:8]}"
        }
        assert "preprocessing.segment" not in index.by_type


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'report.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def prepare() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(prepare())

    async def session_override() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    monkeypatch.setattr("app.api.routes.get_settings", lambda: Settings(artifact_root=tmp_path))
    app = create_app()
    app.dependency_overrides[get_session] = session_override
    with TestClient(app) as client:
        yield client
    asyncio.run(engine.dispose())


def run_pipeline(client: TestClient) -> str:
    """Drive the real pipeline so the report has genuine runs to cite."""

    generated = client.post(
        "/api/v1/simulation/generate",
        json={"scenario": "S2", "n_steps": 2500, "seed": 12, "input_count": 2},
    )
    assert generated.status_code == 201, generated.text
    version_id = generated.json()["data"]["version_id"]

    lagged = client.post(
        "/api/v1/preprocessing/delay/apply",
        json={
            "version_id": version_id,
            "lag_map": {"u1": 3, "u2": 8},
            "user_confirmed": True,
            "recommendation_source": "manual",
            "evidence_summary": {"fixture": "known_simulation_lags"},
        },
    )
    assert lagged.status_code == 201, lagged.text
    version_id = lagged.json()["data"]["result_version_id"]

    segment = client.post(
        "/api/v1/preprocessing/segment",
        json={
            "version_id": version_id,
            "input_columns": ["u1", "u2"],
            "output_column": "y",
            "window_size": 60,
            "max_segments": 6,
        },
    )
    assert segment.status_code == 202, segment.text

    fitted = client.post(
        "/api/v1/modeling/arx/fit",
        json={
            "version_id": version_id,
            "input_columns": ["u1", "u2"],
            "output_column": "y",
            "na": 2,
            "nb": [2, 2],
            "delays": [3, 8],
        },
    )
    assert fitted.status_code == 200, fitted.text
    return version_id


class TestReportApi:
    def test_report_cites_real_runs_and_binds_every_number(self, client: TestClient) -> None:
        version_id = run_pipeline(client)
        response = client.post("/api/v1/reports/generate", json={"version_id": version_id})
        assert response.status_code == 200, response.text
        data = response.json()["data"]

        assert data["bindings"], "the report must bind at least one figure to a run"
        assert data["fully_resolved"] is True
        assert data["unresolved"] == []
        for binding in data["bindings"]:
            assert binding["run_id"]
            assert binding["resolved"] is True
        assert data["cited_runs"] == sorted({binding["run_id"] for binding in data["bindings"]})
        assert any(section["key"] == "selection" for section in data["sections"])
        assert any(section["key"] == "model" for section in data["sections"])

    def test_report_body_contains_no_placeholder_left_over(self, client: TestClient) -> None:
        version_id = run_pipeline(client)
        data = client.post("/api/v1/reports/generate", json={"version_id": version_id}).json()[
            "data"
        ]
        assert "{{" not in data["markdown"]

    def test_report_artifact_is_written_to_disk(self, client: TestClient, tmp_path: Path) -> None:
        version_id = run_pipeline(client)
        data = client.post("/api/v1/reports/generate", json={"version_id": version_id}).json()[
            "data"
        ]
        assert (tmp_path / data["artifact_uri"]).is_file()

    def test_report_without_runs_is_refused(self, client: TestClient) -> None:
        response = client.post("/api/v1/reports/generate", json={"version_id": str(uuid4())})
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "REPORT_NO_RUNS"

    def test_report_accepts_a_cleaning_derived_version(self, client: TestClient) -> None:
        generated = client.post(
            "/api/v1/simulation/generate",
            json={"scenario": "S4", "n_steps": 1200, "seed": 77, "input_count": 2},
        )
        assert generated.status_code == 201, generated.text
        source_version_id = generated.json()["data"]["version_id"]

        cleaned = client.post(
            "/api/v1/preprocessing/clean",
            json={
                "version_id": source_version_id,
                "target_sample_period_seconds": 1.0,
                "interpolation": "linear",
                "anomaly_detector": "hampel",
                "hampel_window": 5,
            },
        )
        assert cleaned.status_code == 202, cleaned.text
        derived_version_id = cleaned.json()["data"]["derived_version_id"]

        response = client.post(
            "/api/v1/reports/generate", json={"version_id": derived_version_id}
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["fully_resolved"] is True
        assert data["unresolved"] == []
        assert any(section["key"] == "cleaning" for section in data["sections"])


class TestExportApi:
    def test_export_writes_the_selected_rows_and_a_manifest(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        version_id = run_pipeline(client)
        response = client.post(
            "/api/v1/delivery/export",
            json={
                "version_id": version_id,
                "input_columns": ["u1", "u2"],
                "output_column": "y",
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]

        assert data["exported_rows"] > 0
        assert data["exported_rows"] < data["source_rows"], "export must be a real subset"
        assert 0 < data["coverage_ratio"] < 1

        csv_path = tmp_path / data["csv_uri"]
        assert csv_path.is_file()
        with csv_path.open(encoding="utf-8") as handle:
            rows = list(csv.reader(handle))
        assert rows[0] == data["columns"]
        assert len(rows) - 1 == data["exported_rows"]

        manifest = json.loads((tmp_path / data["manifest_uri"]).read_text(encoding="utf-8"))
        assert manifest["version_id"] == version_id
        assert manifest["exported_rows"] == data["exported_rows"]

        csv_download = client.get(f"/api/v1/delivery/exports/{data['export_id']}/csv")
        manifest_download = client.get(
            f"/api/v1/delivery/exports/{data['export_id']}/manifest"
        )
        assert csv_download.status_code == 200
        assert csv_download.headers["content-type"].startswith("text/csv")
        assert manifest_download.status_code == 200
        assert manifest_download.json()["exported_rows"] == data["exported_rows"]

    def test_explicit_indices_are_honoured(self, client: TestClient) -> None:
        version_id = run_pipeline(client)
        response = client.post(
            "/api/v1/delivery/export",
            json={
                "version_id": version_id,
                "input_columns": ["u1", "u2"],
                "output_column": "y",
                "sample_indices": [100, 101, 102, 103],
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["exported_rows"] == 4

    def test_export_without_a_selection_is_refused(self, client: TestClient) -> None:
        generated = client.post(
            "/api/v1/simulation/generate",
            json={"scenario": "S1", "n_steps": 1200, "seed": 3, "input_count": 1},
        )
        version_id = generated.json()["data"]["version_id"]
        response = client.post(
            "/api/v1/delivery/export",
            json={"version_id": version_id, "input_columns": ["u1"], "output_column": "y"},
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "EXPORT_NO_SELECTION"


def test_processing_run_scope_requires_dataset_and_version_when_both_are_requested() -> None:
    requested_dataset = uuid4()
    other_dataset = uuid4()
    requested_version = uuid4()
    other_version = uuid4()
    same_dataset_old_version = ProcessingRun(
        dataset_id=requested_dataset,
        source_version_id=other_version,
        run_type="preprocessing.clean",
        status="succeeded",
        parameters={},
        result={"effective_version_id": str(other_version)},
    )
    same_version_other_dataset = ProcessingRun(
        dataset_id=other_dataset,
        source_version_id=requested_version,
        run_type="preprocessing.clean",
        status="succeeded",
        parameters={},
        result={"effective_version_id": str(requested_version)},
    )
    exact_scope = ProcessingRun(
        dataset_id=requested_dataset,
        source_version_id=other_version,
        run_type="preprocessing.clean",
        status="succeeded",
        parameters={},
        result={"effective_version_id": str(requested_version)},
    )

    assert not _matches(
        same_dataset_old_version,
        dataset_id=requested_dataset,
        version_id=requested_version,
    )
    assert not _matches(
        same_version_other_dataset,
        dataset_id=requested_dataset,
        version_id=requested_version,
    )
    assert _matches(exact_scope, dataset_id=requested_dataset, version_id=requested_version)
    assert _matches(same_dataset_old_version, dataset_id=requested_dataset, version_id=None)
    assert _matches(same_version_other_dataset, dataset_id=None, version_id=requested_version)
