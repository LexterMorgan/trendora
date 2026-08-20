"""Orchestrate Hacker News fetch → normalize → persist for selected feeds."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from trendora.connectors.base import ChannelIngestionOutcome, IngestionResult
from trendora.connectors.hackernews.client import HackerNewsClient
from trendora.connectors.hackernews.exceptions import (
    HackerNewsConfigurationError,
    HackerNewsHttpError,
    HackerNewsItemError,
    HackerNewsResponseError,
)
from trendora.connectors.hackernews.normalizer import DEFAULT_FEEDS, NormalizedStory, normalize_story
from trendora.connectors.hackernews.persistence import StoryPersistResult, persist_story
from trendora.connectors.hackernews.schemas import ItemResource
from trendora.db.session import get_session_factory

logger = logging.getLogger("trendora.connectors.hackernews")

DEFAULT_MAX_ITEMS_PER_FEED = 50
ALLOWED_FEEDS = set(DEFAULT_FEEDS)

_FETCH_ERRORS = (
    HackerNewsHttpError,
    HackerNewsResponseError,
    HackerNewsItemError,
)


class HackerNewsDataSource(Protocol):
    def list_feed_ids(self, feed: str, *, max_items: int) -> list[int]: ...

    def get_item(self, item_id: int) -> ItemResource | None: ...


class StoryStore(Protocol):
    def persist(self, story: NormalizedStory) -> StoryPersistResult: ...


class SqlAlchemyStoryStore:
    """One transaction per story. Does not span the whole feed run."""

    def __init__(self, session_factory: sessionmaker[Session] | None = None) -> None:
        self._session_factory = session_factory or get_session_factory()

    def persist(self, story: NormalizedStory) -> StoryPersistResult:
        session = self._session_factory()
        try:
            result = persist_story(session, story)
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def parse_feeds(value: str | Sequence[str] | None) -> tuple[str, ...]:
    """Return unique HN feed names in first-seen order.

    ``None`` selects topstories, newstories, and beststories.
    """

    if value is None:
        return DEFAULT_FEEDS
    if isinstance(value, str):
        tokens = value.split(",")
    else:
        tokens = list(value)

    allowed = ", ".join(DEFAULT_FEEDS)
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in tokens:
        token = raw.strip().lower()
        if not token:
            continue
        if token not in ALLOWED_FEEDS:
            raise HackerNewsConfigurationError(
                f"Unknown feed {raw!r}. Allowed: {allowed}"
            )
        if token in seen:
            continue
        seen.add(token)
        ordered.append(token)
    if not ordered:
        raise HackerNewsConfigurationError(f"At least one feed is required. Allowed: {allowed}")
    return tuple(ordered)


class HackerNewsConnector:
    source_code = "hacker_news"

    def __init__(
        self,
        client: HackerNewsDataSource,
        store: StoryStore,
        *,
        feeds: Sequence[str] | None = None,
        max_items: int = DEFAULT_MAX_ITEMS_PER_FEED,
    ) -> None:
        self._client = client
        self._store = store
        self._feeds = parse_feeds(feeds)
        if max_items < 1:
            raise HackerNewsConfigurationError("max items per feed must be >= 1")
        self._max_items = max_items

    def ingest(self, *, collected_at: datetime | None = None) -> IngestionResult:
        if collected_at is not None and collected_at.tzinfo is None:
            raise ValueError("collected_at must be timezone-aware")
        run_collected_at = collected_at or datetime.now(timezone.utc)

        logger.info(
            "hackernews.ingest.start feeds=%s max_items=%s",
            ",".join(self._feeds),
            self._max_items,
        )
        result = IngestionResult(source_code=self.source_code, watchlist_size=len(self._feeds))
        ordered_ids, feeds_by_id = self._collect_ids(result)
        result.watchlist_size = len(ordered_ids)

        for item_id in ordered_ids:
            try:
                outcome = self._ingest_one(item_id, feeds_by_id[item_id], run_collected_at)
            except IntegrityError:
                logger.exception("hackernews.ingest.integrity_error item_id=%s", item_id)
                raise
            except SQLAlchemyError:
                logger.exception("hackernews.ingest.database_error item_id=%s", item_id)
                raise
            result.outcomes.append(outcome)
            if outcome.ok:
                logger.info(
                    "hackernews.ingest.item_ok item_id=%s snapshots=%s",
                    item_id,
                    outcome.snapshots_inserted,
                )
            else:
                logger.error(
                    "hackernews.ingest.item_failed item_id=%s error=%s",
                    item_id,
                    outcome.error,
                )

        logger.info(
            "hackernews.ingest.complete succeeded=%s failed=%s snapshots=%s",
            len(result.succeeded),
            len(result.failed),
            result.snapshots_inserted,
        )
        return result

    def _collect_ids(self, result: IngestionResult) -> tuple[list[int], dict[int, list[str]]]:
        ordered_ids: list[int] = []
        feeds_by_id: dict[int, list[str]] = {}
        for feed in self._feeds:
            try:
                ids = self._client.list_feed_ids(feed, max_items=self._max_items)
            except _FETCH_ERRORS as exc:
                logger.error("hackernews.ingest.feed_failed feed=%s error=%s", feed, exc)
                result.outcomes.append(ChannelIngestionOutcome(external_id=feed, error=str(exc)))
                continue
            logger.info("hackernews.ingest.feed_collected feed=%s items=%s", feed, len(ids))
            for item_id in ids:
                if item_id not in feeds_by_id:
                    ordered_ids.append(item_id)
                    feeds_by_id[item_id] = []
                if feed not in feeds_by_id[item_id]:
                    feeds_by_id[item_id].append(feed)
        return ordered_ids, feeds_by_id

    def _ingest_one(
        self,
        item_id: int,
        feeds: Sequence[str],
        collected_at: datetime,
    ) -> ChannelIngestionOutcome:
        try:
            item = self._client.get_item(item_id)
            if item is None:
                raise HackerNewsItemError(f"Hacker News item {item_id} is missing")
            story = normalize_story(item, feeds=feeds, collected_at=collected_at)
            persisted = self._store.persist(story)
        except _FETCH_ERRORS as exc:
            return ChannelIngestionOutcome(external_id=str(item_id), error=str(exc))

        return ChannelIngestionOutcome(
            external_id=str(item_id),
            content_items_upserted=1,
            snapshots_inserted=persisted.snapshots_inserted,
        )


def build_hackernews_connector(
    *,
    feeds: Sequence[str] | None = None,
    max_items: int = DEFAULT_MAX_ITEMS_PER_FEED,
    client: HackerNewsDataSource | None = None,
    store: StoryStore | None = None,
    http_client=None,
) -> HackerNewsConnector:
    hn_client: HackerNewsDataSource
    if client is not None:
        hn_client = client
    else:
        hn_client = HackerNewsClient(http_client=http_client)
    return HackerNewsConnector(
        hn_client,
        store or SqlAlchemyStoryStore(),
        feeds=feeds,
        max_items=max_items,
    )
