"""Self-hosted SearXNG public web search client.

Uses a locally hosted SearXNG instance's JSON search API — no paid provider,
no scraping. One HTTP client, finite timeout, and one bounded retry on HTTP 429
(rate limit), matching the Serper gateway contract.

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

import logging
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
from trendora.connectors.web_search.url_safety import extract_domain, is_safe_url

logger = logging.getLogger("trendora.connectors.web_search.searxng_gateway")

MAX_RESULTS = 15
_USER_AGENT = "Trendora/0.0.1"
_RETRY_STATUS = 429
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


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
    ) -> None:
        if not base_url or not base_url.strip():
            raise WebSearchConfigurationError("SEARXNG_URL required")
        self._base_url = _validate_endpoint(base_url)
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client(
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers={"User-Agent": _USER_AGENT},
        )

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> SearxngGateway:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def search(self, query: str, *, limit: int = MAX_RESULTS) -> list[SearchResult]:
        """Return validated, exact-URL-deduplicated results in provider order."""
        if not query or not query.strip():
            return []
        bounded = max(1, min(limit, MAX_RESULTS))
        payload = self._get(query.strip(), bounded)

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
            if url in seen:
                continue
            seen.add(url)
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
        logger.info("web_search.searxng.query results=%s limit=%s", len(results), bounded)
        return results

    def _get(self, query: str, limit: int) -> dict[str, Any]:
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
