"""Persist normalized GitHub repositories through existing SQLAlchemy models."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from trendora.connectors.github.normalizer import (
    GH_SOURCE_CODE,
    NormalizedRepository,
    NormalizedSnapshot,
)
from trendora.models import ContentItem, MetricSnapshot, Source

logger = logging.getLogger("trendora.connectors.github.persistence")


@dataclass(frozen=True)
class RepositoryPersistResult:
    content_item_created: bool
    content_item_updated: bool
    snapshots_inserted: int


def persist_repository(session: Session, repository: NormalizedRepository) -> RepositoryPersistResult:
    """Write one repository. Caller owns the transaction (commit/rollback)."""

    source = session.scalar(select(Source).where(Source.code == GH_SOURCE_CODE))
    if source is None:
        raise RuntimeError(
            "GitHub source registry row is missing. Run Alembic revision 0001_initial_schema."
        )

    content, created = _upsert_content_item(session, source_id=source.id, repository=repository)
    session.flush()

    snapshots_inserted = 0
    for snapshot in repository.snapshots:
        snapshots_inserted += _insert_snapshot_if_absent(
            session,
            source_id=source.id,
            snapshot=snapshot,
            content_item_id=content.id,
        )

    logger.info(
        "github.persist.repository external_id=%s created=%s snapshots=%s",
        repository.external_id,
        created,
        snapshots_inserted,
    )
    return RepositoryPersistResult(
        content_item_created=created,
        content_item_updated=not created,
        snapshots_inserted=snapshots_inserted,
    )


def _upsert_content_item(
    session: Session,
    *,
    source_id,
    repository: NormalizedRepository,
) -> tuple[ContentItem, bool]:
    content = session.scalar(
        select(ContentItem).where(
            ContentItem.source_id == source_id,
            ContentItem.external_id == repository.external_id,
        )
    )
    if content is None:
        content = ContentItem(
            source_id=source_id,
            publisher_id=None,
            external_id=repository.external_id,
            content_type=repository.content_type,
            title=repository.title,
            description=repository.description,
            url=repository.url,
            published_at=repository.published_at,
            market_id=None,
            source_metadata=repository.source_metadata,
            retain_until=repository.retain_until,
        )
        session.add(content)
        return content, True

    content.publisher_id = None
    content.content_type = repository.content_type
    content.title = repository.title
    content.description = repository.description
    content.url = repository.url
    content.published_at = repository.published_at
    content.market_id = None
    content.source_metadata = repository.source_metadata
    content.retain_until = repository.retain_until
    return content, False


def _insert_snapshot_if_absent(
    session: Session,
    *,
    source_id,
    snapshot: NormalizedSnapshot,
    content_item_id,
) -> int:
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
            publisher_id=None,
            metric_name=snapshot.metric_name,
            metric_value=snapshot.metric_value,
            observed_at=snapshot.observed_at,
            collected_at=snapshot.collected_at,
            retention_policy_id=None,
            retain_until=snapshot.retain_until,
            source_metadata=snapshot.source_metadata,
        )
    )
    return 1
