"""Normalization tests. No HTTP and no database."""

from datetime import datetime, timedelta, timezone

import pytest

from trendora.connectors.youtube.normalizer import (
    METADATA_POLICY_CODE,
    STATS_POLICY_CODE,
    normalize_channel,
    parse_count,
    parse_youtube_datetime,
    retain_until,
)
from trendora.connectors.youtube.schemas import ChannelResource, VideoResource
from tests.fixtures.youtube_responses import (
    CHANNEL_A,
    CHANNELS_LIST_HIDDEN_SUBSCRIBERS,
    CHANNELS_LIST_OK,
    VIDEO_1,
    VIDEOS_LIST_MALFORMED_STATS,
    VIDEOS_LIST_NO_STATS,
    VIDEOS_LIST_OK,
)

COLLECTED = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)


def test_parse_count_skips_malformed_and_negative() -> None:
    assert parse_count("10") == 10
    assert parse_count(0) == 0
    assert parse_count("not-a-number") is None
    assert parse_count("-3") is None
    assert parse_count(None) is None


def test_parse_youtube_datetime_timezone_aware() -> None:
    parsed = parse_youtube_datetime("2024-01-01T12:00:00Z")
    assert parsed is not None
    assert parsed.tzinfo is not None
    assert parse_youtube_datetime("not-a-date") is None


def test_retention_uses_existing_thirty_day_policy() -> None:
    assert retain_until(COLLECTED, policy_code=STATS_POLICY_CODE) == COLLECTED + timedelta(days=30)
    assert retain_until(COLLECTED, policy_code=METADATA_POLICY_CODE) == COLLECTED + timedelta(days=30)


def test_channel_and_video_normalization() -> None:
    channel = ChannelResource.model_validate(CHANNELS_LIST_OK["items"][0])
    videos = [VideoResource.model_validate(item) for item in VIDEOS_LIST_OK["items"]]
    bundle = normalize_channel(channel, videos, collected_at=COLLECTED)

    assert bundle.publisher_external_id == CHANNEL_A
    assert bundle.publisher_name == "SEA AI Education"
    assert bundle.market_code == "ID"
    assert bundle.publisher_url.endswith(CHANNEL_A)
    assert bundle.publisher_retain_until == COLLECTED + timedelta(days=30)

    publisher_metrics = {row.metric_name: row for row in bundle.publisher_snapshots}
    assert set(publisher_metrics) == {"view_count", "subscriber_count", "video_count"}
    assert publisher_metrics["view_count"].metric_value == 1000
    assert publisher_metrics["view_count"].observed_at == COLLECTED
    assert publisher_metrics["view_count"].collected_at == COLLECTED
    assert publisher_metrics["view_count"].retention_policy_code == STATS_POLICY_CODE
    assert publisher_metrics["view_count"].subject == "publisher"

    first = bundle.content_items[0]
    assert first.external_id == VIDEO_1
    assert first.content_type == "video"
    assert first.published_at is not None
    assert first.published_at.tzinfo is not None
    assert first.source_metadata["duration"] == "PT10M3S"
    video_metrics = {row.metric_name: row.metric_value for row in first.snapshots}
    assert video_metrics == {"view_count": 100, "like_count": 10, "comment_count": 2}
    assert "favorite_count" not in video_metrics

    second_metrics = {row.metric_name for row in bundle.content_items[1].snapshots}
    assert second_metrics == {"view_count"}


def test_hidden_subscribers_and_unknown_country_are_not_invented() -> None:
    channel = ChannelResource.model_validate(CHANNELS_LIST_HIDDEN_SUBSCRIBERS["items"][0])
    bundle = normalize_channel(channel, [], collected_at=COLLECTED)
    assert bundle.market_code is None
    assert {row.metric_name for row in bundle.publisher_snapshots} == {"view_count", "video_count"}


def test_malformed_and_missing_statistics_skip_metrics() -> None:
    channel = ChannelResource.model_validate(CHANNELS_LIST_OK["items"][0])
    malformed = [VideoResource.model_validate(item) for item in VIDEOS_LIST_MALFORMED_STATS["items"]]
    bundle = normalize_channel(channel, malformed, collected_at=COLLECTED)
    assert {row.metric_name: row.metric_value for row in bundle.content_items[0].snapshots} == {
        "comment_count": 4
    }

    empty = [VideoResource.model_validate(item) for item in VIDEOS_LIST_NO_STATS["items"]]
    bundle = normalize_channel(channel, empty, collected_at=COLLECTED)
    assert bundle.content_items[0].snapshots == ()
    assert bundle.content_items[0].published_at is None


def test_naive_collected_at_is_rejected() -> None:
    channel = ChannelResource.model_validate(CHANNELS_LIST_OK["items"][0])
    with pytest.raises(ValueError, match="timezone-aware"):
        normalize_channel(channel, [], collected_at=datetime(2026, 8, 19))
