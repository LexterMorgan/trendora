"""Facebook public Page client tests. All HTTP mocked; no live Meta calls."""

from __future__ import annotations

import logging
from datetime import date

import httpx
import pytest

from trendora.connectors.facebook.client import FacebookPublicClient, POST_FIELDS
from trendora.connectors.facebook.exceptions import (
    FacebookApiError,
    FacebookConfigurationError,
    FacebookHttpError,
    FacebookResponseError,
)

TEST_TOKEN = "test-facebook-token-not-real"


def _post(
    post_id: str,
    *,
    message: str | None = "hello",
    created: str | None = "2026-08-10T08:00:00+0000",
    permalink: str | None = None,
    shares: int | None = 3,
    reactions: int | None = 12,
    comments: int | None = 4,
    page_id: str = "page1",
    page_name: str = "Example Page",
) -> dict:
    item: dict = {
        "id": post_id,
        "from": {"id": page_id, "name": page_name},
    }
    if message is not None:
        item["message"] = message
    if created is not None:
        item["created_time"] = created
    if permalink is not None:
        item["permalink_url"] = permalink
    else:
        item["permalink_url"] = f"https://www.facebook.com/p/p{post_id}"
    if shares is not None:
        item["shares"] = {"count": shares}
    if reactions is not None:
        item["reactions"] = {"summary": {"total_count": reactions}}
    if comments is not None:
        item["comments"] = {"summary": {"total_count": comments}}
    return item


def _payload(posts: list, *, after: str | None = None) -> dict:
    payload = {"data": posts}
    if after:
        payload["paging"] = {"cursors": {"before": "B", "after": after}}
    return payload


def _client(handler) -> FacebookPublicClient:
    transport = httpx.MockTransport(handler)
    return FacebookPublicClient(TEST_TOKEN, "v19.0", http_client=httpx.Client(transport=transport))


