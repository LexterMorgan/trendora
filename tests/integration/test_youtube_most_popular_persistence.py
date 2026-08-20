"""PostgreSQL persistence tests for regional mostPopular ingestion.

These tests roll back and never call the YouTube API. Assertions are scoped to
fixture external IDs because the database may already contain M2A watchlist rows.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session, sessionmaker

from trendora.config import reset_settings_cache
from trendora.connectors.youtube.most_popular import MostPopularConnector
from trendora.connectors.youtube.normalizer import ChannelIngestionBundle
from trendora.connectors.youtube.persistence import persist_channel
from trendora.connectors.youtube.schemas import ChannelResource, VideoCategoryResource, VideoResource
from trendora.db.session import get_engine, reset_engine
from trendora.models import ContentItem, MetricSnapshot, Publisher
from trendora.reference import SOURCE_IDS
from tests.fixtures.youtube_responses import (
    CHANNEL_A,
    CHANNEL_C,
    CHANNELS_LIST_A_AND_C,
    MOSTPOPULAR_ID_PAGE_1,
    MOSTPOPULAR_ID_PAGE_2,
    MOSTPOPULAR_SG,
    VIDEO_1,
    VIDEO_CHART_1,
    VIDEO_CATEGORIES_ID,
    VIDEO_CATEGORIES_SG,
)

pytestmark = pytest.mark.integration

COLLECTED = datetime(2026, 8, 20, 16, 0, tzinfo=timezone.utc)
COLLECTED_LATER = datetime(2026, 8, 20, 17, 0, tzinfo=timezone.utc)


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

    def persist(self, bundle: ChannelIngestionBundle):
        return persist_channel(self._session, bundle)


class _FakeClient:
    def __init__(
        self,
        *,
        categories: dict[str, list[VideoCategoryResource]],
        charts: dict[str, list[VideoResource]],
        channels: list[ChannelResource],
    ) -> None:
        self.categories = categories
        self.charts = charts
        self.channels = channels
        self.playlist_calls = 0

    def list_video_categories(self, region_code: str) -> list[VideoCategoryResource]:
        return self.categories.get(region_code, [])

    def list_most_popular_videos(self, region_code: str, *, max_videos: int) -> list[VideoResource]:
        return self.charts.get(region_code, [])[:max_videos]

    def list_channels(self, channel_ids):
        wanted = set(channel_ids)
        return [channel for channel in self.channels if channel.id in wanted]

    def list_upload_video_ids(self, uploads_playlist_id: str, *, limit: int) -> list[str]:
        self.playlist_calls += 1
        raise AssertionError("mostPopular persistence must not crawl playlistItems")


def _categories(payload: dict) -> list[VideoCategoryResource]:
    return [VideoCategoryResource.model_validate(item) for item in payload["items"]]


def _videos(*payloads: dict) -> list[VideoResource]:
    items: list[VideoResource] = []
    seen: set[str] = set()
    for payload in payloads:
        for raw in payload["items"]:
            video = VideoResource.model_validate(raw)
            if video.id in seen:
                continue
            seen.add(video.id)
            items.append(video)
    return items


def _channels() -> list[ChannelResource]:
    return [ChannelResource.model_validate(item) for item in CHANNELS_LIST_A_AND_C["items"]]


def _ingest(session: Session, *, collected_at: datetime, regions: tuple[str, ...] = ("ID", "SG")):
    client = _FakeClient(
        categories={
            "ID": _categories(VIDEO_CATEGORIES_ID),
            "SG": _categories(VIDEO_CATEGORIES_SG),
        },
        charts={
            "ID": _videos(MOSTPOPULAR_ID_PAGE_1, MOSTPOPULAR_ID_PAGE_2),
            "SG": _videos(MOSTPOPULAR_SG),
        },
        channels=_channels(),
    )
    connector = MostPopularConnector(
        client,
        _SessionStore(session),
        region_codes=regions,
        max_videos_per_market=50,
    )
    result = connector.ingest(collected_at=collected_at)
    session.flush()
    assert client.playlist_calls == 0
    return result


def _youtube_publisher(session: Session, external_id: str) -> Publisher | None:
    return (
        session.query(Publisher)
        .filter(
            Publisher.source_id == SOURCE_IDS["youtube"],
            Publisher.external_id == external_id,
        )
        .one_or_none()
    )


def _youtube_content(session: Session, external_id: str) -> ContentItem | None:
    return (
        session.query(ContentItem)
        .filter(
            ContentItem.source_id == SOURCE_IDS["youtube"],
            ContentItem.external_id == external_id,
        )
        .one_or_none()
    )


def _snapshots_for_content(session: Session, content_id) -> list[MetricSnapshot]:
    return (
        session.query(MetricSnapshot)
        .filter(MetricSnapshot.content_item_id == content_id)
        .all()
    )


def test_chart_only_publisher_and_video_are_created(db_session: Session) -> None:
    result = _ingest(db_session, collected_at=COLLECTED, regions=("ID",))
    assert result.failed == []

    publisher = _youtube_publisher(db_session, CHANNEL_C)
    assert publisher is not None
    assert publisher.name == "US Chart Channel"
    assert publisher.market_id is None

    video = _youtube_content(db_session, VIDEO_CHART_1)
    assert video is not None
    assert video.publisher_id == publisher.id
    assert video.content_type == "video"
    assert video.source_metadata["chart"] == "mostPopular"
    assert video.source_metadata["region_codes"] == ["ID"]
    assert video.market_id is None


def test_overlap_identity_is_not_duplicated(db_session: Session) -> None:
    first = _ingest(db_session, collected_at=COLLECTED, regions=("ID",))
    second = _ingest(db_session, collected_at=COLLECTED, regions=("ID",))
    db_session.flush()

    publishers = (
        db_session.query(Publisher)
        .filter(
            Publisher.source_id == SOURCE_IDS["youtube"],
            Publisher.external_id == CHANNEL_A,
        )
        .all()
    )
    assert len(publishers) == 1
    videos = (
        db_session.query(ContentItem)
        .filter(
            ContentItem.source_id == SOURCE_IDS["youtube"],
            ContentItem.external_id == VIDEO_1,
        )
        .all()
    )
    assert len(videos) == 1

    channel_a_outcome = next(row for row in first.succeeded if row.external_id == CHANNEL_A)
    repeat = next(row for row in second.succeeded if row.external_id == CHANNEL_A)
    assert channel_a_outcome.publisher_created is True
    assert repeat.publisher_created is False
    assert repeat.snapshots_inserted == 0


def test_later_collected_at_appends_snapshots(db_session: Session) -> None:
    _ingest(db_session, collected_at=COLLECTED, regions=("ID",))
    video = _youtube_content(db_session, VIDEO_1)
    assert video is not None
    first_count = len(_snapshots_for_content(db_session, video.id))
    assert first_count > 0

    _ingest(db_session, collected_at=COLLECTED, regions=("ID",))
    assert len(_snapshots_for_content(db_session, video.id)) == first_count

    _ingest(db_session, collected_at=COLLECTED_LATER, regions=("ID",))
    assert len(_snapshots_for_content(db_session, video.id)) == first_count * 2


def test_merged_region_metadata_survives_persistence(db_session: Session) -> None:
    _ingest(db_session, collected_at=COLLECTED, regions=("ID", "SG"))
    video = _youtube_content(db_session, VIDEO_1)
    assert video is not None
    assert video.source_metadata["chart"] == "mostPopular"
    assert video.source_metadata["region_codes"] == ["ID", "SG"]
    assert video.source_metadata["category_titles_by_region"] == {
        "ID": "Education",
        "SG": "Education (SG)",
    }
    assert video.source_metadata["chart_positions_by_region"] == {"ID": 1, "SG": 1}

    publisher = _youtube_publisher(db_session, CHANNEL_A)
    assert publisher is not None
    assert publisher.market_id is not None

    snapshots = _snapshots_for_content(db_session, video.id)
    collected_times = {row.collected_at for row in snapshots}
    assert collected_times == {COLLECTED}
    assert all(row.source_metadata["region_codes"] == ["ID", "SG"] for row in snapshots)
