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

# Simplified (topic-first) requests are global by default: no explicit country
# restriction, not comprehensive worldwide coverage. They also run global
# discovery across the two configured topic-search sources.
DEFAULT_MARKETS: tuple[str, ...] = ()
DEFAULT_SIMPLIFIED_SOURCES: tuple[str, ...] = ("youtube", "public_web")
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

    if market is not None and markets is not None:
        raise ResearchValidationError("provide either 'market' or 'markets', not both")

    # An explicit market (singular or plural) is a regional request. No market
    # supplied — omitted or an empty list — is a **global** request: no country
    # restriction. Regional requests keep their existing behavior and default
    # sources; global requests default to the two configured topic-search
    # sources.
    regional = market is not None or bool(markets)

    default_from, default_to = _default_date_window()
    if markets is None and market is not None:
        markets = [market]
    if not regional:
        markets = list(DEFAULT_MARKETS)
    if date_from is None:
        date_from = default_from
    if date_to is None:
        date_to = default_to

    sources = request.get("sources")
    if sources is None:
        sources = DEFAULT_SOURCE_CODES if regional else DEFAULT_SIMPLIFIED_SOURCES

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
