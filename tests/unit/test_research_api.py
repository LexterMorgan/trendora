"""M15 research API tests. No database, no live YouTube, no API key needed."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
from fastapi.testclient import TestClient

from trendora.api import create_app
from trendora.api.app import (
    get_github_forecast_product,
    get_research_application_service,
)
from trendora.connectors.youtube.client import YouTubeClient
from trendora.diagnostics.models import CadenceClass
from trendora.forecasting.models import ForecastModel, ForecastPoint
from trendora.product import GitHubForecastProduct, GitHubForecastResult
from trendora.research import (
    ResearchApplicationService,
    ResearchCapabilityResolver,
    YouTubeResearchRetriever,
)
from tests.fixtures.youtube_responses import (
    CHANNEL_A,
    QUOTA_ERROR,
    SEARCH_EMPTY,
    SEARCH_PAGE_1,
    VIDEO_1,
    VIDEO_2,
    VIDEOS_LIST_OK,
)

TEST_KEY = "test-key-not-real"
UTC = timezone.utc
PATH = "/api/v1/research"
REPO = UUID("88888888-8888-4888-8888-888888888801")


def _valid_payload(**overrides) -> dict:
    payload = {
        "topic": "AI education",
        "market": "SG",
        "date_from": "2026-08-01",
        "date_to": "2026-08-31",
        "sources": ["youtube"],
        "result_limit": 20,
    }
    payload.update(overrides)
    return payload


def _youtube_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/search"):
        return httpx.Response(200, json=SEARCH_PAGE_1)
    assert request.url.path.endswith("/videos")
    return httpx.Response(200, json=VIDEOS_LIST_OK)


def _make_app(handler) -> tuple[TestClient, ResearchApplicationService]:
    client = YouTubeClient(TEST_KEY, http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    retriever = YouTubeResearchRetriever(client)
    service = ResearchApplicationService(ResearchCapabilityResolver(), {"youtube": retriever})
    return _app_with_service(service), service


def _make_app_no_config() -> TestClient:
    service = ResearchApplicationService(ResearchCapabilityResolver(), {})
    return _app_with_service(service)


def _app_with_service(service: ResearchApplicationService) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_research_application_service] = lambda: service
    return TestClient(app)


def _parse(dt_str: str) -> datetime:
    return datetime.fromisoformat(dt_str)


def _fb_post(
    post_id: str,
    *,
    message: str | None = "hello fb",
    created: str = "2026-08-10T08:00:00+0000",
    reactions: int | None = 12,
    comments: int | None = 4,
    shares: int | None = 3,
) -> dict:
    item: dict = {
        "id": post_id,
        "from": {"id": "page1", "name": "Example Page"},
        "created_time": created,
        "permalink_url": f"https://www.facebook.com/p/p{post_id}",
    }
    if message is not None:
        item["message"] = message
    if reactions is not None:
        item["reactions"] = {"summary": {"total_count": reactions}}
    if comments is not None:
        item["comments"] = {"summary": {"total_count": comments}}
    if shares is not None:
        item["shares"] = {"count": shares}
    return item


def _facebook_payload(**overrides) -> dict:
    payload = _valid_payload(
        sources=["facebook"], facebook_page_id="page1", result_limit=10
    )
    payload.update(overrides)
    return payload


def _make_facebook_app(handler) -> tuple[TestClient, ResearchApplicationService]:
    from trendora.connectors.facebook.client import FacebookPublicClient
    from trendora.research import FacebookResearchRetriever

    client = FacebookPublicClient(
        "test-facebook-token-not-real",
        "v19.0",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    retriever = FacebookResearchRetriever(client)
    service = ResearchApplicationService(ResearchCapabilityResolver(), {"facebook": retriever})
    return _app_with_service(service), service


def _facebook_handler(posts: list[dict]):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": posts})

    return handler


class TestRequest:
    def test_valid_request_returns_200(self) -> None:
        client, _ = _make_app(_youtube_handler)
        response = client.post(PATH, json=_valid_payload())
        assert response.status_code == 200

    def test_sources_map_to_source_codes(self) -> None:
        client, _ = _make_app(_youtube_handler)
        body = client.post(PATH, json=_valid_payload()).json()
        assert body["query"]["sources"] == ["youtube"]
        assert body["query"]["topic"] == "AI education"
        assert body["query"]["market"] == "SG"
        assert body["query"]["date_from"] == "2026-08-01"
        assert body["query"]["date_to"] == "2026-08-31"
        assert body["query"]["result_limit"] == 20

    def test_invalid_market_returns_422_invalid_research_request(self) -> None:
        client, _ = _make_app(_youtube_handler)
        response = client.post(PATH, json=_valid_payload(market="US"))
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_research_request"

    def test_blank_topic_returns_422_invalid_research_request(self) -> None:
        client, _ = _make_app(_youtube_handler)
        response = client.post(PATH, json=_valid_payload(topic="   "))
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_research_request"

    def test_invalid_date_window_returns_422_invalid_research_request(self) -> None:
        client, _ = _make_app(_youtube_handler)
        response = client.post(
            PATH, json=_valid_payload(date_from="2026-08-31", date_to="2026-08-01")
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_research_request"

    def test_invalid_result_limit_returns_422_invalid_research_request(self) -> None:
        client, _ = _make_app(_youtube_handler)
        for limit in (0, -1, 101):
            response = client.post(PATH, json=_valid_payload(result_limit=limit))
            assert response.status_code == 422
            assert response.json()["error"]["code"] == "invalid_research_request"

    def test_malformed_body_returns_422_invalid_request(self) -> None:
        client, _ = _make_app(_youtube_handler)
        response = client.post(PATH, json={"market": "SG"})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_request"


class TestSuccess:
    def test_success_response_shape(self) -> None:
        client, _ = _make_app(_youtube_handler)
        body = client.post(PATH, json=_valid_payload()).json()
        assert set(body) == {
            "query",
            "coverage",
            "executed_sources",
            "status",
            "references",
        }
        assert body["status"] == "completed"
        assert body["coverage"]["completeness"] == "complete"
        assert body["executed_sources"] == ["youtube"]
        assert len(body["references"]) == 2

    def test_reference_fields_serialized(self) -> None:
        client, _ = _make_app(_youtube_handler)
        body = client.post(PATH, json=_valid_payload()).json()
        reference = body["references"][0]
        assert reference["source_code"] == "youtube"
        assert reference["content_external_id"] == VIDEO_1
        assert reference["url"] == f"https://www.youtube.com/watch?v={VIDEO_1}"
        assert reference["channel_external_id"] == CHANNEL_A
        assert reference["source_rank"] == 1

    def test_description_and_channel_title_preserved(self) -> None:
        client, _ = _make_app(_youtube_handler)
        body = client.post(PATH, json=_valid_payload()).json()
        reference = body["references"][0]
        assert reference["description"] == "A lesson"
        assert reference["channel_title"] == "SEA AI Education"

    def test_missing_metric_serializes_as_null(self) -> None:
        client, _ = _make_app(_youtube_handler)
        body = client.post(PATH, json=_valid_payload()).json()
        second = body["references"][1]  # VIDEO_2 has only viewCount
        assert second["metrics"] == {
            "view_count": 5,
            "like_count": None,
            "comment_count": None,
            "reaction_count": None,
            "share_count": None,
        }

    def test_zero_metric_remains_zero(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/search"):
                return httpx.Response(200, json=SEARCH_PAGE_1)
            payload = {
                "items": [
                    {
                        "id": VIDEO_1,
                        "snippet": {"title": "Zero views"},
                        "statistics": {"viewCount": "0", "likeCount": "1"},
                    }
                ]
            }
            return httpx.Response(200, json=payload)

        client, _ = _make_app(handler)
        body = client.post(PATH, json=_valid_payload()).json()
        assert body["references"][0]["metrics"]["view_count"] == 0

    def test_datetimes_serialize_timezone_aware(self) -> None:
        client, _ = _make_app(_youtube_handler)
        body = client.post(PATH, json=_valid_payload()).json()
        reference = body["references"][0]
        published = _parse(reference["published_at"])
        collected = _parse(reference["collected_at"])
        assert published.tzinfo is not None
        assert collected.tzinfo is not None

    def test_market_context_and_basis_preserved(self) -> None:
        client, _ = _make_app(_youtube_handler)
        body = client.post(PATH, json=_valid_payload()).json()
        for reference in body["references"]:
            assert reference["market_context"] == "SG"
            assert reference["market_basis"] == "youtube_region_availability"

    def test_no_country_or_language_fields(self) -> None:
        client, _ = _make_app(_youtube_handler)
        body = client.post(PATH, json=_valid_payload()).json()
        reference = body["references"][0]
        for forbidden in ("creator_country", "publisher_country", "origin_country", "language"):
            assert forbidden not in reference

    def test_source_rank_preserved_in_order(self) -> None:
        client, _ = _make_app(_youtube_handler)
        body = client.post(PATH, json=_valid_payload()).json()
        assert [r["source_rank"] for r in body["references"]] == [1, 2]

    def test_zero_results_returns_200_completed_empty(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=SEARCH_EMPTY)

        client, _ = _make_app(handler)
        response = client.post(PATH, json=_valid_payload())
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "completed"
        assert body["references"] == []
        # Execution provenance makes a successful zero-result search observable.
        assert body["executed_sources"] == ["youtube"]

    def test_no_derived_metrics(self) -> None:
        client, _ = _make_app(_youtube_handler)
        body = client.post(PATH, json=_valid_payload()).json()
        for reference in body["references"]:
            assert set(reference["metrics"]) == {
                "view_count",
                "like_count",
                "comment_count",
                "reaction_count",
                "share_count",
            }


class TestExecutionTruth:
    def test_static_availability_alone_does_not_mean_execution(self) -> None:
        # stack_exchange statically supports public_search but has no retriever.
        client, _ = _make_app(_youtube_handler)
        body = client.post(
            PATH, json=_valid_payload(sources=["stack_exchange", "youtube"])
        ).json()
        by_source = {item["source_code"]: item for item in body["coverage"]["sources"]}
        assert by_source["stack_exchange"]["status"] == "available"
        assert by_source["youtube"]["status"] == "available"
        # Only youtube was actually executed.
        assert body["executed_sources"] == ["youtube"]
        assert body["status"] == "completed"

    def test_executable_source_wins_over_earlier_statically_available_source(self) -> None:
        # stack_exchange appears first and is statically available but not
        # executable; youtube appears later and is genuinely executable.
        client, _ = _make_app(_youtube_handler)
        body = client.post(
            PATH, json=_valid_payload(sources=["stack_exchange", "youtube"])
        ).json()
        assert body["executed_sources"] == ["youtube"]
        assert all(ref["source_code"] == "youtube" for ref in body["references"])

    def test_unavailable_source_is_never_executed(self) -> None:
        client, _ = _make_app(_youtube_handler)
        body = client.post(
            PATH, json=_valid_payload(sources=["instagram", "youtube"])
        ).json()
        assert body["executed_sources"] == ["youtube"]
        assert all(ref["source_code"] == "youtube" for ref in body["references"])

    def test_coverage_unchanged_by_runtime_executor_availability(self) -> None:
        # Runtime executor absence does not falsify static capability truth.
        client, _ = _make_app(_youtube_handler)
        body = client.post(
            PATH, json=_valid_payload(sources=["stack_exchange", "youtube"])
        ).json()
        assert body["coverage"]["completeness"] == "complete"
        by_source = {item["source_code"]: item for item in body["coverage"]["sources"]}
        assert by_source["stack_exchange"]["status"] == "available"

    def test_no_runtime_retriever_for_only_available_source_is_not_completed(self) -> None:
        # stack_exchange is the only requested source, statically available,
        # but no retriever exists -> runtime/service error, never completed.
        client, _ = _make_app(_youtube_handler)
        response = client.post(PATH, json=_valid_payload(sources=["stack_exchange"]))
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "research_source_not_configured"


class TestPartialCoverage:
    def test_partial_coverage_executes_youtube_only(self) -> None:
        client, _ = _make_app(_youtube_handler)
        response = client.post(
            PATH, json=_valid_payload(sources=["youtube", "instagram"])
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "completed"
        assert body["coverage"]["completeness"] == "partial"
        assert body["executed_sources"] == ["youtube"]
        by_source = {item["source_code"]: item for item in body["coverage"]["sources"]}
        assert by_source["youtube"]["status"] == "available"
        assert by_source["instagram"]["status"] == "unavailable"
        assert by_source["instagram"]["reason"] == "source_unknown"
        assert all(ref["source_code"] == "youtube" for ref in body["references"])
        assert not any(ref["source_code"] == "instagram" for ref in body["references"])


class TestBlocked:
    def test_blocked_returns_422_research_no_coverage(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("retriever must not be called for a blocked run")

        client, _ = _make_app(handler)
        response = client.post(
            PATH, json=_valid_payload(sources=["instagram", "tiktok"])
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "research_no_coverage"
        assert "error" in response.json()


class TestRuntimeConfig:
    def test_missing_config_is_not_capability_not_supported(self) -> None:
        client = _make_app_no_config()
        response = client.post(PATH, json=_valid_payload())
        assert response.status_code == 503
        body = response.json()
        assert body["error"]["code"] == "research_source_not_configured"
        assert "capability_not_supported" not in body["error"]["code"]


class TestUpstream:
    def test_upstream_failure_is_not_empty_success(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json=QUOTA_ERROR)

        client, _ = _make_app(handler)
        response = client.post(PATH, json=_valid_payload())
        assert response.status_code == 502
        body = response.json()
        assert body["error"]["code"] == "research_upstream_error"

    def test_upstream_error_does_not_leak_secrets_or_tracebacks(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json=QUOTA_ERROR)

        client, _ = _make_app(handler)
        body = client.post(PATH, json=_valid_payload()).json()
        raw = str(body)
        assert TEST_KEY not in raw
        assert "Traceback" not in raw
        assert "at 0x" not in raw


class TestFacebook:
    def test_facebook_success_serializes_metrics(self) -> None:
        client, _ = _make_facebook_app(
            _facebook_handler([_fb_post("p1", reactions=12, comments=4, shares=3)])
        )
        body = client.post(PATH, json=_facebook_payload()).json()
        assert body["status"] == "completed"
        assert body["executed_sources"] == ["facebook"]
        assert body["query"]["facebook_page_id"] == "page1"
        reference = body["references"][0]
        assert reference["source_code"] == "facebook"
        assert reference["content_external_id"] == "p1"
        assert reference["url"] == "https://www.facebook.com/p/pp1"
        assert reference["description"] == "hello fb"
        assert reference["title"] is None
        assert reference["metrics"] == {
            "view_count": None,
            "like_count": None,
            "comment_count": 4,
            "reaction_count": 12,
            "share_count": 3,
        }

    def test_facebook_nullable_metrics_serialize_as_null(self) -> None:
        client, _ = _make_facebook_app(
            _facebook_handler([_fb_post("p1", reactions=None, comments=None, shares=None)])
        )
        body = client.post(PATH, json=_facebook_payload()).json()
        assert body["references"][0]["metrics"] == {
            "view_count": None,
            "like_count": None,
            "comment_count": None,
            "reaction_count": None,
            "share_count": None,
        }

    def test_facebook_zero_posts_completes_empty(self) -> None:
        client, _ = _make_facebook_app(_facebook_handler([]))
        response = client.post(PATH, json=_facebook_payload())
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "completed"
        assert body["references"] == []
        assert body["executed_sources"] == ["facebook"]

    def test_facebook_missing_page_id_returns_422(self) -> None:
        client, _ = _make_facebook_app(_facebook_handler([]))
        response = client.post(
            PATH, json=_valid_payload(sources=["facebook"], result_limit=10)
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_research_request"

    def test_facebook_unsafe_page_id_returns_422(self) -> None:
        client, _ = _make_facebook_app(_facebook_handler([]))
        for bad in ("a/b", "a b", "..", "."):
            response = client.post(
                PATH, json=_facebook_payload(facebook_page_id=bad)
            )
            assert response.status_code == 422
            assert response.json()["error"]["code"] == "invalid_research_request"

    def test_page_id_with_youtube_only_returns_422(self) -> None:
        client, _ = _make_facebook_app(_facebook_handler([]))
        response = client.post(
            PATH, json=_valid_payload(facebook_page_id="page1")
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_research_request"

    def test_mixed_facebook_and_youtube_sources_returns_422(self) -> None:
        client, _ = _make_facebook_app(_facebook_handler([]))
        response = client.post(
            PATH, json=_facebook_payload(sources=["facebook", "youtube"])
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_research_request"

    def test_facebook_without_retriever_returns_503(self) -> None:
        client, _ = _make_app(_youtube_handler)  # only youtube configured
        response = client.post(PATH, json=_facebook_payload())
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "research_source_not_configured"

    def test_facebook_configuration_error_maps_to_sanitized_503(self) -> None:
        from trendora.connectors.facebook.exceptions import FacebookConfigurationError
        from trendora.research import FacebookResearchRetriever

        class FailingClient:
            def list_page_posts(self, page_id, *, date_from, date_to, limit):
                raise FacebookConfigurationError(
                    f"bad page id {page_id} and secret test-facebook-token-not-real"
                )

        service = ResearchApplicationService(
            ResearchCapabilityResolver(),
            {"facebook": FacebookResearchRetriever(FailingClient())},
        )
        response = _app_with_service(service).post(PATH, json=_facebook_payload())
        assert response.status_code == 503
        body = response.json()
        assert body["error"]["code"] == "research_source_not_configured"
        assert body["error"]["message"] == "The requested source is not configured."
        raw = str(body)
        assert "test-facebook-token-not-real" not in raw
        assert "Traceback" not in raw

    def test_facebook_upstream_failure_returns_502(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                503, json={"error": {"message": "upstream", "code": 2}}
            )

        client, _ = _make_facebook_app(handler)
        response = client.post(PATH, json=_facebook_payload())
        assert response.status_code == 502
        assert response.json()["error"]["code"] == "research_upstream_error"

    def test_facebook_upstream_transport_failure_returns_502(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        client, _ = _make_facebook_app(handler)
        response = client.post(PATH, json=_facebook_payload())
        assert response.status_code == 502
        assert response.json()["error"]["code"] == "research_upstream_error"

    def test_facebook_errors_do_not_leak_token_or_tracebacks(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                500, json={"error": {"message": "bad token test-facebook-token-not-real"}}
            )

        client, _ = _make_facebook_app(handler)
        body = client.post(PATH, json=_facebook_payload()).json()
        raw = str(body)
        assert "test-facebook-token-not-real" not in raw
        assert "Traceback" not in raw
        assert "at 0x" not in raw
        assert body["error"]["message"] == "The upstream source failed."


class TestForecastBoundary:
    def _stub_forecast_result(self) -> GitHubForecastResult:
        t0 = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
        return GitHubForecastResult(
            source_code="github",
            metric_name="stargazer_count",
            content_item_id=REPO,
            content_external_id="m10fixture/repo",
            model=ForecastModel.NAIVE,
            horizon=4,
            interval=timedelta(days=7),
            origin="trendora_forecast",
            points=tuple(ForecastPoint(at=t0 + timedelta(days=7 * n), value=999.0) for n in range(1, 5)),
            observation_count=5,
            history_start=t0,
            history_end=t0 + timedelta(days=3),
            latest_observed_at=t0 + timedelta(days=3),
            cadence=CadenceClass.VARIABLE,
            irregular_cadence=True,
        )

    def test_forecast_endpoint_still_works_alongside_research(self) -> None:
        app = create_app()
        result = self._stub_forecast_result()

        class _Stub:
            def forecast(self, request):  # noqa: ARG002
                return result

        app.dependency_overrides[get_github_forecast_product] = lambda: _Stub()
        client = TestClient(app)
        response = client.get(
            "/api/v1/forecasts/github/{0}".format(REPO),
            params={"metric": "stargazer_count"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["origin"] == "trendora_forecast"
        assert len(body["points"]) == 4


class TestOpenAPI:
    def test_openapi_has_research_post_and_forecast_get(self) -> None:
        app = create_app()
        schema = app.openapi()
        paths = schema["paths"]
        assert "post" in paths["/api/v1/research"]
        assert "get" in paths["/api/v1/forecasts/github/{content_item_id}"]
        schemas = schema["components"]["schemas"]
        assert "ResearchRequest" in schemas
        assert "ResearchResponse" in schemas
        assert "ResearchReferenceResponse" in schemas
        assert "ResearchMetricsResponse" in schemas
        assert "facebook_page_id" in schemas["ResearchRequest"]["properties"]
        metric_props = schemas["ResearchMetricsResponse"]["properties"]
        for field in ("view_count", "like_count", "comment_count", "reaction_count", "share_count"):
            assert field in metric_props
