"""Manual Hacker News ingestion. Not a scheduler."""

from __future__ import annotations

import argparse
import logging
import sys

from trendora.config import get_settings
from trendora.connectors.hackernews.connector import (
    DEFAULT_MAX_ITEMS_PER_FEED,
    build_hackernews_connector,
    parse_feeds,
)
from trendora.connectors.hackernews.exceptions import HackerNewsConfigurationError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m trendora.connectors.hackernews",
        description="Ingest Hacker News top/new/best stories into Trendora.",
    )
    parser.add_argument(
        "--feeds",
        default=None,
        help="Comma-separated feeds (default topstories,newstories,beststories).",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=DEFAULT_MAX_ITEMS_PER_FEED,
        help="Max items to fetch per feed (default 50).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger = logging.getLogger("trendora.connectors.hackernews.cli")

    try:
        feeds = parse_feeds(args.feeds)
        connector = build_hackernews_connector(feeds=feeds, max_items=args.max_items)
    except HackerNewsConfigurationError as exc:
        logger.error("%s", exc)
        return 2

    result = connector.ingest()
    logger.info(
        "hackernews.cli.summary feeds=%s attempted=%s succeeded=%s failed=%s snapshots=%s",
        ",".join(feeds),
        result.watchlist_size,
        len(result.succeeded),
        len(result.failed),
        result.snapshots_inserted,
    )
    return 1 if result.failed else 0


if __name__ == "__main__":
    sys.exit(main())
