"""Persist normalized Stack Exchange questions through existing SQLAlchemy models."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from trendora.connectors.stackexchange.normalizer import (
    NormalizedQuestion,
    NormalizedSnapshot,
    SE_SOURCE_CODE,
)
from trendora.models import ContentItem, MetricSnapshot, Source

logger = logging.getLogger("trendora.connectors.stackexchange.persistence")


@dataclass(frozen=True)
class QuestionPersistResult:
    content_item_created: bool
    content_item_updated: bool
    snapshots_inserted: int


def persist_question(session: Session, question: NormalizedQuestion) -> QuestionPersistResult:
    """Write one question. Caller owns the transaction (commit/rollback)."""

    source = session.scalar(select(Source).where(Source.code == SE_SOURCE_CODE))
    if source is None:
        raise RuntimeError(
            "Stack Exchange source registry row is missing. Run Alembic revision 0001_initial_schema."
        )

    content, created = _upsert_content_item(session, source_id=source.id, question=question)
    session.flush()

    snapshots_inserted = 0
    for snapshot in question.snapshots:
        snapshots_inserted += _insert_snapshot_if_absent(
            session,
            source_id=source.id,
            snapshot=snapshot,
            content_item_id=content.id,
        )

    logger.info(
        "stackexchange.persist.question external_id=%s created=%s snapshots=%s",
        question.external_id,
        created,
        snapshots_inserted,
    )
    return QuestionPersistResult(
        content_item_created=created,
        content_item_updated=not created,
        snapshots_inserted=snapshots_inserted,
    )


def _upsert_content_item(
    session: Session,
    *,
    source_id,
    question: NormalizedQuestion,
) -> tuple[ContentItem, bool]:
    content = session.scalar(
        select(ContentItem).where(
            ContentItem.source_id == source_id,
            ContentItem.external_id == question.external_id,
        )
    )
    if content is None:
        content = ContentItem(
            source_id=source_id,
            publisher_id=None,
            external_id=question.external_id,
            content_type=question.content_type,
            title=question.title,
            description=question.description,
            url=question.url,
            published_at=question.published_at,
            market_id=None,
            source_metadata=question.source_metadata,
            retain_until=question.retain_until,
        )
        session.add(content)
        return content, True

    content.publisher_id = None
    content.content_type = question.content_type
    content.title = question.title
    content.description = question.description
    content.url = question.url
    content.published_at = question.published_at
    content.market_id = None
    content.source_metadata = question.source_metadata
    content.retain_until = question.retain_until
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
