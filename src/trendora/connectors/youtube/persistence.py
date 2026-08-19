"""Persist normalized YouTube records through existing SQLAlchemy models."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from trendora.connectors.youtube.normalizer import (
    ChannelIngestionBundle,
    NormalizedContentItem,
    NormalizedSnapshot,
    YOUTUBE_SOURCE_CODE,
)
from trendora.models import ContentItem, Market, MetricSnapshot, Publisher, RetentionPolicy, Source

logger = logging.getLogger("trendora.connectors.youtube.persistence")


@dataclass(frozen=True)
class ChannelPersistResult:
    publisher_created: bool
    publisher_updated: bool
    content_items_upserted: int
    snapshots_inserted: int


def persist_channel(session: Session, bundle: ChannelIngestionBundle) -> ChannelPersistResult:
    """Write one channel bundle. Caller owns the transaction (commit/rollback)."""

    source = session.scalar(select(Source).where(Source.code == YOUTUBE_SOURCE_CODE))
    if source is None:
        raise RuntimeError(
            "YouTube source registry row is missing. Run Alembic revision 0001_initial_schema."
        )

    stats_policy = _policy(session, "youtube_non_authorized_stats")
    market_id = None
    if bundle.market_code:
        market = session.scalar(select(Market).where(Market.code == bundle.market_code))
        market_id = market.id if market is not None else None

    publisher, created = _upsert_publisher(session, source_id=source.id, market_id=market_id, bundle=bundle)
    session.flush()

    snapshots_inserted = 0
    for snapshot in bundle.publisher_snapshots:
        snapshots_inserted += _insert_snapshot_if_absent(
            session,
            source_id=source.id,
            snapshot=snapshot,
            policy_id=stats_policy.id,
            publisher_id=publisher.id,
            content_item_id=None,
        )

    for item in bundle.content_items:
        content = _upsert_content_item(
            session,
            source_id=source.id,
            publisher_id=publisher.id,
            market_id=market_id,
            item=item,
        )
        session.flush()
        for snapshot in item.snapshots:
            snapshots_inserted += _insert_snapshot_if_absent(
                session,
                source_id=source.id,
                snapshot=snapshot,
                policy_id=stats_policy.id,
                publisher_id=None,
                content_item_id=content.id,
            )

    logger.info(
        "youtube.persist.channel channel_id=%s publisher_created=%s videos=%s snapshots=%s",
        bundle.publisher_external_id,
        created,
        len(bundle.content_items),
        snapshots_inserted,
    )
    return ChannelPersistResult(
        publisher_created=created,
        publisher_updated=not created,
        content_items_upserted=len(bundle.content_items),
        snapshots_inserted=snapshots_inserted,
    )


def _policy(session: Session, code: str) -> RetentionPolicy:
    policy = session.scalar(select(RetentionPolicy).where(RetentionPolicy.code == code))
    if policy is None:
        raise RuntimeError(f"retention policy {code!r} is missing. Run Alembic revision 0001_initial_schema.")
    return policy


def _upsert_publisher(
    session: Session,
    *,
    source_id,
    market_id,
    bundle: ChannelIngestionBundle,
) -> tuple[Publisher, bool]:
    publisher = session.scalar(
        select(Publisher).where(
            Publisher.source_id == source_id,
            Publisher.external_id == bundle.publisher_external_id,
        )
    )
    if publisher is None:
        publisher = Publisher(
            source_id=source_id,
            external_id=bundle.publisher_external_id,
            name=bundle.publisher_name,
            url=bundle.publisher_url,
            market_id=market_id,
            source_metadata=bundle.publisher_source_metadata,
            retain_until=bundle.publisher_retain_until,
        )
        session.add(publisher)
        return publisher, True

    publisher.name = bundle.publisher_name
    publisher.url = bundle.publisher_url
    publisher.market_id = market_id
    publisher.source_metadata = bundle.publisher_source_metadata
    publisher.retain_until = bundle.publisher_retain_until
    return publisher, False


def _upsert_content_item(
    session: Session,
    *,
    source_id,
    publisher_id,
    market_id,
    item: NormalizedContentItem,
) -> ContentItem:
    content = session.scalar(
        select(ContentItem).where(
            ContentItem.source_id == source_id,
            ContentItem.external_id == item.external_id,
        )
    )
    if content is None:
        content = ContentItem(
            source_id=source_id,
            publisher_id=publisher_id,
            external_id=item.external_id,
            content_type=item.content_type,
            title=item.title,
            description=item.description,
            url=item.url,
            published_at=item.published_at,
            market_id=market_id,
            source_metadata=item.source_metadata,
            retain_until=item.retain_until,
        )
        session.add(content)
        return content

    content.publisher_id = publisher_id
    content.content_type = item.content_type
    content.title = item.title
    content.description = item.description
    content.url = item.url
    content.published_at = item.published_at
    content.market_id = market_id
    content.source_metadata = item.source_metadata
    content.retain_until = item.retain_until
    return content


def _insert_snapshot_if_absent(
    session: Session,
    *,
    source_id,
    snapshot: NormalizedSnapshot,
    policy_id,
    publisher_id,
    content_item_id,
) -> int:
    if snapshot.subject == "publisher":
        existing = session.scalar(
            select(MetricSnapshot.id).where(
                MetricSnapshot.publisher_id == publisher_id,
                MetricSnapshot.metric_name == snapshot.metric_name,
                MetricSnapshot.collected_at == snapshot.collected_at,
            )
        )
    else:
        existing = session.scalar(
            select(MetricSnapshot.id).where(
                MetricSnapshot.content_item_id == content_item_id,
                MetricSnapshot.metric_name == snapshot.metric_name,
                MetricSnapshot.collected_at == snapshot.collected_at,
            )
        )
    if existing is not None:
        return 0

    session.add(
        MetricSnapshot(
            source_id=source_id,
            content_item_id=content_item_id,
            publisher_id=publisher_id,
            metric_name=snapshot.metric_name,
            metric_value=snapshot.metric_value,
            observed_at=snapshot.observed_at,
            collected_at=snapshot.collected_at,
            retention_policy_id=policy_id,
            retain_until=snapshot.retain_until,
            source_metadata=snapshot.source_metadata,
        )
    )
    return 1
