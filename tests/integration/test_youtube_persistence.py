"""PostgreSQL persistence tests for YouTube ingestion. Skipped without DATABASE_URL.

These tests roll back and never call the YouTube API.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session, sessionmaker

from trendora.config import reset_settings_cache
from trendora.connectors.youtube.normalizer import normalize_channel
from trendora.connectors.youtube.persistence import persist_channel
from trendora.connectors.youtube.schemas import ChannelResource, VideoResource
from trendora.db.session import get_engine, reset_engine
from trendora.models import ContentItem, MetricSnapshot, Publisher
from trendora.reference import RETENTION_POLICY_IDS, SOURCE_IDS
from tests.fixtures.youtube_responses import CHANNEL_A, CHANNELS_LIST_OK, VIDEOS_LIST_OK

pytestmark = pytest.mark.integration

COLLECTED = datetime(2026, 8, 19, 16, 0, tzinfo=timezone.utc)
COLLECTED_LATER = datetime(2026, 8, 19, 17, 0, tzinfo=timezone.utc)


def _database_url() -> str | None:
    return os.environ.get("DATABASE_URL") or os.environ.get("TRENDORA_TEST_DATABASE_URL")


@pytest.fixture
def db_session() -> Session:
    if not _database_url():
        pytest.skip("DATABASE_URL is not configured")
    reset_settings_cache()
    reset_engine()
    engine = get_engine()
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(bind=connection, autoflush=False, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        reset_engine()
        reset_settings_cache()


def _bundle(collected_at: datetime):
    channel = ChannelResource.model_validate(CHANNELS_LIST_OK["items"][0])
    videos = [VideoResource.model_validate(item) for item in VIDEOS_LIST_OK["items"]]
    return normalize_channel(channel, videos, collected_at=collected_at)


def test_persist_is_idempotent_for_identities_and_append_only_for_metrics(db_session: Session) -> None:
    first = persist_channel(db_session, _bundle(COLLECTED))
    db_session.flush()
    assert first.publisher_created is True
    first_snapshots = first.snapshots_inserted
    assert first_snapshots > 0

    second = persist_channel(db_session, _bundle(COLLECTED))
    db_session.flush()
    assert second.publisher_created is False
    assert second.publisher_updated is True
    assert second.snapshots_inserted == 0

    third = persist_channel(db_session, _bundle(COLLECTED_LATER))
    db_session.flush()
    assert third.publisher_created is False
    assert third.snapshots_inserted == first_snapshots

    publishers = (
        db_session.query(Publisher)
        .filter(
            Publisher.source_id == SOURCE_IDS["youtube"],
            Publisher.external_id == CHANNEL_A,
        )
        .all()
    )
    assert len(publishers) == 1
    publisher = publishers[0]
    assert publisher.market_id is not None
    assert publisher.retain_until == COLLECTED_LATER + timedelta(days=30)

    videos = db_session.query(ContentItem).filter(ContentItem.publisher_id == publisher.id).all()
    assert len(videos) == 2

    video_row_ids = [item.id for item in videos]
    snapshots = (
        db_session.query(MetricSnapshot)
        .filter(
            (MetricSnapshot.publisher_id == publisher.id)
            | (MetricSnapshot.content_item_id.in_(video_row_ids))
        )
        .all()
    )
    assert len(snapshots) == first_snapshots * 2
    assert all(row.retention_policy_id == RETENTION_POLICY_IDS["youtube_non_authorized_stats"] for row in snapshots)
    assert all(row.observed_at.tzinfo is not None for row in snapshots)
    assert all(row.collected_at.tzinfo is not None for row in snapshots)
    assert all(
        (row.content_item_id is not None) ^ (row.publisher_id is not None) for row in snapshots
    )
