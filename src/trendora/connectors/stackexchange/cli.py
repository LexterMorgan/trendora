"""Manual Stack Exchange ingestion. Not a scheduler."""

from __future__ import annotations

import argparse
import logging
import sys

from trendora.config import get_settings
from trendora.connectors.stackexchange.connector import (
    DEFAULT_MAX_ITEMS_PER_SITE,
    build_stackexchange_connector,
    parse_sites,
    parse_tags,
)
from trendora.connectors.stackexchange.exceptions import StackExchangeConfigurationError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m trendora.connectors.stackexchange",
        description="Ingest public Stack Exchange questions into Trendora.",
    )
    parser.add_argument(
        "--sites",
        default=None,
        help="Comma-separated site slugs (default stackoverflow,datascience).",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=DEFAULT_MAX_ITEMS_PER_SITE,
        help="Max questions to fetch per site (default 50).",
    )
    parser.add_argument(
        "--tags",
        default=None,
        help="Optional comma-separated tags (max 5). Sent as tagged= with semicolons.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logger = logging.getLogger("trendora.connectors.stackexchange.cli")

    try:
        sites = parse_sites(args.sites)
        tags = parse_tags(args.tags)
        connector = build_stackexchange_connector(
            sites=sites,
            max_items=args.max_items,
            tags=tags,
            api_key=settings.stackexchange_api_key,
        )
    except StackExchangeConfigurationError as exc:
        logger.error("%s", exc)
        return 2

    result = connector.ingest()
    logger.info(
        "stackexchange.cli.summary sites=%s attempted=%s succeeded=%s failed=%s snapshots=%s",
        ",".join(sites),
        result.watchlist_size,
        len(result.succeeded),
        len(result.failed),
        result.snapshots_inserted,
    )
    return 1 if result.failed else 0


if __name__ == "__main__":
    sys.exit(main())
