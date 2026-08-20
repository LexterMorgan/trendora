"""Manual GitHub ingestion. Not a scheduler."""

from __future__ import annotations

import argparse
import logging
import sys

from trendora.config import get_settings
from trendora.connectors.github.connector import (
    DEFAULT_MAX_ITEMS,
    build_github_connector,
    parse_repositories,
)
from trendora.connectors.github.exceptions import GitHubConfigurationError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m trendora.connectors.github",
        description="Ingest explicit public GitHub repositories into Trendora.",
    )
    parser.add_argument(
        "--repos",
        default=None,
        help="Comma-separated owner/repository identifiers. Overrides GITHUB_REPOSITORIES.",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=DEFAULT_MAX_ITEMS,
        help="Max repositories to fetch (default 50).",
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
    logger = logging.getLogger("trendora.connectors.github.cli")

    try:
        if args.repos is not None:
            repositories = parse_repositories(args.repos)
        else:
            repositories = parse_repositories(settings.github_repositories)
        if not repositories:
            raise GitHubConfigurationError(
                "At least one GitHub repository is required. Set GITHUB_REPOSITORIES "
                "or pass --repos owner/repository."
            )
        connector = build_github_connector(
            repositories=repositories,
            max_items=args.max_items,
            token=settings.github_token,
        )
    except GitHubConfigurationError as exc:
        logger.error("%s", exc)
        return 2

    result = connector.ingest()
    logger.info(
        "github.cli.summary repos=%s attempted=%s succeeded=%s failed=%s snapshots=%s",
        ",".join(repositories[: args.max_items] if args.max_items > 0 else repositories),
        result.watchlist_size,
        len(result.succeeded),
        len(result.failed),
        result.snapshots_inserted,
    )
    return 1 if result.failed else 0


if __name__ == "__main__":
    sys.exit(main())
