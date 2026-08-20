"""Regional mostPopular orchestrator tests. Fake client and store; no live API."""

from datetime import datetime, timezone

import pytest

from trendora.connectors.youtube.exceptions import YouTubeApiError, YouTubeConfigurationError
from trendora.connectors.youtube.most_popular import (
    DEFAULT_MOST_POPULAR_MARKETS,
    MostPopularConnector,
    parse_region_codes,
)
from trendora.connectors.youtube.normalizer import ChannelIngestionBundle
from trendora.connectors.youtube.persistence import ChannelPersistResult
from trendora.connectors.youtube.schemas import ChannelResource, VideoCategoryResource, VideoResource
from tests.fixtures.youtube_responses import (
    CHANNEL_A,
    CHANNEL_C,
    CHANNELS_LIST_A_AND_C,
    CHANNELS_LIST_OK,
    MOSTPOPULAR_EMPTY,
    MOSTPOPULAR_ID_PAGE_1,
    MOSTPOPULAR_ID_PAGE_2,
    MOSTPOPULAR_NO_CHANNEL_ID,
    MOSTPOPULAR_SG,
    VIDEO_1,
    VIDEO_2,
    VIDEO_CHART_1,
    VIDEO_CATEGORIES_ID,
    VIDEO_CATEGORIES_SG,
    VIDEO_NO_CHANNEL,
)

COLLECTED = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)


class FakeMostPopularClient:
    def __init__(
        self,
        *,
        categories: dict[str, list[VideoCategoryResource]] | None = None,
        charts: dict[str, list[VideoResource]] | None = None,
        channels: list[ChannelResource] | None = None,
        region_errors: dict[str, Exception] | None = None,
    ) -> None:
        self.categories = categories or {}
        self.charts = charts or {}
        self.channels = channels or []
        self.region_errors = region_errors or {}
        self.category_requests: list[str] = []
        self.chart_requests: list[tuple[str, int]] = []
        self.channel_requests: list[tuple[str, ...]] = []

    def list_video_categories(self, region_code: str) -> list[VideoCategoryResource]:
        if region_code in self.region_errors:
            raise self.region_errors[region_code]
        self.category_requests.append(region_code)
        return self.categories.get(region_code, [])

    def list_most_popular_videos(self, region_code: str, *, max_videos: int) -> list[VideoResource]:
        if region_code in self.region_errors:
            raise self.region_errors[region_code]
        self.chart_requests.append((region_code, max_videos))
        return self.charts.get(region_code, [])[:max_videos]

    def list_channels(self, channel_ids):
        self.channel_requests.append(tuple(channel_ids))
        wanted = set(channel_ids)
        return [channel for channel in self.channels if channel.id in wanted]


class FakeStore:
    def __init__(self) -> None:
        self.bundles: list[ChannelIngestionBundle] = []

    def persist(self, bundle: ChannelIngestionBundle) -> ChannelPersistResult:
        self.bundles.append(bundle)
        return ChannelPersistResult(
            publisher_created=True,
            publisher_updated=False,
            content_items_upserted=len(bundle.content_items),
            snapshots_inserted=len(bundle.publisher_snapshots)
            + sum(len(item.snapshots) for item in bundle.content_items),
        )


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


def test_parse_region_codes_defaults_to_seeded_sea_markets() -> None:
    assert parse_region_codes(None) == DEFAULT_MOST_POPULAR_MARKETS
    assert parse_region_codes(None) == ("ID", "TH", "MY", "SG", "VN", "PH")


def test_parse_region_codes_normalizes_and_dedupes() -> None:
    assert parse_region_codes("id, SG,id") == ("ID", "SG")


def test_parse_region_codes_rejects_unknown_markets() -> None:
    with pytest.raises(YouTubeConfigurationError, match="Unknown market"):
        parse_region_codes("ID,US")


