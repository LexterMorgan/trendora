"""Stable analytics read contracts. These are not SQLAlchemy ORM objects."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class SubjectKind(StrEnum):
    CONTENT_ITEM = "content_item"
    PUBLISHER = "publisher"


class Aggregation(StrEnum):
    """Safe Trendora-derived aggregations. Not official source metrics."""

    COUNT = "count"
    EARLIEST_OBSERVED_AT = "earliest_observed_at"
    LATEST_OBSERVED_AT = "latest_observed_at"
    LATEST_VALUE = "latest_value"


@dataclass(frozen=True)
class MetricObservation:
    """One stored snapshot, identified independently of the ORM instance."""

    snapshot_id: UUID
    source_code: str
    source_id: UUID
    metric_name: str
    metric_value: int
    observed_at: datetime
    collected_at: datetime
    subject_kind: SubjectKind
    content_item_id: UUID | None = None
    content_external_id: str | None = None
    content_type: str | None = None
    publisher_id: UUID | None = None
    publisher_external_id: str | None = None
    market_id: UUID | None = None
    market_code: str | None = None


@dataclass(frozen=True)
class MetricSeries:
    """Ordered observations. Empty series are valid and contain no fabricated rows."""

    observations: tuple[MetricObservation, ...]
    source_code: str | None = None
    metric_name: str | None = None

    @property
    def empty(self) -> bool:
        return len(self.observations) == 0

    def __len__(self) -> int:
        return len(self.observations)


@dataclass(frozen=True)
class AggregateSummary:
    """A Trendora-derived aggregate over stored observations.

    ``origin`` is always ``trendora_derived``. These values are not official
    source API fields.
    """

    aggregation: Aggregation
    origin: str
    observation_count: int
    value: int | datetime | None
    earliest_observed_at: datetime | None
    latest_observed_at: datetime | None
    source_code: str | None = None
    metric_name: str | None = None


def series_sort_key(observation: MetricObservation) -> tuple[datetime, datetime, str]:
    return (observation.observed_at, observation.collected_at, str(observation.snapshot_id))


def latest_sort_key(observation: MetricObservation) -> tuple[datetime, datetime, str]:
    return (observation.observed_at, observation.collected_at, str(observation.snapshot_id))


def ordered_observations(rows: Sequence[MetricObservation]) -> tuple[MetricObservation, ...]:
    return tuple(sorted(rows, key=series_sort_key))
