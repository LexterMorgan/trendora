"""Hacker News HTTP client tests. All responses are mocked; no network."""

import httpx
import pytest

from trendora.connectors.hackernews.client import HackerNewsClient
from trendora.connectors.hackernews.exceptions import HackerNewsHttpError, HackerNewsResponseError
from tests.fixtures.hackernews_responses import (
    MALFORMED_FEED,
    MALFORMED_ITEM,
    MISSING_ID,
    STORY_A,
    STORY_A_ID,
    TOPSTORIES_IDS,
)


def _client(handler) -> HackerNewsClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    return HackerNewsClient(http_client=http)


def test_list_feed_ids_request_and_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://hacker-news.firebaseio.com/v0/topstories.json"
        assert "algolia" not in str(request.url)
        return httpx.Response(200, json=TOPSTORIES_IDS)

    ids = _client(handler).list_feed_ids("topstories", max_items=2)
    assert ids == [STORY_A_ID, 1002]


def test_get_item_request_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == f"https://hacker-news.firebaseio.com/v0/item/{STORY_A_ID}.json"
        return httpx.Response(200, json=STORY_A)

    item = _client(handler).get_item(STORY_A_ID)
    assert item is not None
    assert item.id == STORY_A_ID
    assert item.type == "story"
    assert item.title == "Example AI education tool"


def test_get_item_missing_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith(f"/item/{MISSING_ID}.json")
        return httpx.Response(200, text="null", headers={"content-type": "application/json"})

    assert _client(handler).get_item(MISSING_ID) is None


def test_malformed_feed_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=MALFORMED_FEED)

    with pytest.raises(HackerNewsResponseError, match="list"):
        _client(handler).list_feed_ids("newstories", max_items=10)


def test_malformed_item_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=MALFORMED_ITEM)

    with pytest.raises(HackerNewsResponseError, match="object"):
        _client(handler).get_item(STORY_A_ID)


def test_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with pytest.raises(HackerNewsHttpError, match="500"):
        _client(handler).list_feed_ids("beststories", max_items=5)


def test_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns failed", request=request)

    with pytest.raises(HackerNewsHttpError, match="HTTP request failed"):
        _client(handler).get_item(STORY_A_ID)


def test_max_items_less_than_one_returns_empty() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json=TOPSTORIES_IDS)

    assert _client(handler).list_feed_ids("topstories", max_items=0) == []
    assert calls == []