def test_ingest_fetches_categories_and_charts_per_region_in_stable_order() -> None:
    client = FakeMostPopularClient(
        categories={"ID": _categories(VIDEO_CATEGORIES_ID), "SG": _categories(VIDEO_CATEGORIES_SG)},
        charts={
            "ID": _videos(MOSTPOPULAR_ID_PAGE_1, MOSTPOPULAR_ID_PAGE_2),
            "SG": _videos(MOSTPOPULAR_SG),
        },
        channels=_channels(),
    )
    store = FakeStore()
    connector = MostPopularConnector(
        client,
        store,
        region_codes=("ID", "SG"),
        max_videos_per_market=50,
    )
    result = connector.ingest(collected_at=COLLECTED)

    assert client.category_requests == ["ID", "SG"]
    assert [region for region, _limit in client.chart_requests] == ["ID", "SG"]
    assert all(limit == 50 for _region, limit in client.chart_requests)
    assert result.failed == []
    assert {outcome.external_id for outcome in result.succeeded} == {CHANNEL_A, CHANNEL_C}


def test_ingest_does_not_crawl_playlists_or_search() -> None:
    client = FakeMostPopularClient(
        categories={"ID": _categories(VIDEO_CATEGORIES_ID)},
        charts={"ID": _videos(MOSTPOPULAR_ID_PAGE_1)},
        channels=[ChannelResource.model_validate(CHANNELS_LIST_OK["items"][0])],
    )
    MostPopularConnector(client, FakeStore(), region_codes=("ID",)).ingest(collected_at=COLLECTED)
    assert not hasattr(client, "list_upload_video_ids")
    assert not hasattr(client, "list_videos")
    assert not hasattr(client, "search")
    assert client.channel_requests == [(CHANNEL_A,)]


def test_empty_chart_skips_region_without_failing() -> None:
    client = FakeMostPopularClient(
        categories={"ID": _categories(VIDEO_CATEGORIES_ID), "SG": _categories(VIDEO_CATEGORIES_SG)},
        charts={"ID": _videos(MOSTPOPULAR_EMPTY), "SG": _videos(MOSTPOPULAR_SG)},
        channels=_channels(),
    )
    store = FakeStore()
    result = MostPopularConnector(client, store, region_codes=("ID", "SG")).ingest(collected_at=COLLECTED)
    assert result.failed == []
    persisted_ids = {bundle.publisher_external_id for bundle in store.bundles}
    assert persisted_ids == {CHANNEL_A, CHANNEL_C}


def test_duplicate_video_across_regions_is_merged_before_persist() -> None:
    client = FakeMostPopularClient(
        categories={"ID": _categories(VIDEO_CATEGORIES_ID), "SG": _categories(VIDEO_CATEGORIES_SG)},
        charts={
            "ID": _videos(MOSTPOPULAR_ID_PAGE_1, MOSTPOPULAR_ID_PAGE_2),
            "SG": _videos(MOSTPOPULAR_SG),
        },
        channels=_channels(),
    )
    store = FakeStore()
    MostPopularConnector(client, store, region_codes=("ID", "SG")).ingest(collected_at=COLLECTED)

    by_channel = {bundle.publisher_external_id: bundle for bundle in store.bundles}
    assert len(by_channel) == 2
    video_one = next(item for item in by_channel[CHANNEL_A].content_items if item.external_id == VIDEO_1)
    assert video_one.source_metadata["chart"] == "mostPopular"
    assert video_one.source_metadata["region_codes"] == ["ID", "SG"]
    assert video_one.source_metadata["category_id"] == "27"
    assert video_one.source_metadata["category_title"] == "Education"
    assert video_one.source_metadata["category_titles_by_region"] == {
        "ID": "Education",
        "SG": "Education (SG)",
    }
    assert video_one.source_metadata["chart_positions_by_region"] == {"ID": 1, "SG": 1}
    assert all(item.snapshots[0].collected_at == COLLECTED for item in by_channel[CHANNEL_A].content_items)
    assert video_one.snapshots[0].source_metadata is not None
    assert video_one.snapshots[0].source_metadata["chart"] == "mostPopular"
    assert video_one.snapshots[0].source_metadata["region_codes"] == ["ID", "SG"]


