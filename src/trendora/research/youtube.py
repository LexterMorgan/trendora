"""YouTube-first research retrieval (M14).

Orchestrates public discovery and enrichment through the existing YouTube
client and produces normalized in-memory ``ResearchReference`` objects.

- discovery: ``search.list`` (type=video, order=relevance) for the query's
  topic, market region, and date window, with deterministic pagination.
- enrichment: the existing ``videos.list`` path (parts snippet/contentDetails/
  statistics), reusing the client's tested chunked/validated method.
- normalization: official metadata + public statistics only. No derived
  metrics, no scores, no persistence.

Enrichment choice: the repository's existing ``videos.list`` implementation
already returns the snippet/statistics fields a reference needs and is the
tested path used by M2A/M2B. YouTube's newer ``videos.batchGetStats``
(separate granular quota bucket, 1 unit/call) exists and could be a future
quota optimization, but M14 keeps enrichment on the established videos.list
path to avoid introducing an untested endpoint shape. This is a documented
engineering choice, not a claim that batchGetStats does not exist.

Market semantics: ``ResearchQuery.market`` becomes YouTube ``regionCode``.
The reference preserves ``market_context`` (the requested market) and
``market_basis`` (``youtube_region_availability``). regionCode is regional
availability/viewability only; no creator/publisher/content-origin country
and no language is ever inferred from it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from trendora.connectors.youtube.client import YouTubeClient
from trendora.connectors.youtube.normalizer import parse_count, parse_youtube_datetime
from trendora.connectors.youtube.schemas import SearchResource, VideoResource

from trendora.research.models import (
    MarketBasis,
    ResearchMetrics,
    ResearchQuery,
    ResearchReference,
)

YOUTUBE_SOURCE_CODE = "youtube"


@dataclass(frozen=True, kw_only=True)
class _CollectedVideo:
    """Raw collected/enriched data for one video, before reference mapping."""

    video_id: str
    title: str | None
    description: str | None
    channel_external_id: str | None
    channel_title: str | None
    published_at: datetime | None
    source_rank: int
    market_context: str
    statistics: ResearchMetrics
    collected_at: datetime


class YouTubeResearchRetriever:
    """Retrieves and normalizes YouTube research references for a query.

    In-memory only: nothing is persisted. Uses the existing YouTube client;
    no new network path.
    """

    def __init__(self, client: YouTubeClient) -> None:
        self._client = client

    def collect(
        self,
        query: ResearchQuery,
        *,
        collected_at: datetime | None = None,
    ) -> tuple[_CollectedVideo, ...]:
        """Search + enrich for a query; returns raw collected videos.

        Source rank is assigned from the deduplicated source search order
        (first unique result = rank 1), so pagination and deduplication do
        not create gaps and enrichment never reorders references.
        """
        at = collected_at if collected_at is not None else datetime.now(timezone.utc)
        if at.tzinfo is None:
            raise ValueError("collected_at must be timezone-aware")
        search_results = self._client.search_videos(
            query=query.topic,
            region_code=query.market,
            published_after=_to_rfc3339(query.date_from),
            published_before=_to_rfc3339(query.date_to + timedelta(days=1)),
            limit=query.result_limit,
        )
        video_ids = [result.video_id for result in search_results if result.video_id is not None]
        if not video_ids:
            return ()
        enriched = self._client.list_videos(video_ids)
        by_id = {video.id: video for video in enriched}
        collected: list[_CollectedVideo] = []
        for rank, result in enumerate(search_results, start=1):
            video_id = result.video_id
            if video_id is None:
                continue
            collected.append(
                _build_collected(
                    result,
                    by_id.get(video_id),
                    collected_at=at,
                    source_rank=rank,
                    market_context=query.market,
                )
            )
        return tuple(collected)

    def normalize(
        self,
        collected: Sequence[_CollectedVideo],
    ) -> tuple[ResearchReference, ...]:
        """Map raw collected videos to normalized research references."""
        return tuple(
            ResearchReference(
                source_code=YOUTUBE_SOURCE_CODE,
                content_external_id=item.video_id,
                collected_at=item.collected_at,
                url=f"https://www.youtube.com/watch?v={item.video_id}",
                title=item.title,
                description=item.description,
                published_at=item.published_at,
                channel_external_id=item.channel_external_id,
                channel_title=item.channel_title,
                market_context=item.market_context,
                market_basis=MarketBasis.YOUTUBE_REGION_AVAILABILITY,
                source_rank=item.source_rank,
                metrics=item.statistics,
            )
            for item in collected
        )


def _build_collected(
    result: SearchResource,
    video: VideoResource | None,
    *,
    collected_at: datetime,
    source_rank: int,
    market_context: str,
) -> _CollectedVideo:
    video_id = result.video_id
    if video_id is None:
        raise ValueError("cannot collect a search result without a video id")
    if video is not None:
        title = video.snippet.title or result.snippet.title
        description = video.snippet.description or result.snippet.description
        channel = video.snippet.channel_id or result.snippet.channel_id
        published_at = parse_youtube_datetime(video.snippet.published_at) or parse_youtube_datetime(
            result.snippet.published_at
        )
        statistics = _parse_metrics(video.statistics)
    else:
        title = result.snippet.title
        description = result.snippet.description
        channel = result.snippet.channel_id
        published_at = parse_youtube_datetime(result.snippet.published_at)
        statistics = _parse_metrics({})
    return _CollectedVideo(
        video_id=video_id,
        title=title,
        description=description,
        channel_external_id=channel,
        channel_title=result.snippet.channel_title,
        published_at=published_at,
        source_rank=source_rank,
        statistics=statistics,
        collected_at=collected_at,
        market_context=market_context,
    )


def _parse_metrics(statistics: Mapping[str, Any]) -> ResearchMetrics:
    """Parse only official YouTube video statistic fields.

    Missing statistics are explicit ``None`` (never zero and never derived).
    """
    return ResearchMetrics(
        view_count=parse_count(statistics.get("viewCount")),
        like_count=parse_count(statistics.get("likeCount")),
        comment_count=parse_count(statistics.get("commentCount")),
    )


def _to_rfc3339(value: date) -> str:
    """Render a calendar date as a UTC RFC 3339 timestamp at midnight."""
    return f"{value.isoformat()}T00:00:00Z"
