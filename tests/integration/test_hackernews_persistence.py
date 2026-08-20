"""PostgreSQL persistence tests for Hacker News ingestion.

These tests roll back and never call the Hacker News API. Assertions are scoped
to fixture external IDs.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session, sessionmaker

from trendora.config import reset_settings_cache
from trendora.connectors.hackernews.connector import HackerNewsConnector
from trendora.connectors.hackernews.normalizer import NormalizedStory
from trendora.connectors.hackernews.persistence import persist_story
from trendora.connectors.hackernews.schemas import ItemResource
from trendora.db.session import get_engine, reset_engine
from trendora.models import ContentItem, MetricSnapshot, Publisher
from trendora.reference import SOURCE_IDS
from tests.fixtures.hackernews_responses import STORY_A, STORY_A_ID, STORY_B, STORY_B_ID

pytestmark = pytest.mark.integration

COLLECTED = datetime(2026, 8, 20, 19, 0, tzinfo=timezone.utc)
COLLECTED_LATER = datetime(2026, 8, 20, 20, 0, tzinfo=timezone.utc)
HN_SOURCE = SOURCE_IDS["hacker_news"]


@pytest.fixture
def db_session(database_url: str) -> Session:
    assert database_url
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


class _SessionStore:
    def __init__(self, session: Session) -> None:
        self._session = session

    def persist(self, story: NormalizedStory):
        return persist_story(self._session, story)


class _FakeClient:
    def __init__(self, feeds: dict[str, list[int]], items: dict[int, ItemResource]) -> None:
        self.feeds = feeds
        self.items = items

    def list_feed_ids(self, feed: str, *, max_items: int) -> list[int]:
        return list(self.feeds.get(feed, []))[:max_items]

    def get_item(self, item_id: int) -> ItemResource | None:
        return self.items.get(item_id)


def _ingest(session: Session, *, collected_at: datetime, feeds: dict[str, list[int]]) -> None:
    items = {
        STORY_A_ID: ItemResource.model_validate(STORY_A),
        STORY_B_ID: ItemResource.model_validate(STORY_B),
    }
    connector = HackerNewsConnector(
        _FakeClient(feeds, items),
        _SessionStore(session),
        feeds=tuple(feeds),
        max_items=50,
    )
    result = connector.ingest(collected_at=collected_at)
    session.flush()
    assert result.failed == []


def _content(session: Session, external_id: str) -> ContentItem | None:
    return (
        session.query(ContentItem)
        .filter(
            ContentItem.source_id == HN_SOURCE,
            ContentItem.external_id == external_id,
        )
        .one_or_none()
    )


def test_new_story_creates_content_identity_without_publisher(db_session: Session) -> None:
    _ingest(db_session, collected_at=COLLECTED, feeds={"topstories": [STORY_A_ID]})
    story = _content(db_session, str(STORY_A_ID))
    assert story is not None
    assert story.content_type == "story"
    assert story.publisher_id is None
    assert story.market_id is None
    assert story.source_metadata["author"] == "alice"
    assert story.source_metadata["feeds"] == ["topstories"]

    publishers = (
        db_session.query(Publisher)
        .filter(Publisher.source_id == HN_SOURCE, Publisher.external_id == "alice")
        .all()
    )
    assert publishers == []

    snapshots = (
        db_session.query(MetricSnapshot)
        .filter(MetricSnapshot.content_item_id == story.id)
        .all()
    )
    names = {row.metric_name: row.metric_value for row in snapshots}
    assert names["score"] == 120
    assert names["comment_count"] == 15
    assert all(row.publisher_id is None for row in snapshots)
    assert all(row.retention_policy_id is None for row in snapshots)


def test_reingest_same_collected_at_is_idempotent_and_later_appends(db_session: Session) -> None:
    _ingest(db_session, collected_at=COLLECTED, feeds={"topstories": [STORY_A_ID]})
    first = _content(db_session, str(STORY_A_ID))
    assert first is not None
    first_count = (
        db_session.query(MetricSnapshot).filter(MetricSnapshot.content_item_id == first.id).count()
    )
    assert first_count > 0

    _ingest(db_session, collected_at=COLLECTED, feeds={"topstories": [STORY_A_ID]})
    stories = (
        db_session.query(ContentItem)
        .filter(
            ContentItem.source_id == HN_SOURCE,
            ContentItem.external_id == str(STORY_A_ID),
        )
        .all()
    )
    assert len(stories) == 1
    assert (
        db_session.query(MetricSnapshot).filter(MetricSnapshot.content_item_id == first.id).count()
        == first_count
    )

    _ingest(db_session, collected_at=COLLECTED_LATER, feeds={"topstories": [STORY_A_ID]})
    assert (
        db_session.query(MetricSnapshot).filter(MetricSnapshot.content_item_id == first.id).count()
        == first_count * 2
    )


def test_cross_feed_duplicate_has_one_identity_and_merged_feeds(db_session: Session) -> None:
    _ingest(
        db_session,
        collected_at=COLLECTED,
        feeds={"topstories": [STORY_A_ID, STORY_B_ID], "beststories": [STORY_A_ID]},
    )
    stories = (
        db_session.query(ContentItem)
        .filter(
            ContentItem.source_id == HN_SOURCE,
            ContentItem.external_id == str(STORY_A_ID),
        )
        .all()
    )
    assert len(stories) == 1
    assert stories[0].source_metadata["feeds"] == ["topstories", "beststories"]
    assert stories[0].market_id is None

    snapshots = (
        db_session.query(MetricSnapshot)
        .filter(MetricSnapshot.content_item_id == stories[0].id)
        .all()
    )
    assert {row.collected_at for row in snapshots} == {COLLECTED}
    score_rows = [row for row in snapshots if row.metric_name == "score"]
    assert len(score_rows) == 1