def test_market_id_stays_on_channel_country_not_chart_region() -> None:
    client = FakeMostPopularClient(
        categories={"ID": _categories(VIDEO_CATEGORIES_ID)},
        charts={"ID": _videos(MOSTPOPULAR_ID_PAGE_2)},
        channels=_channels(),
    )
    store = FakeStore()
    MostPopularConnector(client, store, region_codes=("ID",)).ingest(collected_at=COLLECTED)
    bundle = store.bundles[0]
    assert bundle.publisher_external_id == CHANNEL_C
    assert bundle.market_code is None
    video = bundle.content_items[0]
    assert video.external_id == VIDEO_CHART_1
    assert video.source_metadata["region_codes"] == ["ID"]
    assert video.source_metadata["category_title"] == "Entertainment"


def test_video_without_channel_id_is_skipped() -> None:
    client = FakeMostPopularClient(
        categories={"ID": _categories(VIDEO_CATEGORIES_ID)},
        charts={"ID": _videos(MOSTPOPULAR_NO_CHANNEL_ID)},
        channels=[ChannelResource.model_validate(CHANNELS_LIST_OK["items"][0])],
    )
    store = FakeStore()
    result = MostPopularConnector(client, store, region_codes=("ID",)).ingest(collected_at=COLLECTED)
    assert result.failed == []
    assert [bundle.publisher_external_id for bundle in store.bundles] == [CHANNEL_A]
    persisted_videos = [item.external_id for item in store.bundles[0].content_items]
    assert VIDEO_NO_CHANNEL not in persisted_videos
    assert VIDEO_1 in persisted_videos
    assert client.channel_requests == [(CHANNEL_A,)]


def test_one_run_uses_one_collected_at() -> None:
    client = FakeMostPopularClient(
        categories={"ID": _categories(VIDEO_CATEGORIES_ID), "SG": _categories(VIDEO_CATEGORIES_SG)},
        charts={"ID": _videos(MOSTPOPULAR_ID_PAGE_1), "SG": _videos(MOSTPOPULAR_SG)},
        channels=_channels(),
    )
    store = FakeStore()
    MostPopularConnector(client, store, region_codes=("ID", "SG")).ingest(collected_at=COLLECTED)
    timestamps = {bundle.collected_at for bundle in store.bundles}
    assert timestamps == {COLLECTED}


def test_region_api_error_fails_that_region_and_continues() -> None:
    client = FakeMostPopularClient(
        categories={"SG": _categories(VIDEO_CATEGORIES_SG)},
        charts={"SG": _videos(MOSTPOPULAR_SG)},
        channels=_channels(),
        region_errors={"ID": YouTubeApiError("quota exceeded", status_code=403, reason="quotaExceeded")},
    )
    store = FakeStore()
    result = MostPopularConnector(client, store, region_codes=("ID", "SG")).ingest(collected_at=COLLECTED)
    assert [row.external_id for row in result.failed] == ["ID"]
    assert "quota" in (result.failed[0].error or "").lower()
    assert {bundle.publisher_external_id for bundle in store.bundles} == {CHANNEL_A, CHANNEL_C}


def test_chart_only_channel_is_not_on_a_watchlist() -> None:
    client = FakeMostPopularClient(
        categories={"ID": _categories(VIDEO_CATEGORIES_ID)},
        charts={"ID": _videos(MOSTPOPULAR_ID_PAGE_2)},
        channels=_channels(),
    )
    store = FakeStore()
    connector = MostPopularConnector(client, store, region_codes=("ID",))
    assert not hasattr(connector, "_watchlist")
    connector.ingest(collected_at=COLLECTED)
    assert store.bundles[0].publisher_external_id == CHANNEL_C


def test_channel_videos_are_grouped_and_persisted_once() -> None:
    client = FakeMostPopularClient(
        categories={"ID": _categories(VIDEO_CATEGORIES_ID)},
        charts={"ID": _videos(MOSTPOPULAR_ID_PAGE_1)},
        channels=[ChannelResource.model_validate(CHANNELS_LIST_OK["items"][0])],
    )
    store = FakeStore()
    MostPopularConnector(client, store, region_codes=("ID",)).ingest(collected_at=COLLECTED)
    assert len(store.bundles) == 1
    assert {item.external_id for item in store.bundles[0].content_items} == {VIDEO_1, VIDEO_2}
