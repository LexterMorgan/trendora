"""Hacker News Firebase API HTTP client. No SQLAlchemy. No normalization."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from pydantic import ValidationError

from trendora.connectors.hackernews.exceptions import HackerNewsHttpError, HackerNewsResponseError
from trendora.connectors.hackernews.schemas import ItemResource

logger = logging.getLogger("trendora.connectors.hackernews.client")

HN_API_BASE = "https://hacker-news.firebaseio.com/v0"
_USER_AGENT = "Trendora/0.0.1"


class HackerNewsClient:
    """HTTPS client for official HN Firebase list and item endpoints.

    Algolia and HTML scraping are intentionally not implemented.
    """

    def __init__(self, *, http_client: httpx.Client | None = None) -> None:
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client(
            timeout=httpx.Timeout(20.0, connect=10.0),
            headers={"User-Agent": _USER_AGENT},
        )

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> HackerNewsClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def list_feed_ids(self, feed: str, *, max_items: int) -> list[int]:
        if max_items < 1:
            return []
        payload = self._get(f"{feed}.json")
        if not isinstance(payload, list):
            raise HackerNewsResponseError(f"Hacker News {feed} feed was not a list")
        ids: list[int] = []
        for raw in payload:
            if not isinstance(raw, int) or isinstance(raw, bool) or raw < 1:
                logger.warning("hackernews.feed.invalid_id feed=%s value=%r", feed, raw)
                continue
            if raw in ids:
                continue
            ids.append(raw)
            if len(ids) >= max_items:
                break
        logger.info("hackernews.feed.listed feed=%s returned=%s limit=%s", feed, len(ids), max_items)
        return ids[:max_items]

    def get_item(self, item_id: int) -> ItemResource | None:
        payload = self._get(f"item/{item_id}.json")
        if payload is None:
            return None
        if not isinstance(payload, dict):
            raise HackerNewsResponseError(f"Hacker News item {item_id} was not an object")
        try:
            return ItemResource.model_validate(payload)
        except ValidationError as exc:
            raise HackerNewsResponseError(f"Hacker News item {item_id} was malformed") from exc

    def _get(self, endpoint: str) -> Any:
        url = f"{HN_API_BASE}/{endpoint}"
        logger.info("hackernews.api.request endpoint=%s", endpoint)
        try:
            response = self._http.get(url)
        except httpx.HTTPError as exc:
            logger.exception(
                "hackernews.api.http_failure endpoint=%s error_type=%s",
                endpoint,
                type(exc).__name__,
            )
            raise HackerNewsHttpError(f"Hacker News HTTP request failed for {endpoint}") from exc

        if response.status_code >= 400:
            logger.error(
                "hackernews.api.http_error endpoint=%s status=%s",
                endpoint,
                response.status_code,
            )
            raise HackerNewsHttpError(
                f"Hacker News {endpoint} failed with HTTP {response.status_code}",
                status_code=response.status_code,
            )

        try:
            return response.json()
        except ValueError as exc:
            raise HackerNewsResponseError(f"Hacker News {endpoint} returned non-JSON") from exc
