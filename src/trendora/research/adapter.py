"""Contract adaptation layer for flexible research requests (M35A).

Accepts both full contracts and simplified requests, mapping the latter to
complete contracts using sensible defaults. Maintains 100% backward
compatibility with existing API contracts: this layer runs *before* the
service executes anything and never weakens domain validation — the resulting
``ResearchQuery`` is still fully validated (markets, dates, sources, limits,
citation grounding downstream).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from trendora.research.models import (
    DEFAULT_RESULT_LIMIT,
    DEFAULT_SOURCE_CODES,
    ResearchQuery,
    ResearchValidationError,
)

DEFAULT_MARKETS: tuple[str, ...] = ("SG",)
DEFAULT_DATE_WINDOW_DAYS = 30


def _default_date_window() -> tuple[date, date]:
    """Last 30 days (inclusive), ending today."""
    today = date.today()
    return (today - timedelta(days=DEFAULT_DATE_WINDOW_DAYS - 1), today)


def adapt_research_request(request: dict[str, Any]) -> ResearchQuery:
    """Adapt a request dict to a validated ``ResearchQuery`` instance.

    Supports two modes:

    1. Full contract: all fields provided (unchanged behavior).
    2. Simplified contract: only ``topic`` required; ``markets``, date window,
       sources, and ``result_limit`` are filled from defaults.

    Explicitly provided values always win. Raises ``ResearchValidationError``
    when ``topic`` is missing/blank or any downstream value is invalid.
    """
    topic = request.get("topic")
    if not isinstance(topic, str) or not topic.strip():
        raise ResearchValidationError("topic is required")

    markets = request.get("markets")
    market = request.get("market")
    date_from = request.get("date_from")
    date_to = request.get("date_to")

    # Preserve the M26C contract for full/partial requests: exactly one of
    # ``market`` / ``markets`` must be supplied when a date window is given.
    # Simplified mode is a topic-first request with no explicit market *and* no
    # explicit date fields, which is completed from defaults below.
    market_supplied = markets is not None or market is not None
    dates_supplied = date_from is not None or date_to is not None
    simplified = not market_supplied and not dates_supplied

    if market is not None and markets is not None:
        raise ResearchValidationError("provide either 'market' or 'markets', not both")

    default_from, default_to = _default_date_window()
    if simplified:
        markets = list(DEFAULT_MARKETS)
        date_from = default_from
        date_to = default_to
    else:
        if markets is None and market is not None:
            markets = [market]
        if date_from is None:
            date_from = default_from
        if date_to is None:
            date_to = default_to

    sources = request.get("sources")
    if sources is None:
        sources = DEFAULT_SOURCE_CODES

    result_limit = request.get("result_limit")
    if result_limit is None:
        result_limit = DEFAULT_RESULT_LIMIT

    return ResearchQuery(
        topic=topic,
        markets=tuple(markets) if markets is not None else (),
        date_from=date_from,
        date_to=date_to,
        source_codes=tuple(sources),
        result_limit=result_limit,
        facebook_page_id=request.get("facebook_page_id"),
        market=None,
    )
