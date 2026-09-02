"""Facebook Graph API public Page client (M25A).

Reads public posts and visible engagement from an explicitly supplied Page ID.
No keyword search, no discovery, no scraping, no user login. The Trendora
backend will later authenticate with its own reviewed Meta app credentials;
no credentials exist yet and every test is mocked.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any

import httpx
from pydantic import ValidationError

from trendora.connectors.facebook.exceptions import (
    FacebookApiError,
    FacebookConfigurationError,
    FacebookHttpError,
    FacebookResponseError,
)
from trendora.connectors.facebook.schemas import FacebookPostResource, FacebookPostsResponse

logger = logging.getLogger("trendora.connectors.facebook.client")

GRAPH_API_BASE = "https://graph.facebook.com"
GRAPH_VERSION_RE = re.compile(r"^v\d+\.\d+$")
PAGE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
MAX_PAGE_SIZE = 100
MIN_PAGE_SIZE = 1

POST_FIELDS = (
    "id,message,created_time,permalink_url,"
    "from{id,name},shares,"
    "reactions.limit(0).summary(true),comments.limit(0).summary(true)"
)


class FacebookPublicClient:
    """HTTPS client for public Facebook Page endpoints. No SQL, no scraping."""

    def __init__(
        self,
        access_token: str,
        graph_version: str,
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        token = access_token.strip()
        if not token:
            raise FacebookConfigurationError("access token must not be blank")
        version = graph_version.strip()
        if not GRAPH_VERSION_RE.match(version):
            raise FacebookConfigurationError(
                f"graph_version must look like 'v<major>.<minor>' (e.g. v19.0); got {version!r}"
            )
        self._access_token = token
        self._graph_version = version
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client(
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers={"User-Agent": "Trendora/0.0.1"},
        )

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> "FacebookPublicClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def list_page_posts(
        self,
        page_id: str,
        *,
        date_from: date,
        date_to: date,
        limit: int,
    ) -> tuple[FacebookPostResource, ...]:
        """List public posts for a known Page ID within an inclusive date range.

        ``date_from``/``date_to`` are inclusive calendar days; the exclusive
        boundary passed to Graph is midnight UTC of the day after ``date_to``.
        """
        page = page_id.strip()
        if (
            not PAGE_ID_RE.match(page)
            or ".." in page
            or page.startswith(".")
            or page.endswith(".")
        ):
            raise FacebookConfigurationError(
                "page_id must be a safe identifier (ASCII letters, digits, _, ., -)"
            )
        if date_from > date_to:
            raise FacebookConfigurationError("date_from must not be after date_to")
        if not MIN_PAGE_SIZE <= limit <= MAX_PAGE_SIZE:
            raise FacebookConfigurationError(
                f"limit must be between {MIN_PAGE_SIZE} and {MAX_PAGE_SIZE}"
            )
        try:
            since = _utc_midnight(date_from)
            until = _utc_midnight(date_to + timedelta(days=1))
        except OverflowError as exc:
            raise FacebookConfigurationError(
                "date range cannot be represented as a Graph API boundary"
            ) from None

        collected: list[FacebookPostResource] = []
        seen: set[str] = set()
        used_cursors: set[str] = set()
        after: str | None = None

        while len(collected) < limit:
            remaining = limit - len(collected)
            params: dict[str, str | int] = {
                "fields": POST_FIELDS,
                "since": since,
                "until": until,
                "limit": min(MAX_PAGE_SIZE, remaining),
            }
            if after:
                params["after"] = after
            payload = self._get_page_posts(page, params)
            response = _validate_posts_response(payload)
            for post in response.data:
                if post.id in seen:
                    continue
                seen.add(post.id)
                collected.append(post)
                if len(collected) >= limit:
                    break
            logger.info(
                "facebook.posts.page page_id=%s collected=%s limit=%s",
                page,
                len(collected),
                limit,
            )
            if len(collected) >= limit:
                break
            after = _next_cursor(response)
            if not after:
                break
            if after in used_cursors:
                raise FacebookResponseError(
                    "Facebook returned an already-used pagination cursor"
                )
            used_cursors.add(after)
        return tuple(collected[:limit])

    def _get_page_posts(
        self,
        page_id: str,
        params: Mapping[str, str | int],
    ) -> dict[str, Any]:
        url = f"{GRAPH_API_BASE}/{self._graph_version}/{page_id}/posts"
        headers = {"Authorization": f"Bearer {self._access_token}"}
        try:
            response = self._http.get(url, params=dict(params), headers=headers)
        except httpx.HTTPError as exc:
            logger.error(
                "facebook.api.http_failure page_id=%s error_type=%s",
                page_id,
                type(exc).__name__,
            )
            raise FacebookHttpError(
                f"Facebook HTTP request failed for page {page_id}"
            ) from None

        try:
            decoded = response.json()
        except ValueError:
            decoded = None

        if response.status_code >= 400:
            if isinstance(decoded, dict) and "error" in decoded:
                raise _api_error_from_payload(page_id, response.status_code, decoded)
            raise FacebookApiError(
                f"Facebook {page_id}/posts failed with HTTP {response.status_code}",
                status_code=response.status_code,
            )
        if not isinstance(decoded, dict):
            raise FacebookResponseError(
                f"Facebook {page_id}/posts returned non-object JSON"
            )
        if "error" in decoded:
            raise _api_error_from_payload(page_id, response.status_code, decoded)
        return decoded


def _utc_midnight(value: date) -> str:
    return f"{value.isoformat()}T00:00:00Z"


def _validate_posts_response(payload: dict[str, Any]) -> FacebookPostsResponse:
    try:
        return FacebookPostsResponse.model_validate(payload)
    except ValidationError:
        raise FacebookResponseError(
            "Facebook posts response failed strict validation"
        ) from None


def _next_cursor(response: FacebookPostsResponse) -> str | None:
    paging = response.paging
    if paging is None or paging.cursors is None:
        return None
    after = paging.cursors.after
    if after is None:
        return None
    after = after.strip()
    return after or None


def _api_error_from_payload(
    page_id: str,
    status_code: int,
    payload: Mapping[str, Any],
) -> FacebookApiError:
    code: int | None = None
    reason: int | None = None
    error = payload.get("error")
    if isinstance(error, dict):
        raw_code = error.get("code")
        if isinstance(raw_code, int):
            code = raw_code
        raw_subcode = error.get("error_subcode")
        if isinstance(raw_subcode, int):
            reason = raw_subcode
    logger.error(
        "facebook.api.error page_id=%s status=%s code=%s subcode=%s",
        page_id,
        status_code,
        code,
        reason,
    )
    message = f"Facebook {page_id}/posts API error"
    if code is not None:
        message += f" (code {code})"
    return FacebookApiError(
        message,
        status_code=status_code,
        reason=str(reason) if reason is not None else None,
    )