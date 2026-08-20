"""Stack Exchange HTTP client tests. All responses are mocked; no network."""

from __future__ import annotations

import logging

import httpx
import pytest

from trendora.connectors.stackexchange.client import StackExchangeClient
from trendora.connectors.stackexchange.exceptions import (
    StackExchangeApiError,
    StackExchangeHttpError,
    StackExchangeResponseError,
)
from tests.fixtures.stackexchange_responses import (
    API_ERROR,
    QUESTIONS_EMPTY,
    QUESTIONS_MALFORMED,
    QUESTIONS_PAGE_1,
    QUESTIONS_PAGE_2,
    QUESTIONS_WITH_BACKOFF,
    QUESTION_SO_A,
    QUESTION_SO_B,
    QUESTION_SO_C,
    SO_QUESTION_ID,
)

TEST_KEY = "se-test-key-not-real"


def _client(handler, *, api_key: str | None = None, sleeper=None) -> StackExchangeClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    return StackExchangeClient(api_key=api_key, http_client=http, sleeper=sleeper)


def test_list_questions_basic_request_params() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/2.3/questions")
        assert request.url.host == "api.stackexchange.com"
        assert "/search" not in request.url.path
        assert "/answers" not in request.url.path
        assert "/users" not in request.url.path
        assert "/comments" not in request.url.path
        assert request.url.params["site"] == "stackoverflow"
        assert request.url.params["sort"] == "activity"
        assert request.url.params["order"] == "desc"
        assert request.url.params["page"] == "1"
        assert request.url.params["pagesize"] == "2"
        assert "key" not in request.url.params
        assert "tagged" not in request.url.params
        return httpx.Response(200, json=QUESTIONS_PAGE_1)

    questions = _client(handler).list_questions("stackoverflow", max_items=2)
    assert [row.question_id for row in questions] == [SO_QUESTION_ID, QUESTION_SO_B["question_id"]]
    assert questions[0].title == QUESTION_SO_A["title"]


def test_list_questions_serializes_tags_with_semicolons() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["tagged"] == "python;sql;data-science"
        return httpx.Response(200, json=QUESTIONS_EMPTY)

    questions = _client(handler).list_questions(
        "stackoverflow",
        max_items=10,
        tags=("python", "sql", "data-science"),
    )
    assert questions == []


def test_pagination_follows_has_more_and_stops_at_max_items() -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params["page"]
        pagesize = request.url.params["pagesize"]
        calls.append((page, pagesize))
        if page == "1":
            assert pagesize == "3"
            return httpx.Response(200, json=QUESTIONS_PAGE_1)
        if page == "2":
            assert pagesize == "1"
            return httpx.Response(200, json=QUESTIONS_PAGE_2)
        raise AssertionError(f"unexpected page {page}")

    questions = _client(handler).list_questions("stackoverflow", max_items=3)
    assert calls == [("1", "3"), ("2", "1")]
    assert [row.question_id for row in questions] == [
        SO_QUESTION_ID,
        QUESTION_SO_B["question_id"],
        QUESTION_SO_C["question_id"],
    ]


def test_pagination_stops_at_max_items_without_extra_page() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.params["page"])
        return httpx.Response(200, json=QUESTIONS_PAGE_1)

    questions = _client(handler).list_questions("stackoverflow", max_items=2)
    assert calls == ["1"]
    assert len(questions) == 2


def test_pagination_stops_when_has_more_is_false() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.params["page"])
        return httpx.Response(200, json={"items": [QUESTION_SO_A], "has_more": False})

    questions = _client(handler).list_questions("stackoverflow", max_items=50)
    assert calls == ["1"]
    assert [row.question_id for row in questions] == [SO_QUESTION_ID]


