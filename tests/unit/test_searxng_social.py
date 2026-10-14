"""Bounded public-social search batch (SearXNG). Fully mocked; no network."""

from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timezone

import httpx
import pytest

from trendora.connectors.web_search.exceptions import WebSearchApiError, WebSearchHttpError
from trendora.connectors.web_search.platforms import PLATFORM_QUERY_DOMAINS, classify_platform
from trendora.connectors.web_search.searxng_gateway import (
    MAX_ATTEMPTS,
    MAX_PARALLEL,
    MAX_QUERIES,
    SearxngGateway,
)
from trendora.research.models import ResearchQuery
from trendora.research.web_search import WebSearchResearchRetriever

BASE = "http://127.0.0.1:8888"
UTC = timezone.utc
T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _gateway(handler) -> SearxngGateway:
    return SearxngGateway(BASE, async_transport=httpx.MockTransport(handler))


def _results(*entries) -> dict:
    items = []
    for entry in entries:
        items.append(entry if isinstance(entry, dict) else {"title": entry, "url": entry, "content": "s"})
    return {"results": items}


def _query(limit: int = 15) -> ResearchQuery:
    return ResearchQuery(
        topic="ai education", markets=(), date_from=date(2026, 8, 1),
        date_to=date(2026, 8, 31), source_codes=("public_web",), result_limit=limit,
    )


