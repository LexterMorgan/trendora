"""Regional YouTube mostPopular chart ingestion. Sibling of the M2A watchlist connector.

Chart-only channels are hydrated with channels.list and persisted from chart videos
only. playlistItems.list is never used here. search.list is not used.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from trendora.connectors.base import ChannelIngestionOutcome, IngestionResult
from trendora.connectors.youtube.client import YouTubeClient
from trendora.connectors.youtube.connector import ChannelStore, SqlAlchemyChannelStore
from trendora.connectors.youtube.exceptions import (
    ChannelIngestionError,
    YouTubeApiError,
    YouTubeConfigurationError,
    YouTubeHttpError,
    YouTubeResponseError,
)
from trendora.connectors.youtube.normalizer import NormalizedContentItem, normalize_channel
from trendora.connectors.youtube.schemas import ChannelResource, VideoCategoryResource, VideoResource
from trendora.reference import MARKET_IDS

logger = logging.getLogger("trendora.connectors.youtube.most_popular")

DEFAULT_MOST_POPULAR_MARKETS: tuple[str, ...] = ("ID", "TH", "MY", "SG", "VN", "PH")
DEFAULT_MAX_VIDEOS_PER_MARKET = 50

_FETCH_ERRORS = (
    YouTubeApiError,
    YouTubeHttpError,
    YouTubeResponseError,
    ChannelIngestionError,
)


class MostPopularDataSource(Protocol):
    def list_video_categories(self, region_code: str) -> list[VideoCategoryResource]: ...

    def list_most_popular_videos(self, region_code: str, *, max_videos: int) -> list[VideoResource]: ...

    def list_channels(self, channel_ids: Sequence[str]) -> list[ChannelResource]: ...


@dataclass
class _ChartObservation:
    video: VideoResource
    region_codes: list[str]
    chart_positions_by_region: dict[str, int]
    category_titles_by_region: dict[str, str]


def parse_region_codes(value: str | Sequence[str] | None) -> tuple[str, ...]:
    """Return unique SEA market codes in first-seen order.

    ``None`` selects the default six seeded markets. Unknown codes raise.
    """

    if value is None:
        return DEFAULT_MOST_POPULAR_MARKETS
    if isinstance(value, str):
        tokens = value.split(",")
    else:
        tokens = list(value)

    allowed = ", ".join(DEFAULT_MOST_POPULAR_MARKETS)
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in tokens:
        token = raw.strip()
        if not token:
            continue
        code = token.upper()
        if code not in MARKET_IDS:
            raise YouTubeConfigurationError(
                f"Unknown market code {token!r}. Allowed: {allowed}"
            )
        if code in seen:
            continue
        seen.add(code)
        ordered.append(code)
    if not ordered:
        raise YouTubeConfigurationError(
            f"At least one market code is required. Allowed: {allowed}"
        )
    return tuple(ordered)


def apply_most_popular_metadata(
    item: NormalizedContentItem,
    observation: _ChartObservation,
) -> NormalizedContentItem:
    """Attach merged chart-origin metadata without changing market_id."""

    metadata = dict(item.source_metadata)
    metadata["chart"] = "mostPopular"
    metadata["region_codes"] = list(observation.region_codes)
    titles = dict(observation.category_titles_by_region)
    if titles:
        first_region = observation.region_codes[0]
        metadata["category_title"] = titles.get(first_region) or next(iter(titles.values()))
        if len(set(titles.values())) > 1:
            metadata["category_titles_by_region"] = titles
    if observation.chart_positions_by_region:
        metadata["chart_positions_by_region"] = dict(observation.chart_positions_by_region)

    chart_snapshot_meta = {
        "chart": "mostPopular",
        "region_codes": list(observation.region_codes),
    }
    snapshots = tuple(
        replace(
            snapshot,
            source_metadata={**(snapshot.source_metadata or {}), **chart_snapshot_meta},
        )
        for snapshot in item.snapshots
    )
    return replace(item, source_metadata=metadata, snapshots=snapshots)


class MostPopularConnector:
    source_code = "youtube"

    def __init__(
        self,
        client: MostPopularDataSource,
        store: ChannelStore,
        *,
        region_codes: Sequence[str] | None = None,
        max_videos_per_market: int = DEFAULT_MAX_VIDEOS_PER_MARKET,
    ) -> None:
        self._client = client
        self._store = store
        self._region_codes = parse_region_codes(region_codes)
        if max_videos_per_market < 1:
            raise YouTubeConfigurationError("max videos per market must be >= 1")
        self._max_videos = max_videos_per_market

    def ingest(self, *, collected_at: datetime | None = None) -> IngestionResult:
        if collected_at is not None and collected_at.tzinfo is None:
            raise ValueError("collected_at must be timezone-aware")
        run_collected_at = collected_at or datetime.now(timezone.utc)

        logger.info(
            "youtube.most_popular.start markets=%s max_videos_per_market=%s",
            ",".join(self._region_codes),
            self._max_videos,
        )
        result = IngestionResult(source_code=self.source_code, watchlist_size=len(self._region_codes))
        observations = self._collect_observations(result)
        if not observations:
            logger.info("youtube.most_popular.complete no_chart_videos")
            return result

        channel_ids = _unique_channel_ids(observations)
        channels = self._client.list_channels(channel_ids)
        by_id = {channel.id: channel for channel in channels}
        grouped = _group_by_channel(observations)

        for channel_id in channel_ids:
            try:
                outcome = self._persist_channel(
                    channel_id,
                    by_id.get(channel_id),
                    grouped.get(channel_id, []),
                    run_collected_at,
                )
            except IntegrityError:
                logger.exception("youtube.most_popular.integrity_error channel_id=%s", channel_id)
                raise
            except SQLAlchemyError:
                logger.exception("youtube.most_popular.database_error channel_id=%s", channel_id)
                raise
            result.outcomes.append(outcome)
            if outcome.ok:
                logger.info(
                    "youtube.most_popular.channel_ok channel_id=%s videos=%s snapshots=%s",
                    channel_id,
                    outcome.content_items_upserted,
                    outcome.snapshots_inserted,
                )
            else:
                logger.error(
                    "youtube.most_popular.channel_failed channel_id=%s error=%s",
                    channel_id,
                    outcome.error,
                )

        logger.info(
            "youtube.most_popular.complete succeeded=%s failed=%s snapshots=%s",
            len(result.succeeded),
            len(result.failed),
            result.snapshots_inserted,
        )
        return result

    def _collect_observations(self, result: IngestionResult) -> dict[str, _ChartObservation]:
        observations: dict[str, _ChartObservation] = {}
        for region in self._region_codes:
            try:
                categories = {
                    category.id: (category.snippet.title or "").strip()
                    for category in self._client.list_video_categories(region)
                    if category.id and (category.snippet.title or "").strip()
                }
                videos = self._client.list_most_popular_videos(region, max_videos=self._max_videos)
            except _FETCH_ERRORS as exc:
                logger.error(
                    "youtube.most_popular.region_failed region=%s error=%s",
                    region,
                    exc,
                )
                result.outcomes.append(ChannelIngestionOutcome(external_id=region, error=str(exc)))
                continue

            logger.info(
                "youtube.most_popular.region_collected region=%s videos=%s categories=%s",
                region,
                len(videos),
                len(categories),
            )
            for position, video in enumerate(videos, start=1):
                _record_observation(observations, video, region=region, position=position, categories=categories)
        return observations

    def _persist_channel(
        self,
        channel_id: str,
        channel: ChannelResource | None,
        observations: Sequence[_ChartObservation],
        collected_at: datetime,
    ) -> ChannelIngestionOutcome:
        try:
            if channel is None:
                raise ChannelIngestionError(
                    f"channels.list did not return channel {channel_id}"
                )
            videos = [item.video for item in observations]
            bundle = normalize_channel(channel, videos, collected_at=collected_at)
            by_video_id = {item.video.id: item for item in observations}
            bundle = replace(
                bundle,
                content_items=tuple(
                    apply_most_popular_metadata(item, by_video_id[item.external_id])
                    for item in bundle.content_items
                    if item.external_id in by_video_id
                ),
            )
            persisted = self._store.persist(bundle)
        except _FETCH_ERRORS as exc:
            return ChannelIngestionOutcome(external_id=channel_id, error=str(exc))

        return ChannelIngestionOutcome(
            external_id=channel_id,
            publisher_created=persisted.publisher_created,
            publisher_updated=persisted.publisher_updated,
            content_items_upserted=persisted.content_items_upserted,
            snapshots_inserted=persisted.snapshots_inserted,
        )


def build_most_popular_connector(
    *,
    api_key: str,
    region_codes: Sequence[str] | None = None,
    max_videos_per_market: int = DEFAULT_MAX_VIDEOS_PER_MARKET,
    client: MostPopularDataSource | None = None,
    store: ChannelStore | None = None,
    http_client=None,
) -> MostPopularConnector:
    youtube_client: MostPopularDataSource
    if client is not None:
        youtube_client = client
    else:
        youtube_client = YouTubeClient(api_key, http_client=http_client)
    return MostPopularConnector(
        youtube_client,
        store or SqlAlchemyChannelStore(),
        region_codes=region_codes,
        max_videos_per_market=max_videos_per_market,
    )


def _record_observation(
    observations: dict[str, _ChartObservation],
    video: VideoResource,
    *,
    region: str,
    position: int,
    categories: Mapping[str, str],
) -> None:
    channel_id = (video.snippet.channel_id or "").strip()
    if not channel_id:
        logger.warning(
            "youtube.most_popular.missing_channel_id video_id=%s region=%s",
            video.id,
            region,
        )
        return

    category_id = video.snippet.category_id
    category_title = categories.get(category_id) if category_id else None
    existing = observations.get(video.id)
    if existing is None:
        titles = {region: category_title} if category_title else {}
        observations[video.id] = _ChartObservation(
            video=video,
            region_codes=[region],
            chart_positions_by_region={region: position},
            category_titles_by_region=titles,
        )
        return

    if region not in existing.region_codes:
        existing.region_codes.append(region)
    existing.chart_positions_by_region.setdefault(region, position)
    if category_title:
        existing.category_titles_by_region.setdefault(region, category_title)


def _unique_channel_ids(observations: Mapping[str, _ChartObservation]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for observation in observations.values():
        channel_id = (observation.video.snippet.channel_id or "").strip()
        if not channel_id or channel_id in seen:
            continue
        seen.add(channel_id)
        ordered.append(channel_id)
    return ordered


def _group_by_channel(observations: Mapping[str, _ChartObservation]) -> dict[str, list[_ChartObservation]]:
    grouped: dict[str, list[_ChartObservation]] = {}
    for observation in observations.values():
        channel_id = (observation.video.snippet.channel_id or "").strip()
        if not channel_id:
            continue
        grouped.setdefault(channel_id, []).append(observation)
    return grouped


__all__ = [
    "DEFAULT_MAX_VIDEOS_PER_MARKET",
    "DEFAULT_MOST_POPULAR_MARKETS",
    "MostPopularConnector",
    "MostPopularDataSource",
    "apply_most_popular_metadata",
    "build_most_popular_connector",
    "parse_region_codes",
]
