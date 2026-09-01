"""M14 YouTube research retrieval tests. No database, no live YouTube."""

from __future__ import annotations

from datetime import date, datetime, timezone

from dataclasses import fields

import httpx
import pytest

from trendora.connectors.youtube.client import YouTubeClient
from trendora.connectors.youtube.exceptions import YouTubeApiError
from trendora.research import (
    MarketBasis,
    ResearchCapabilityResolver,
    ResearchMetrics,
    ResearchQuery,
    ResearchRun,
    ResearchRunStatus,
    ResearchStateError,
    YouTubeResearchRetriever,
)
from trendora.research.youtube import _to_rfc3339
from tests.fixtures.youtube_responses import (
    CHANNEL_A,
    QUOTA_ERROR,
    SEARCH_EMPTY,
    SEARCH_PAGE_1,
    SEARCH_PAGE_2,
    VIDEO_1,
    VIDEO_2,
    VIDEO_3,
    VIDEOS_LIST_OK,
)

TEST_KEY = "test-key-not-real"
UTC = timezone.utc
COLLECTED_AT = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)


def _client(handler) -> YouTubeClient:
    transport = httpx.MockTransport(handler)
    return YouTubeClient(TEST_KEY, http_client=httpx.Client(transport=transport))


def _query(**kwargs) -> ResearchQuery:
    payload = dict(
        topic="AI education",
        market="SG",
        date_from=date(2026, 8, 1),
        date_to=date(2026, 8, 30),
    )
    payload.update(kwargs)
    return ResearchQuery(**payload)


