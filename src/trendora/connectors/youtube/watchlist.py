"""Parse curated YouTube channel IDs from configuration.

Handles are rejected. Discovery is out of scope for M2A.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from trendora.connectors.youtube.exceptions import InvalidYouTubeWatchlistError

# Standard YouTube channel IDs are 24 characters starting with "UC".
_CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")


def parse_channel_ids(value: str | Sequence[str] | None) -> tuple[str, ...]:
    """Return unique channel IDs in first-seen order.

    Empty input yields an empty tuple. Completely empty comma slots (trailing
    commas) are ignored. Any non-empty invalid token raises.
    """

    if value is None:
        return ()
    if isinstance(value, str):
        tokens = value.split(",")
    else:
        tokens = list(value)

    seen: set[str] = set()
    ordered: list[str] = []
    for raw in tokens:
        token = raw.strip()
        if not token:
            continue
        if not _CHANNEL_ID_RE.fullmatch(token):
            raise InvalidYouTubeWatchlistError(
                "YOUTUBE_CHANNEL_IDS entries must be 24-character channel IDs "
                f"starting with 'UC' (not handles or URLs). Invalid value: {token!r}"
            )
        if token in seen:
            continue
        seen.add(token)
        ordered.append(token)
    return tuple(ordered)
