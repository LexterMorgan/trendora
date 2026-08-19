"""YouTube connector orchestration tests. Fake client and store; no live API."""

from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from trendora.connectors.youtube.connector import YouTubeConnector
from trendora.connectors.youtube.exceptions import EmptyWatchlistError
from trendora.connectors.youtube.normalizer import ChannelIngestionBundle
from trendora.connectors.youtube.persistence import ChannelPersistResult
from trendora.connectors.youtube.schemas import ChannelResource, VideoResource
from tests.fixtures.youtube_responses import (
    CHANNEL_A,
    CHANNEL_B,
    CHANNELS_LIST_MISSING_UPLOADS,
    CHANNELS_LIST_OK,
    VIDEO_1,
    VIDEO_2,
    VIDEOS_LIST_OK,
)

COLLECTED = datetime(2026, 8, 19, 15, 0, tzinfo=timezone.utc)


class FakeClient:
    def __init__(
        self,
        *,
        channels: list[ChannelResource] | None = None,
        video_ids: list[str] | None = None,
        videos: list[VideoResource] | None = None,
        fail: Exception | None = None,
    ) -> None:
        self.channels = channels or []
        self.video_ids = video_ids if video_ids is not None else [VIDEO_1, VIDEO_2]
        self.videos = videos or [VideoResource.model_validate(item) for item in VIDEOS_LIST_OK["items"]]
        self.fail = fail
        self.channel_requests: list[tuple[str, ...]] = []
        self.playlist_requests: list[tuple[str, int]] = []
        self.video_requests: list[tuple[str, ...]] = []

    def list_channels(self, channel_ids):
        if self.fail:
            raise self.fail
        self.channel_requests.append(tuple(channel_ids))
        return self.channels

    def list_upload_video_ids(self, uploads_playlist_id: str, *, limit: int) -> list[str]:
        self.playlist_requests.append((uploads_playlist_id, limit))
        return self.video_ids[:limit]

    def list_videos(self, video_ids):
        self.video_requests.append(tuple(video_ids))
        return [video for video in self.videos if video.id in set(video_ids)]


class FakeStore:
    def __init__(self, *, fail: Exception | None = None) -> None:
        self.bundles: list[ChannelIngestionBundle] = []
        self.fail = fail

    def persist(self, bundle: ChannelIngestionBundle) -> ChannelPersistResult:
        if self.fail:
            raise self.fail
        self.bundles.append(bundle)
        return ChannelPersistResult(
            publisher_created=True,
            publisher_updated=False,
            content_items_upserted=len(bundle.content_items),
            snapshots_inserted=len(bundle.publisher_snapshots)
            + sum(len(item.snapshots) for item in bundle.content_items),
        )


def _channel() -> ChannelResource:
    return ChannelResource.model_validate(CHANNELS_LIST_OK["items"][0])


def test_empty_watchlist_fails_before_any_request() -> None:
    client = FakeClient()
    connector = YouTubeConnector(client, FakeStore(), watchlist=())
    with pytest.raises(EmptyWatchlistError, match="YOUTUBE_CHANNEL_IDS"):
        connector.ingest()
    assert client.channel_requests == []


def test_duplicate_watchlist_ids_are_ingested_once() -> None:
    store = FakeStore()
    client = FakeClient(channels=[_channel()])
    connector = YouTubeConnector(
        client,
        store,
        watchlist=(CHANNEL_A, CHANNEL_A),
        max_videos_per_channel=10,
    )
    result = connector.ingest(collected_at=COLLECTED)
    assert result.watchlist_size == 1
    assert len(result.succeeded) == 1
    assert len(store.bundles) == 1
    assert client.playlist_requests[0][1] == 10


def test_successful_ingest_normalizes_and_persists() -> None:
    store = FakeStore()
    connector = YouTubeConnector(
        FakeClient(channels=[_channel()]),
        store,
        watchlist=(CHANNEL_A,),
        max_videos_per_channel=2,
    )
    result = connector.ingest(collected_at=COLLECTED)
    assert result.failed == []
    outcome = result.succeeded[0]
    assert outcome.external_id == CHANNEL_A
    assert outcome.content_items_upserted == 2
    assert outcome.snapshots_inserted > 0
    bundle = store.bundles[0]
    assert bundle.collected_at == COLLECTED
    assert all(item.snapshots[0].collected_at == COLLECTED for item in bundle.content_items if item.snapshots)


def test_missing_uploads_playlist_fails_that_channel_only() -> None:
    missing = ChannelResource.model_validate(CHANNELS_LIST_MISSING_UPLOADS["items"][0])
    present = _channel()
    present_id_swap = ChannelResource.model_validate({**CHANNELS_LIST_OK["items"][0], "id": CHANNEL_B})
    store = FakeStore()
    client = FakeClient(channels=[missing, present_id_swap], video_ids=[], videos=[])
    connector = YouTubeConnector(
        client,
        store,
        watchlist=(CHANNEL_A, CHANNEL_B),
        max_videos_per_channel=5,
    )
    result = connector.ingest(collected_at=COLLECTED)
    assert [row.external_id for row in result.failed] == [CHANNEL_A]
    assert "uploads playlist" in (result.failed[0].error or "")
    assert [row.external_id for row in result.succeeded] == [CHANNEL_B]


def test_unknown_channel_id_is_a_channel_failure() -> None:
    connector = YouTubeConnector(
        FakeClient(channels=[]),
        FakeStore(),
        watchlist=(CHANNEL_A,),
    )
    result = connector.ingest(collected_at=COLLECTED)
    assert len(result.failed) == 1
    assert "did not return" in (result.failed[0].error or "")


def test_integrity_error_is_not_swallowed() -> None:
    connector = YouTubeConnector(
        FakeClient(channels=[_channel()], video_ids=[], videos=[]),
        FakeStore(fail=IntegrityError("stmt", {}, Exception("unique"))),
        watchlist=(CHANNEL_A,),
    )
    with pytest.raises(IntegrityError):
        connector.ingest(collected_at=COLLECTED)


def test_connector_does_not_call_search() -> None:
    client = FakeClient(channels=[_channel()], video_ids=[], videos=[])
    YouTubeConnector(client, FakeStore(), watchlist=(CHANNEL_A,)).ingest(collected_at=COLLECTED)
    assert client.channel_requests
    assert not hasattr(client, "search")
