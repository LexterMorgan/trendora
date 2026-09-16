"""Web search research retrieval (M36A).

Thin adapter over ``SerperGateway``: one search per query, normalized to
``ResearchReference``. Public indexed content only — no engagement metrics, no
transcript, no derived metrics, no persistence. ``market_contexts`` stays empty
because the provider does not filter by region. ``published_at`` stays ``None``:
provider date strings are relative/ambiguous and are not parsed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from trendora.connectors.web_search import SearchResult
from trendora.connectors.web_search.serper_gateway import SerperGateway
from trendora.research.models import ResearchQuery, ResearchReference

WEB_SEARCH_SOURCE_CODE = "public_web"


@dataclass(frozen=True, slots=True)
class WebSearchCollectedBatch:
    """Raw search results plus the single timezone-aware collection timestamp."""

    results: tuple[SearchResult, ...]
    collected_at: datetime


class WebSearchResearchRetriever:
    """One query, one search call, normalized references."""

    def __init__(self, gateway: SerperGateway) -> None:
        self._gateway = gateway

    def collect(
        self,
        query: ResearchQuery,
        *,
        collected_at: datetime | None = None,
    ) -> WebSearchCollectedBatch:
        at = collected_at if collected_at is not None else datetime.now(timezone.utc)
        if at.utcoffset() is None:
            raise ValueError("collected_at must be timezone-aware")
        results = self._gateway.search(query.topic, limit=query.result_limit)
        return WebSearchCollectedBatch(results=tuple(results), collected_at=at)

    def normalize(self, collected: object) -> tuple[ResearchReference, ...]:
        if not isinstance(collected, WebSearchCollectedBatch):
            raise TypeError("collected must be a WebSearchCollectedBatch")
        references: list[ResearchReference] = []
        for rank, result in enumerate(collected.results, start=1):
            if not result.url:
                continue
            references.append(
                ResearchReference(
                    source_code=WEB_SEARCH_SOURCE_CODE,
                    content_external_id=result.url,
                    collected_at=collected.collected_at,
                    url=result.url,
                    title=result.title or None,
                    description=result.snippet or None,
                    published_at=None,
                    channel_external_id=None,
                    channel_title=result.domain or None,
                    market_contexts=(),
                    source_rank=rank,
                )
            )
        return tuple(references)
