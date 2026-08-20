"""Map YouTube resources onto Trendora domain records. No HTTP. No Session."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from trendora.connectors.youtube.schemas import ChannelResource, VideoResource
from trendora.reference import MARKET_IDS, RETENTION_POLICIES

YOUTUBE_SOURCE_CODE = "youtube"
CONTENT_TYPE_VIDEO = "video"

STATS_POLICY_CODE = "youtube_non_authorized_stats"
METADATA_POLICY_CODE = "youtube_non_authorized_metadata"

VIDEO_METRIC_FIELDS: tuple[tuple[str, str], ...] = (
    ("viewCount", "view_count"),
    ("likeCount", "like_count"),
    ("commentCount", "comment_count"),
)
CHANNEL_METRIC_FIELDS: tuple[tuple[str, str], ...] = (
    ("viewCount", "view_count"),
    ("subscriberCount", "subscriber_count"),
    ("videoCount", "video_count"),
)


def _policy_days(code: str) -> int:
    for row in RETENTION_POLICIES:
        if row["code"] == code:
            days = row["retention_days"]
            if not isinstance(days, int):
                raise RuntimeError(f"retention policy {code} is missing retention_days")
            return days
    raise RuntimeError(f"unknown retention policy {code}")


def retain_until(collected_at: datetime, *, policy_code: str) -> datetime:
    return collected_at + timedelta(days=_policy_days(policy_code))


def parse_youtube_datetime(value: str | None) -> datetime | None:
    if not value or not str(value).strip():
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_count(value: object) -> int | None:
    if value is None or value is False:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    if parsed < 0:
        return None
    return parsed


@dataclass(frozen=True)
class NormalizedSnapshot:
    metric_name: str
    metric_value: int
    observed_at: datetime
    collected_at: datetime
    retention_policy_code: str
    retain_until: datetime
    subject: Literal["publisher", "content_item"]
    source_metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class NormalizedContentItem:
    external_id: str
    publisher_external_id: str
    content_type: str
    title: str | None
    description: str | None
    url: str | None
    published_at: datetime | None
    source_metadata: dict[str, Any]
    retain_until: datetime
    snapshots: tuple[NormalizedSnapshot, ...] = ()


@dataclass(frozen=True)
class ChannelIngestionBundle:
    """One channel plus its videos, ready for persistence."""

    publisher_external_id: str
    publisher_name: str | None
    publisher_url: str | None
    market_code: str | None
    publisher_source_metadata: dict[str, Any]
    publisher_retain_until: datetime
    publisher_snapshots: tuple[NormalizedSnapshot, ...]
    content_items: tuple[NormalizedContentItem, ...] = field(default_factory=tuple)
    collected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def normalize_channel(
    channel: ChannelResource,
    videos: Sequence[VideoResource],
    *,
    collected_at: datetime,
) -> ChannelIngestionBundle:
    if collected_at.tzinfo is None:
        raise ValueError("collected_at must be timezone-aware")

    stats_until = retain_until(collected_at, policy_code=STATS_POLICY_CODE)
    meta_until = retain_until(collected_at, policy_code=METADATA_POLICY_CODE)
    country = (channel.snippet.country or "").strip().upper() or None
    market_code = country if country in MARKET_IDS else None

    publisher_metadata: dict[str, Any] = {
        "kind": "youtube#channel",
        "custom_url": channel.snippet.custom_url,
        "published_at": channel.snippet.published_at,
        "country": channel.snippet.country,
        "description": channel.snippet.description,
        "uploads_playlist_id": channel.uploads_playlist_id,
    }

    publisher_snapshots = _channel_snapshots(
        channel.statistics,
        collected_at=collected_at,
        retain_until_at=stats_until,
    )

    items = tuple(
        normalize_video(video, publisher_external_id=channel.id, collected_at=collected_at)
        for video in videos
    )

    return ChannelIngestionBundle(
        publisher_external_id=channel.id,
        publisher_name=channel.snippet.title,
        publisher_url=f"https://www.youtube.com/channel/{channel.id}",
        market_code=market_code,
        publisher_source_metadata=publisher_metadata,
        publisher_retain_until=meta_until,
        publisher_snapshots=publisher_snapshots,
        content_items=items,
        collected_at=collected_at,
    )


def normalize_video(
    video: VideoResource,
    *,
    publisher_external_id: str,
    collected_at: datetime,
) -> NormalizedContentItem:
    meta_until = retain_until(collected_at, policy_code=METADATA_POLICY_CODE)
    stats_until = retain_until(collected_at, policy_code=STATS_POLICY_CODE)
    details = video.content_details
    snippet = video.snippet
    source_metadata: dict[str, Any] = {
        "kind": "youtube#video",
        "channel_id": snippet.channel_id or publisher_external_id,
        "category_id": snippet.category_id,
        "duration": details.duration if details else None,
        "definition": details.definition if details else None,
        "caption": details.caption if details else None,
        "default_language": snippet.default_language,
        "default_audio_language": snippet.default_audio_language,
        "tags": snippet.tags,
    }
    snapshots = _video_snapshots(
        video.statistics,
        collected_at=collected_at,
        retain_until_at=stats_until,
    )
    return NormalizedContentItem(
        external_id=video.id,
        publisher_external_id=publisher_external_id,
        content_type=CONTENT_TYPE_VIDEO,
        title=snippet.title,
        description=snippet.description,
        url=f"https://www.youtube.com/watch?v={video.id}",
        published_at=parse_youtube_datetime(snippet.published_at),
        source_metadata=source_metadata,
        retain_until=meta_until,
        snapshots=snapshots,
    )


def _channel_snapshots(
    statistics: dict[str, Any],
    *,
    collected_at: datetime,
    retain_until_at: datetime,
) -> tuple[NormalizedSnapshot, ...]:
    hidden = statistics.get("hiddenSubscriberCount") is True
    rows: list[NormalizedSnapshot] = []
    for youtube_field, metric_name in CHANNEL_METRIC_FIELDS:
        if metric_name == "subscriber_count" and hidden:
            continue
        parsed = parse_count(statistics.get(youtube_field))
        if parsed is None:
            continue
        rows.append(
            _snapshot(
                metric_name=metric_name,
                metric_value=parsed,
                youtube_field=youtube_field,
                collected_at=collected_at,
                retain_until_at=retain_until_at,
                subject="publisher",
            )
        )
    return tuple(rows)


def _video_snapshots(
    statistics: dict[str, Any],
    *,
    collected_at: datetime,
    retain_until_at: datetime,
) -> tuple[NormalizedSnapshot, ...]:
    rows: list[NormalizedSnapshot] = []
    for youtube_field, metric_name in VIDEO_METRIC_FIELDS:
        parsed = parse_count(statistics.get(youtube_field))
        if parsed is None:
            continue
        rows.append(
            _snapshot(
                metric_name=metric_name,
                metric_value=parsed,
                youtube_field=youtube_field,
                collected_at=collected_at,
                retain_until_at=retain_until_at,
                subject="content_item",
            )
        )
    return tuple(rows)


def _snapshot(
    *,
    metric_name: str,
    metric_value: int,
    youtube_field: str,
    collected_at: datetime,
    retain_until_at: datetime,
    subject: Literal["publisher", "content_item"],
) -> NormalizedSnapshot:
    return NormalizedSnapshot(
        metric_name=metric_name,
        metric_value=metric_value,
        observed_at=collected_at,
        collected_at=collected_at,
        retention_policy_code=STATS_POLICY_CODE,
        retain_until=retain_until_at,
        subject=subject,
        source_metadata={"youtube_field": youtube_field},
    )
