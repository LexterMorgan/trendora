"""Stack Exchange API v2.3 HTTP client. No SQLAlchemy. No normalization."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from typing import Any

import httpx
from pydantic import ValidationError

from trendora.connectors.stackexchange.exceptions import (
    StackExchangeApiError,
    StackExchangeHttpError,
    StackExchangeResponseError,
)
from trendora.connectors.stackexchange.schemas import QuestionResource, QuestionsWrapper

logger = logging.getLogger("trendora.connectors.stackexchange.client")

STACKEXCHANGE_API_BASE = "https://api.stackexchange.com/2.3"
_USER_AGENT = "Trendora/0.0.1"
_MAX_PAGESIZE = 100
_SORT = "activity"
_ORDER = "desc"


class StackExchangeClient:
    """HTTPS client for official Stack Exchange /questions reads.

    Search, answers, users, comments, and write operations are not implemented.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        http_client: httpx.Client | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        key = (api_key or "").strip()
        self._api_key = key or None
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client(
            timeout=httpx.Timeout(20.0, connect=10.0),
            headers={"User-Agent": _USER_AGENT},
        )
        self._sleep = sleeper or time.sleep
        self._seen_requests: set[tuple[str, int, str, str, str]] = set()
        self._pending_backoff = 0

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> StackExchangeClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def list_questions(
        self,
        site: str,
        *,
        max_items: int,
        tags: Sequence[str] = (),
    ) -> list[QuestionResource]:
        if max_items < 1:
            return []

        tagged = ";".join(tags) if tags else ""
        collected: list[QuestionResource] = []
        page = 1
        while len(collected) < max_items:
            remaining = max_items - len(collected)
            pagesize = min(_MAX_PAGESIZE, remaining)
            request_key = (site, page, _SORT, _ORDER, tagged)
            if request_key in self._seen_requests:
                logger.warning(
                    "stackexchange.api.duplicate_skipped site=%s page=%s",
                    site,
                    page,
                )
                break
            self._seen_requests.add(request_key)

            if self._pending_backoff > 0:
                self._sleep(self._pending_backoff)
                self._pending_backoff = 0

            wrapper = self._get_questions(
                site=site,
                page=page,
                pagesize=pagesize,
                tagged=tagged,
            )
            backoff = _positive_int(wrapper.backoff)
            if backoff:
                self._pending_backoff = backoff

            items = wrapper.items if isinstance(wrapper.items, list) else []
            logger.info(
                "stackexchange.page site=%s page=%s items=%s has_more=%s max_items=%s",
                site,
                page,
                len(items),
                wrapper.has_more,
                max_items,
            )
            for raw in items:
                question = _parse_question(raw)
                if question is None:
                    continue
                collected.append(question)
                if len(collected) >= max_items:
                    break
            if len(collected) >= max_items or not wrapper.has_more:
                break
            page += 1
        return collected[:max_items]

    def _get_questions(
        self,
        *,
        site: str,
        page: int,
        pagesize: int,
        tagged: str,
    ) -> QuestionsWrapper:
        params: dict[str, str | int] = {
            "site": site,
            "sort": _SORT,
            "order": _ORDER,
            "page": page,
            "pagesize": pagesize,
        }
        if tagged:
            params["tagged"] = tagged
        if self._api_key:
            params["key"] = self._api_key

        logger.info(
            "stackexchange.api.request site=%s page=%s pagesize=%s tagged=%s",
            site,
            page,
            pagesize,
            tagged or "",
        )
        try:
            response = self._http.get(f"{STACKEXCHANGE_API_BASE}/questions", params=params)
        except httpx.HTTPError as exc:
            logger.exception(
                "stackexchange.api.http_failure site=%s page=%s error_type=%s",
                site,
                page,
                type(exc).__name__,
            )
            raise StackExchangeHttpError(
                f"Stack Exchange HTTP request failed for /questions site={site}"
            ) from exc

        try:
            decoded = response.json()
        except ValueError:
            decoded = None

        if isinstance(decoded, dict) and decoded.get("error_id") is not None:
            raise _api_error_from_payload(decoded, status_code=response.status_code)

        if response.status_code >= 400:
            logger.error(
                "stackexchange.api.http_error site=%s page=%s status=%s",
                site,
                page,
                response.status_code,
            )
            raise StackExchangeHttpError(
                f"Stack Exchange /questions failed with HTTP {response.status_code}",
                status_code=response.status_code,
            )

        if decoded is None:
            raise StackExchangeResponseError("Stack Exchange /questions returned non-JSON")

        return _parse_wrapper(decoded)


def _parse_wrapper(decoded: object) -> QuestionsWrapper:
    if not isinstance(decoded, dict):
        raise StackExchangeResponseError("Stack Exchange /questions returned non-object JSON")
    items = decoded.get("items")
    if items is None:
        items = []
    if not isinstance(items, list):
        raise StackExchangeResponseError("Stack Exchange response 'items' was not a list")
    try:
        wrapper = QuestionsWrapper.model_validate({**decoded, "items": items})
    except ValidationError as exc:
        raise StackExchangeResponseError("Stack Exchange /questions wrapper was malformed") from exc
    if wrapper.quota_remaining is not None or wrapper.quota_max is not None:
        logger.info(
            "stackexchange.api.quota remaining=%s max=%s",
            wrapper.quota_remaining,
            wrapper.quota_max,
        )
    return wrapper


def _parse_question(raw: object) -> QuestionResource | None:
    if not isinstance(raw, dict):
        logger.warning("stackexchange.question.invalid_resource skipped malformed item")
        return None
    try:
        question = QuestionResource.model_validate(raw)
    except ValidationError:
        logger.warning("stackexchange.question.invalid_resource skipped malformed item")
        return None
    if question.question_id < 1:
        logger.warning("stackexchange.question.invalid_resource skipped malformed item")
        return None
    return question


def _api_error_from_payload(payload: dict[str, Any], *, status_code: int) -> StackExchangeApiError:
    error_id = payload.get("error_id") if isinstance(payload.get("error_id"), int) else None
    error_name = payload.get("error_name") if isinstance(payload.get("error_name"), str) else None
    message = payload.get("error_message")
    if not isinstance(message, str) or not message.strip():
        message = "Stack Exchange API error"
    logger.error(
        "stackexchange.api.error error_id=%s error_name=%s status=%s",
        error_id,
        error_name,
        status_code,
    )
    return StackExchangeApiError(
        message.strip(),
        error_id=error_id,
        error_name=error_name,
        status_code=status_code,
    )


def _positive_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value if value > 0 else 0
