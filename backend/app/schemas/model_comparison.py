"""Public contracts for comparisons of persisted model evaluations."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.common import Schema
from app.schemas.experiment_spec import Digest
from app.schemas.model_evaluation import (
    EvaluationModelType,
    EvaluationPartition,
    MetricAggregation,
    MetricName,
    RegressionMetrics,
)


class ModelComparisonRequest(Schema):
    evaluation_run_ids: tuple[UUID, ...] = Field(min_length=2, max_length=10)

    @model_validator(mode="after")
    def check_unique_ids(self) -> Self:
        if len(set(self.evaluation_run_ids)) != len(self.evaluation_run_ids):
            raise ValueError("Evaluation run IDs must be distinct")
        return self


class ModelComparisonScope(Schema):
    dataset_id: UUID
    dataset_version_id: UUID
    dataset_sha256: Digest
    partition: EvaluationPartition
    target_column: str
    prediction_length: int
    sample_counts_by_horizon: tuple[int, ...]
    evaluation_count: int


Rank = Annotated[int, Field(ge=1)]


class RankingEntry(Schema):
    evaluation_run_id: UUID
    model_id: UUID
    value: float
    rank: Rank


class RankedHorizon(Schema):
    horizon_step: int
    metrics: RegressionMetrics
    ranks: dict[MetricName, Rank | None]


class HorizonRanking(Schema):
    horizon_step: int
    rankings: dict[MetricName, tuple[RankingEntry, ...]]


class ModelComparisonCandidate(Schema):
    evaluation_run_id: UUID
    model_id: UUID
    model_type: EvaluationModelType
    model_name: str
    feature_names: tuple[str, ...]
    sample_count: int
    metrics: RegressionMetrics
    ranks: dict[MetricName, Rank | None]
    horizons: tuple[RankedHorizon, ...] = ()
    metric_aggregation: MetricAggregation | None = None


class ModelComparisonResult(Schema):
    scope: ModelComparisonScope
    candidates: tuple[ModelComparisonCandidate, ...]
    rankings: dict[MetricName, tuple[RankingEntry, ...]]
    horizon_rankings: tuple[HorizonRanking, ...] = ()
    aggregation_method: Literal["macro_average"] | None = Field(
        default=None,
        description="Arithmetic mean of each metric over its defined forecast steps.",
    )
    compatibility: tuple[str, ...]
