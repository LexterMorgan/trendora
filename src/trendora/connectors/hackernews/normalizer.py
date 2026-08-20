"""Map Hacker News items onto Trendora domain records. No HTTP. No Session."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from trendora.connectors.hackernews.exceptions import HackerNewsItemError
from trendora.connectors.hackernews.schemas import ItemResource

HN_SOURCE_CODE = "hacker_news"
CONTENT_TYPE_STORY = "story"
HN_ITEM_URL = "https://news.ycombinator.com/item?id={id}"

DEFAULT_FEEDS: tuple[str, ...] = ("topstories", "newstories", "beststories")


@dataclass(frozen=True)
class NormalizedSnapshot:
    metric_name: str
    metric_value: int
    observed_at: datetime
    collected_at: datetime
    subject: Literal["content_item"] = "content_item"
    source_metadata: dict[str, Any] | None = None
    retention_policy_code: str | None = None
    retain_until: datetime | None = None


@dataclass(frozen=True)
class NormalizedStory:
    external_id: str
    content_type: str
    title: str | None
    description: str | None
    url: str | None
    published_at: datetime | None
    source_metadata: dict[str, Any]
    snapshots: tuple[NormalizedSnapshot, ...]
    collected_at: datetime
    retain_until: datetime | None = None


def normalize_story(
    item: ItemResource,
    *,
    feeds: Sequence[str],
    collected_at: datetime,
) -> NormalizedStory:
    if collected_at.tzinfo is None:
        raise ValueError("collected_at must be timezone-aware")
    if item.deleted:
        raise HackerNewsItemError(f"Hacker News item {item.id} is deleted")
    if item.dead:
        raise HackerNewsItemError(f"Hacker News item {item.id} is dead")
    if item.type != CONTENT_TYPE_STORY:
        raise HackerNewsItemError(
            f"Hacker News item {item.id} is type {item.type!r}, not a story"
        )

    article_url = (item.url or "").strip() or None
    content_url = article_url or HN_ITEM_URL.format(id=item.id)
    text = (item.text or "").strip() or None
    metadata: dict[str, Any] = {
        "kind": "hacker_news#item",
        "hn_type": item.type,
        "author": (item.by or "").strip() or None,
        "feeds": _stable_feeds(feeds),
        "url": article_url,
    }
    if text is not None:
        metadata["text"] = text

    return NormalizedStory(
        external_id=str(item.id),
        content_type=CONTENT_TYPE_STORY,
        title=(item.title or "").strip() or None,
        description=text,
        url=content_url,
        published_at=_unix_time(item.time),
        source_metadata=metadata,
        snapshots=_story_snapshots(item, collected_at=collected_at),
        collected_at=collected_at,
    )


def _stable_feeds(feeds: Sequence[str]) -> list[str]:
    order = {name: index for index, name in enumerate(DEFAULT_FEEDS)}
    unique = list(dict.fromkeys(feeds))
    return sorted(unique, key=lambda name: order.get(name, len(order)))


def _unix_time(value: int | None) -> datetime | None:
    if value is None or value < 0:
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc)


def _story_snapshots(item: ItemResource, *, collected_at: datetime) -> tuple[NormalizedSnapshot, ...]:
    rows: list[NormalizedSnapshot] = []
    if item.score is not None and item.score >= 0:
        rows.append(
            NormalizedSnapshot(
                metric_name="score",
                metric_value=item.score,
                observed_at=collected_at,
                collected_at=collected_at,
                source_metadata={"hn_field": "score"},
            )
        )
    if item.descendants is not None and item.descendants >= 0:
        rows.append(
            NormalizedSnapshot(
                metric_name="comment_count",
                metric_value=item.descendants,
                observed_at=collected_at,
                collected_at=collected_at,
                source_metadata={"hn_field": "descendants"},
            )
        )
    return tuple(rows)
