"""Serper.dev public web search client (M36A / M36A.1).

Official indexed-search API only — no scraping. One HTTP client, finite
timeout, and one bounded retry on HTTP 429 (rate limit). No persistence, no
normalization, no derived metrics.

Security boundary: only absolute HTTP(S) URLs with no userinfo and no
whitespace/control characters become results. Invalid provider entries are
dropped and never surface (not in results, references, logs, or API responses).
The API key appears only in the outbound ``X-API-KEY`` header.
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

logger = logging.getLogger("trendora.connectors.web_search.serper_gateway")

MAX_RESULTS = 15
API_ENDPOINT = "https://google.serper.dev/search"
_USER_AGENT = "Trendora/0.0.1"
_RETRY_STATUS = 429
_ALLOWED_SCHEMES = frozenset({"http", "https"})


def _is_safe_url(value: object) -> bool:
    """True only for absolute HTTP(S) URLs with no userinfo or whitespace.

    Rejects non-strings, blank/untrimmed values, any whitespace or control
    character, non-HTTP(S) schemes, missing hostnames, embedded credentials,
    and malformed ports.
    """
    if not isinstance(value, str):
        return False
    if not value or not value.strip():
        return False
    if value != value.strip():
        return False
    if any(ch.isspace() for ch in value):
        return False
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        return False
    try:
        parsed = urlsplit(value)
        scheme = parsed.scheme.lower()
        if scheme not in _ALLOWED_SCHEMES:
            return False
        if not parsed.hostname:
            return False
        if parsed.username is not None or parsed.password is not None:
            return False
        # Accessing .port raises ValueError on malformed ports; access it to
        # fail closed without leaking the URL.
        _ = parsed.port
    except ValueError:
        return False
    return True


def _extract_domain(parsed_or_url: object) -> str:
    """Hostname only — never scheme, port, or credentials."""
    try:
        if isinstance(parsed_or_url, str):
            parsed_or_url = urlsplit(parsed_or_url)
        hostname = parsed_or_url.hostname  # type: ignore[union-attr]
    except (ValueError, AttributeError):
        return ""
    return hostname or ""


class SerperGateway:
    """Search public indexed content through Serper.dev."""

    def __init__(self, api_key: str | None = None, *, http_client: httpx.Client | None = None) -> None:
        if not api_key or not api_key.strip():
            raise WebSearchConfigurationError("SERPER_API_KEY required")
        self._api_key = api_key.strip()
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client(
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers={"User-Agent": _USER_AGENT},
        )

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> SerperGateway:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def search(self, query: str, *, limit: int = MAX_RESULTS) -> list[SearchResult]:
        """Return validated, exact-URL-deduplicated results in provider order."""
        if not query or not query.strip():
            return []
        bounded = max(1, min(limit, MAX_RESULTS))
        payload = self._post(query.strip(), bounded)

        organic = payload.get("organic")
        if organic is None:
            # Conservative: a missing organic list is an empty search, never a
            # fabricated result.
            return []
        if not isinstance(organic, list):
            raise WebSearchResponseError("web search provider returned a malformed organic list")

        results: list[SearchResult] = []
        seen: set[str] = set()
        skipped = 0
        for raw in organic:
            if len(results) >= bounded:
                break
            if not isinstance(raw, dict):
                skipped += 1
                continue
            link = raw.get("link")
            if not _is_safe_url(link):
                skipped += 1
                continue
            url = link.strip() if isinstance(link, str) else ""  # already whitespace-free
            if url in seen:
                continue
            seen.add(url)
            title = raw.get("title")
            snippet = raw.get("snippet")
            results.append(
                SearchResult(
                    url=url,
                    title=title if isinstance(title, str) else "",
                    snippet=snippet if isinstance(snippet, str) else "",
                    domain=_extract_domain(url),
                )
            )
        if skipped:
            logger.warning(
                "web_search.serper.invalid_results_skipped count=%s", skipped
            )
        logger.info("web_search.serper.query results=%s limit=%s", len(results), bounded)
        return results

    def _post(self, query: str, limit: int) -> dict[str, Any]:
        headers = {"X-API-KEY": self._api_key, "content-type": "application/json"}
        body = {"q": query, "num": limit}
        for attempt in (1, 2):
            transport_failed = False
            try:
                response = self._http.post(API_ENDPOINT, headers=headers, json=body)
            except httpx.HTTPError:
                # Never bind the upstream exception; exit the handler before
                # raising so no __cause__/__context__ chain can survive.
                transport_failed = True
                response = None
            if transport_failed:
                logger.warning("web_search.serper.transport_error")
                raise WebSearchHttpError("web search request failed")
            if response.status_code == _RETRY_STATUS and attempt == 1:
                logger.warning("web_search.serper.rate_limited retrying")
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
