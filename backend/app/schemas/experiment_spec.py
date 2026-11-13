"""Version-local CSV data-record positions, zero based; all ranges are [start, stop)."""

from __future__ import annotations

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    Field,
    SerializerFunctionWrapHandler,
    StrictInt,
    model_serializer,
    model_validator,
)

from app.schemas.common import Schema

Index = Annotated[StrictInt, Field(ge=0)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class RowRange(Schema):
    start: Index
    stop: Index

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.stop <= self.start:
            raise ValueError("RowRange must be nonempty and half-open")
        return self


def validate_ranges(ranges: tuple[RowRange, ...]) -> None:
    if any(left.stop > right.start for left, right in zip(ranges, ranges[1:], strict=False)):
        raise ValueError("Ranges must be sorted and non-overlapping")


class IndexFile(Schema):
    """UTF-8 decimal row IDs, one per line, strictly increasing; never a pickle."""

    uri: str = Field(min_length=1)
    sha256: Digest
    count: Index = Field(gt=0)


class RowSet(Schema):
    ranges: tuple[RowRange, ...] = Field(default=(), max_length=10000)
    index_file: IndexFile | None = None

    @model_validator(mode="after")
    def validate_selection(self) -> Self:
        validate_ranges(self.ranges)
        if bool(self.ranges) == (self.index_file is not None):
            raise ValueError("Specify nonempty ranges OR an index file")
        return self

    @property
    def count(self) -> int:
        return (
            self.index_file.count if self.index_file else sum(r.stop - r.start for r in self.ranges)
        )


class TimeAxis(Schema):
    column: str | None = None
    sample_period_seconds: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    sampling_status: Literal["uniform", "irregular", "unknown"] = "unknown"
    timestamp_policy: Literal["preserve_source"] = "preserve_source"


class FeatureSpec(Schema):
    """Row r is the target y[r]; each feature is read at r-lag, never r+lag.

    Horizon 1 denotes the existing one-step equation/static regression contract.
    Multi-step origins and feature-availability rules are not implemented yet.
    """

    kind: Literal["dynamic_lags", "tabular"]
    input_lags: dict[str, tuple[Index, ...]] = Field(default_factory=dict)
    target_lags: tuple[Annotated[StrictInt, Field(gt=0)], ...] = ()
    history_window: Index = 0
    prediction_horizon: Annotated[StrictInt, Field(ge=1, le=1)] = 1
    initialization_policy: Literal["fixed", "past_residual"] = "fixed"

    @model_validator(mode="after")
    def validate_lags(self) -> Self:
        lags = [lag for values in self.input_lags.values() for lag in values] + list(
            self.target_lags
        )
        if any(tuple(sorted(set(v))) != v for v in self.input_lags.values()):
            raise ValueError("Input lags must be sorted and unique")
        if tuple(sorted(set(self.target_lags))) != self.target_lags:
            raise ValueError("Target lags must be sorted and unique")
        if max(lags, default=0) > self.history_window:
            raise ValueError("history_window must cover all feature lags")
        return self


class SplitSpec(Schema):
    train: tuple[RowRange, ...] = Field(min_length=1, max_length=10000)
    validation: tuple[RowRange, ...] = Field(min_length=1, max_length=10000)
    test: tuple[RowRange, ...] = Field(min_length=1, max_length=10000)
    history_guard: Index = 0
    history_access_policy: Literal["past_within_run"] = "past_within_run"

    @model_validator(mode="after")
    def validate_splits(self) -> Self:
        for ranges in (self.train, self.validation, self.test):
            validate_ranges(ranges)
        if (
            self.train[-1].stop > self.validation[0].start
            or self.validation[-1].stop > self.test[0].start
        ):
            raise ValueError("Stage 1A requires chronologically ordered partitions")
        return self


class TrainingSelection(Schema):
    mode: Literal["full_train", "selected_rows"] = "full_train"
    source_run_id: UUID | None = None
    source_version_id: UUID | None = None
    requested_indices: RowSet | None = None

    @model_validator(mode="after")
    def validate_mode(self) -> Self:
        if self.mode == "selected_rows":
            if (
                self.requested_indices is None
                or self.source_run_id is None
                or self.source_version_id is None
            ):
                raise ValueError("Selected rows require exact run, version and nonempty selection")
        elif any(
            v is not None
            for v in (self.source_run_id, self.source_version_id, self.requested_indices)
        ):
            raise ValueError("Full Train must not carry a selected-row source")
        return self


class EvaluationSpec(Schema):
    scopes: tuple[Literal["validation", "test"], ...] = ("validation",)
    prediction_modes: tuple[Literal["one_step", "free_run", "prediction"], ...] = (
        "one_step",
        "free_run",
    )
    sample_indices: dict[Literal["validation", "test"], RowSet] = Field(default_factory=dict)
    resolution_status: Literal["unresolved", "resolved"] = "unresolved"

    @model_validator(mode="after")
    def validate_scopes(self) -> Self:
        if not self.scopes or len(set(self.scopes)) != len(self.scopes):
            raise ValueError("Evaluation scopes must be nonempty and unique")
        if not self.prediction_modes or len(set(self.prediction_modes)) != len(
            self.prediction_modes
        ):
            raise ValueError("Prediction modes must be nonempty and unique")
        if set(self.sample_indices) - set(self.scopes):
            raise ValueError("Evaluation rows must belong to declared scopes")
        if self.resolution_status == "resolved" and set(self.sample_indices) != set(self.scopes):
            raise ValueError("Resolved evaluation requires rows for every scope")
        return self


class PreprocessingStep(Schema):
    operation: str
    parameters: dict[str, object] = Field(default_factory=dict)
    source_version_id: UUID
    result_version_id: UUID
    source_run_id: UUID
    fit_partition: Literal["train", "validation", "test", "all", "not_applicable", "unknown"] = (
        "unknown"
    )
    fit_indices: RowSet | None = None
    causality: Literal["causal", "noncausal", "unknown"] = "unknown"


class LeakageAssessment(Schema):
    status: Literal["unknown", "potential_leakage", "verified_train_only"] = "unknown"
    evidence: tuple[str, ...] = ()


class ResourceBudget(Schema):
    timeout_seconds: Annotated[StrictInt, Field(gt=0)] | None = None
    max_threads: Annotated[StrictInt, Field(gt=0)] | None = None
    memory_mb: Annotated[StrictInt, Field(gt=0)] | None = None
    enforcement: Literal["not_implemented"] = "not_implemented"


class ConfirmedRowOrder(Schema):
    """User attestation tied to one immutable CSV, without time continuity evidence."""

    dataset_version_id: UUID
    csv_sha256: Digest
    row_order_status: Literal["user_confirmed"] = "user_confirmed"


class ExperimentSpec(Schema):
    spec_version: Literal[1] = 1
    task_type: Literal["dynamic_system_identification", "supervised_regression"]
    application: Literal["regression", "soft_sensor"] | None = None
    dataset_id: UUID
    dataset_version_id: UUID
    dataset_version_sha256: Digest
    row_count: Annotated[StrictInt, Field(gt=0)]
    input_columns: tuple[str, ...] = Field(min_length=1)
    target_column: str | None = None
    time_axis: TimeAxis = Field(default_factory=TimeAxis)
    continuous_runs: tuple[RowRange, ...] = Field(max_length=10000)
    ordered_record_ranges: tuple[RowRange, ...] | None = Field(
        default=None, min_length=1, max_length=10000
    )
    row_order: ConfirmedRowOrder | None = None
    feature_spec: FeatureSpec
    split: SplitSpec
    training_selection: TrainingSelection = Field(default_factory=TrainingSelection)
    evaluation: EvaluationSpec = Field(default_factory=EvaluationSpec)
    preprocessing: tuple[PreprocessingStep, ...] = ()
    leakage: LeakageAssessment = Field(default_factory=LeakageAssessment)
    random_seed: StrictInt | None = None
    resource_budget: ResourceBudget = Field(default_factory=ResourceBudget)

    @model_serializer(mode="wrap")
    def serialize_contract(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        document = handler(self)
        if self.row_order is None:
            # Preserve legacy serialized bytes and hashes, including nested Manifest Specs.
            document.pop("row_order", None)
            document.pop("ordered_record_ranges", None)
        return document

    @model_validator(mode="after")
    def validate_contract(self) -> Self:
        if self.row_order is None:
            if self.ordered_record_ranges is not None or not self.continuous_runs:
                raise ValueError("Continuous runs are required without confirmed row order")
        elif (
            not self.ordered_record_ranges
            or self.continuous_runs
            or self.row_order.dataset_version_id != self.dataset_version_id
            or self.row_order.csv_sha256 != self.dataset_version_sha256
            or self.task_type != "supervised_regression"
            or self.feature_spec.kind != "tabular"
            or self.feature_spec.history_window
            or self.feature_spec.input_lags
            or self.feature_spec.target_lags
            or self.time_axis != TimeAxis()
            or self.training_selection.mode != "full_train"
        ):
            raise ValueError("Confirmed row order requires a matching static, untimed contract")
        else:
            validate_ranges(self.ordered_record_ranges)
        if not self.target_column or self.target_column in self.input_columns:
            raise ValueError("Current supervised tasks require a separate target")
        if any(not c for c in self.input_columns) or len(set(self.input_columns)) != len(
            self.input_columns
        ):
            raise ValueError("Inputs must be nonempty, unique and ordered")
        if set(self.feature_spec.input_lags) - set(self.input_columns):
            raise ValueError("Lag features reference unknown inputs")
        if self.task_type == "dynamic_system_identification":
            if self.feature_spec.kind != "dynamic_lags" or self.time_axis.column is None:
                raise ValueError("Dynamic identification requires time and lag features")
            if self.application is not None:
                raise ValueError("Regression application does not describe dynamic identification")
        if self.task_type == "supervised_regression" and self.split.history_guard != 0:
            raise ValueError("Nonzero regression history_guard is not implemented in Stage 1A")
        validate_ranges(self.continuous_runs)
        for r in (
            *self.continuous_runs,
            *(self.ordered_record_ranges or ()),
            *self.split.train,
            *self.split.validation,
            *self.split.test,
        ):
            if r.stop > self.row_count:
                raise ValueError("Range exceeds CSV data-record count")
        return self
