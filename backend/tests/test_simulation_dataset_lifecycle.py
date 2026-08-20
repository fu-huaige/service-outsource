import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from uuid import UUID

import pytest
from app.core.config import Settings
from app.core.db import get_session
from app.main import create_app
from app.models import Base
from app.models.optimization import OptimizationStudy, OptimizationTrialRecord
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
def lifecycle_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'lifecycle.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def prepare() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(prepare())

    async def session_override() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    monkeypatch.setattr(
        "app.api.routes.get_settings",
        lambda: Settings(
            artifact_root=tmp_path,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'lifecycle.db'}",
        ),
    )
    app = create_app()
    app.state.session_factory = session_factory
    app.dependency_overrides[get_session] = session_override
    with TestClient(app) as client:
        yield client
    asyncio.run(engine.dispose())


def _generate(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/api/v1/simulation/generate",
        json={"scenario": "S2", "n_steps": 900, "input_count": 2, "seed": 2026},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def test_simulation_is_registered_as_dataset_version_profile_and_download(
    lifecycle_client: TestClient,
) -> None:
    generated = _generate(lifecycle_client)
    dataset_id = str(generated["dataset_id"])
    version_id = str(generated["version_id"])
    assert UUID(dataset_id).version == 4
    assert UUID(version_id).version == 4
    assert generated["download_url"] == f"/api/v1/datasets/{dataset_id}/download"

    detail = lifecycle_client.get(f"/api/v1/datasets/{dataset_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["source"] == "simulation"
    assert detail.json()["data"]["latest_version_id"] == version_id
    assert detail.json()["data"]["preview"]["rows"]

    profile = lifecycle_client.get(f"/api/v1/datasets/{dataset_id}/profile")
    assert profile.status_code == 200, profile.text
    assert profile.json()["data"]["version_id"] == version_id

    versions = lifecycle_client.get(f"/api/v1/datasets/{dataset_id}/versions")
    assert versions.status_code == 200, versions.text
    nodes = versions.json()["data"]["nodes"]
    assert len(nodes) == 1
    assert nodes[0]["id"] == version_id
    assert nodes[0]["tool"] == "simulation_generate"

    downloaded = lifecycle_client.get(str(generated["download_url"]))
    assert downloaded.status_code == 200
    assert len(downloaded.text.splitlines()) == 901
    assert downloaded.text.splitlines()[0] == "timestamp,u1,u2,y"


def test_simulation_report_and_empty_dashboard_use_real_asset_lifecycle(
    lifecycle_client: TestClient,
) -> None:
    assert lifecycle_client.get("/api/v1/dashboard/leaderboard").json()["data"]["items"] == []
    generated = _generate(lifecycle_client)
    version_id = str(generated["version_id"])

    segment = lifecycle_client.post(
        "/api/v1/preprocessing/segment",
        json={
            "version_id": version_id,
            "input_columns": ["u1", "u2"],
            "output_column": "y",
            "window_size": 60,
            "max_segments": 3,
        },
    )
    assert segment.status_code == 202, segment.text
    fitted = lifecycle_client.post(
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

    report = lifecycle_client.post("/api/v1/reports/generate", json={"version_id": version_id})
    assert report.status_code == 200, report.text
    artifact_uri = report.json()["data"]["artifact_uri"]
    assert artifact_uri


def test_dashboard_historical_study_never_invents_baseline_or_dataset_ids(
    lifecycle_client: TestClient,
) -> None:
    generated = _generate(lifecycle_client)
    dataset_id = str(generated["dataset_id"])
    version_id = str(generated["version_id"])

    async def seed_completed_study() -> None:
        session_factory = lifecycle_client.app.state.session_factory
        async with session_factory() as session:
            study = OptimizationStudy(
                id=UUID("11111111-1111-4111-8111-111111111111"),
                dataset_id=UUID(dataset_id),
                version_id=UUID(version_id),
                status="succeeded",
                objective="val_free_run_fit",
                parameters={},
                best_trial_number=1,
                best_value=0.6,
                best_params={"window_size": 60, "max_segments": 4, "nk": 3},
                fingerprint={},
                statistics={},
            )
            session.add(study)
            session.add_all(
                [
                    OptimizationTrialRecord(
                        study_id=study.id,
                        trial_number=0,
                        state="complete",
                        value=0.2,
                        params={},
                        metrics={"val_free_run_fit": 20.0},
                        cache_hit=False,
                    ),
                    OptimizationTrialRecord(
                        study_id=study.id,
                        trial_number=1,
                        state="complete",
                        value=0.6,
                        params={},
                        metrics={"val_free_run_fit": 60.0},
                        cache_hit=False,
                    ),
                ]
            )
            await session.commit()

    asyncio.run(seed_completed_study())
    response = lifecycle_client.get("/api/v1/dashboard/leaderboard")
    assert response.status_code == 200, response.text
    entries = response.json()["data"]["items"]
    assert len(entries) == 1
    assert entries[0]["dataset_id"] == dataset_id
    assert entries[0]["version_id"] == version_id
    assert entries[0]["baseline_available"] is False
    assert entries[0]["baseline_validation_fit"] is None
    assert entries[0]["optimized_validation_fit"] == 60.0
    assert entries[0]["optimized_test_fit"] is None
    assert entries[0]["improvement"] is None


def test_dashboard_reads_persisted_baseline_and_final_test_evaluation(
    lifecycle_client: TestClient,
) -> None:
    generated = _generate(lifecycle_client)
    dataset_id = UUID(str(generated["dataset_id"]))
    version_id = UUID(str(generated["version_id"]))

    async def seed_study() -> None:
        session_factory = lifecycle_client.app.state.session_factory
        async with session_factory() as session:
            study = OptimizationStudy(
                id=UUID("22222222-2222-4222-8222-222222222222"),
                dataset_id=dataset_id,
                version_id=version_id,
                status="succeeded",
                objective="val_free_run_fit",
                parameters={},
                best_trial_number=1,
                best_value=0.6,
                best_params={"window_size": 60, "max_segments": 4, "nk": 3},
                fingerprint={},
                statistics={
                    "evaluations": {
                        "baseline": {"validation_free_run_fit": 20.0},
                        "final_test": {
                            "test_free_run_fit": 40.0,
                            "test_one_step_fit": 80.0,
                            "test_one_step_r2": 0.96,
                            "test_free_run_r2": 0.64,
                            "generalization_gap": 20.0,
                        },
                    }
                },
            )
            session.add(study)
            session.add_all(
                [
                    OptimizationTrialRecord(
                        study_id=study.id,
                        trial_number=0,
                        state="complete",
                        value=0.2,
                        params={},
                        metrics={"val_free_run_fit": 88.0},
                        cache_hit=False,
                    ),
                    OptimizationTrialRecord(
                        study_id=study.id,
                        trial_number=1,
                        state="complete",
                        value=0.6,
                        params={},
                        metrics={"val_free_run_fit": 60.0},
                        cache_hit=False,
                    ),
                ]
            )
            await session.commit()

    asyncio.run(seed_study())
    entries = lifecycle_client.get("/api/v1/dashboard/leaderboard").json()["data"]["items"]
    entry = next(item for item in entries if item["study_id"] == "22222222-2222-4222-8222-222222222222")
    assert entry["baseline_validation_fit"] == 20.0
    assert entry["optimized_validation_fit"] == 60.0
    assert entry["optimized_test_fit"] == 40.0
    assert entry["optimized_test_one_step_fit"] == 80.0
    assert entry["optimized_test_one_step_r2"] == 0.96
    assert entry["optimized_test_free_run_r2"] == 0.64
    assert entry["improvement"] == 40.0
    assert entry["generalization_gap"] == 20.0
    assert entry["baseline_available"] is True
    assert entry["test_available"] is True
    assert entry["generalization_risk"] == "attention"
