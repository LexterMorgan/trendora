"""M36A.1 public web search correctness & security tests. Fully mocked."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from trendora.api import create_app
from trendora.api.app import (
    get_research_application_service,
    get_research_report_service,
)
from trendora.connectors.web_search import SearchResult
from trendora.connectors.web_search.exceptions import (
    WebSearchApiError,
    WebSearchConfigurationError,
    WebSearchHttpError,
    WebSearchResponseError,
)
from trendora.connectors.web_search.serper_gateway import (
    MAX_RESULTS,
    SerperGateway,
    _extract_domain,
    _is_safe_url,
)
from trendora.research import (
    ResearchApplicationService,
    ResearchCapabilityResolver,
    ResearchQuery,
)
from trendora.research.models import CoverageStatus, PlatformCapability
from trendora.research.web_search import (
    WEB_SEARCH_SOURCE_CODE,
    WebSearchResearchRetriever,
)

UTC = timezone.utc
T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
FAKE_KEY = "test-api-key-abc123"
PATH = "/api/v1/research"


def _gateway(handler, key: str = FAKE_KEY) -> SerperGateway:
    return SerperGateway(
        key, http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def _ok_handler(payload):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return handler


def _organic(*links, **extra) -> dict:
    items = []
    for entry in links:
        if isinstance(entry, str):
            items.append({"title": entry, "link": entry, "snippet": "s"})
        else:
            items.append(entry)
    payload = {"organic": items}
    payload.update(extra)
    return payload


class TestSafeUrlBoundary:
    @pytest.mark.parametrize(
        "url",
        [
            "http://example.com/a",
            "https://example.com/a",
            "https://h/x",
            "HTTP://example.com/a",
            "HTTPS://Example.COM/A",
            "https://example.com:8443/x",
        ],
    )
    def test_accepts_absolute_http_urls(self, url):
        assert _is_safe_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "",
            "   ",
            None,
            123,
            ["https://example.com"],
            {"url": "https://example.com"},
            "javascript:alert(1)",
            "data:text/html,x",
            "file:///etc/passwd",
            "mailto:a@example.com",
            "ftp://example.com/x",
            "https:///nohost",
            "https://user:pass@example.com/x",
            "https://user@example.com/x",
            "https://example.com/x ",
            " https://example.com/x",
            "https://example.com/has space",
            "https://example.com/\ttab",
            "https://example.com/\nnewline",
            "https://example.com/\x00null",
            "https://example.com:port/x",
            "https://example.com:99999/x",
            "//example.com/x",
            "example.com/x",
            "/relative",
        ],
    )
    def test_rejects_unsafe_urls(self, url):
        assert _is_safe_url(url) is False

    def test_invalid_urls_never_become_results(self):
        gateway = _gateway(
            _ok_handler(
                _organic(
                    "https://good.com/1",
                    "javascript:alert(1)",
                    {"title": "x", "link": "https://user:pass@bad.com/2"},
                    {"title": "no link"},
                    {"link": None},
                )
            )
        )
        results = gateway.search("q", limit=10)
        assert [r.url for r in results] == ["https://good.com/1"]

    def test_skipped_count_logged_without_url(self, caplog):
        with caplog.at_level(logging.WARNING):
            gateway = _gateway(
                _ok_handler(_organic("javascript:alert(1)", "file:///x", "https://ok.com/1"))
            )
            gateway.search("q", limit=10)
        messages = [r.getMessage() for r in caplog.records]
        joined = " ".join(messages)
        assert "invalid_results_skipped count=2" in joined
        assert "javascript" not in joined
        assert "file:///" not in joined

    def test_searcherror_drops_invalid_not_converts(self):
        retriever = _retriever(
            _ok_handler(_organic("mailto:a@b.com", "https://ok.com/1"))
        )
        refs = retriever.normalize(retriever.collect(_query(), collected_at=T0))
        assert [r.url for r in refs] == ["https://ok.com/1"]


class TestDomainExtraction:
    def test_hostname_only(self):
        assert _extract_domain("https://example.com:8443/a?b=1#c") == "example.com"
        assert _extract_domain("https://user:pass@example.com/x") == "example.com"
        # urlsplit().hostname is lowercased (hostname normalization).
        assert _extract_domain("https://Sub.Example.COM/x") == "sub.example.com"

    def test_empty_when_unavailable(self):
        assert _extract_domain("not a url") == ""
        assert _extract_domain("") == ""


class TestDeduplication:
    def test_exact_url_first_wins(self):
        gateway = _gateway(
            _ok_handler(
                _organic(
                    {"title": "First", "link": "https://a.com/x", "snippet": "first"},
                    {"title": "Second", "link": "https://a.com/x", "snippet": "second"},
                )
            )
        )
        results = gateway.search("q", limit=10)
        assert len(results) == 1
        assert results[0].title == "First"
        assert results[0].snippet == "first"

    def test_distinct_urls_not_merged(self):
        gateway = _gateway(
            _ok_handler(
                _organic("https://a.com/x", "https://a.com/x?y=1", "https://a.com/x#frag")
            )
        )
        assert len(gateway.search("q", limit=10)) == 3

    def test_duplicates_do_not_consume_positions(self):
        gateway = _gateway(
            _ok_handler(
                _organic("https://a.com/1", "https://a.com/1", "https://b.com/2")
            )
        )
        assert [r.url for r in gateway.search("q", limit=10)] == [
            "https://a.com/1",
            "https://b.com/2",
        ]


class TestEnvelopePolicy:
    def test_missing_organic_returns_empty(self):
        gateway = _gateway(_ok_handler({}))
        assert gateway.search("q", limit=5) == []

    def test_empty_organic_returns_empty(self):
        gateway = _gateway(_ok_handler({"organic": []}))
        assert gateway.search("q", limit=5) == []

    def test_non_list_organic_raises(self):
        gateway = _gateway(_ok_handler({"organic": {"link": "https://a.com"}}))
        with pytest.raises(WebSearchResponseError):
            gateway.search("q", limit=5)

    def test_non_object_json_raises(self):
        gateway = _gateway(_ok_handler(["not", "an", "object"]))
        with pytest.raises(WebSearchResponseError):
            gateway.search("q", limit=5)

    def test_json_null_is_non_object_not_parse_failure(self):
        # NOTE: httpx.Response(200, json=None) sends an EMPTY body (json=None is
        # httpx's "no JSON content" sentinel), which is a parse failure, not a
        # null JSON body. To exercise a real `null` body we send content=b"null",
        # which response.json() decodes to None and must reach the
        # non-object-JSON branch.
        gateway = _gateway(lambda request: httpx.Response(200, content=b"null"))
        with pytest.raises(WebSearchResponseError) as exc:
            gateway.search("q", limit=5)
        message = str(exc.value)
        assert "non-object JSON" in message
        assert "non-JSON body" not in message

    def test_non_json_body_raises(self):
        gateway = _gateway(lambda request: httpx.Response(200, text="<html>nope</html>"))
        with pytest.raises(WebSearchResponseError):
            gateway.search("q", limit=5)

    def test_non_dict_organic_entries_skipped(self):
        gateway = _gateway(_ok_handler({"organic": ["str", 42, {"title": "ok", "link": "https://a.com/1"}]}))
        assert [r.url for r in gateway.search("q", limit=5)] == ["https://a.com/1"]


class TestHttpBehavior:
    def test_limit_capped_at_max_results(self):
        gateway = _gateway(_ok_handler(_organic(*[f"https://i.com/{i}" for i in range(30)])))
        assert len(gateway.search("q", limit=100)) == MAX_RESULTS

    def test_retries_once_on_429(self):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(429, json={"message": "rate limited"})
            return httpx.Response(200, json=_organic("https://a.com/1"))

        results = _gateway(handler).search("q", limit=5)
        assert calls["n"] == 2
        assert len(results) == 1

    def test_persistent_429_no_further_retry(self):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            return httpx.Response(429, json={})

        with pytest.raises(WebSearchApiError):
            _gateway(handler).search("q", limit=5)
        assert calls["n"] == 2

    @pytest.mark.parametrize("status", [400, 401, 403, 404, 500, 503])
    def test_no_retry_for_normal_errors(self, status):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            return httpx.Response(status, json={})

        with pytest.raises(WebSearchApiError):
            _gateway(handler).search("q", limit=5)
        assert calls["n"] == 1

    def test_transport_error_raises_http_error(self):
        def handler(request):
            raise httpx.ConnectError("boom")

        with pytest.raises(WebSearchHttpError):
            _gateway(handler).search("q", limit=5)

    def test_blank_query_returns_empty(self):
        assert _gateway(_ok_handler({"organic": []})).search("   ", limit=5) == []


class TestAuthAndLeakage:
    def test_key_only_in_outbound_header(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["key"] = request.headers.get("X-API-KEY")
            captured["url"] = str(request.url)
            return httpx.Response(200, json=_organic("https://a.com/1"))

        _gateway(handler).search("q", limit=5)
        assert captured["key"] == FAKE_KEY
        assert FAKE_KEY not in captured["url"]

    def test_config_error_does_not_include_key(self):
        with pytest.raises(WebSearchConfigurationError) as exc:
            SerperGateway(api_key="   ")
        assert "   " not in str(exc.value)

    def test_api_error_has_no_key_or_body(self):
        body = {"message": f"bad {FAKE_KEY}", "raw": "SECRET"}
        gateway = _gateway(lambda request: httpx.Response(500, json=body))
        with pytest.raises(WebSearchApiError) as exc:
            gateway.search("q", limit=5)
        text = f"{exc.value!r} {exc.value.args}"
        assert FAKE_KEY not in text
        assert "SECRET" not in text
        assert exc.value.__cause__ is None
        assert exc.value.__context__ is None

    def test_transport_error_chain_is_clean(self):
        def handler(request):
            raise httpx.ConnectError(f"failed with {FAKE_KEY}")

        with pytest.raises(WebSearchHttpError) as exc:
            _gateway(handler).search("q", limit=5)
        assert exc.value.__cause__ is None
        assert exc.value.__context__ is None
        assert FAKE_KEY not in repr(exc.value)
        assert FAKE_KEY not in str(exc.value)
        assert FAKE_KEY not in str(exc.value.args)

    def test_transport_error_traceback_is_clean(self):
        import traceback

        def handler(request):
            raise httpx.ConnectError(f"failed with {FAKE_KEY}")

        with pytest.raises(WebSearchHttpError):
            try:
                _gateway(handler).search("q", limit=5)
            except WebSearchHttpError:
                formatted = traceback.format_exc()
                assert FAKE_KEY not in formatted
                assert "ConnectError" not in formatted
                raise

    def test_non_json_body_chain_and_traceback_clean(self):
        import traceback

        def handler(request):
            return httpx.Response(200, content=b"not json with " + FAKE_KEY.encode())

        with pytest.raises(WebSearchResponseError) as exc:
            try:
                _gateway(handler).search("q", limit=5)
            except WebSearchResponseError:
                formatted = traceback.format_exc()
                assert FAKE_KEY not in formatted
                raise
        assert exc.value.__cause__ is None
        assert exc.value.__context__ is None

    def test_transport_failure_logs_are_clean(self, caplog):
        def handler(request):
            raise httpx.ConnectError(f"failed with {FAKE_KEY}")

        with caplog.at_level(logging.DEBUG):
            with pytest.raises(WebSearchHttpError):
                _gateway(handler).search("q", limit=5)
        joined = " ".join(r.getMessage() for r in caplog.records)
        assert FAKE_KEY not in joined
        assert "ConnectError" not in joined
        assert "failed with" not in joined

    def test_http_error_has_no_key(self):
        def handler(request):
            raise httpx.ConnectError(f"failed with {FAKE_KEY}")

        with pytest.raises(WebSearchHttpError) as exc:
            _gateway(handler).search("q", limit=5)
        assert FAKE_KEY not in f"{exc.value!r} {exc.value.args}"

    def test_search_logs_no_key_or_raw_url(self, caplog):
        with caplog.at_level(logging.DEBUG):
            _gateway(_ok_handler(_organic("https://secret.example.com/path"))).search("q", limit=5)
        joined = " ".join(r.getMessage() for r in caplog.records)
        assert FAKE_KEY not in joined
        assert "secret.example.com" not in joined


class TestLifecycle:
    def test_owned_client_closed_once(self):
        gateway = SerperGateway(FAKE_KEY)
        gateway.close()
        gateway.close()  # idempotent-ish; must not raise

    def test_injected_client_not_closed(self):
        client = httpx.Client(transport=httpx.MockTransport(_ok_handler({"organic": []})))
        gateway = SerperGateway(FAKE_KEY, http_client=client)
        gateway.close()
        assert client.is_closed is False
        client.close()

    def test_application_service_closes_gateway_once(self, monkeypatch):
        import trendora.api.app as app_module

        closed = {"n": 0}

        class FakeGateway:
            def __init__(self, key):
                assert key == FAKE_KEY

            def search(self, query, *, limit=MAX_RESULTS):
                return []

            def close(self):
                closed["n"] += 1

        class FakeSettings:
            youtube_api_key = None
            meta_access_token = None
            meta_graph_api_version = None
            serper_api_key = FAKE_KEY
            web_search_enabled = True

        monkeypatch.setattr(app_module, "get_settings", lambda: FakeSettings())
        monkeypatch.setattr(app_module, "SerperGateway", FakeGateway)

        generator = app_module.get_research_application_service()
        service = next(generator)
        assert "public_web" in service._retrievers  # noqa: SLF001
        generator.close()
        assert closed["n"] == 1

    def test_gateway_not_built_when_disabled(self, monkeypatch):
        import trendora.api.app as app_module

        class FakeSettings:
            youtube_api_key = None
            meta_access_token = None
            meta_graph_api_version = None
            serper_api_key = FAKE_KEY
            web_search_enabled = False

        monkeypatch.setattr(app_module, "get_settings", lambda: FakeSettings())
        generator = app_module.get_research_application_service()
        service = next(generator)
        assert "public_web" not in service._retrievers  # noqa: SLF001
        generator.close()


def _retriever(handler) -> WebSearchResearchRetriever:
    return WebSearchResearchRetriever(_gateway(handler))


def _query(limit: int = 5, markets=("SG",)) -> ResearchQuery:
    return ResearchQuery(
        topic="AI education",
        markets=markets,
        date_from=date(2026, 8, 1),
        date_to=date(2026, 8, 31),
        source_codes=("public_web",),
        result_limit=limit,
    )


class TestCapabilities:
    def test_public_web_declared_without_regional(self):
        decl = ResearchCapabilityResolver().declarations["public_web"]
        assert PlatformCapability.PUBLIC_SEARCH in decl.supported
        assert PlatformCapability.CONTENT_LOOKUP in decl.supported
        assert PlatformCapability.REGIONAL_DISCOVERY not in decl.supported

    def test_public_web_resolves_available(self):
        coverage = ResearchCapabilityResolver().resolve(_query())
        assert coverage.sources[0].status is CoverageStatus.AVAILABLE
        assert coverage.sources[0].capability is PlatformCapability.PUBLIC_SEARCH

    def test_no_serp_gateway_alias(self):
        assert "serp_gateway" not in ResearchCapabilityResolver().declarations


class TestProviderNeutralSource:
    def test_source_code_is_public_web(self):
        assert WEB_SEARCH_SOURCE_CODE == "public_web"
        retriever = _retriever(_ok_handler(_organic("https://a.com/1")))
        refs = retriever.normalize(retriever.collect(_query(), collected_at=T0))
        assert refs[0].source_code == "public_web"
        assert refs[0].url == "https://a.com/1"
        assert refs[0].content_external_id == "https://a.com/1"
        assert refs[0].title == "https://a.com/1"
        assert refs[0].channel_title == "a.com"
        assert refs[0].market_contexts == ()
        assert refs[0].published_at is None
        assert refs[0].metrics.view_count is None

    def test_published_at_always_none(self):
        retriever = _retriever(
            _ok_handler({"organic": [{"title": "t", "link": "https://a.com/1", "date": "2024-09-01"}]})
        )
        refs = retriever.normalize(retriever.collect(_query(), collected_at=T0))
        assert refs[0].published_at is None

    def test_naive_datetime_rejected(self):
        retriever = _retriever(_ok_handler(_organic("https://a.com/1")))
        with pytest.raises(ValueError, match="timezone-aware"):
            retriever.collect(_query(), collected_at=datetime.now())

    def test_aware_datetime_accepted(self):
        retriever = _retriever(_ok_handler(_organic("https://a.com/1")))
        aware = datetime.now(timezone.utc)
        batch = retriever.collect(_query(), collected_at=aware)
        assert batch.collected_at.utcoffset() is not None
        assert retriever.normalize(batch)[0].collected_at == aware

    def test_tzinfo_with_none_utcoffset_rejected(self):
        import datetime as dt_module

        class LyingTz(dt_module.tzinfo):
            def utcoffset(self, value):  # noqa: ARG002
                return None

            def dst(self, value):  # noqa: ARG002
                return None

        retriever = _retriever(_ok_handler(_organic("https://a.com/1")))
        with pytest.raises(ValueError, match="timezone-aware"):
            retriever.collect(_query(), collected_at=datetime(2026, 9, 1, tzinfo=LyingTz()))


class TestApiExecution:
    def _app(self, handler, *, retriever_key="public_web"):
        gateway = _gateway(handler)
        service = ResearchApplicationService(
            ResearchCapabilityResolver(),
            {retriever_key: WebSearchResearchRetriever(gateway)},
        )
        app = create_app()
        app.dependency_overrides[get_research_application_service] = lambda: service
        return TestClient(app), service

    def test_public_web_only_execution(self):
        client, _ = self._app(_ok_handler(_organic("https://a.com/1", "https://b.com/2")))
        body = client.post(
            PATH,
            json={
                "topic": "t",
                "markets": ["SG"],
                "sources": ["public_web"],
                "result_limit": 5,
            },
        ).json()
        assert body["status"] == "completed"
        assert body["executed_sources"] == ["public_web"]
        assert [r["url"] for r in body["references"]] == [
            "https://a.com/1",
            "https://b.com/2",
        ]

    def test_zero_evidence_completes_empty(self):
        client, _ = self._app(_ok_handler({"organic": []}))
        body = client.post(
            PATH,
            json={"topic": "t", "markets": ["SG"], "sources": ["public_web"], "result_limit": 5},
        ).json()
        assert body["status"] == "completed"
        assert body["references"] == []

    def test_multi_market_web_single_call(self):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            return httpx.Response(200, json=_organic("https://a.com/1"))

        client, _ = self._app(handler)
        body = client.post(
            PATH,
            json={
                "topic": "t",
                "markets": ["SG", "ID", "TH"],
                "sources": ["public_web"],
                "result_limit": 6,
            },
        ).json()
        assert body["status"] == "completed"
        assert calls["n"] == 1

    def test_upstream_error_maps_502_sanitized(self):
        def handler(request):
            return httpx.Response(500, json={"message": f"boom {FAKE_KEY}", "x": "SECRET"})

        client, _ = self._app(handler)
        response = client.post(
            PATH,
            json={"topic": "t", "markets": ["SG"], "sources": ["public_web"], "result_limit": 5},
        )
        assert response.status_code == 502
        assert response.json()["error"]["code"] == "research_upstream_error"
        raw = str(response.json())
        assert FAKE_KEY not in raw and "SECRET" not in raw

    def test_unconfigured_public_web_maps_503(self):
        service = ResearchApplicationService(ResearchCapabilityResolver(), {})
        app = create_app()
        app.dependency_overrides[get_research_application_service] = lambda: service
        response = TestClient(app).post(
            PATH,
            json={"topic": "t", "markets": ["SG"], "sources": ["public_web"], "result_limit": 5},
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "research_source_not_configured"

    def test_combined_youtube_and_public_web(self):
        import tests.unit.test_research_api as api_tests

        full = api_tests._valid_payload(  # noqa: SLF001
            market="SG",
            sources=["youtube", "public_web"],
            result_limit=4,
        )
        full.pop("date_from", None)
        full.pop("date_to", None)

        yt_client = api_tests.YouTubeClient(
            api_tests.TEST_KEY,
            http_client=httpx.Client(transport=httpx.MockTransport(api_tests._youtube_handler)),  # noqa: SLF001
        )
        from trendora.research import YouTubeResearchRetriever

        service = ResearchApplicationService(
            ResearchCapabilityResolver(),
            {
                "youtube": YouTubeResearchRetriever(yt_client),
                "public_web": WebSearchResearchRetriever(
                    _gateway(_ok_handler(_organic("https://a.com/1")))
                ),
            },
        )
        app = create_app()
        app.dependency_overrides[get_research_application_service] = lambda: service
        body = TestClient(app).post(PATH, json=full).json()
        assert body["status"] == "completed"
        assert body["executed_sources"] == ["youtube", "public_web"]
        codes = [r["source_code"] for r in body["references"]]
        assert "public_web" in codes
        assert body["references"][-1]["source_code"] == "public_web"


class TestReportPipeline:
    def _report_service(self, events, handler):
        from tests.unit.test_research_reporting import (
            RecordingIdeationProvider,
            RecordingInterpretationProvider,
            RecordingStrategyProvider,
        )
        from trendora.research import (
            GroundedIdeationService,
            GroundedInterpretationService,
            GroundedStrategyService,
            ResearchReportService,
        )

        research = ResearchApplicationService(
            ResearchCapabilityResolver(),
            {"public_web": WebSearchResearchRetriever(_gateway(handler))},
        )
        return (
            ResearchReportService(
                research,
                GroundedInterpretationService(RecordingInterpretationProvider(events)),
                GroundedStrategyService(RecordingStrategyProvider(events)),
                GroundedIdeationService(RecordingIdeationProvider(events)),
            ),
            events,
        )

    def test_public_web_report_runs_each_ai_stage_once(self):
        events: list[str] = []
        service, _ = self._report_service(
            events, _ok_handler(_organic("https://a.com/1", "https://b.com/2"))
        )
        report = service.build_report(
            topic="t",
            markets=["SG"],
            date_from=date(2026, 8, 1),
            date_to=date(2026, 8, 31),
            sources=["public_web"],
            result_limit=5,
        )
        assert report.status.value == "completed"
        assert events == ["interpretation", "strategy", "ideation"]

    def test_public_web_report_zero_evidence_no_ai(self):
        events: list[str] = []
        service, _ = self._report_service(events, _ok_handler({"organic": []}))
        report = service.build_report(
            topic="t",
            markets=["SG"],
            date_from=date(2026, 8, 1),
            date_to=date(2026, 8, 31),
            sources=["public_web"],
            result_limit=5,
        )
        assert report.status.value == "no_evidence"
        assert events == []

    def test_report_endpoint_upstream_error_maps_502(self):
        events: list[str] = []
        service, _ = self._report_service(
            events, lambda request: httpx.Response(500, json={"message": FAKE_KEY})
        )
        app = create_app()
        app.dependency_overrides[get_research_report_service] = lambda: service
        response = TestClient(app).post(
            "/api/v1/research/report",
            json={"topic": "t", "markets": ["SG"], "sources": ["public_web"], "result_limit": 5},
        )
        assert response.status_code == 502
        assert response.json()["error"]["code"] == "research_upstream_error"
        assert FAKE_KEY not in str(response.json())
