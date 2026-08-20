"""Hacker News orchestrator tests. Fake client and store; no live API."""

from datetime import datetime, timezone

import pytest

from trendora.connectors.hackernews.connector import (
    DEFAULT_FEEDS,
    HackerNewsConnector,
    parse_feeds,
)
from trendora.connectors.hackernews.exceptions import HackerNewsConfigurationError, HackerNewsHttpError
from trendora.connectors.hackernews.normalizer import NormalizedStory
from trendora.connectors.hackernews.persistence import StoryPersistResult
from trendora.connectors.hackernews.schemas import ItemResource
from tests.fixtures.hackernews_responses import (
    COMMENT_ITEM,
    STORY_A,
    STORY_A_ID,
    STORY_B,
    STORY_B_ID,
    STORY_C,
    STORY_C_ID,
)

COLLECTED = datetime(2026, 8, 20, 18, 30, tzinfo=timezone.utc)


class FakeClient:
    def __init__(
        self,
        *,
        feeds: dict[str, list[int]] | None = None,
        items: dict[int, ItemResource] | None = None,
        feed_errors: dict[str, Exception] | None = None,
        missing_ids: set[int] | None = None,
    ) -> None:
        self.feeds = feeds or {}
        self.items = items or {}
        self.feed_errors = feed_errors or {}
        self.missing_ids = missing_ids or set()
        self.feed_requests: list[tuple[str, int]] = []
        self.item_requests: list[int] = []

    def list_feed_ids(self, feed: str, *, max_items: int) -> list[int]:
        if feed in self.feed_errors:
            raise self.feed_errors[feed]
        self.feed_requests.append((feed, max_items))
        return list(self.feeds.get(feed, []))[:max_items]

    def get_item(self, item_id: int) -> ItemResource | None:
        self.item_requests.append(item_id)
        if item_id in self.missing_ids:
            return None
        return self.items.get(item_id)


class FakeStore:
    def __init__(self) -> None:
        self.stories: list[NormalizedStory] = []

    def persist(self, story: NormalizedStory) -> StoryPersistResult:
        self.stories.append(story)
        return StoryPersistResult(
            content_item_created=True,
            content_item_updated=False,
            snapshots_inserted=len(story.snapshots),
        )


def _items() -> dict[int, ItemResource]:
    return {
        STORY_A_ID: ItemResource.model_validate(STORY_A),
        STORY_B_ID: ItemResource.model_validate(STORY_B),
        STORY_C_ID: ItemResource.model_validate(STORY_C),
        1096: ItemResource.model_validate(COMMENT_ITEM),
    }


def test_parse_feeds_defaults_and_dedupes() -> None:
    assert parse_feeds(None) == DEFAULT_FEEDS
    assert parse_feeds("beststories, topstories,beststories") == ("beststories", "topstories")


def test_parse_feeds_rejects_unknown() -> None:
    with pytest.raises(HackerNewsConfigurationError, match="Unknown feed"):
        parse_feeds("topstories,askstories")


def test_ingest_fetches_configured_feeds_in_stable_order() -> None:
    client = FakeClient(
        feeds={
            "topstories": [STORY_A_ID],
            "newstories": [STORY_B_ID],
            "beststories": [STORY_C_ID],
        },
        items=_items(),
    )
    store = FakeStore()
    result = HackerNewsConnector(client, store, feeds=DEFAULT_FEEDS, max_items=50).ingest(
        collected_at=COLLECTED
    )
    assert [feed for feed, _limit in client.feed_requests] == [
        "topstories",
        "newstories",
        "beststories",
    ]
    assert all(limit == 50 for _feed, limit in client.feed_requests)
    assert result.failed == []
    assert {row.external_id for row in result.succeeded} == {
        str(STORY_A_ID),
        str(STORY_B_ID),
        str(STORY_C_ID),
    }


def test_duplicate_item_across_feeds_is_fetched_and_persisted_once() -> None:
    client = FakeClient(
        feeds={"topstories": [STORY_A_ID, STORY_B_ID], "beststories": [STORY_A_ID]},
        items=_items(),
    )
    store = FakeStore()
    HackerNewsConnector(
        client,
        store,
        feeds=("topstories", "beststories"),
        max_items=10,
    ).ingest(collected_at=COLLECTED)
    assert client.item_requests.count(STORY_A_ID) == 1
    stories_a = [row for row in store.stories if row.external_id == str(STORY_A_ID)]
    assert len(stories_a) == 1
    assert stories_a[0].source_metadata["feeds"] == ["topstories", "beststories"]
    assert stories_a[0].collected_at == COLLECTED
    assert all(row.collected_at == COLLECTED for row in store.stories)


def test_feed_subset_and_max_items_are_honored() -> None:
    client = FakeClient(feeds={"newstories": [STORY_B_ID, STORY_C_ID]}, items=_items())
    HackerNewsConnector(client, FakeStore(), feeds=("newstories",), max_items=1).ingest(
        collected_at=COLLECTED
    )
    assert client.feed_requests == [("newstories", 1)]
    assert client.item_requests == [STORY_B_ID]


def test_failed_feed_is_isolated_and_other_feeds_continue() -> None:
    client = FakeClient(
        feeds={"beststories": [STORY_C_ID]},
        items=_items(),
        feed_errors={"topstories": HackerNewsHttpError("boom", status_code=500)},
    )
    result = HackerNewsConnector(
        client,
        FakeStore(),
        feeds=("topstories", "beststories"),
        max_items=10,
    ).ingest(collected_at=COLLECTED)
    assert [row.external_id for row in result.failed] == ["topstories"]
    assert [row.external_id for row in result.succeeded] == [str(STORY_C_ID)]


def test_failed_item_is_isolated() -> None:
    client = FakeClient(
        feeds={"topstories": [STORY_A_ID, 1096, 1099]},
        items=_items(),
        missing_ids={1099},
    )
    store = FakeStore()
    result = HackerNewsConnector(client, store, feeds=("topstories",), max_items=10).ingest(
        collected_at=COLLECTED
    )
    assert [row.external_id for row in result.succeeded] == [str(STORY_A_ID)]
    failed_ids = {row.external_id for row in result.failed}
    assert failed_ids == {"1096", "1099"}
    assert [row.external_id for row in store.stories] == [str(STORY_A_ID)]


def test_connector_does_not_call_youtube_or_users() -> None:
    client = FakeClient(feeds={"topstories": [STORY_A_ID]}, items=_items())
    HackerNewsConnector(client, FakeStore(), feeds=("topstories",)).ingest(collected_at=COLLECTED)
    assert not hasattr(client, "list_channels")
    assert not hasattr(client, "search")
    assert not hasattr(client, "get_user")
