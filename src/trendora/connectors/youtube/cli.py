"""Manual YouTube watchlist ingestion. Not a scheduler."""

from __future__ import annotations

import argparse
import logging
import sys

from trendora.config import get_settings
from trendora.connectors.youtube.connector import build_youtube_connector
from trendora.connectors.youtube.exceptions import EmptyWatchlistError, YouTubeConfigurationError
from trendora.connectors.youtube.watchlist import parse_channel_ids


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m trendora.connectors.youtube",
        description="Ingest a curated YouTube channel watchlist into Trendora.",
    )
    parser.add_argument(
        "--channel-ids",
        default=None,
        help="Comma-separated UC… channel IDs (overrides YOUTUBE_CHANNEL_IDS).",
    )
    parser.add_argument(
        "--max-videos",
        type=int,
        default=None,
        help="Max uploads to fetch per channel (overrides YOUTUBE_MAX_VIDEOS_PER_CHANNEL).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger = logging.getLogger("trendora.connectors.youtube.cli")

    api_key = settings.youtube_api_key
    if not api_key:
        logger.error(
            "YOUTUBE_API_KEY is not set. Copy .env.example to .env and add a YouTube Data API v3 key."
        )
        return 2

    raw_ids = args.channel_ids if args.channel_ids is not None else settings.youtube_channel_ids
    try:
        watchlist = parse_channel_ids(raw_ids)
    except YouTubeConfigurationError as exc:
        logger.error("%s", exc)
        return 2

    max_videos = args.max_videos if args.max_videos is not None else settings.youtube_max_videos_per_channel
    connector = build_youtube_connector(
        api_key=api_key,
        watchlist=watchlist,
        max_videos_per_channel=max_videos,
    )
    try:
        result = connector.ingest()
    except EmptyWatchlistError as exc:
        logger.error("%s", exc)
        return 2

    logger.info(
        "youtube.cli.summary watchlist=%s succeeded=%s failed=%s videos=%s snapshots=%s",
        result.watchlist_size,
        len(result.succeeded),
        len(result.failed),
        result.content_items_upserted,
        result.snapshots_inserted,
    )
    return 1 if result.failed else 0


if __name__ == "__main__":
    sys.exit(main())
