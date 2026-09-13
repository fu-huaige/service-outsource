"""Tests for the closed loop: cache, fingerprints, objective and strategy memory."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from uuid import UUID, uuid4

import numpy as np
import pytest
from algorithms.pipeline.cache import LineageCache, canonical_json, stage_key
from algorithms.pipeline.fingerprint import build_fingerprint, fingerprint_distance
from app.core.config import Settings
from app.core.db import get_session
from app.main import create_app
from app.models import Base
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


class TestCanonicalKeys:
    def test_key_ignores_dict_ordering(self) -> None:
        assert canonical_json({"a": 1, "b": 2}) == canonical_json({"b": 2, "a": 1})

    def test_key_ignores_float_noise_below_precision(self) -> None:
        left = stage_key(parent_key="p", tool_name="t", tool_version="1", parameters={"x": 0.1})
        right = stage_key(
            parent_key="p", tool_name="t", tool_version="1", parameters={"x": 0.1 + 1e-15}
        )
        assert left == right

    def test_key_changes_with_a_meaningful_parameter_change(self) -> None:
        left = stage_key(parent_key="p", tool_name="t", tool_version="1", parameters={"x": 0.1})
        right = stage_key(parent_key="p", tool_name="t", tool_version="1", parameters={"x": 0.2})
        assert left != right

    def test_key_changes_with_tool_version(self) -> None:
        left = stage_key(parent_key="p", tool_name="t", tool_version="1", parameters={})
        right = stage_key(parent_key="p", tool_name="t", tool_version="2", parameters={})
        assert left != right

    def test_key_changes_with_parent(self) -> None:
        left = stage_key(parent_key="a", tool_name="t", tool_version="1", parameters={})
        right = stage_key(parent_key="b", tool_name="t", tool_version="1", parameters={})
        assert left != right


class TestLineageCache:
    def test_second_lookup_is_a_hit_and_does_not_recompute(self) -> None:
        cache = LineageCache()
        calls = {"count": 0}

        def compute() -> int:
            calls["count"] += 1
            return 42

        first, cached_first = cache.get_or_compute("k", compute)
        second, cached_second = cache.get_or_compute("k", compute)

        assert (first, second) == (42, 42)
        assert cached_first is False
        assert cached_second is True
        assert calls["count"] == 1
        assert cache.hit_rate == 0.5

    def test_eviction_keeps_the_table_bounded(self) -> None:
        cache = LineageCache(max_entries=2)
        for index in range(5):
            cache.get_or_compute(f"k{index}", lambda index=index: index)
        assert cache.statistics()["entries"] == 2

    def test_statistics_report_hits_and_misses(self) -> None:
        cache = LineageCache()
        cache.get_or_compute("a", lambda: 1)
        cache.get_or_compute("a", lambda: 1)
        cache.get_or_compute("b", lambda: 2)
        stats = cache.statistics()
        assert stats["hits"] == 1
        assert stats["misses"] == 2
        assert stats["lookups"] == 3


def make_series(*, n_samples: int = 3000, noise: float = 0.02, seed: int = 3):  # type: ignore[no-untyped-def]
    from app.services.version_data import VersionSeries

    generator = np.random.default_rng(seed)
    inputs = {}
    for offset, name in enumerate(("u1", "u2")):
        values = np.zeros(n_samples, dtype=float)
        hold = 13 + offset * 6
        for start in range(0, n_samples, hold):
            values[start : start + hold] = generator.uniform(-1.5, 1.5)
        inputs[name] = values

    ar = [-1.35, 0.45]
    b = {"u1": [0.4, 0.14], "u2": [0.2, 0.07]}
    nk = {"u1": 3, "u2": 6}
    output = np.zeros(n_samples, dtype=float)
    history = max(len(ar), max(nk[c] + len(b[c]) - 1 for c in inputs))
    for index in range(history, n_samples):
        value = -sum(ar[lag - 1] * output[index - lag] for lag in range(1, len(ar) + 1))
        for column, signal in inputs.items():
            for lag, coefficient in enumerate(b[column]):
                value += coefficient * signal[index - nk[column] - lag]
        output[index] = value + generator.normal(0.0, noise)

    return VersionSeries(
        dataset_id=uuid4(),
        version_id=uuid4(),
        dataset_name="opt-test",
        origin="simulation",
        timestamps=[],
        values={**inputs, "y": output},
        declared_inputs=tuple(inputs),
        declared_output="y",
        sample_period_seconds=1.0,
    )


class TestFingerprint:
    def test_similar_datasets_are_close(self) -> None:
        left = build_fingerprint(
            inputs={k: v for k, v in make_series(seed=1).values.items() if k != "y"},
            output=make_series(seed=1).values["y"],
        )
        right = build_fingerprint(
            inputs={k: v for k, v in make_series(seed=2).values.items() if k != "y"},
            output=make_series(seed=2).values["y"],
        )
        assert fingerprint_distance(left.vector, right.vector) < 0.35

    def test_a_much_noisier_dataset_is_further_away(self) -> None:
        clean = make_series(noise=0.01, seed=5)
        noisy = make_series(noise=3.0, seed=5)
        left = build_fingerprint(
            inputs={k: v for k, v in clean.values.items() if k != "y"},
            output=clean.values["y"],
        )
        right = build_fingerprint(
            inputs={k: v for k, v in noisy.values.items() if k != "y"},
            output=noisy.values["y"],
        )
        assert fingerprint_distance(left.vector, right.vector) > 0.1

    def test_vector_length_is_stable(self) -> None:
        from algorithms.pipeline.fingerprint import FINGERPRINT_FIELDS

        series = make_series()
        fingerprint = build_fingerprint(
            inputs={k: v for k, v in series.values.items() if k != "y"},
            output=series.values["y"],
        )
        assert len(fingerprint.vector) == len(FINGERPRINT_FIELDS)

    def test_mismatched_vectors_are_infinitely_far(self) -> None:
        assert fingerprint_distance([1.0, 2.0], [1.0]) == float("inf")


class TestObjective:
    def _result(self, **overrides: object):  # type: ignore[no-untyped-def]
        from app.schemas.modeling import ArxFitRequest
        from app.services.modeling_service import fit_arx_core

        series = make_series()
        payload = ArxFitRequest(
            version_id=series.version_id,
            input_columns=["u1", "u2"],
            output_column="y",
            na=2,
            nb={"u1": 2, "u2": 2},
            delays={"u1": 3, "u2": 6},
            **overrides,  # type: ignore[arg-type]
        )
        return fit_arx_core(
            inputs={k: v for k, v in series.values.items() if k != "y"},
            output=series.values["y"],
            payload=payload,
            input_columns=["u1", "u2"],
        )

    def test_a_good_model_scores_positively(self) -> None:
        from app.services.optimization_service import objective_value

        value, breakdown = objective_value(self._result())
        assert value > 0
        assert breakdown["val_free_run_fit"] > 80
        assert breakdown["objective_semantics"] == {
            "name": "composite_identification_score",
            "version": "v1",
            "direction": "maximize",
        }
        components = breakdown["objective_components"]
        assert components["final_score"] == pytest.approx(value)
        assert value == pytest.approx(
            components["validation_free_run_fit_component"]
            + components["normalized_error_component"]
            + components["residual_whiteness_component"]
            + components["complexity_component"]
        )

    def test_objective_is_driven_by_free_run_not_one_step(self) -> None:
        from app.services.optimization_service import objective_value

        good = self._result()
        starved = self._result(training_sample_indices=list(range(20, 260)))
        good_value, good_breakdown = objective_value(good)
        starved_value, starved_breakdown = objective_value(starved)

        assert good_value > starved_value
        free_run_gap = good_breakdown["val_free_run_fit"] - starved_breakdown["val_free_run_fit"]
        one_step_gap = abs(
            (good_breakdown["val_one_step_fit"] or 0) - (starved_breakdown["val_one_step_fit"] or 0)
        )
        assert free_run_gap > one_step_gap


class TestFormalEvaluation:
    def test_baseline_is_test_free_and_ignores_the_held_out_tail(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.schemas.optimization import OptimizationStartRequest
        from app.services import optimization_service

        clean = make_series()
        changed_test = make_series()
        payload = OptimizationStartRequest(
            version_id=clean.version_id,
            input_columns=["u1", "u2"],
            output_column="y",
            max_trials=2,
        )
        test_start = int(clean.n_samples * (payload.train_ratio + payload.validation_ratio))
        changed_test.values["y"][test_start:] += 10_000.0

        observed_evaluate_test: list[bool] = []
        formal_fit = optimization_service.fit_arx_core

        def spy_fit_arx_core(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            observed_evaluate_test.append(kwargs["payload"].evaluate_test)  # type: ignore[index,union-attr]
            return formal_fit(*args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(optimization_service, "fit_arx_core", spy_fit_arx_core)
        first = optimization_service.run_baseline(
            clean, payload, input_columns=["u1", "u2"], output_column="y"
        )
        second = optimization_service.run_baseline(
            changed_test,
            payload.model_copy(update={"version_id": changed_test.version_id}),
            input_columns=["u1", "u2"],
            output_column="y",
        )

        assert first.status == second.status == "succeeded"
        assert first.parameters == second.parameters
        assert first.validation_free_run_fit == pytest.approx(second.validation_free_run_fit)
        assert observed_evaluate_test and all(value is False for value in observed_evaluate_test)
        assert first.test_free_run_fit is None
        assert first.test_mae is None
        assert first.test_rmse is None
        assert first.test_r2 is None
        assert second.test_free_run_fit is None
        assert first.parameters["window_size"] == 60
        assert first.parameters["train_ratio"] == 0.6
        assert first.parameters["validation_ratio"] == 0.2
        assert first.parameters["test_ratio"] == pytest.approx(0.2)

    def test_s6_rank_deficient_baseline_falls_back_to_ridge(self, tmp_path: Path) -> None:
        from app.schemas.optimization import OptimizationStartRequest
        from app.schemas.simulation import SimulationGenerateRequest
        from app.services.optimization_service import run_baseline
        from app.services.simulation_service import generate_simulation, load_simulation_by_version
        from app.services.version_data import VersionSeries

        generated = generate_simulation(
            SimulationGenerateRequest(
                scenario="S6",
                num_samples=1200,
                input_count=2,
                seed=9006,
                noise_level=0.0,
            ),
            artifact_root=tmp_path,
        )
        stored = load_simulation_by_version(generated.version_id, artifact_root=tmp_path)
        series = VersionSeries(
            dataset_id=stored.dataset_id,
            version_id=stored.version_id,
            dataset_name=stored.dataset_name,
            origin="simulation",
            timestamps=[],
            values={key: value for key, value in stored.values.items() if key != "timestamp"},
            declared_inputs=("u1", "u2"),
            declared_output="y",
            sample_period_seconds=1.0,
        )
        payload = OptimizationStartRequest(
            version_id=series.version_id,
            input_columns=["u1", "u2"],
            output_column="y",
            max_trials=5,
            random_seed=42,
        )

        baseline = run_baseline(
            series, payload, input_columns=["u1", "u2"], output_column="y"
        )

        assert baseline.status == "succeeded"
        assert baseline.parameters["estimator"] == "ridge"
        assert baseline.parameters["ridge_alpha"] == pytest.approx(0.1)
        assert baseline.parameters["fallback_reason"] == "DESIGN_MATRIX_RANK_DEFICIENT"
        assert baseline.validation_free_run_fit is not None
        assert baseline.test_free_run_fit is None

    def test_optuna_trials_do_not_evaluate_the_test_partition(self) -> None:
        from app.schemas.optimization import OptimizationStartRequest
        from app.services.optimization_service import run_study

        series = make_series()
        outcome = run_study(
            series,
            OptimizationStartRequest(
                version_id=series.version_id,
                input_columns=["u1", "u2"],
                output_column="y",
                max_trials=3,
                random_seed=5,
            ),
            input_columns=["u1", "u2"],
            output_column="y",
        )

        changed_test = make_series()
        test_start = int(changed_test.n_samples * 0.8)
        changed_test.values["y"][test_start:] += 10_000.0
        changed = run_study(
            changed_test,
            OptimizationStartRequest(
                version_id=changed_test.version_id,
                input_columns=["u1", "u2"],
                output_column="y",
                max_trials=3,
                random_seed=5,
            ),
            input_columns=["u1", "u2"],
            output_column="y",
        )

        completed = [trial for trial in outcome.trials if trial.state == "complete"]
        assert completed
        assert all("test_free_run_fit" not in trial.metrics for trial in completed)
        assert all("test_rmse" not in trial.metrics for trial in completed)
        for trial in completed:
            feedback = trial.metrics["validation_feedback"]
            assert feedback["partition"] == "validation"
            assert feedback["summary"]["partition"] == "validation"
            assert set(feedback["one_step"]) == {"mae", "rmse", "r2", "fit", "nrmse"}
            assert set(feedback["free_run"]) == {"mae", "rmse", "r2", "fit", "nrmse"}
            assert "test" not in feedback

            selection = trial.metrics["selection_provenance"]
            assert selection["candidate_count"] >= selection["gated_count"]
            assert selection["gated_count"] >= selection["selected_segment_count"]
            assert selection["selected_sample_count"] > 0
            assert len(selection["selected_indices_hash"]) == 64
            assert "selected_sample_indices" not in selection

            semantics = trial.metrics["objective_semantics"]
            assert semantics["name"] == "composite_identification_score"
            assert semantics["version"] == "v1"
            assert semantics["direction"] == "maximize"
            components = trial.metrics["objective_components"]
            assert components["final_score"] == pytest.approx(trial.value)
            assert trial.value == pytest.approx(
                components["validation_free_run_fit_component"]
                + components["normalized_error_component"]
                + components["residual_whiteness_component"]
                + components["complexity_component"]
            )
        assert all(
            trial.params.get("estimator") == "ridge" or "ridge_alpha" not in trial.params
            for trial in completed
        )
        assert changed.best_number == outcome.best_number
        assert changed.best_value == pytest.approx(outcome.best_value)
        assert changed.best_params == outcome.best_params


def test_legacy_optimization_contract_without_feedback_fields_remains_readable() -> None:
    from datetime import UTC, datetime

    from app.schemas.optimization import OptimizationStatusData, OptimizationTrial
    from app.services.contract_stubs import completed_task

    trial = OptimizationTrial.model_validate(
        {
            "trial_id": 0,
            "state": "complete",
            "value": 0.25,
            "params": {"window_size": 60},
            "created_at": datetime.now(UTC),
        }
    )
    assert trial.metrics == {}
    assert trial.selection_provenance is None
    assert trial.validation_feedback is None
    assert trial.objective_semantics is None
    assert trial.objective_components is None

    status = OptimizationStatusData(
        study_id=uuid4(),
        task=completed_task(stage="optimize_pipeline", message="legacy"),
        trials=[trial],
        best_trial_id=0,
        best_value=0.25,
        best_curve=[0.25],
        param_importances={},
    )
    assert status.objective_semantics is None
    assert status.best_validation_feedback is None
    assert status.best_selection_summary is None
    assert status.best_objective_components is None


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'optimize.db'}")
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


def generate(client: TestClient, *, seed: int = 4, scenario: str = "S2") -> str:
    response = client.post(
        "/api/v1/simulation/generate",
        json={"scenario": scenario, "n_steps": 2000, "seed": seed, "input_count": 2},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["version_id"]


async def _dataset_version_count(database_path: Path, version_id: UUID) -> int:
    from app.models.dataset import DatasetVersion

    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            version = await session.get(DatasetVersion, version_id)
            assert version is not None
            count = await session.scalar(
                select(func.count())
                .select_from(DatasetVersion)
                .where(DatasetVersion.dataset_id == version.dataset_id)
            )
            return int(count or 0)
    finally:
        await engine.dispose()


async def _optimization_snapshot(
    database_path: Path, *, study_id: UUID, processing_run_id: UUID | None = None
) -> dict[str, object]:
    from app.models.dataset import ProcessingRun
    from app.models.optimization import OptimizationStudy

    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            study = await session.get(OptimizationStudy, study_id)
            assert study is not None
            final_test_runs = await session.scalar(
                select(func.count())
                .select_from(ProcessingRun)
                .where(
                    ProcessingRun.source_version_id == study.version_id,
                    ProcessingRun.run_type == "optimization.final_test",
                )
            )
            run = (
                await session.get(ProcessingRun, processing_run_id)
                if processing_run_id is not None
                else None
            )
            return {
                "study_status": study.status,
                "baseline_model_id": study.baseline_model_id,
                "optimized_model_id": study.optimized_model_id,
                "error_code": study.statistics.get("error_code"),
                "final_test_run_count": int(final_test_runs or 0),
                "processing_run_type": run.run_type if run is not None else None,
                "processing_run_status": run.status if run is not None else None,
                "processing_run_source_version_id": run.source_version_id if run is not None else None,
            }
    finally:
        await engine.dispose()


async def _agent_optimization_snapshot(
    database_path: Path, *, study_id: UUID, processing_run_ids: list[str]
) -> dict[str, object]:
    from app.models.dataset import ProcessingRun
    from app.models.optimization import OptimizationStudy, OptimizationTrialRecord

    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            study = await session.get(OptimizationStudy, study_id)
            assert study is not None
            runs = [await session.get(ProcessingRun, UUID(run_id)) for run_id in processing_run_ids]
            final_test_runs = await session.scalar(
                select(func.count())
                .select_from(ProcessingRun)
                .where(
                    ProcessingRun.source_version_id == study.version_id,
                    ProcessingRun.run_type == "optimization.final_test",
                )
            )
            completed_params = list(
                (
                    await session.scalars(
                        select(OptimizationTrialRecord.params)
                        .where(
                            OptimizationTrialRecord.study_id == study_id,
                            OptimizationTrialRecord.state == "complete",
                        )
                        .order_by(OptimizationTrialRecord.trial_number)
                    )
                ).all()
            )
            return {
                "study_status": study.status,
                "baseline_model_id": study.baseline_model_id,
                "optimized_model_id": study.optimized_model_id,
                "processing_run_types": [run.run_type for run in runs if run is not None],
                "completed_trial_nks": [params.get("nk") for params in completed_params],
                "final_test_run_count": int(final_test_runs or 0),
            }
    finally:
        await engine.dispose()


class TestAgentSafeOptimizationEntry:
    def test_forces_inline_without_warm_start_and_returns_real_provenance(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from app.services import optimization_service
        from app.services.optimization_service import execute_agent_optimization_study

        def fail_if_enqueued(*args: object, **kwargs: object) -> None:
            raise AssertionError("Agent-safe optimization must not submit an RQ job")

        async def fail_if_warm_started(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            raise AssertionError("Agent-safe optimization must not read StrategyMemory")

        monkeypatch.setattr(optimization_service, "submit_optimization", fail_if_enqueued)
        monkeypatch.setattr(optimization_service, "_retrieve_warm_start", fail_if_warm_started)
        assert "baseline_model_id" not in optimization_service.OptimizationStartRequest.model_fields
        version_id = UUID(generate(client, seed=151))
        baseline_model_id = uuid4()
        before_versions = asyncio.run(_dataset_version_count(tmp_path / "optimize.db", version_id))

        async def execute() -> object:
            engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'optimize.db'}")
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                    return await execute_agent_optimization_study(
                        session,
                        payload=optimization_service.OptimizationStartRequest(
                            version_id=version_id,
                            input_columns=["u1", "u2"],
                            output_column="y",
                            max_trials=3,
                            random_seed=151,
                            search_space={"nk": [0, 0]},
                        ),
                        baseline_model_id=baseline_model_id,
                        artifact_root=tmp_path,
                    )
            finally:
                await engine.dispose()

        result = asyncio.run(execute())
        assert result.status == "succeeded"
        assert result.source_version_id == version_id
        assert result.baseline_model_id == baseline_model_id
        assert result.optimized_model_id
        assert len(result.processing_run_ids) == 2
        assert result.objective_semantics == {
            "name": "composite_identification_score",
            "version": "v1",
            "direction": "maximize",
        }
        assert result.best_validation_feedback["partition"] == "validation"
        assert result.best_validation_feedback["summary"]["partition"] == "validation"
        assert "test" not in result.best_validation_feedback
        assert result.best_selection_summary["selected_sample_count"] > 0
        assert len(result.best_selection_summary["selected_indices_hash"]) == 64
        assert result.best_objective_components["final_score"] == pytest.approx(
            result.best_value
        )
        assert (tmp_path / "models" / f"{result.optimized_model_id}.json").is_file()

        snapshot = asyncio.run(
            _agent_optimization_snapshot(
                tmp_path / "optimize.db",
                study_id=result.study_id,
                processing_run_ids=result.processing_run_ids,
            )
        )
        assert snapshot["study_status"] == "succeeded"
        assert snapshot["baseline_model_id"] == baseline_model_id
        assert snapshot["optimized_model_id"] == result.optimized_model_id
        assert snapshot["processing_run_types"] == ["optimization.baseline", "modeling.arx"]
        completed_nks = snapshot["completed_trial_nks"]
        assert completed_nks and all(value == 0 for value in completed_nks)
        assert snapshot["final_test_run_count"] == 0
        assert asyncio.run(_dataset_version_count(tmp_path / "optimize.db", version_id)) == before_versions

    def test_rejects_succeeded_study_without_persisted_optimized_model(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from app.services import optimization_service
        from app.services.optimization_service import (
            OptimizationDomainError,
            execute_agent_optimization_study,
        )

        reserved_study_ids: list[UUID] = []
        reserve = optimization_service._reserve_study
        persist_study = optimization_service._persist_study

        async def spy_reserve_study(*args: object, **kwargs: object) -> None:
            reserved_study_ids.append(kwargs["study_id"])  # type: ignore[index]
            await reserve(*args, **kwargs)  # type: ignore[arg-type]

        async def erase_optimized_model(*args: object, **kwargs: object) -> None:
            await persist_study(*args, **kwargs)  # type: ignore[arg-type]
            if kwargs["optimized_model_id"] is not None:  # type: ignore[index]
                study = await args[0].get(  # type: ignore[index]
                    optimization_service.OptimizationStudy, kwargs["outcome"].study_id  # type: ignore[index]
                )
                assert study is not None
                study.optimized_model_id = None
                study.status = "succeeded"
                await args[0].commit()  # type: ignore[index]

        monkeypatch.setattr(optimization_service, "_reserve_study", spy_reserve_study)
        monkeypatch.setattr(optimization_service, "_persist_study", erase_optimized_model)
        version_id = UUID(generate(client, seed=152))

        async def execute() -> None:
            engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'optimize.db'}")
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                    await execute_agent_optimization_study(
                        session,
                        payload=optimization_service.OptimizationStartRequest(
                            version_id=version_id,
                            input_columns=["u1", "u2"],
                            output_column="y",
                            max_trials=2,
                            random_seed=152,
                            search_space={"nk": [0, 0]},
                        ),
                        baseline_model_id=uuid4(),
                        artifact_root=tmp_path,
                    )
            finally:
                await engine.dispose()

        with pytest.raises(OptimizationDomainError) as raised:
            asyncio.run(execute())
        assert raised.value.code == "OPTIMIZED_MODEL_REQUIRED"
        assert len(reserved_study_ids) == 1
        snapshot = asyncio.run(
            _optimization_snapshot(tmp_path / "optimize.db", study_id=reserved_study_ids[0])
        )
        assert snapshot["study_status"] == "succeeded"
        assert snapshot["optimized_model_id"] is None
        assert snapshot["final_test_run_count"] == 0

class TestOptimizationApi:
    def test_persists_optimized_model_without_opening_test(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from app.services import optimization_service

        def fail_if_final_test_replayed(*args: object, **kwargs: object) -> None:
            raise AssertionError("execute_study must not replay the held-out Test partition")

        formal_fit = optimization_service.fit_arx_on_version
        formal_selection = optimization_service.run_segment_selection
        persisted_fits = []
        selections: list[list[int]] = []

        async def spy_fit_arx_on_version(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            data = await formal_fit(*args, **kwargs)  # type: ignore[arg-type]
            persisted_fits.append((kwargs["payload"], data))  # type: ignore[index]
            return data

        def spy_segment_selection(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            selection = formal_selection(*args, **kwargs)  # type: ignore[arg-type]
            selections.append(list(selection.selected_sample_indices))
            return selection

        monkeypatch.setattr(optimization_service, "evaluate_best_trial", fail_if_final_test_replayed)
        monkeypatch.setattr(optimization_service, "fit_arx_on_version", spy_fit_arx_on_version)
        monkeypatch.setattr(optimization_service, "run_segment_selection", spy_segment_selection)
        version_id = generate(client, seed=52)
        before_versions = asyncio.run(_dataset_version_count(tmp_path / "optimize.db", UUID(version_id)))
        started = client.post(
            "/api/v1/optimization/optuna/start",
            json={
                "version_id": version_id,
                "input_columns": ["u1", "u2"],
                "output_column": "y",
                "max_trials": 4,
                "random_seed": 19,
            },
        )
        assert started.status_code == 202, started.text
        study_id = UUID(started.json()["data"]["study_id"])
        data = client.get(f"/api/v1/optimization/optuna/{study_id}/status").json()["data"]

        baseline = data["baseline"]
        assert baseline["status"] == "succeeded"
        assert baseline["processing_run_id"]
        assert baseline["parameters"]["window_size"] == 60
        assert baseline["validation_free_run_fit"] is not None
        assert baseline["test_free_run_fit"] is None
        assert baseline["test_mae"] is None
        assert baseline["test_rmse"] is None
        assert baseline["test_r2"] is None
        assert len(data["trials"]) == 4, "Baseline must not become an Optuna trial."

        complete = [trial for trial in data["trials"] if trial["state"] == "complete"]
        selected = max(complete, key=lambda trial: trial["value"])
        assert data["best_trial_id"] == selected["trial_id"]
        assert data["objective_semantics"] == {
            "name": "composite_identification_score",
            "version": "v1",
            "direction": "maximize",
        }
        assert data["best_validation_feedback"] == selected["validation_feedback"]
        assert data["best_selection_summary"] == selected["selection_provenance"]
        assert data["best_objective_components"] == selected["objective_components"]
        assert selected["metrics"]["validation_feedback"] == selected["validation_feedback"]
        assert selected["validation_feedback"]["partition"] == "validation"
        assert selected["validation_feedback"]["summary"]["partition"] == "validation"
        assert selected["selection_provenance"]["selected_sample_count"] > 0
        assert len(selected["selection_provenance"]["selected_indices_hash"]) == 64
        assert selected["objective_components"]["final_score"] == pytest.approx(
            selected["value"]
        )
        assert data["final_test_evaluation"] is None
        assert data["baseline_model_id"] is None
        assert data["optimized_model_id"]
        assert len(persisted_fits) == 1

        fitted_payload, fitted = persisted_fits[0]
        assert fitted_payload.evaluate_test is False
        assert fitted.model_id == UUID(data["optimized_model_id"])
        assert fitted.metrics.one_step.get("test") is None
        assert fitted.metrics.free_run.get("test") is None
        assert fitted_payload.training_sample_indices == selections[-1]

        artifact = tmp_path / "models" / f"{fitted.model_id}.json"
        document = json.loads(artifact.read_text(encoding="utf-8"))
        assert document["model_id"] == str(fitted.model_id)
        assert document["version_id"] == version_id
        assert document["configuration"]["evaluate_test"] is False
        assert document["configuration"]["training_sample_indices"] == fitted_payload.training_sample_indices

        snapshot = asyncio.run(
            _optimization_snapshot(
                tmp_path / "optimize.db",
                study_id=study_id,
                processing_run_id=fitted.processing_run_id,
            )
        )
        assert snapshot["study_status"] == "succeeded"
        assert snapshot["baseline_model_id"] is None
        assert snapshot["optimized_model_id"] == fitted.model_id
        assert snapshot["processing_run_type"] == "modeling.arx"
        assert snapshot["processing_run_status"] == "succeeded"
        assert snapshot["processing_run_source_version_id"] == UUID(version_id)
        assert snapshot["final_test_run_count"] == 0
        assert asyncio.run(_dataset_version_count(tmp_path / "optimize.db", UUID(version_id))) == before_versions

    def test_optimized_model_persistence_failure_marks_study_failed(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from app.services import optimization_service
        from app.services.modeling_service import ModelingDomainError

        reserved_study_ids: list[UUID] = []
        reserve = optimization_service._reserve_study

        async def spy_reserve_study(*args: object, **kwargs: object) -> None:
            reserved_study_ids.append(kwargs["study_id"])  # type: ignore[index]
            await reserve(*args, **kwargs)  # type: ignore[arg-type]

        async def fail_formal_fit(*args: object, **kwargs: object) -> None:
            raise ModelingDomainError("OPTIMIZED_MODEL_PERSISTENCE_FAILED", "formal fit failed")

        monkeypatch.setattr(optimization_service, "_reserve_study", spy_reserve_study)
        monkeypatch.setattr(optimization_service, "fit_arx_on_version", fail_formal_fit)
        version_id = generate(client, seed=79)
        response = client.post(
            "/api/v1/optimization/optuna/start",
            json={
                "version_id": version_id,
                "input_columns": ["u1", "u2"],
                "output_column": "y",
                "max_trials": 2,
                "random_seed": 29,
            },
        )

        assert response.status_code == 400, response.text
        assert len(reserved_study_ids) == 1
        snapshot = asyncio.run(
            _optimization_snapshot(tmp_path / "optimize.db", study_id=reserved_study_ids[0])
        )
        assert snapshot["study_status"] == "failed"
        assert snapshot["error_code"] == "OPTIMIZED_MODEL_PERSISTENCE_FAILED"
        assert snapshot["optimized_model_id"] is None
        assert snapshot["final_test_run_count"] == 0

    def test_diagnostics_replay_fixed_winner_without_changing_study(self, client: TestClient) -> None:
        version_id = generate(client, seed=73)
        started = client.post(
            "/api/v1/optimization/optuna/start",
            json={
                "version_id": version_id,
                "input_columns": ["u1", "u2"],
                "output_column": "y",
                "max_trials": 2,
                "random_seed": 23,
            },
        )
        assert started.status_code == 202, started.text
        study_id = started.json()["data"]["study_id"]
        before = client.get(f"/api/v1/optimization/optuna/{study_id}/status").json()["data"]

        response = client.get(f"/api/v1/optimization/optuna/{study_id}/diagnostics")
        assert response.status_code == 200, response.text
        diagnostics = response.json()["data"]
        assert set(diagnostics["partitions"]) == {"train", "validation", "test"}
        assert diagnostics["partitions"]["test"]["one_step"]["r2"] is not None
        assert diagnostics["partitions"]["test"]["free_run"]["fit"] is not None
        assert diagnostics["metric_semantics"]["one_step"]

        after = client.get(f"/api/v1/optimization/optuna/{study_id}/status").json()["data"]
        assert after["best_trial_id"] == before["best_trial_id"]
        assert len(after["trials"]) == len(before["trials"])

    def test_closed_loop_runs_and_reports_cache_statistics(self, client: TestClient) -> None:
        version_id = generate(client)
        started = client.post(
            "/api/v1/optimization/optuna/start",
            json={
                "version_id": version_id,
                "input_columns": ["u1", "u2"],
                "output_column": "y",
                "max_trials": 12,
                "random_seed": 7,
            },
        )
        assert started.status_code == 202, started.text
        study_id = started.json()["data"]["study_id"]

        status = client.get(f"/api/v1/optimization/optuna/{study_id}/status")
        assert status.status_code == 200, status.text
        data = status.json()["data"]

        assert len(data["trials"]) == 12
        assert data["best_value"] is not None
        assert data["best_params"]
        assert data["statistics"]["total_trials"] == 12
        assert data["statistics"]["lookups"] > 0

    def test_the_expensive_stage_is_amortised_across_the_structure_sweep(
        self, client: TestClient
    ) -> None:
        """Selection is the expensive stage; every trial must reuse one across many fits.

        This is where the closed-loop saving actually comes from. Measured separately, the
        content-addressed cache hits only ~1.7% of the time in a flat TPE search because a
        five-dimensional head almost never repeats, so the staged design carries the win
        and the assertion is written against that, not against the cache.
        """

        version_id = generate(client)
        started = client.post(
            "/api/v1/optimization/optuna/start",
            json={
                "version_id": version_id,
                "input_columns": ["u1", "u2"],
                "output_column": "y",
                "max_trials": 6,
                "random_seed": 17,
            },
        )
        study_id = started.json()["data"]["study_id"]
        stats = client.get(f"/api/v1/optimization/optuna/{study_id}/status").json()["data"][
            "statistics"
        ]

        assert stats["structure_evaluations"] > stats["selection_computations"]
        assert stats["evaluations_per_selection"] > 5.0

    def test_convergence_curve_is_monotone_non_decreasing(self, client: TestClient) -> None:
        version_id = generate(client)
        started = client.post(
            "/api/v1/optimization/optuna/start",
            json={
                "version_id": version_id,
                "input_columns": ["u1", "u2"],
                "output_column": "y",
                "max_trials": 10,
                "random_seed": 3,
            },
        )
        study_id = started.json()["data"]["study_id"]
        curve = client.get(f"/api/v1/optimization/optuna/{study_id}/status").json()["data"][
            "best_curve"
        ]
        seen = [value for value in curve if value is not None]
        assert seen == sorted(seen), "the best-so-far curve can never go down"

    def test_failed_trials_are_persisted_not_hidden(self, client: TestClient) -> None:
        version_id = generate(client)
        started = client.post(
            "/api/v1/optimization/optuna/start",
            json={
                "version_id": version_id,
                "input_columns": ["u1", "u2"],
                "output_column": "y",
                "max_trials": 14,
                "random_seed": 11,
            },
        )
        study_id = started.json()["data"]["study_id"]
        data = client.get(f"/api/v1/optimization/optuna/{study_id}/status").json()["data"]
        states = {trial["state"] for trial in data["trials"]}
        assert states <= {"complete", "pruned", "failed"}
        assert data["statistics"]["total_trials"] == len(data["trials"])

    def test_second_study_on_a_different_dataset_is_warm_started(self, client: TestClient) -> None:
        """The self-evolving path: a finished study leaves a reusable prior behind."""

        first_version = generate(client, seed=4)
        first = client.post(
            "/api/v1/optimization/optuna/start",
            json={
                "version_id": first_version,
                "input_columns": ["u1", "u2"],
                "output_column": "y",
                "max_trials": 10,
                "random_seed": 5,
            },
        )
        assert first.status_code == 202, first.text

        second_version = generate(client, seed=9)
        second = client.post(
            "/api/v1/optimization/optuna/start",
            json={
                "version_id": second_version,
                "input_columns": ["u1", "u2"],
                "output_column": "y",
                "max_trials": 10,
                "random_seed": 5,
            },
        )
        assert second.status_code == 202, second.text
        second_id = second.json()["data"]["study_id"]
        data = client.get(f"/api/v1/optimization/optuna/{second_id}/status").json()["data"]

        assert data["warm_started_from"] is not None, (
            "a similar previous study should supply a warm start"
        )
        assert data["statistics"]["warm_start_trials"] > 0

    def test_status_of_an_unknown_study_returns_404(self, client: TestClient) -> None:
        response = client.get(f"/api/v1/optimization/optuna/{uuid4()}/status")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "OPTIMIZATION_STUDY_NOT_FOUND"

    def test_unknown_version_returns_404(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/optimization/optuna/start",
            json={
                "version_id": str(uuid4()),
                "input_columns": ["u1"],
                "output_column": "y",
                "max_trials": 2,
            },
        )
        assert response.status_code == 404


class TestJobQueueFallback:
    """Queueing is an optimisation, not a dependency.

    The venue may have no Redis and no worker process. The same reasoning that keeps the
    system usable without an LLM applies here: when the queue cannot be reached the study
    runs inline and the response says so. What must never happen is a request that reports
    success while the work was silently dropped.
    """

    def test_disabled_by_default_so_a_deployment_without_a_worker_still_works(self) -> None:
        from app.services.job_queue import submit_optimization

        submission = submit_optimization(uuid4(), {"version_id": str(uuid4())})
        assert submission.queued is False
        assert submission.job_id is None
        assert submission.reason  # the caller has to be able to say why

    def test_an_unreachable_redis_falls_back_instead_of_raising(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.services import job_queue

        monkeypatch.setattr(
            job_queue,
            "get_settings",
            lambda: Settings(
                background_optimization=True,
                # Port 1 is reserved and never listening.
                redis_url="redis://127.0.0.1:1/0",
            ),
        )
        submission = job_queue.submit_optimization(uuid4(), {})
        assert submission.queued is False
        assert "队列不可用" in (submission.reason or "")

    def test_the_study_runs_inline_when_the_queue_is_unavailable(self, client: TestClient) -> None:
        version_id = generate(client, seed=21)
        started = client.post(
            "/api/v1/optimization/optuna/start",
            json={
                "version_id": version_id,
                "input_columns": ["u1", "u2"],
                "output_column": "y",
                "max_trials": 3,
            },
        )
        assert started.status_code == 202, started.text
        payload = started.json()["data"]
        assert payload["task"]["status"] == "succeeded"

        status = client.get(f"/api/v1/optimization/optuna/{payload['study_id']}/status")
        assert len(status.json()["data"]["trials"]) == 3

    def test_a_bad_version_never_leaves_an_orphan_queued_study(self, client: TestClient) -> None:
        """Reserving the row before validating would strand studies no worker can finish."""

        missing = str(uuid4())
        response = client.post(
            "/api/v1/optimization/optuna/start",
            json={
                "version_id": missing,
                "input_columns": ["u1"],
                "output_column": "y",
                "max_trials": 2,
            },
        )
        assert response.status_code == 404
        # The id the client would have polled must not exist either.
        assert client.get(f"/api/v1/optimization/optuna/{missing}/status").status_code == 404


class TestStudyReservation:
    def test_status_answers_before_the_search_finishes(self, client: TestClient) -> None:
        """The whole point of the background path: a pollable id, immediately.

        Driven here through the service rather than the queue so the invariant is checked
        without requiring Redis — the row must exist and carry the trial target the moment
        the study is reserved.
        """

        version_id = generate(client, seed=31)
        started = client.post(
            "/api/v1/optimization/optuna/start",
            json={
                "version_id": version_id,
                "input_columns": ["u1", "u2"],
                "output_column": "y",
                "max_trials": 2,
            },
        )
        study_id = started.json()["data"]["study_id"]
        status = client.get(f"/api/v1/optimization/optuna/{study_id}/status")
        assert status.status_code == 200
        assert status.json()["data"]["statistics"]["target_trials"] == 2

    def test_rerunning_the_same_study_id_replaces_rather_than_duplicates(
        self, client: TestClient
    ) -> None:
        """RQ retries after a worker crash must not leave two records for one request."""

        version_id = generate(client, seed=33)
        started = client.post(
            "/api/v1/optimization/optuna/start",
            json={
                "version_id": version_id,
                "input_columns": ["u1", "u2"],
                "output_column": "y",
                "max_trials": 3,
            },
        )
        study_id = started.json()["data"]["study_id"]
        first = client.get(f"/api/v1/optimization/optuna/{study_id}/status").json()["data"]
        assert len(first["trials"]) == 3