def test_pagesize_never_exceeds_api_limit() -> None:
    sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        pagesize = int(request.url.params["pagesize"])
        page = int(request.url.params["page"])
        sizes.append(pagesize)
        assert pagesize <= 100
        items = [
            {"question_id": page * 1000 + index, "title": f"q{index}"}
            for index in range(pagesize)
        ]
        return httpx.Response(200, json={"items": items, "has_more": page < 3})

    questions = _client(handler).list_questions("stackoverflow", max_items=250)
    assert sizes == [100, 100, 50]
    assert len(questions) == 250


def test_empty_results() -> None:
    questions = _client(lambda request: httpx.Response(200, json=QUESTIONS_EMPTY)).list_questions(
        "datascience",
        max_items=10,
    )
    assert questions == []


def test_malformed_wrapper_payload() -> None:
    with pytest.raises(StackExchangeResponseError, match="items"):
        _client(lambda request: httpx.Response(200, json=QUESTIONS_MALFORMED)).list_questions(
            "stackoverflow",
            max_items=10,
        )


def test_malformed_question_is_skipped() -> None:
    payload = {
        "items": [QUESTION_SO_A, {"title": "no id"}, QUESTION_SO_B],
        "has_more": False,
    }

    questions = _client(lambda request: httpx.Response(200, json=payload)).list_questions(
        "stackoverflow",
        max_items=10,
    )
    assert [row.question_id for row in questions] == [SO_QUESTION_ID, QUESTION_SO_B["question_id"]]


def test_http_error() -> None:
    with pytest.raises(StackExchangeHttpError, match="500"):
        _client(lambda request: httpx.Response(500, text="boom")).list_questions(
            "stackoverflow",
            max_items=5,
        )


def test_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns failed", request=request)

    with pytest.raises(StackExchangeHttpError, match="HTTP request failed"):
        _client(handler).list_questions("stackoverflow", max_items=5)


def test_api_error() -> None:
    with pytest.raises(StackExchangeApiError, match="site is required"):
        _client(lambda request: httpx.Response(400, json=API_ERROR)).list_questions(
            "stackoverflow",
            max_items=5,
        )


def test_backoff_is_honored_before_next_request() -> None:
    sleeps: list[float] = []
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(200, json=QUESTIONS_WITH_BACKOFF)
        return httpx.Response(200, json={"items": [QUESTION_SO_B], "has_more": False})

    questions = _client(handler, sleeper=sleeps.append).list_questions(
        "stackoverflow",
        max_items=2,
    )
    assert sleeps == [5]
    assert calls == 2
    assert [row.question_id for row in questions] == [SO_QUESTION_ID, QUESTION_SO_B["question_id"]]


def test_backoff_does_not_sleep_when_no_further_request_is_needed() -> None:
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=QUESTIONS_WITH_BACKOFF)

    questions = _client(handler, sleeper=sleeps.append).list_questions(
        "stackoverflow",
        max_items=1,
    )
    assert sleeps == []
    assert [row.question_id for row in questions] == [SO_QUESTION_ID]


def test_duplicate_request_combo_is_not_sent_twice() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url.copy_with(query=request.url.query)))
        return httpx.Response(200, json={"items": [QUESTION_SO_A], "has_more": False})

    client = _client(handler)
    first = client.list_questions("stackoverflow", max_items=1, tags=("python",))
    second = client.list_questions("stackoverflow", max_items=1, tags=("python",))
    assert len(calls) == 1
    assert [row.question_id for row in first] == [SO_QUESTION_ID]
    assert second == []


def test_optional_api_key_is_sent_but_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["key"] == TEST_KEY
        return httpx.Response(200, json=QUESTIONS_EMPTY)

    with caplog.at_level(logging.INFO, logger="trendora.connectors.stackexchange.client"):
        _client(handler, api_key=TEST_KEY).list_questions("stackoverflow", max_items=5)
    combined = "\n".join(record.getMessage() for record in caplog.records)
    assert TEST_KEY not in combined
    assert "key=" not in combined


def test_max_items_less_than_one_returns_empty() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json=QUESTIONS_PAGE_1)

    assert _client(handler).list_questions("stackoverflow", max_items=0) == []
    assert calls == []
