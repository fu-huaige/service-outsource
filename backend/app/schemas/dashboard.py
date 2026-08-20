from uuid import UUID

from pydantic import Field

from app.schemas.common import Schema


class LeaderboardEntry(Schema):
    dataset_id: UUID
    dataset_name: str
    version_id: UUID
    study_id: UUID
    status: str
    baseline_fit: float = Field(description="该研究首个完成 trial 的验证自由仿真 FIT。")
    optimized_fit: float = Field(description="最优 trial 的验证自由仿真 FIT。")
    improvement: float
    validation_fit: float
    test_fit: float | None = None
    generalization_gap: float | None = None
    contribution_summary: str | None = None


class DashboardLeaderboardData(Schema):
    items: list[LeaderboardEntry] = Field(default_factory=list)
