"""Orchestrate YouTube fetch → normalize → persist for a curated watchlist."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from trendora.connectors.base import ChannelIngestionOutcome, IngestionResult
from trendora.connectors.youtube.client import YouTubeClient
from trendora.connectors.youtube.exceptions import (
    ChannelIngestionError,
    EmptyWatchlistError,
    YouTubeApiError,
    YouTubeConfigurationError,
    YouTubeConnectorError,
    YouTubeHttpError,
    YouTubeResponseError,
)
from trendora.connectors.youtube.normalizer import ChannelIngestionBundle, normalize_channel
from trendora.connectors.youtube.persistence import ChannelPersistResult, persist_channel
from trendora.connectors.youtube.schemas import ChannelResource
from trendora.connectors.youtube.watchlist import parse_channel_ids
from trendora.db.session import get_session_factory

logger = logging.getLogger("trendora.connectors.youtube")

_FETCH_ERRORS = (
    YouTubeApiError,
    YouTubeHttpError,
    YouTubeResponseError,
    ChannelIngestionError,
)


class YouTubeDataSource(Protocol):
    def list_channels(self, channel_ids: Sequence[str]) -> list[ChannelResource]: ...

    def list_upload_video_ids(self, uploads_playlist_id: str, *, limit: int) -> list[str]: ...

    def list_videos(self, video_ids: Sequence[str]) -> list: ...


class ChannelStore(Protocol):
    def persist(self, bundle: ChannelIngestionBundle) -> ChannelPersistResult: ...


class SqlAlchemyChannelStore:
    """One transaction per channel. Does not span the whole watchlist."""

    def __init__(self, session_factory: sessionmaker[Session] | None = None) -> None:
        self._session_factory = session_factory or get_session_factory()

    def persist(self, bundle: ChannelIngestionBundle) -> ChannelPersistResult:
        session = self._session_factory()
        try:
            result = persist_channel(session, bundle)
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


class YouTubeConnector:
    source_code = "youtube"

    def __init__(
        self,
        client: YouTubeDataSource,
        store: ChannelStore,
        *,
        watchlist: Sequence[str],
        max_videos_per_channel: int = 50,
    ) -> None:
        self._client = client
        self._store = store
        self._watchlist = parse_channel_ids(watchlist)
        if max_videos_per_channel < 1:
            raise YouTubeConfigurationError("YOUTUBE_MAX_VIDEOS_PER_CHANNEL must be >= 1")
        self._max_videos = max_videos_per_channel

    def ingest(self, *, collected_at: datetime | None = None) -> IngestionResult:
        if not self._watchlist:
            raise EmptyWatchlistError(
                "YOUTUBE_CHANNEL_IDS is empty. Set a comma-separated list of YouTube "
                "channel IDs (UC…) before running ingestion."
            )
        if collected_at is not None and collected_at.tzinfo is None:
            raise ValueError("collected_at must be timezone-aware")

        logger.info(
            "youtube.ingest.start watchlist_size=%s max_videos_per_channel=%s",
            len(self._watchlist),
            self._max_videos,
        )
        channels = self._client.list_channels(self._watchlist)
        by_id = {channel.id: channel for channel in channels}

        result = IngestionResult(source_code=self.source_code, watchlist_size=len(self._watchlist))
        for channel_id in self._watchlist:
            channel_collected_at = collected_at or datetime.now(timezone.utc)
            try:
                outcome = self._ingest_one(channel_id, by_id.get(channel_id), channel_collected_at)
            except IntegrityError:
                logger.exception("youtube.ingest.integrity_error channel_id=%s", channel_id)
                raise
            except SQLAlchemyError:
                logger.exception("youtube.ingest.database_error channel_id=%s", channel_id)
                raise
            result.outcomes.append(outcome)
            if outcome.ok:
                logger.info(
                    "youtube.ingest.channel_ok channel_id=%s videos=%s snapshots=%s",
                    channel_id,
                    outcome.content_items_upserted,
                    outcome.snapshots_inserted,
                )
            else:
                logger.error(
                    "youtube.ingest.channel_failed channel_id=%s error=%s",
                    channel_id,
                    outcome.error,
                )

        logger.info(
            "youtube.ingest.complete succeeded=%s failed=%s snapshots=%s",
            len(result.succeeded),
            len(result.failed),
            result.snapshots_inserted,
        )
        return result

    def _ingest_one(
        self,
        channel_id: str,
        channel: ChannelResource | None,
        collected_at: datetime,
    ) -> ChannelIngestionOutcome:
        try:
            if channel is None:
                raise ChannelIngestionError(
                    f"channels.list did not return channel {channel_id}"
                )
            logger.info("youtube.channel.fetch channel_id=%s", channel_id)
            uploads = channel.uploads_playlist_id
            if not uploads:
                raise ChannelIngestionError(
                    f"channel {channel_id} has no uploads playlist in contentDetails"
                )
            video_ids = self._client.list_upload_video_ids(uploads, limit=self._max_videos)
            logger.info(
                "youtube.videos.discovered channel_id=%s count=%s",
                channel_id,
                len(video_ids),
            )
            videos = self._client.list_videos(video_ids) if video_ids else []
            logger.info(
                "youtube.videos.hydrated channel_id=%s count=%s",
                channel_id,
                len(videos),
            )
            bundle = normalize_channel(channel, videos, collected_at=collected_at)
            logger.info(
                "youtube.normalize.done channel_id=%s videos=%s publisher_metrics=%s",
                channel_id,
                len(bundle.content_items),
                len(bundle.publisher_snapshots),
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


def build_youtube_connector(
    *,
    api_key: str,
    watchlist: Sequence[str],
    max_videos_per_channel: int = 50,
    client: YouTubeDataSource | None = None,
    store: ChannelStore | None = None,
    http_client=None,
) -> YouTubeConnector:
    youtube_client: YouTubeDataSource
    if client is not None:
        youtube_client = client
    else:
        youtube_client = YouTubeClient(api_key, http_client=http_client)
    return YouTubeConnector(
        youtube_client,
        store or SqlAlchemyChannelStore(),
        watchlist=watchlist,
        max_videos_per_channel=max_videos_per_channel,
    )


__all__ = [
    "ChannelStore",
    "SqlAlchemyChannelStore",
    "YouTubeConnector",
    "YouTubeDataSource",
    "YouTubeConnectorError",
    "build_youtube_connector",
]