class TestQueryPlan:
    def test_one_general_query_plus_one_per_platform_bounded_to_seven(self):
        seen: list[str] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.url.params["q"])
            return httpx.Response(200, json=_results(f"https://example.com/{len(seen)}"))

        batch = _gateway(handler).search_social("ai education", limit=5)
        assert len(seen) == MAX_QUERIES == 7
        assert seen[0] == "ai education"
        assert set(seen[1:]) == {f"site:{domain} ai education" for domain in PLATFORM_QUERY_DOMAINS}
        assert batch.succeeded == 7 and batch.failed == 0 and batch.skipped == 0
        assert batch.partial is False

    def test_blank_topic_sends_nothing(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("no request expected")

        batch = _gateway(handler).search_social("   ")
        assert batch.attempted == 0 and batch.results == () and batch.partial is False


class TestMergeAndIdentity:
    def test_merges_dedupes_by_identity_and_caps_at_limit(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            q = request.url.params["q"]
            if q == "ai education":
                return httpx.Response(200, json=_results(
                    {"title": "g1", "url": "https://news.example/a", "content": "s"},
                    {"title": "g2", "url": "https://news.example/b?utm_source=x", "content": "s"},
                ))
            if "site:reddit.com" in q:
                return httpx.Response(200, json=_results(
                    {"title": "r1", "url": "https://news.example/b", "content": "s"},   # dup of g2 (campaign params ignored)
                    {"title": "r2", "url": "https://www.reddit.com/r/x", "content": "s"},
                ))
            return httpx.Response(200, json=_results())

        batch = _gateway(handler).search_social("ai education", limit=3)
        # Round-robin merge: general first, then the platform batch, then what
        # remains. The campaign duplicate is dropped and never takes a slot.
        assert [r.title for r in batch.results] == ["g1", "r2", "g2"]
        assert len(batch.results) == 3, "the cap still bounds the batch"
        assert sum(1 for r in batch.results if r.url == "https://news.example/b") == 0
        reddit = next(r for r in batch.results if r.title == "r2")
        assert reddit.domain == "www.reddit.com"
        assert classify_platform(reddit.url) == "Reddit"


class TestBoundsAndFailures:
    def test_attempts_bounded_at_fourteen_with_retry(self):
        calls = {"n": 0}

        async def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(429, json={})

        with pytest.raises(WebSearchApiError):
            _gateway(handler).search_social("ai education")
        assert calls["n"] == MAX_ATTEMPTS == 14

    def test_at_most_two_simultaneous_requests(self):
        state = {"inflight": 0, "max": 0}

        async def handler(request: httpx.Request) -> httpx.Response:
            state["inflight"] += 1
            state["max"] = max(state["max"], state["inflight"])
            await asyncio.sleep(0.01)
            state["inflight"] -= 1
            return httpx.Response(200, json=_results(f"https://example.com/{request.url.params['q']}"))

        _gateway(handler).search_social("ai education")
        assert 1 <= state["max"] <= MAX_PARALLEL == 2

    def test_partial_failure_keeps_surviving_results(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            if "site:tiktok.com" in request.url.params["q"]:
                return httpx.Response(500, json={})
            return httpx.Response(200, json=_results("https://example.com/ok"))

        batch = _gateway(handler).search_social("ai education", limit=15)
        assert batch.partial is True
        assert batch.failed == 1 and batch.succeeded == 6
        assert len(batch.results) >= 1

    def test_total_failure_raises_closed(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("searxng down")

        with pytest.raises(WebSearchHttpError):
            _gateway(handler).search_social("ai education")

    def test_zero_results_is_not_a_failure(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"results": []})

        batch = _gateway(handler).search_social("ai education")
        assert batch.results == ()
        assert batch.succeeded == 7 and batch.failed == 0 and batch.skipped == 0
        assert batch.partial is False

    def test_budget_cancels_slow_queries_and_skips_the_rest(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            if "site:" in request.url.params["q"]:
                await asyncio.sleep(2.0)  # would exceed the shared budget
            return httpx.Response(200, json=_results("https://example.com/general"))

        started = time.monotonic()
        batch = _gateway(handler).search_social("ai education", limit=5, budget_seconds=0.08)
        elapsed = time.monotonic() - started
        assert elapsed < 1.0, "the shared budget must cancel in-flight requests"
        assert batch.succeeded == 1 and batch.failed >= 1 and batch.skipped >= 1
        assert batch.partial is True
        assert [r.domain for r in batch.results] == ["example.com"]


class TestRetriever:
    def test_retriever_reports_partial_and_keeps_source_identity(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            if "site:linkedin.com" in request.url.params["q"]:
                return httpx.Response(500, json={})
            return httpx.Response(200, json=_results(
                {"title": "t", "url": "https://x.com/u/status/1", "content": "s"},
            ))

        retriever = WebSearchResearchRetriever(_gateway(handler))
        batch = retriever.collect(_query(5), collected_at=T0)
        assert batch.partial is True
        assert retriever.take_partial() is True
        assert retriever.take_partial() is False  # reset after reading

        refs = retriever.normalize(batch)
        web = [r for r in refs if r.source_code == "public_web"]
        assert web and web[0].url == "https://x.com/u/status/1"
        assert web[0].content_external_id == "https://x.com/u/status/1"
        assert web[0].published_at is None
        assert classify_platform(web[0].url) == "X"


class TestCoveragePartial:
    def test_partial_note_keeps_status_and_adds_reason(self):
        from trendora.research.models import (
            CoverageCompleteness, CoverageReason, CoverageStatus, PlatformCapability,
            ResearchCoverage, ResearchRun, SourceCoverage,
        )

        run = ResearchRun(_query(5))
        run._coverage = ResearchCoverage(  # noqa: SLF001 - direct fixture
            sources=(SourceCoverage(
                source_code="public_web", capability=PlatformCapability.PUBLIC_SEARCH,
                status=CoverageStatus.AVAILABLE,
            ),),
            completeness=CoverageCompleteness.COMPLETE,
        )
        run.note_partial_coverage("public_web", CoverageReason.SEARCH_PARTIAL)
        entry = run.coverage.sources[0]
        assert entry.status is CoverageStatus.AVAILABLE
        assert entry.reason is CoverageReason.SEARCH_PARTIAL



SOCIAL_BY_DOMAIN = {
    "reddit.com": "https://www.reddit.com/r/x/comments/1",
    "tiktok.com": "https://www.tiktok.com/@a/video/1",
    "instagram.com": "https://www.instagram.com/p/1",
    "x.com": "https://x.com/u/status/1",
    "linkedin.com": "https://www.linkedin.com/posts/1",
    "facebook.com": "https://www.facebook.com/page/posts/1",
}


class TestMergeFairness:
    def test_social_results_survive_a_full_general_batch(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            q = request.url.params["q"]
            if not q.startswith("site:"):
                return httpx.Response(200, json=_results(
                    *[{"title": f"news {i}", "url": f"https://news{i}.example/story", "content": "s"} for i in range(15)]
                ))
            domain = q.split()[0].removeprefix("site:")
            return httpx.Response(200, json=_results(
                {"title": f"{domain} post", "url": SOCIAL_BY_DOMAIN[domain], "content": "s"}
            ))

        batch = _gateway(handler).search_social("ai education", limit=15)
        urls = [result.url for result in batch.results]
        assert len(urls) == 15
        for social in SOCIAL_BY_DOMAIN.values():
            assert social in urls, f"{social} was discarded"
        # Round-robin: general first, then one per platform batch, then the rest.
        assert urls[0] == "https://news0.example/story"
        assert urls[1:7] == list(SOCIAL_BY_DOMAIN.values())
        assert urls[7:] == [f"https://news{i}.example/story" for i in range(1, 9)]

    def test_duplicate_campaign_urls_keep_the_first_owner_and_use_no_extra_slot(self):
        general_url = "https://news.example/story?id=7&utm_source=newsletter"

        async def handler(request: httpx.Request) -> httpx.Response:
            q = request.url.params["q"]
            if not q.startswith("site:"):
                return httpx.Response(200, json=_results(
                    {"title": "general owner", "url": general_url, "content": "s"},
                    {"title": "general second", "url": "https://news.example/other", "content": "s"},
                ))
            if "site:reddit.com" in q:
                return httpx.Response(200, json=_results(
                    {"title": "campaign duplicate", "url": "https://news.example/story?id=7", "content": "s"},
                    {"title": "reddit result", "url": "https://www.reddit.com/r/x/comments/1", "content": "s"},
                ))
            return httpx.Response(200, json={"results": []})

        batch = _gateway(handler).search_social("ai education", limit=3)
        assert [result.title for result in batch.results] == ["general owner", "reddit result", "general second"]
        assert batch.results[0].url == general_url, "the first occurrence keeps the original URL"
        assert not any(result.title == "campaign duplicate" for result in batch.results)

    def test_failed_and_empty_batches_do_not_block_the_others(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            q = request.url.params["q"]
            if not q.startswith("site:"):
                return httpx.Response(200, json=_results(
                    {"title": "g1", "url": "https://news.example/a", "content": "s"},
                    {"title": "g2", "url": "https://news.example/b", "content": "s"},
                ))
            if "site:tiktok.com" in q:
                return httpx.Response(500, json={})
            if "site:x.com" in q:
                return httpx.Response(200, json=_results({"title": "x post", "url": SOCIAL_BY_DOMAIN["x.com"], "content": "s"}))
            return httpx.Response(200, json={"results": []})

        batch = _gateway(handler).search_social("ai education", limit=15)
        titles = [result.title for result in batch.results]
        assert titles == ["g1", "x post", "g2"]
        assert batch.partial is True and batch.failed == 1

    def test_exhausted_batches_redistribute_their_slots(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            q = request.url.params["q"]
            if not q.startswith("site:"):
                return httpx.Response(200, json=_results({"title": "g1", "url": "https://news.example/a", "content": "s"}))
            if "site:reddit.com" in q:
                return httpx.Response(200, json=_results(
                    {"title": "r1", "url": "https://www.reddit.com/r/x/comments/1", "content": "s"},
                    {"title": "r2", "url": "https://www.reddit.com/r/x/comments/2", "content": "s"},
                    {"title": "r3", "url": "https://www.reddit.com/r/x/comments/3", "content": "s"},
                ))
            return httpx.Response(200, json={"results": []})

        batch = _gateway(handler).search_social("ai education", limit=3)
        assert [result.title for result in batch.results] == ["g1", "r1", "r2"]

    def test_small_limits_stay_deterministic(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            q = request.url.params["q"]
            if not q.startswith("site:"):
                return httpx.Response(200, json=_results(
                    *[{"title": f"g{i}", "url": f"https://news{i}.example/story", "content": "s"} for i in range(3)]
                ))
            if "site:reddit.com" in q:
                return httpx.Response(200, json=_results(
                    {"title": "r1", "url": "https://www.reddit.com/r/x/comments/1", "content": "s"},
                    {"title": "r2", "url": "https://www.reddit.com/r/x/comments/2", "content": "s"},
                ))
            if "site:tiktok.com" in q:
                return httpx.Response(200, json=_results(
                    {"title": "t1", "url": "https://www.tiktok.com/@a/video/1", "content": "s"},
                    {"title": "t2", "url": "https://www.tiktok.com/@a/video/2", "content": "s"},
                ))
            return httpx.Response(200, json={"results": []})

        gateway = _gateway(handler)
        assert [r.title for r in gateway.search_social("ai education", limit=2).results] == ["g0", "r1"]
        assert [r.title for r in gateway.search_social("ai education", limit=3).results] == ["g0", "r1", "t1"]
        assert [r.title for r in gateway.search_social("ai education", limit=5).results] == ["g0", "r1", "t1", "g1", "r2"]
        assert [r.title for r in gateway.search_social("ai education", limit=5).results] == ["g0", "r1", "t1", "g1", "r2"]