class TestRetriever:
    def test_collect_and_normalize_end_to_end(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/search"):
                return httpx.Response(200, json=SEARCH_PAGE_1)
            assert request.url.path.endswith("/videos")
            return httpx.Response(200, json=VIDEOS_LIST_OK)

        retriever = YouTubeResearchRetriever(_client(handler))
        collected = retriever.collect(_query(), collected_at=COLLECTED_AT)
        references = retriever.normalize(collected)

        assert len(references) == 2
        first = references[0]
        assert first.source_code == "youtube"
        assert first.content_external_id == VIDEO_1
        assert first.url == f"https://www.youtube.com/watch?v={VIDEO_1}"
        assert first.title == "Intro to Python"
        # Enriched video snippet description takes precedence over the search snippet.
        assert first.description == "A lesson"
        assert first.published_at == datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
        assert first.channel_external_id == CHANNEL_A
        assert first.channel_title == "SEA AI Education"
        assert first.metrics == ResearchMetrics(view_count=100, like_count=10, comment_count=2)
        assert first.metrics.view_count == 100
        assert first.metrics.like_count == 10
        assert first.metrics.comment_count == 2
        assert first.collected_at == COLLECTED_AT

    def test_metrics_are_official_fields_only(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/search"):
                return httpx.Response(200, json=SEARCH_PAGE_1)
            return httpx.Response(200, json=VIDEOS_LIST_OK)

        retriever = YouTubeResearchRetriever(_client(handler))
        references = retriever.normalize(retriever.collect(_query(), collected_at=COLLECTED_AT))
        for reference in references:
            assert {f.name for f in fields(ResearchMetrics)} == {
                "view_count",
                "like_count",
                "comment_count",
            }
            assert isinstance(reference.metrics, ResearchMetrics)

    def test_missing_raw_metric_remains_none(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/search"):
                return httpx.Response(200, json=SEARCH_PAGE_1)
            return httpx.Response(200, json=VIDEOS_LIST_OK)

        retriever = YouTubeResearchRetriever(_client(handler))
        references = retriever.normalize(retriever.collect(_query(), collected_at=COLLECTED_AT))
        second = references[1]  # VIDEO_2 in VIDEOS_LIST_OK has only viewCount
        assert second.metrics.view_count == 5
        assert second.metrics.like_count is None
        assert second.metrics.comment_count is None

    def test_zero_is_distinct_from_missing(self) -> None:
        metrics = ResearchMetrics(view_count=0, like_count=None, comment_count=2)
        assert metrics.view_count == 0
        assert metrics.like_count is None
        assert metrics.view_count is not None

    def test_metrics_cannot_be_mutated(self) -> None:
        metrics = ResearchMetrics(view_count=100, like_count=10, comment_count=2)
        with pytest.raises(AttributeError):
            metrics.view_count = 999  # frozen dataclass

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/search"):
                return httpx.Response(200, json=SEARCH_PAGE_1)
            return httpx.Response(200, json=VIDEOS_LIST_OK)

        retriever = YouTubeResearchRetriever(_client(handler))
        references = retriever.normalize(retriever.collect(_query(), collected_at=COLLECTED_AT))
        with pytest.raises(AttributeError):
            references[0].metrics.comment_count = 999

    def test_missing_enrichment_still_yields_reference_with_search_metadata(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/search"):
                return httpx.Response(200, json=SEARCH_PAGE_2)
            # enrichment returns none of the searched ids
            return httpx.Response(200, json={"items": []})

        retriever = YouTubeResearchRetriever(_client(handler))
        references = retriever.normalize(retriever.collect(_query(), collected_at=COLLECTED_AT))
        assert len(references) == 1
        assert references[0].content_external_id == VIDEO_3
        assert references[0].title == "Advanced Python"
        assert references[0].description == "Deeper Python topics."
        assert references[0].channel_title == "Tech Channel B"
        assert references[0].metrics == ResearchMetrics()
        assert references[0].metrics.view_count is None
        assert references[0].metrics.like_count is None
        assert references[0].metrics.comment_count is None

    def test_description_falls_back_to_search_snippet(self) -> None:
        # VIDEOS_LIST_OK VIDEO_2 has no description, so the search snippet is used.
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/search"):
                return httpx.Response(200, json=SEARCH_PAGE_1)
            return httpx.Response(200, json=VIDEOS_LIST_OK)

        retriever = YouTubeResearchRetriever(_client(handler))
        references = retriever.normalize(retriever.collect(_query(), collected_at=COLLECTED_AT))
        assert references[1].description == "Second search result."

    def test_market_context_and_basis(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/search"):
                return httpx.Response(200, json=SEARCH_PAGE_1)
            return httpx.Response(200, json=VIDEOS_LIST_OK)

        retriever = YouTubeResearchRetriever(_client(handler))
        references = retriever.normalize(retriever.collect(_query(), collected_at=COLLECTED_AT))
        for reference in references:
            assert reference.market_context == "SG"
            assert reference.market_basis is MarketBasis.YOUTUBE_REGION_AVAILABILITY

    def test_market_context_matches_requested_market(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/search"):
                return httpx.Response(200, json=SEARCH_PAGE_1)
            return httpx.Response(200, json=VIDEOS_LIST_OK)

        retriever = YouTubeResearchRetriever(_client(handler))
        references = retriever.normalize(
            retriever.collect(_query(market="TH"), collected_at=COLLECTED_AT)
        )
        assert references[0].market_context == "TH"
        assert references[0].market_basis is MarketBasis.YOUTUBE_REGION_AVAILABILITY

    def test_no_creator_publisher_or_origin_country_inferred(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/search"):
                return httpx.Response(200, json=SEARCH_PAGE_1)
            return httpx.Response(200, json=VIDEOS_LIST_OK)

        retriever = YouTubeResearchRetriever(_client(handler))
        references = retriever.normalize(retriever.collect(_query(), collected_at=COLLECTED_AT))
        reference = references[0]
        for forbidden in ("creator_country", "publisher_country", "origin_country", "country"):
            assert not hasattr(reference, forbidden)
        # The market basis is explicitly availability, not origin.
        assert reference.market_basis is MarketBasis.YOUTUBE_REGION_AVAILABILITY

    def test_no_language_inferred_from_market(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/search"):
                return httpx.Response(200, json=SEARCH_PAGE_1)
            return httpx.Response(200, json=VIDEOS_LIST_OK)

        retriever = YouTubeResearchRetriever(_client(handler))
        references = retriever.normalize(retriever.collect(_query(), collected_at=COLLECTED_AT))
        assert not hasattr(references[0], "language")

    def test_source_rank_is_one_based_and_consecutive(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/search"):
                return httpx.Response(200, json=SEARCH_PAGE_1)
            return httpx.Response(200, json=VIDEOS_LIST_OK)

        retriever = YouTubeResearchRetriever(_client(handler))
        references = retriever.normalize(retriever.collect(_query(), collected_at=COLLECTED_AT))
        assert [r.source_rank for r in references] == [1, 2]

    def test_pagination_rank_continuity_across_pages(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/search"):
                if request.url.params.get("pageToken") == "SEARCHPAGE2":
                    return httpx.Response(200, json=SEARCH_PAGE_2)
                return httpx.Response(200, json=SEARCH_PAGE_1)
            return httpx.Response(200, json=VIDEOS_LIST_OK)

        retriever = YouTubeResearchRetriever(_client(handler))
        references = retriever.normalize(
            retriever.collect(
                _query(result_limit=55),
                collected_at=COLLECTED_AT,
            )
        )
        assert [r.content_external_id for r in references] == [VIDEO_1, VIDEO_2, VIDEO_3]
        assert [r.source_rank for r in references] == [1, 2, 3]

    def test_dedupe_does_not_create_rank_gaps(self) -> None:
        # The client dedupes by video id; ranks must stay consecutive.
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/search"):
                payload = {
                    "items": [
                        {"id": {"kind": "youtube#video", "videoId": VIDEO_1}, "snippet": {"title": "A"}},
                        {"id": {"kind": "youtube#video", "videoId": VIDEO_1}, "snippet": {"title": "B"}},
                        {"id": {"kind": "youtube#video", "videoId": VIDEO_2}, "snippet": {"title": "C"}},
                    ]
                }
                return httpx.Response(200, json=payload)
            return httpx.Response(200, json=VIDEOS_LIST_OK)

        retriever = YouTubeResearchRetriever(_client(handler))
        references = retriever.normalize(retriever.collect(_query(), collected_at=COLLECTED_AT))
        assert [r.content_external_id for r in references] == [VIDEO_1, VIDEO_2]
        assert [r.source_rank for r in references] == [1, 2]

    def test_enrichment_does_not_reorder_references(self) -> None:
        # Search order is [VIDEO_2, VIDEO_1]; enrichment returns the opposite
        # order. References must keep source search order and ranks.
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/search"):
                payload = {
                    "items": [
                        {"id": {"kind": "youtube#video", "videoId": VIDEO_2}, "snippet": {"title": "Second"}},
                        {"id": {"kind": "youtube#video", "videoId": VIDEO_1}, "snippet": {"title": "First"}},
                    ]
                }
                return httpx.Response(200, json=payload)
            # enrichment returns reverse order
            return httpx.Response(200, json={"items": VIDEOS_LIST_OK["items"][::-1]})

        retriever = YouTubeResearchRetriever(_client(handler))
        references = retriever.normalize(retriever.collect(_query(), collected_at=COLLECTED_AT))
        assert [r.content_external_id for r in references] == [VIDEO_2, VIDEO_1]
        assert [r.source_rank for r in references] == [1, 2]

    def test_date_window_conversion_is_inclusive_exclusive(self) -> None:
        query = _query(date_from=date(2026, 8, 1), date_to=date(2026, 8, 30))
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured.update(dict(request.url.params))
            return httpx.Response(200, json=SEARCH_EMPTY)

        YouTubeResearchRetriever(_client(handler)).collect(query, collected_at=COLLECTED_AT)
        assert captured["publishedAfter"] == "2026-08-01T00:00:00Z"
        assert captured["publishedBefore"] == "2026-08-31T00:00:00Z"

    def test_to_rfc3339_uses_utc_midnight(self) -> None:
        assert _to_rfc3339(date(2026, 8, 1)) == "2026-08-01T00:00:00Z"

    def test_empty_search_yields_no_references(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=SEARCH_EMPTY)

        retriever = YouTubeResearchRetriever(_client(handler))
        assert retriever.normalize(retriever.collect(_query(), collected_at=COLLECTED_AT)) == ()

    def test_collected_at_must_be_aware(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=SEARCH_EMPTY)

        retriever = YouTubeResearchRetriever(_client(handler))
        with pytest.raises(ValueError, match="timezone-aware"):
            retriever.collect(_query(), collected_at=datetime(2026, 8, 31, 12, 0))


class TestRunExecution:
    def _ready_run(self) -> ResearchRun:
        run = ResearchRun(_query())
        run.resolve_capabilities(ResearchCapabilityResolver())
        assert run.status is ResearchRunStatus.READY
        return run

    def _youtube_handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json=SEARCH_PAGE_1)
        return httpx.Response(200, json=VIDEOS_LIST_OK)

    def test_execute_reads_references_and_completes(self) -> None:
        retriever = YouTubeResearchRetriever(_client(self._youtube_handler))
        run = self._ready_run()
        run.execute("youtube", retriever)
        assert run.status is ResearchRunStatus.COMPLETED
        assert run.references is not None
        assert len(run.references) == 2
        assert all(ref.source_code == "youtube" for ref in run.references)

    def test_run_is_top_level_result_with_query_coverage_status_and_references(self) -> None:
        retriever = YouTubeResearchRetriever(_client(self._youtube_handler))
        run = self._ready_run()
        assert run.query.topic == "AI education"
        assert run.coverage is not None
        run.execute("youtube", retriever)
        assert run.status is ResearchRunStatus.COMPLETED
        assert run.references is not None and len(run.references) == 2

    def test_execute_failure_marks_failed_and_reraises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json=QUOTA_ERROR)

        retriever = YouTubeResearchRetriever(_client(handler))
        run = self._ready_run()
        with pytest.raises(YouTubeApiError):
            run.execute("youtube", retriever)
        assert run.status is ResearchRunStatus.FAILED
        assert run.references is None

    def test_blocked_run_cannot_execute(self) -> None:
        run = ResearchRun(_query(source_codes=("instagram", "tiktok")))
        run.resolve_capabilities(ResearchCapabilityResolver())
        assert run.status is ResearchRunStatus.BLOCKED
        retriever = YouTubeResearchRetriever(_client(self._youtube_handler))
        with pytest.raises(ResearchStateError):
            run.execute("youtube", retriever)

    def test_ready_is_not_completed_without_execution(self) -> None:
        run = self._ready_run()
        assert run.status is ResearchRunStatus.READY
        assert run.references is None
