"""M26C multi-market research + execution tests. Fully mocked."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from trendora.research import (
    MarketBasis,
    ResearchApplicationService,
    ResearchCapabilityResolver,
    ResearchMetrics,
    ResearchQuery,
    ResearchReference,
    ResearchRunStatus,
    ResearchValidationError,
)
from trendora.research.application import _allocate_target_limits, _resolve_markets
from trendora.research.models import _merge_targets

UTC = timezone.utc
T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _ref(source, external, *, markets=(), rank=1, **metrics):
    return ResearchReference(
        source_code=source,
        content_external_id=external,
        collected_at=T0,
        url=f"https://example.com/{source}/{external}",
        title=f"{source} {external}",
        description="desc",
        published_at=T0,
        market_contexts=markets,
        market_context=markets[0] if len(markets) == 1 else None,
        market_basis=MarketBasis.YOUTUBE_REGION_AVAILABILITY if source == "youtube" else None,
        source_rank=rank,
        metrics=ResearchMetrics(**metrics),
    )


class RecordingRetriever:
    def __init__(self, refs, error=None):
        self.refs = refs
        self.error = error
        self.calls = []

    def collect(self, query, *, collected_at=None):
        self.calls.append(query)
        if self.error is not None:
            raise self.error
        return object()

    def normalize(self, collected):
        return self.refs


def _service(**retrievers):
    return ResearchApplicationService(ResearchCapabilityResolver(), retrievers)


class TestMarketResolution:
    def test_legacy_singular_market(self):
        assert _resolve_markets("SG", None) == ("SG",)

    def test_plural_markets(self):
        assert _resolve_markets(None, ["SG", "ID"]) == ("SG", "ID")

    def test_both_rejected(self):
        with pytest.raises(ResearchValidationError, match="not both"):
            _resolve_markets("SG", ["ID"])

    def test_neither_rejected(self):
        with pytest.raises(ResearchValidationError, match="required"):
            _resolve_markets(None, None)


class TestQueryMarkets:
    def test_singular_market_normalizes(self):
        q = ResearchQuery(
            topic="t", market="sg", date_from=date(2026, 8, 1), date_to=date(2026, 8, 31)
        )
        assert q.markets == ("SG",)
        assert q.market == "SG"

    def test_plural_normalized_deduplicated_preserving_order(self):
        q = ResearchQuery(
            topic="t",
            markets=["SG", "id", "sg", "TH"],
            date_from=date(2026, 8, 1),
            date_to=date(2026, 8, 31),
        )
        assert q.markets == ("SG", "ID", "TH")
        assert q.market is None

    def test_unsupported_market_rejected(self):
        with pytest.raises(ResearchValidationError, match="unsupported"):
            ResearchQuery(
                topic="t",
                markets=["SG", "US"],
                date_from=date(2026, 8, 1),
                date_to=date(2026, 8, 31),
            )

    def test_blank_market_entry_rejected(self):
        with pytest.raises(ResearchValidationError, match="blank"):
            ResearchQuery(
                topic="t",
                markets=["SG", "  "],
                date_from=date(2026, 8, 1),
                date_to=date(2026, 8, 31),
            )

    def test_empty_markets_rejected(self):
        with pytest.raises(ResearchValidationError, match="market"):
            ResearchQuery(
                topic="t", date_from=date(2026, 8, 1), date_to=date(2026, 8, 31)
            )


class TestTargetAllocation:
    def test_even_split(self):
        assert _allocate_target_limits(4, 2) == (2, 2)

    def test_remainder_to_earlier_targets(self):
        assert _allocate_target_limits(5, 3) == (2, 2, 1)

    def test_three_markets_youtube(self):
        assert _allocate_target_limits(7, 3) == (3, 2, 2)


class TestExecutionTargets:
    def _execute(self, markets, sources, result_limit, facebook_page_id=None, **retrievers):
        return _service(**retrievers).execute(
            topic="AI education",
            markets=markets,
            date_from=date(2026, 8, 1),
            date_to=date(2026, 8, 31),
            sources=sources,
            result_limit=result_limit,
            facebook_page_id=facebook_page_id,
        )

    def test_youtube_called_once_per_market_with_region_and_limit(self):
        yt = RecordingRetriever(())
        run = self._execute(["SG", "ID"], ["youtube"], 5, youtube=yt)
        assert run.status is ResearchRunStatus.COMPLETED
        assert len(yt.calls) == 2
        assert yt.calls[0].markets == ("SG",)
        assert yt.calls[1].markets == ("ID",)
        assert yt.calls[0].result_limit == 3
        assert yt.calls[1].result_limit == 2

    def test_facebook_called_once_across_multiple_markets(self):
        fb = RecordingRetriever(())
        run = self._execute(
            ["SG", "ID", "TH"], ["facebook"], 6, facebook=fb, facebook_page_id="page1"
        )
        assert run.status is ResearchRunStatus.COMPLETED
        assert len(fb.calls) == 1
        assert fb.calls[0].markets == ("SG", "ID", "TH")
        assert fb.calls[0].result_limit == 6

    def test_facebook_requires_page_id(self):
        fb = RecordingRetriever(())
        with pytest.raises(ResearchValidationError, match="facebook_page_id"):
            self._execute(["SG", "ID"], ["facebook"], 6, facebook=fb)

    def test_mixed_source_target_order(self):
        yt = RecordingRetriever(())
        fb = RecordingRetriever(())
        run = self._execute(
            ["SG", "ID"],
            ["youtube", "facebook"],
            6,
            youtube=yt,
            facebook=fb,
            facebook_page_id="page1",
        )
        assert run.status is ResearchRunStatus.COMPLETED
        assert len(yt.calls) == 2
        assert len(fb.calls) == 1
        assert run.executed_sources == ("youtube", "facebook")
        assert yt.calls[0].result_limit == 2
        assert yt.calls[1].result_limit == 2
        assert fb.calls[0].result_limit == 2

    def test_result_limit_below_target_count_rejected(self):
        yt = RecordingRetriever(())
        with pytest.raises(ResearchValidationError, match="result_limit"):
            self._execute(["SG", "ID", "TH"], ["youtube"], 2, youtube=yt)

    def test_target_failure_fails_run(self):
        yt = RecordingRetriever((), error=RuntimeError("boom"))
        with pytest.raises(RuntimeError, match="boom"):
            self._execute(["SG", "ID"], ["youtube"], 4, youtube=yt)


class TestMergeDedup:
    def _batch(self, retriever, query_limit, refs):
        q = ResearchQuery(
            topic="t",
            markets=("SG",),
            date_from=date(2026, 8, 1),
            date_to=date(2026, 8, 31),
            result_limit=query_limit,
        )
        return (retriever, q, None)

    def test_duplicate_youtube_first_wins_facts_union_market_contexts(self):
        first = _ref("youtube", "v1", markets=("SG",), view_count=100)
        dup = _ref("youtube", "v1", markets=("ID",), view_count=999)
        merged = _merge_targets(
            (
                self._batch(RecordingRetriever((first,)), 2, None),
                self._batch(RecordingRetriever((dup,)), 2, None),
            )
        )
        assert len(merged) == 1
        assert merged[0].market_contexts == ("SG", "ID")
        assert merged[0].metrics.view_count == 100
        assert merged[0].market_context is None

    def test_union_preserves_selected_market_order(self):
        first = _ref("youtube", "v1", markets=("ID", "TH"))
        dup = _ref("youtube", "v1", markets=("SG",))
        merged = _merge_targets(
            (
                self._batch(RecordingRetriever((first,)), 2, None),
                self._batch(RecordingRetriever((dup,)), 2, None),
            )
        )
        assert merged[0].market_contexts == ("ID", "TH", "SG")

    def test_no_metric_aggregation(self):
        first = _ref("youtube", "v1", markets=("SG",), view_count=100, like_count=10)
        dup = _ref("youtube", "v1", markets=("ID",), view_count=500, like_count=50)
        merged = _merge_targets(
            (
                self._batch(RecordingRetriever((first,)), 2, None),
                self._batch(RecordingRetriever((dup,)), 2, None),
            )
        )
        assert merged[0].metrics.view_count == 100
        assert merged[0].metrics.like_count == 10

    def test_source_local_rank_reassigned_after_dedup(self):
        a1 = _ref("youtube", "v1", markets=("SG",), rank=5)
        a2 = _ref("youtube", "v2", markets=("SG",), rank=9)
        b1 = _ref("facebook", "p1", rank=3)
        merged = _merge_targets(
            (
                self._batch(RecordingRetriever((a1, a2)), 5, None),
                self._batch(RecordingRetriever((b1,)), 5, None),
            )
        )
        assert [(r.source_code, r.source_rank) for r in merged] == [
            ("youtube", 1),
            ("youtube", 2),
            ("facebook", 1),
        ]

    def test_global_cap_respected(self):
        yt_refs = tuple(_ref("youtube", f"v{i}", markets=("SG",)) for i in range(10))
        fb_refs = tuple(_ref("facebook", f"p{i}") for i in range(10))
        merged = _merge_targets(
            (
                self._batch(RecordingRetriever(yt_refs), 3, None),
                self._batch(RecordingRetriever(fb_refs), 2, None),
            )
        )
        assert len(merged) == 5

    def test_distinct_sources_same_id_not_deduped(self):
        yt = _ref("youtube", "x1", markets=("SG",))
        fb = _ref("facebook", "x1")
        merged = _merge_targets(
            (
                self._batch(RecordingRetriever((yt,)), 1, None),
                self._batch(RecordingRetriever((fb,)), 1, None),
            )
        )
        assert len(merged) == 2

    def test_all_empty_targets_produce_empty(self):
        merged = _merge_targets(
            (
                self._batch(RecordingRetriever(()), 2, None),
                self._batch(RecordingRetriever(()), 2, None),
            )
        )
        assert merged == []


class TestMultimarketAPI:
    def _client(self, handler):
        import httpx
        from fastapi.testclient import TestClient

        from trendora.api import create_app
        from trendora.api.app import get_research_application_service
        from trendora.connectors.youtube.client import YouTubeClient
        from trendora.research import YouTubeResearchRetriever

        client = YouTubeClient(
            "test-key", http_client=httpx.Client(transport=httpx.MockTransport(handler))
        )
        service = ResearchApplicationService(
            ResearchCapabilityResolver(), {"youtube": YouTubeResearchRetriever(client)}
        )
        app = create_app()
        app.dependency_overrides[get_research_application_service] = lambda: service
        return TestClient(app)

    def _youtube_handler(self, request):
        import httpx

        from tests.fixtures.youtube_responses import SEARCH_PAGE_1, VIDEOS_LIST_OK

        if request.url.path.endswith("/search"):
            return httpx.Response(200, json=SEARCH_PAGE_1)
        return httpx.Response(200, json=VIDEOS_LIST_OK)

    def _plural_payload(self, **overrides):
        payload = {
            "topic": "AI education",
            "markets": ["SG", "ID"],
            "date_from": "2026-08-01",
            "date_to": "2026-08-31",
            "sources": ["youtube"],
            "result_limit": 4,
        }
        payload.update(overrides)
        return payload

    def test_plural_request_returns_markets_and_null_market(self):
        client = self._client(self._youtube_handler)
        body = client.post("/api/v1/research", json=self._plural_payload()).json()
        assert body["query"]["markets"] == ["SG", "ID"]
        assert body["query"]["market"] is None

    def test_plural_request_normalizes_and_dedupes(self):
        client = self._client(self._youtube_handler)
        body = client.post(
            "/api/v1/research",
            json=self._plural_payload(markets=["sg", "ID", "sg"]),
        ).json()
        assert body["query"]["markets"] == ["SG", "ID"]

    def test_legacy_singular_request_still_works(self):
        client = self._client(self._youtube_handler)
        body = client.post(
            "/api/v1/research",
            json={
                "topic": "AI education",
                "market": "SG",
                "date_from": "2026-08-01",
                "date_to": "2026-08-31",
                "sources": ["youtube"],
                "result_limit": 20,
            },
        ).json()
        assert body["status"] == "completed"
        assert body["query"]["markets"] == ["SG"]
        assert body["query"]["market"] == "SG"
        for ref in body["references"]:
            assert ref["market_contexts"] == ["SG"]
            assert ref["market_context"] == "SG"

    def test_both_market_and_markets_rejected(self):
        client = self._client(self._youtube_handler)
        payload = self._plural_payload()
        payload["market"] = "SG"
        response = client.post("/api/v1/research", json=payload)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_research_request"

    def test_neither_market_rejected(self):
        client = self._client(self._youtube_handler)
        payload = self._plural_payload()
        del payload["markets"]
        response = client.post("/api/v1/research", json=payload)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_research_request"

    def test_unsupported_market_in_plural_rejected(self):
        client = self._client(self._youtube_handler)
        response = client.post(
            "/api/v1/research", json=self._plural_payload(markets=["SG", "US"])
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_research_request"

    def test_blank_market_entry_rejected(self):
        client = self._client(self._youtube_handler)
        response = client.post(
            "/api/v1/research", json=self._plural_payload(markets=["SG", ""])
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_research_request"
