"""Shared Facebook Page identifier normalization (M25C).

Single source of truth for Page-ID safety used by both the HTTP client
(M25A) and the research query (M25C). ``None`` means "not supplied"; any
supplied blank or unsafe identifier raises ``ValueError`` with a sanitized
message (never the raw identifier), which each boundary converts to its own
error type.
"""

from __future__ import annotations

import re

PAGE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def normalize_page_id(page_id: str | None) -> str | None:
    """Return a normalized Page ID, or ``None`` when not supplied.

    Raises ``ValueError`` for a supplied blank or unsafe identifier.
    """
    if page_id is None:
        return None
    page = page_id.strip()
    if (
        not page
        or not PAGE_ID_RE.match(page)
        or ".." in page
        or page.startswith(".")
        or page.endswith(".")
    ):
        raise ValueError("unsafe facebook page id")
    return page