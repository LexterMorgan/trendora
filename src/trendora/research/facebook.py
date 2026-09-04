"""Facebook research retriever (M25C).

Thin adapter: reads the validated ``query.facebook_page_id``, calls the
injected M25A client once with inclusive dates and result limit, captures one
timezone-aware UTC ``collected_at``, and maps posts to references via M25B.
No topic filtering, market inference, search, ranking, scoring, retry, or
persistence. Never owns or closes the injected client.

Connector imports are lazy / type-only to avoid a module cycle during
research package init.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from trendora.connectors.facebook.client import FacebookPublicClient
    from trendora.connectors.facebook.schemas import FacebookPostResource

from trendora.research.models import ResearchQuery, ResearchReference


@dataclass(frozen=True, slots=True)
class FacebookCollectedBatch:
    """Raw posts plus the single timezone-aware collection timestamp."""

    posts: tuple["FacebookPostResource", ...]
    collected_at: datetime


class FacebookResearchRetriever:
    """One explicit Facebook Page, one call, normalized references."""

    def __init__(self, client: "FacebookPublicClient") -> None:
        self._client = client

    def collect(
        self,
        query: ResearchQuery,
        *,
        collected_at: datetime | None = None,
    ) -> "FacebookCollectedBatch":
        at = collected_at if collected_at is not None else datetime.now(timezone.utc)
        if at.utcoffset() is None:
            raise ValueError("collected_at must be timezone-aware")
        page_id = query.facebook_page_id
        if page_id is None:
            raise ValueError(
                "facebook research requires a nonblank facebook_page_id"
            )
        posts = self._client.list_page_posts(
            page_id,
            date_from=query.date_from,
            date_to=query.date_to,
            limit=query.result_limit,
        )
        return FacebookCollectedBatch(posts=posts, collected_at=at)

    def normalize(
        self,
        collected: object,
    ) -> tuple[ResearchReference, ...]:
        from trendora.connectors.facebook.normalizer import normalize_facebook_posts

        if not isinstance(collected, FacebookCollectedBatch):
            raise TypeError("collected must be a FacebookCollectedBatch")
        return normalize_facebook_posts(
            collected.posts,
            collected_at=collected.collected_at,
        )
