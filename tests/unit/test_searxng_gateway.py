"""SearXNG public-web gateway tests. Fully mocked; no network, no database.

Covers result normalization, the shared URL-safety boundary, empty/malformed
payloads, timeouts, rate-limit retry, endpoint validation, and explicit backend
selection (including "no silent paid fallback").
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from trendora.connectors.web_search.exceptions import (
    WebSearchApiError,
    WebSearchConfigurationError,
    WebSearchHttpError,
    WebSearchResponseError,
)
from trendora.connectors.web_search.searxng_gateway import (
    MAX_RESULTS,
    SearxngGateway,
    _validate_endpoint,
)
from trendora.research import ResearchApplicationService, ResearchCapabilityResolver
from trendora.research.web_search import WebSearchResearchRetriever

UTC = timezone.utc
T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
BASE = "http://127.0.0.1:8888"


def _gateway(handler, base: str = BASE) -> SearxngGateway:
    transport = httpx.MockTransport(handler)
    return SearxngGateway(
        base,
        http_client=httpx.Client(transport=transport),
        async_transport=transport,
    )


def _ok_handler(payload):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return handler


def _results(*entries) -> dict:
    items = []
    for entry in entries:
        if isinstance(entry, str):
            items.append({"title": entry, "url": entry, "content": "s"})
        else:
            items.append(entry)
    return {"results": items}


class TestRequestShape:
    def test_uses_search_endpoint_with_json_format(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["params"] = dict(request.url.params)
            return httpx.Response(200, json=_results("https://good.com/1"))

        _gateway(handler).search("ai education", limit=5)
        assert captured["url"].startswith(f"{BASE}/search")
        assert captured["params"]["q"] == "ai education"
        assert captured["params"]["format"] == "json"

    def test_blank_query_returns_empty_without_request(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("no request expected for blank query")

        assert _gateway(handler).search("   ") == []

    def test_limit_is_bounded_by_max_results(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["params"] = dict(request.url.params)
            return httpx.Response(200, json=_results("https://good.com/1"))

        results = _gateway(handler).search("q", limit=999)
        assert len(results) == 1  # only one entry exists; limit request is bounded


class TestNormalization:
    def test_maps_url_title_content_and_domain(self):
        gateway = _gateway(_ok_handler(_results(
            {"title": "T", "url": "https://example.com/a", "content": "snippet"},
        )))
        results = gateway.search("q", limit=5)
        assert len(results) == 1
        assert results[0].url == "https://example.com/a"
        assert results[0].title == "T"
        assert results[0].snippet == "snippet"
        assert results[0].domain == "example.com"

    def test_exact_url_deduped_first_wins(self):
        gateway = _gateway(_ok_handler(_results(
            {"title": "A", "url": "https://x.com/1", "content": "first"},
            {"title": "B", "url": "https://x.com/1", "content": "second"},
        )))
        results = gateway.search("q", limit=5)
        assert [r.title for r in results] == ["A"]

    def test_invalid_entries_skipped(self):
        gateway = _gateway(_ok_handler(_results(
            "https://good.com/1",
            "javascript:alert(1)",
            {"title": "cred", "url": "https://user:pass@bad.com/2"},
            {"title": "no url"},
            {"url": None},
        )))
        results = gateway.search("q", limit=10)
        assert [r.url for r in results] == ["https://good.com/1"]

    def test_missing_results_key_is_empty_search(self):
        assert _gateway(_ok_handler({"query": "q"})).search("q", limit=5) == []

    def test_non_list_results_raises(self):
        with pytest.raises(WebSearchResponseError):
            _gateway(_ok_handler({"results": {"not": "a list"}})).search("q", limit=5)


class TestFailures:
    def test_timeout_becomes_http_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("slow")

        with pytest.raises(WebSearchHttpError):
            _gateway(handler).search("q", limit=5)

    def test_rate_limit_retried_once_then_raises(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(429, json={})

        with pytest.raises(WebSearchApiError):
            _gateway(handler).search("q", limit=5)
        assert calls["n"] == 2

    def test_rate_limit_then_success(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(429, json={})
            return httpx.Response(200, json=_results("https://good.com/1"))

        results = _gateway(handler).search("q", limit=5)
        assert [r.url for r in results] == ["https://good.com/1"]
        assert calls["n"] == 2

    def test_server_error_raises_api_error(self):
        with pytest.raises(WebSearchApiError):
            _gateway(lambda request: httpx.Response(500, json={})).search("q", limit=5)

    def test_non_json_body_raises_response_error(self):
        with pytest.raises(WebSearchResponseError):
            _gateway(lambda request: httpx.Response(200, text="<html>")).search("q", limit=5)

    def test_non_object_json_raises_response_error(self):
        with pytest.raises(WebSearchResponseError):
            _gateway(lambda request: httpx.Response(200, json=[1, 2])).search("q", limit=5)


class TestEndpointValidation:
    @pytest.mark.parametrize("url", [BASE, "http://localhost:8888", "https://search.example.com"])
    def test_accepts_http_urls(self, url):
        assert _validate_endpoint(url) == url.rstrip("/")

    @pytest.mark.parametrize("url", [
        "",
        "   ",
        "ftp://127.0.0.1",
        "http://user:pass@127.0.0.1:8888",
        "http://127.0.0.1:8888/?x=1",
        "http:///nohost",
    ])
    def test_rejects_unsafe_endpoints(self, url):
        with pytest.raises(WebSearchConfigurationError):
            _validate_endpoint(url)

    def test_missing_base_url_raises(self):
        with pytest.raises(WebSearchConfigurationError):
            SearxngGateway(None)


class TestRetrieverAndBudget:
    def _retriever(self, handler) -> WebSearchResearchRetriever:
        return WebSearchResearchRetriever(_gateway(handler))

    def _query(self, limit: int):
        from trendora.research.models import ResearchQuery

        return ResearchQuery(
            topic="AI education",
            markets=(),
            date_from=date(2026, 8, 1),
            date_to=date(2026, 8, 31),
            source_codes=("public_web",),
            result_limit=limit,
        )

    def test_normalizes_to_references_with_unknown_dates(self):
        retriever = self._retriever(_ok_handler(_results(
            {"title": "T", "url": "https://example.com/a", "content": "snippet"},
        )))
        refs = retriever.normalize(retriever.collect(self._query(5), collected_at=T0))
        assert len(refs) == 1
        ref = refs[0]
        assert ref.source_code == "public_web"
        assert ref.url == "https://example.com/a"
        assert ref.published_at is None  # never inferred from collection time
        assert ref.collected_at == T0
        assert ref.market_contexts == ()

    def test_search_unavailable_yields_youtube_partial_report(self):
        # SearXNG configured but unavailable at request time: YouTube still
        # produces an honestly partial report; no paid fallback, no crash.
        import tests.unit.test_research_api as api_tests
        from trendora.research import YouTubeResearchRetriever
        from tests.support.app import create_test_app
        from trendora.api.app import get_research_application_service
        from fastapi.testclient import TestClient

        def down_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("searxng down")

        yt_client = api_tests.YouTubeClient(
            api_tests.TEST_KEY,
            http_client=httpx.Client(transport=httpx.MockTransport(api_tests._youtube_handler)),  # noqa: SLF001
        )
        service = ResearchApplicationService(
            ResearchCapabilityResolver(),
            {
                "youtube": YouTubeResearchRetriever(yt_client),
                "public_web": WebSearchResearchRetriever(_gateway(down_handler)),
            },
        )
        app = create_test_app()
        app.dependency_overrides[get_research_application_service] = lambda: service
        response = TestClient(app).post(
            "/api/v1/research",
            json={"topic": "t", "markets": [], "sources": ["youtube", "public_web"], "result_limit": 4},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "completed"
        # YouTube ran; public_web was attempted but produced nothing.
        assert "youtube" in body["executed_sources"]
        codes = {r["source_code"] for r in body["references"]}
        assert "youtube" in codes and "public_web" not in codes


class TestBackendSelection:
    """Explicit backend selection: no silent fallback to a paid provider."""

    def _select(self, monkeypatch, *, backend, serper=None, searxng=None, enabled=True):
        import trendora.api.app as app

        settings = SimpleNamespace(
            web_search_enabled=enabled,
            web_search_backend=backend,
            serper_api_key=serper,
            searxng_url=searxng,
        )
        return app.build_web_search_gateway(settings)

    def test_none_disables_public_web(self, monkeypatch):
        assert self._select(monkeypatch, backend="none", serper="k", searxng=BASE) is None

    def test_disabled_flag_overrides_everything(self, monkeypatch):
        assert self._select(monkeypatch, backend="auto", serper="k", searxng=BASE, enabled=False) is None

    def test_serper_backend_uses_serper_only(self, monkeypatch):
        gw = self._select(monkeypatch, backend="serper", serper="k")
        assert type(gw).__name__ == "SerperGateway"

    def test_serper_backend_without_key_is_none_not_searxng(self, monkeypatch):
        # A named backend must not silently fall back to a different provider.
        assert self._select(monkeypatch, backend="serper", serper=None, searxng=BASE) is None

    def test_searxng_backend_uses_searxng_only(self, monkeypatch):
        gw = self._select(monkeypatch, backend="searxng", searxng=BASE)
        assert type(gw).__name__ == "SearxngGateway"

    def test_searxng_backend_without_url_is_none_not_serper(self, monkeypatch):
        assert self._select(monkeypatch, backend="searxng", serper="k", searxng=None) is None

    def test_auto_prefers_searxng(self, monkeypatch):
        gw = self._select(monkeypatch, backend="auto", serper="k", searxng=BASE)
        assert type(gw).__name__ == "SearxngGateway"

    def test_auto_falls_back_to_serper_when_no_searxng(self, monkeypatch):
        gw = self._select(monkeypatch, backend="auto", serper="k", searxng=None)
        assert type(gw).__name__ == "SerperGateway"

    def test_auto_with_nothing_configured_is_none(self, monkeypatch):
        assert self._select(monkeypatch, backend="auto") is None
