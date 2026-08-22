"""Read-only observation queries over existing metric_snapshots."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session, aliased

from trendora.analytics.exceptions import AnalyticsQueryError
from trendora.analytics.models import (
    MetricObservation,
    SubjectKind,
    latest_sort_key,
    ordered_observations,
)
from trendora.models import ContentItem, Market, MetricSnapshot, Publisher, Source

_CONTENT_PUBLISHER = aliased(Publisher, name="content_publisher")
_CONTENT_MARKET = aliased(Market, name="content_market")
_PUBLISHER_MARKET = aliased(Market, name="publisher_market")


@dataclass(frozen=True)
class ObservationQuery:
    """Deterministic filters. Time bounds apply to ``observed_at``.

    Interval: ``observed_from <= observed_at < observed_until``
    (inclusive start, exclusive end). Omitted bounds are unbounded.
    Timezone-naive datetimes are rejected.

    ``publisher_id`` matches publisher-subject snapshots only (the snapshot
    row's ``publisher_id``). It does not expand to that publisher's content
    items. Use ``content_item_id`` for content-subject series.
    """

    source_code: str | None = None
    metric_name: str | None = None
    content_item_id: UUID | None = None
    publisher_id: UUID | None = None
    market_id: UUID | None = None
    observed_from: datetime | None = None
    observed_until: datetime | None = None


def validate_observation_query(query: ObservationQuery) -> None:
    if query.content_item_id is not None and query.publisher_id is not None:
        raise AnalyticsQueryError("content_item_id and publisher_id are mutually exclusive")
    _require_aware(query.observed_from, "observed_from")
    _require_aware(query.observed_until, "observed_until")


def _require_aware(value: datetime | None, name: str) -> None:
    if value is not None and value.tzinfo is None:
        raise AnalyticsQueryError(f"{name} must be timezone-aware")


def matches_query(observation: MetricObservation, query: ObservationQuery) -> bool:
    """Python-side filter semantics. SQL must match this behavior."""

    validate_observation_query(query)
    if query.source_code is not None and observation.source_code != query.source_code:
        return False
    if query.metric_name is not None and observation.metric_name != query.metric_name:
        return False
    if query.content_item_id is not None and observation.content_item_id != query.content_item_id:
        return False
    if query.publisher_id is not None:
        if observation.subject_kind == SubjectKind.PUBLISHER:
            if observation.publisher_id != query.publisher_id:
                return False
        else:
            return False
    if query.market_id is not None and observation.market_id != query.market_id:
        return False
    if query.observed_from is not None and observation.observed_at < query.observed_from:
        return False
    if query.observed_until is not None and observation.observed_at >= query.observed_until:
        return False
    return True


def apply_observation_query(
    rows: Sequence[MetricObservation],
    query: ObservationQuery,
) -> list[MetricObservation]:
    validate_observation_query(query)
    matched = [row for row in rows if matches_query(row, query)]
    return list(ordered_observations(matched))


class AnalyticsRepository:
    """Read-only SQLAlchemy access to persisted snapshots.

    Never inserts, updates, deletes, or commits.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_observations(self, query: ObservationQuery) -> list[MetricObservation]:
        validate_observation_query(query)
        stmt = _observation_select().where(*_sql_filters(query)).order_by(
            MetricSnapshot.observed_at.asc(),
            MetricSnapshot.collected_at.asc(),
            MetricSnapshot.id.asc(),
        )
        return [_to_observation(row) for row in self._session.execute(stmt).all()]

    def get_latest_observation(self, query: ObservationQuery) -> MetricObservation | None:
        validate_observation_query(query)
        stmt = _observation_select().where(*_sql_filters(query)).order_by(
            MetricSnapshot.observed_at.desc(),
            MetricSnapshot.collected_at.desc(),
            MetricSnapshot.id.desc(),
        ).limit(1)
        row = self._session.execute(stmt).first()
        if row is None:
            return None
        return _to_observation(row)


class InMemoryAnalyticsRepository:
    """Deterministic in-memory reader for unit tests. Not a persistence store."""

    def __init__(self, observations: Sequence[MetricObservation] = ()) -> None:
        self._rows = tuple(observations)

    def list_observations(self, query: ObservationQuery) -> list[MetricObservation]:
        return apply_observation_query(self._rows, query)

    def get_latest_observation(self, query: ObservationQuery) -> MetricObservation | None:
        return latest_observation(self.list_observations(query))


def latest_observation(rows: Sequence[MetricObservation]) -> MetricObservation | None:
    if not rows:
        return None
    return max(rows, key=latest_sort_key)


def _observation_select() -> Select:
    return (
        select(
            MetricSnapshot,
            Source,
            ContentItem,
            Publisher,
            _CONTENT_PUBLISHER,
            _CONTENT_MARKET,
            _PUBLISHER_MARKET,
        )
        .join(Source, MetricSnapshot.source_id == Source.id)
        .outerjoin(ContentItem, MetricSnapshot.content_item_id == ContentItem.id)
        .outerjoin(Publisher, MetricSnapshot.publisher_id == Publisher.id)
        .outerjoin(_CONTENT_PUBLISHER, ContentItem.publisher_id == _CONTENT_PUBLISHER.id)
        .outerjoin(_CONTENT_MARKET, ContentItem.market_id == _CONTENT_MARKET.id)
        .outerjoin(_PUBLISHER_MARKET, Publisher.market_id == _PUBLISHER_MARKET.id)
    )


def _sql_filters(query: ObservationQuery) -> list:
    filters = []
    if query.source_code is not None:
        filters.append(Source.code == query.source_code)
    if query.metric_name is not None:
        filters.append(MetricSnapshot.metric_name == query.metric_name)
    if query.content_item_id is not None:
        filters.append(MetricSnapshot.content_item_id == query.content_item_id)
    if query.publisher_id is not None:
        filters.append(MetricSnapshot.publisher_id == query.publisher_id)
    if query.market_id is not None:
        filters.append(
            (ContentItem.market_id == query.market_id)
            | (Publisher.market_id == query.market_id)
        )
    if query.observed_from is not None:
        filters.append(MetricSnapshot.observed_at >= query.observed_from)
    if query.observed_until is not None:
        filters.append(MetricSnapshot.observed_at < query.observed_until)
    return filters


def _to_observation(row) -> MetricObservation:
    snapshot, source, content, publisher, content_publisher, content_market, publisher_market = row
    if snapshot.content_item_id is not None:
        subject_kind = SubjectKind.CONTENT_ITEM
        publisher_id = content.publisher_id if content is not None else None
        publisher_external_id = (
            content_publisher.external_id if content_publisher is not None else None
        )
        market_id = content.market_id if content is not None else None
        market_code = content_market.code if content_market is not None else None
    else:
        subject_kind = SubjectKind.PUBLISHER
        publisher_id = snapshot.publisher_id
        publisher_external_id = publisher.external_id if publisher is not None else None
        market_id = publisher.market_id if publisher is not None else None
        market_code = publisher_market.code if publisher_market is not None else None

    return MetricObservation(
        snapshot_id=snapshot.id,
        source_code=source.code,
        source_id=source.id,
        metric_name=snapshot.metric_name,
        metric_value=snapshot.metric_value,
        observed_at=snapshot.observed_at,
        collected_at=snapshot.collected_at,
        subject_kind=subject_kind,
        content_item_id=snapshot.content_item_id,
        content_external_id=content.external_id if content is not None else None,
        content_type=content.content_type if content is not None else None,
        publisher_id=publisher_id,
        publisher_external_id=publisher_external_id,
        market_id=market_id,
        market_code=market_code,
    )
