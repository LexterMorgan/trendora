"""Deterministic analytics operations over a read-only observation repository."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from trendora.analytics.exceptions import AnalyticsAggregationError
from trendora.analytics.models import (
    Aggregation,
    AggregateSummary,
    MetricObservation,
    MetricSeries,
)
from trendora.analytics.repository import AnalyticsRepository, ObservationQuery, latest_observation

_ORIGIN = "trendora_derived"


class ObservationReader(Protocol):
    def list_observations(self, query: ObservationQuery) -> list[MetricObservation]: ...

    def get_latest_observation(self, query: ObservationQuery) -> MetricObservation | None: ...


class AnalyticsService:
    """Source-agnostic read API. Does not call external APIs or mutate data."""

    def __init__(self, repository: ObservationReader) -> None:
        self._repository = repository

    @classmethod
    def from_session(cls, session: Session) -> AnalyticsService:
        return cls(AnalyticsRepository(session))

    def get_metric_observations(self, query: ObservationQuery) -> MetricSeries:
        rows = self._repository.list_observations(query)
        return MetricSeries(
            observations=tuple(rows),
            source_code=query.source_code,
            metric_name=query.metric_name,
        )

    def get_metric_series(self, query: ObservationQuery) -> MetricSeries:
        return self.get_metric_observations(query)

    def get_content_metric_series(
        self,
        content_item_id: UUID,
        metric_name: str,
        *,
        observed_from: datetime | None = None,
        observed_until: datetime | None = None,
        source_code: str | None = None,
    ) -> MetricSeries:
        return self.get_metric_series(
            ObservationQuery(
                source_code=source_code,
                metric_name=metric_name,
                content_item_id=content_item_id,
                observed_from=observed_from,
                observed_until=observed_until,
            )
        )

    def get_publisher_metric_series(
        self,
        publisher_id: UUID,
        metric_name: str,
        *,
        observed_from: datetime | None = None,
        observed_until: datetime | None = None,
        source_code: str | None = None,
    ) -> MetricSeries:
        return self.get_metric_series(
            ObservationQuery(
                source_code=source_code,
                metric_name=metric_name,
                publisher_id=publisher_id,
                observed_from=observed_from,
                observed_until=observed_until,
            )
        )

    def get_latest_observation(self, query: ObservationQuery) -> MetricObservation | None:
        return self._repository.get_latest_observation(query)

    def summarize(
        self,
        query: ObservationQuery,
        *,
        aggregation: Aggregation | str,
    ) -> AggregateSummary:
        try:
            kind = aggregation if isinstance(aggregation, Aggregation) else Aggregation(aggregation)
        except ValueError as exc:
            raise AnalyticsAggregationError(
                f"Unsupported aggregation {aggregation!r}. "
                f"Allowed: {', '.join(item.value for item in Aggregation)}"
            ) from exc

        if kind == Aggregation.LATEST_VALUE:
            if query.metric_name is None:
                raise AnalyticsAggregationError("latest_value requires metric_name")
            if query.content_item_id is None and query.publisher_id is None:
                raise AnalyticsAggregationError(
                    "latest_value requires content_item_id or publisher_id"
                )

        series = self.get_metric_observations(query)
        earliest = series.observations[0].observed_at if series.observations else None
        latest = series.observations[-1].observed_at if series.observations else None
        if kind == Aggregation.COUNT:
            value: int | datetime | None = len(series)
        elif kind == Aggregation.EARLIEST_OBSERVED_AT:
            value = earliest
        elif kind == Aggregation.LATEST_OBSERVED_AT:
            value = latest
        else:
            newest = latest_observation(series.observations)
            value = newest.metric_value if newest is not None else None

        return AggregateSummary(
            aggregation=kind,
            origin=_ORIGIN,
            observation_count=len(series),
            value=value,
            earliest_observed_at=earliest,
            latest_observed_at=latest,
            source_code=query.source_code,
            metric_name=query.metric_name,
        )