def _handler_ok(payload: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return handler


class TestConfiguration:
    def test_token_required_nonblank(self) -> None:
        with pytest.raises(FacebookConfigurationError):
            FacebookPublicClient("  ", "v19.0")

    def test_version_validated(self) -> None:
        for bad in ("", "v19", "v19.0.1", "19.0", "v.1", "v19.x"):
            with pytest.raises(FacebookConfigurationError):
                FacebookPublicClient(TEST_TOKEN, bad)

    def test_version_accepts_dotted(self) -> None:
        client = FacebookPublicClient(TEST_TOKEN, "v21.0")
        assert client._graph_version == "v21.0"

    def test_safe_page_ids_accepted(self) -> None:
        for page in ("123456", "page_name-1", "p.1_x", "PageID123"):
            client = _client(_handler_ok(_payload([])))
            client.list_page_posts(page, date_from=date(2026, 8, 1), date_to=date(2026, 8, 31), limit=10)


class TestValidationBeforeHttp:
    def test_blank_and_unsafe_page_ids_rejected_without_http(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("no request expected")

        client = _client(handler)
        for bad in ("", "  ", "a/b", "a?b", "a#b", "a\\b", "a b", "a%2Fb", "../etc"):
            with pytest.raises(FacebookConfigurationError):
                client.list_page_posts(bad, date_from=date(2026, 8, 1), date_to=date(2026, 8, 31), limit=10)

    def test_dot_traversal_page_ids_rejected_without_http(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("no request expected")

        client = _client(handler)
        for bad in (".", "..", "abc..def", "../etc", "foo/../bar", ".hidden", "trailing."):
            with pytest.raises(FacebookConfigurationError):
                client.list_page_posts(bad, date_from=date(2026, 8, 1), date_to=date(2026, 8, 31), limit=10)

    def test_normal_dotted_page_ids_accepted(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_payload([]))

        client = _client(handler)
        for page in ("page.name", "page_name", "page-name", "123456"):
            client.list_page_posts(page, date_from=date(2026, 8, 1), date_to=date(2026, 8, 31), limit=10)

    def test_reversed_dates_rejected(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("no request expected")

        client = _client(handler)
        with pytest.raises(FacebookConfigurationError):
            client.list_page_posts("page1", date_from=date(2026, 8, 31), date_to=date(2026, 8, 1), limit=10)

    @pytest.mark.parametrize("limit", [0, -1, 101])
    def test_invalid_limit_rejected(self, limit: int) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("no request expected")

        client = _client(handler)
        with pytest.raises(FacebookConfigurationError):
            client.list_page_posts("page1", date_from=date(2026, 8, 1), date_to=date(2026, 8, 31), limit=limit)

    def test_date_max_overflow_mapped_cleanly(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("no request expected")

        client = _client(handler)
        with pytest.raises(FacebookConfigurationError, match="cannot be represented"):
            client.list_page_posts(
                "page1", date_from=date.max, date_to=date.max, limit=10
            )


class TestRequestShape:
    def test_path_fields_bounds_headers_and_no_token_in_url(self) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["headers"] = dict(request.headers)
            assert request.url.path == "/v19.0/page1/posts"
            params = request.url.params
            assert params["fields"] == POST_FIELDS
            assert params["since"] == "2026-08-01T00:00:00Z"
            assert params["until"] == "2026-09-01T00:00:00Z"  # exclusive next day, UTC
            assert params["limit"] == "10"
            assert "access_token" not in params
            assert "token" not in str(request.url).lower()
            return httpx.Response(200, json=_payload([_post("p1")]))

        client = _client(handler)
        client.list_page_posts("page1", date_from=date(2026, 8, 1), date_to=date(2026, 8, 31), limit=10)
        assert captured["headers"]["authorization"] == f"Bearer {TEST_TOKEN}"
        assert TEST_TOKEN not in captured["url"]


class TestSuccess:
    def test_one_page(self) -> None:
        client = _client(_handler_ok(_payload([_post("p1"), _post("p2")])))
        posts = client.list_page_posts("page1", date_from=date(2026, 8, 1), date_to=date(2026, 8, 31), limit=10)
        assert [p.id for p in posts] == ["p1", "p2"]
        assert posts[0].message == "hello"
        assert posts[0].created_time == "2026-08-10T08:00:00+0000"

    def test_cursor_pagination(self) -> None:
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.params.get("after"))
            if request.url.params.get("after") == "CURSOR2":
                return httpx.Response(200, json=_payload([_post("p3")]))
            return httpx.Response(200, json=_payload([_post("p1"), _post("p2")], after="CURSOR2"))

        client = _client(handler)
        posts = client.list_page_posts("page1", date_from=date(2026, 8, 1), date_to=date(2026, 8, 31), limit=10)
        assert [p.id for p in posts] == ["p1", "p2", "p3"]
        assert calls == [None, "CURSOR2"]

    def test_repeated_cursor_raises(self) -> None:
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.params.get("after"))
            return httpx.Response(200, json=_payload([_post("p1")], after="CURSORX"))

        client = _client(handler)
        with pytest.raises(FacebookResponseError, match="already-used"):
            client.list_page_posts("page1", date_from=date(2026, 8, 1), date_to=date(2026, 8, 31), limit=100)
        assert len(calls) == 2  # second page repeats cursor, terminates with error

    def test_duplicate_only_page_repeats_cursor_and_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_payload([_post("p1"), _post("p1")], after="CUR"))

        client = _client(handler)
        with pytest.raises(FacebookResponseError, match="already-used"):
            client.list_page_posts("page1", date_from=date(2026, 8, 1), date_to=date(2026, 8, 31), limit=100)

    def test_empty_page_repeats_cursor_and_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_payload([], after="CUR"))

        client = _client(handler)
        with pytest.raises(FacebookResponseError, match="already-used"):
            client.list_page_posts("page1", date_from=date(2026, 8, 1), date_to=date(2026, 8, 31), limit=100)

    def test_does_not_follow_paging_next_url(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            payload = _payload([_post("p1")], after="CURSOR2")
            payload["paging"]["next"] = "https://graph.facebook.com/evil/posts?after=EVIL"
            if request.url.params.get("after") == "CURSOR2":
                return httpx.Response(200, json=_payload([_post("p2")]))
            return httpx.Response(200, json=payload)

        client = _client(handler)
        posts = client.list_page_posts("page1", date_from=date(2026, 8, 1), date_to=date(2026, 8, 31), limit=10)
        assert len(posts) == 2

    def test_limit_enforced_across_pages(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.params.get("after") == "C2":
                return httpx.Response(200, json=_payload([_post("p3")]))
            return httpx.Response(200, json=_payload([_post("p1"), _post("p2")], after="C2"))

        client = _client(handler)
        posts = client.list_page_posts("page1", date_from=date(2026, 8, 1), date_to=date(2026, 8, 31), limit=2)
        assert [p.id for p in posts] == ["p1", "p2"]

    def test_limit_fulfilled_stops_before_rechecking_cursor(self) -> None:
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.params.get("after"))
            if request.url.params.get("after") == "CUR":
                return httpx.Response(200, json=_payload([_post("p2")], after="CUR"))
            return httpx.Response(200, json=_payload([_post("p1")], after="CUR"))

        client = _client(handler)
        posts = client.list_page_posts(
            "page1", date_from=date(2026, 8, 1), date_to=date(2026, 8, 31), limit=2
        )
        assert [p.id for p in posts] == ["p1", "p2"]
        assert len(calls) == 2  # repeated cursor after limit fulfilled is not an error

    def test_stable_deduplication_first_wins(self) -> None:
        client = _client(_handler_ok(_payload([_post("p1", message="first"), _post("p1", message="dupe"), _post("p2")])))
        posts = client.list_page_posts("page1", date_from=date(2026, 8, 1), date_to=date(2026, 8, 31), limit=10)
        assert [p.id for p in posts] == ["p1", "p2"]
        assert posts[0].message == "first"

    def test_missing_optional_metrics_stay_none(self) -> None:
        client = _client(_handler_ok(_payload([_post("p1", shares=None, reactions=None, comments=None)])))
        posts = client.list_page_posts("page1", date_from=date(2026, 8, 1), date_to=date(2026, 8, 31), limit=10)
        assert posts[0].shares is None
        assert posts[0].reactions is None
        assert posts[0].comments is None

    def test_zero_metrics_stay_zero(self) -> None:
        client = _client(_handler_ok(_payload([_post("p1", shares=0, reactions=0, comments=0)])))
        posts = client.list_page_posts("page1", date_from=date(2026, 8, 1), date_to=date(2026, 8, 31), limit=10)
        assert posts[0].shares.count == 0
        assert posts[0].reactions.summary.total_count == 0
        assert posts[0].comments.summary.total_count == 0

    def test_reactions_are_not_labeled_likes(self) -> None:
        client = _client(_handler_ok(_payload([_post("p1")])))
        posts = client.list_page_posts("page1", date_from=date(2026, 8, 1), date_to=date(2026, 8, 31), limit=10)
        assert posts[0].reactions.summary.total_count == 12
        assert not hasattr(posts[0], "like_count")
        assert not hasattr(posts[0].reactions, "like_summary")


class TestErrors:
    def test_transport_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom")

        client = _client(handler)
        with pytest.raises(FacebookHttpError):
            client.list_page_posts("page1", date_from=date(2026, 8, 1), date_to=date(2026, 8, 31), limit=10)

    def test_transport_error_with_token_in_exception_not_leaked(self, caplog) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError(f"connection refused for token {TEST_TOKEN}")

        client = _client(handler)
        with caplog.at_level(logging.ERROR):
            with pytest.raises(FacebookHttpError) as excinfo:
                client.list_page_posts("page1", date_from=date(2026, 8, 1), date_to=date(2026, 8, 31), limit=10)
        assert TEST_TOKEN not in str(excinfo.value)
        assert TEST_TOKEN not in repr(excinfo.value)
        assert TEST_TOKEN not in caplog.text
        assert "ConnectError" in caplog.text

    @pytest.mark.parametrize("status", [400, 403, 404, 429, 500, 503])
    def test_non_success_mapped(self, status: int) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status, json={"error": {"message": "upstream", "code": status}})

        client = _client(handler)
        with pytest.raises(FacebookApiError) as excinfo:
            client.list_page_posts("page1", date_from=date(2026, 8, 1), date_to=date(2026, 8, 31), limit=10)
        assert excinfo.value.status_code == status
        assert TEST_TOKEN not in str(excinfo.value)

    def test_error_message_with_token_not_leaked(self, caplog) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                403,
                json={"error": {"message": f"invalid token {TEST_TOKEN} please reauth", "code": 190, "error_subcode": 456}},
            )

        client = _client(handler)
        with caplog.at_level(logging.ERROR):
            with pytest.raises(FacebookApiError) as excinfo:
                client.list_page_posts("page1", date_from=date(2026, 8, 1), date_to=date(2026, 8, 31), limit=10)
        assert TEST_TOKEN not in str(excinfo.value)
        assert TEST_TOKEN not in repr(excinfo.value)
        assert TEST_TOKEN not in caplog.text
        assert excinfo.value.status_code == 403
        assert excinfo.value.reason == "456"

    def test_error_envelope_mapped(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"error": {"message": "something went wrong", "code": 4, "error_subcode": 1234}},
            )

        client = _client(handler)
        with pytest.raises(FacebookApiError) as excinfo:
            client.list_page_posts("page1", date_from=date(2026, 8, 1), date_to=date(2026, 8, 31), limit=10)
        assert "something went wrong" not in str(excinfo.value)
        assert excinfo.value.reason == "1234"

    def test_data_not_list_rejected_fail_closed(self) -> None:
        client = _client(_handler_ok({"data": "nope"}))
        with pytest.raises(FacebookResponseError):
            client.list_page_posts("page1", date_from=date(2026, 8, 1), date_to=date(2026, 8, 31), limit=10)

    def test_non_object_json_rejected(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=["not", "object"])

        client = _client(handler)
        with pytest.raises(FacebookResponseError):
            client.list_page_posts("page1", date_from=date(2026, 8, 1), date_to=date(2026, 8, 31), limit=10)

    def test_malformed_item_rejected_fail_closed(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_payload([{"id": "p1"}, {"no-id": True}]))

        client = _client(handler)
        with pytest.raises(FacebookResponseError):
            client.list_page_posts("page1", date_from=date(2026, 8, 1), date_to=date(2026, 8, 31), limit=10)

    def test_unknown_extra_field_rejected(self) -> None:
        bad = _post("p1")
        bad["like_count"] = 99
        client = _client(_handler_ok(_payload([bad])))
        with pytest.raises(FacebookResponseError):
            client.list_page_posts("page1", date_from=date(2026, 8, 1), date_to=date(2026, 8, 31), limit=10)

    def test_negative_count_rejected(self) -> None:
        bad = _post("p1", shares=-1)
        client = _client(_handler_ok(_payload([bad])))
        with pytest.raises(FacebookResponseError):
            client.list_page_posts("page1", date_from=date(2026, 8, 1), date_to=date(2026, 8, 31), limit=10)

    def test_malformed_top_level_paging_rejected(self) -> None:
        payload = _payload([_post("p1")], after="X")
        payload["paging"] = {"cursors": "not-an-object"}
        client = _client(_handler_ok(payload))
        with pytest.raises(FacebookResponseError):
            client.list_page_posts("page1", date_from=date(2026, 8, 1), date_to=date(2026, 8, 31), limit=10)


class TestClientLifetime:
    def test_external_client_never_closed(self) -> None:
        closed = []

        class SpyClient(httpx.Client):
            def close(self):
                closed.append(1)
                super().close()

        spy = SpyClient(transport=httpx.MockTransport(_handler_ok(_payload([_post("p1")]))))
        client = FacebookPublicClient(TEST_TOKEN, "v19.0", http_client=spy)
        client.list_page_posts("page1", date_from=date(2026, 8, 1), date_to=date(2026, 8, 31), limit=10)
        client.close()
        assert closed == []

    def test_owned_client_closes_once(self) -> None:
        client = FacebookPublicClient(TEST_TOKEN, "v19.0")
        real = client._http
        calls = []
        original_close = real.close

        def counting_close():
            calls.append(1)
            original_close()

        real.close = counting_close
        client.close()
        assert calls == [1]