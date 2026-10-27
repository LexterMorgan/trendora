"""Self-hosted SearXNG public web search client.

Uses a locally hosted SearXNG instance's JSON search API — no paid provider,
no scraping. One HTTP client, finite timeout, and one bounded retry on HTTP 429
(rate limit), matching the Serper gateway contract.

Public-social discovery (one pass): a single general topic query plus one
bounded domain-targeted query per social platform, merged and deduplicated by
the shared URL identity rule. Bounds are explicit: at most seven logical
queries, at most two simultaneous requests, one shared wall-clock budget for
the whole batch, and at most fourteen HTTP attempts (seven queries x two
attempts, reusing the existing 429 retry). An in-flight request is cancelled at
the budget boundary and later queries are skipped. Results are search-result
titles, snippets, and links only: this is public social *discovery*, never
full-post scraping.

The SearXNG endpoint is operator-configured and is expected to be loopback
(``127.0.0.1``/``::1``/``localhost``); this gateway is a *search* client only.
Any future page-fetch path is a separate, untrusted-URL concern.

Security boundary: only absolute HTTP(S) URLs with no userinfo and no
whitespace/control characters become results (shared ``url_safety`` rule).
Invalid provider entries are dropped and never surface.

Reference: https://docs.searxng.org/dev/search_api.html — JSON output requires
``search.formats`` to include ``json`` in ``settings.yml``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from trendora.connectors.web_search import SearchResult
from trendora.connectors.web_search.exceptions import (
    WebSearchApiError,
    WebSearchConfigurationError,
    WebSearchHttpError,
    WebSearchResponseError,
)
from trendora.connectors.web_search.platforms import PLATFORM_QUERY_DOMAINS
from trendora.connectors.web_search.url_safety import extract_domain, is_safe_url, result_identity

logger = logging.getLogger("trendora.connectors.web_search.searxng_gateway")

MAX_RESULTS = 15
MAX_QUERIES = 7
MAX_PARALLEL = 2
BATCH_BUDGET_SECONDS = 25.0
MAX_ATTEMPTS = 14
_USER_AGENT = "Trendora/0.1.0"
_RETRY_STATUS = 429
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

_WebSearchError = (WebSearchApiError, WebSearchHttpError, WebSearchResponseError)


@dataclass(frozen=True, slots=True)
class SearchBatch:
    """Outcome of one bounded public-social search batch.

    ``attempted`` counts queries that sent a request; ``succeeded`` counts
    queries that returned a well-formed payload (even an empty result list);
    ``skipped`` counts queries never sent because the budget was gone;
    ``failed`` counts attempted queries that errored or timed out. A batch is
    partial when any query failed or was skipped, which is distinct from a
    query that simply returned zero results.
    """

    results: tuple[SearchResult, ...]
    attempted: int
    succeeded: int
    skipped: int
    failed: int

    @property
    def partial(self) -> bool:
        return self.failed > 0 or self.skipped > 0


def _validate_endpoint(value: str) -> str:
    """Return a normalized SearXNG base URL, or raise on an unsafe value.

    Only http(s) URLs are accepted. The endpoint is operator-configured and is
    expected to be loopback; a non-loopback host is allowed but logged, since a
    remote SearXNG is a legitimate operator choice. Embedded credentials and
    query/fragment parts are rejected so the search URL is built predictably.
    """
    text = (value or "").strip().rstrip("/")
    if not text:
        raise WebSearchConfigurationError("SEARXNG_URL required")
    try:
        parsed = urlsplit(text)
    except ValueError:
        raise WebSearchConfigurationError("SEARXNG_URL is not a valid URL") from None
    if parsed.scheme.lower() not in ("http", "https"):
        raise WebSearchConfigurationError("SEARXNG_URL must be an http(s) URL")
    if not parsed.hostname:
        raise WebSearchConfigurationError("SEARXNG_URL must include a host")
    if parsed.username is not None or parsed.password is not None:
        raise WebSearchConfigurationError("SEARXNG_URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise WebSearchConfigurationError("SEARXNG_URL must not include query or fragment")
    if parsed.hostname not in _LOOPBACK_HOSTS:
        logger.warning("web_search.searxng.non_loopback_endpoint")
    return text


class SearxngGateway:
    """Search public indexed content through a self-hosted SearXNG instance."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        http_client: httpx.Client | None = None,
        async_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not base_url or not base_url.strip():
            raise WebSearchConfigurationError("SEARXNG_URL required")
        self._base_url = _validate_endpoint(base_url)
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client(
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers={"User-Agent": _USER_AGENT},
        )
        # Used only by the bounded social batch; a fresh async client is built
        # per batch so cancellation never leaks a connection pool. When a caller
        # injects a client backed by an httpx.MockTransport (tests), reuse that
        # transport for the async batch too.
        if async_transport is not None:
            self._async_transport: httpx.AsyncBaseTransport | None = async_transport
        elif isinstance(getattr(http_client, "_transport", None), httpx.MockTransport):
            self._async_transport = http_client._transport  # type: ignore[union-attr]
        else:
            self._async_transport = None

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> SearxngGateway:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def search(self, query: str, *, limit: int = MAX_RESULTS) -> list[SearchResult]:
        """One general query. Return validated results in provider order."""
        if not query or not query.strip():
            return []
        bounded = max(1, min(limit, MAX_RESULTS))
        payload = self._get(query.strip())
        results = self._validated_results(payload, bounded)
        logger.info("web_search.searxng.query results=%s limit=%s", len(results), bounded)
        return results

    def search_social(
        self,
        topic: str,
        *,
        limit: int = MAX_RESULTS,
        budget_seconds: float = BATCH_BUDGET_SECONDS,
    ) -> SearchBatch:
        """General query plus one bounded domain-targeted query per platform.

        Returns a merged, deduplicated batch. Raises the first error only when
        nothing succeeded (fail closed); otherwise the surviving results are
        returned and the batch reports itself partial.
        """
        if not topic or not topic.strip():
            return SearchBatch(results=(), attempted=0, succeeded=0, skipped=0, failed=0)
        bounded = max(1, min(limit, MAX_RESULTS))
        cleaned = topic.strip()
        queries = (cleaned, *(f"site:{domain} {cleaned}" for domain in PLATFORM_QUERY_DOMAINS))
        queries = queries[:MAX_QUERIES]
        return asyncio.run(self._search_social(queries, bounded, budget_seconds))

    async def _search_social(
        self, queries: tuple[str, ...], bounded: int, budget_seconds: float
    ) -> SearchBatch:
        endpoint = f"{self._base_url}/search"
        deadline = time.monotonic() + max(0.0, budget_seconds)
        semaphore = asyncio.Semaphore(MAX_PARALLEL)
        per_query: list[list[SearchResult] | None] = [None] * len(queries)
        errors: list[Exception] = []
        counters = {"attempted": 0, "succeeded": 0, "skipped": 0}

        async def run(index: int, query: str) -> None:
            async with semaphore:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    counters["skipped"] += 1
                    return
                counters["attempted"] += 1
                try:
                    payload = await asyncio.wait_for(
                        self._aget_async(client, endpoint, query, remaining), timeout=remaining
                    )
                    per_query[index] = self._validated_results(payload, bounded)
                    counters["succeeded"] += 1
                except _WebSearchError as exc:
                    errors.append(exc)
                except asyncio.TimeoutError:
                    errors.append(WebSearchHttpError("web search request timed out"))

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers={"User-Agent": _USER_AGENT},
            transport=self._async_transport,
        ) as client:
            await asyncio.gather(*(run(index, query) for index, query in enumerate(queries)))

        if counters["succeeded"] == 0 and counters["attempted"] > 0:
            raise errors[0] if errors else WebSearchHttpError("web search request failed")
        merged = _merge_diverse(per_query, bounded)
        batch = SearchBatch(
            results=tuple(merged),
            attempted=counters["attempted"],
            succeeded=counters["succeeded"],
            skipped=counters["skipped"],
            failed=counters["attempted"] - counters["succeeded"],
        )
        logger.info(
            "web_search.searxng.social results=%s attempted=%s succeeded=%s skipped=%s",
            len(batch.results), batch.attempted, batch.succeeded, batch.skipped,
        )
        return batch

    async def _aget_async(
        self, client: httpx.AsyncClient, endpoint: str, query: str, remaining: float
    ) -> dict[str, Any]:
        params = {"q": query, "format": "json"}
        timeout = max(0.001, min(remaining, 30.0))
        for attempt in (1, 2):
            try:
                response = await client.get(endpoint, params=params, timeout=timeout)
            except httpx.HTTPError:
                raise WebSearchHttpError("web search request failed") from None
            if response.status_code == _RETRY_STATUS and attempt == 1:
                logger.warning("web_search.searxng.rate_limited retrying")
                continue
            if response.status_code < 200 or response.status_code >= 300:
                raise WebSearchApiError(
                    f"web search provider returned HTTP {response.status_code}",
                    status_code=response.status_code,
                )
            try:
                payload = response.json()
            except ValueError:
                raise WebSearchResponseError("web search provider returned non-JSON body") from None
            if not isinstance(payload, dict):
                raise WebSearchResponseError("web search provider returned non-object JSON")
            return payload
        raise WebSearchApiError("web search provider rate limited", status_code=_RETRY_STATUS)

    def _validated_results(self, payload: dict[str, Any], bounded: int) -> list[SearchResult]:
        raw_results = payload.get("results")
        if raw_results is None:
            # Conservative: a missing results list is an empty search, never a
            # fabricated result.
            return []
        if not isinstance(raw_results, list):
            raise WebSearchResponseError("web search provider returned a malformed results list")

        results: list[SearchResult] = []
        seen: set[str] = set()
        skipped = 0
        for raw in raw_results:
            if len(results) >= bounded:
                break
            if not isinstance(raw, dict):
                skipped += 1
                continue
            link = raw.get("url")
            if not is_safe_url(link):
                skipped += 1
                continue
            url = link.strip() if isinstance(link, str) else ""
            identity = result_identity(url)
            if identity in seen:
                continue
            seen.add(identity)
            title = raw.get("title")
            snippet = raw.get("content")
            results.append(
                SearchResult(
                    url=url,
                    title=title if isinstance(title, str) else "",
                    snippet=snippet if isinstance(snippet, str) else "",
                    domain=extract_domain(url),
                )
            )
        if skipped:
            logger.warning("web_search.searxng.invalid_results_skipped count=%s", skipped)
        return results

    def _get(self, query: str) -> dict[str, Any]:
        params = {"q": query, "format": "json"}
        endpoint = f"{self._base_url}/search"
        for attempt in (1, 2):
            transport_failed = False
            try:
                response = self._http.get(endpoint, params=params)
            except httpx.HTTPError:
                # Never bind the upstream exception; exit the handler before
                # raising so no __cause__/__context__ chain can survive.
                transport_failed = True
                response = None
            if transport_failed:
                logger.warning("web_search.searxng.transport_error")
                raise WebSearchHttpError("web search request failed")
            if response.status_code == _RETRY_STATUS and attempt == 1:
                logger.warning("web_search.searxng.rate_limited retrying")
                continue
            if response.status_code < 200 or response.status_code >= 300:
                raise WebSearchApiError(
                    f"web search provider returned HTTP {response.status_code}",
                    status_code=response.status_code,
                )
            payload: Any = None
            parse_failed = False
            try:
                payload = response.json()
            except ValueError:
                parse_failed = True
                payload = None
            if parse_failed:
                raise WebSearchResponseError("web search provider returned non-JSON body")
            if not isinstance(payload, dict):
                raise WebSearchResponseError("web search provider returned non-object JSON")
            return payload
        raise WebSearchApiError("web search provider rate limited", status_code=_RETRY_STATUS)


def _merge_diverse(
    per_query: list[list[SearchResult] | None], bounded: int
) -> list[SearchResult]:
    """Merge query batches: dedupe in query order, then take round-robin.

    Deduplication runs first across every batch in query order (general, then
    the platform batches in their existing order), so the first occurrence owns
    the identity and later duplicates never consume a slot. The surviving
    nonempty batches are then read round-robin, general first, one result per
    batch per round, preserving order inside each batch and skipping exhausted
    batches so their slots go to whoever remains. The cap is unchanged and the
    outcome is deterministic; which query returned a URL is never used to infer
    a platform.
    """
    seen: set[str] = set()
    batches: list[list[SearchResult]] = []
    for batch in per_query:
        if not batch:
            continue
        deduped: list[SearchResult] = []
        for result in batch:
            identity = result_identity(result.url)
            if identity in seen:
                continue
            seen.add(identity)
            deduped.append(result)
        if deduped:
            batches.append(deduped)
    merged: list[SearchResult] = []
    index = 0
    while len(merged) < bounded and any(index < len(batch) for batch in batches):
        for batch in batches:
            if index < len(batch):
                merged.append(batch[index])
                if len(merged) >= bounded:
                    break
        index += 1
    return merged
