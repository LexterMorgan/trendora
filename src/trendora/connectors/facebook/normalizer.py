"""Normalize Facebook public Page posts into Trendora research references (M25B).

Pure mapping from ``FacebookPostResource`` to ``ResearchReference``. Truthful
only: title stays ``None`` (never invented from the message), description is
the exact source message, market/channel fields stay ``None``, reaction counts
are reactions (never likes). Facebook remains isolated and is not exposed as a
research source yet.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from urllib.parse import urlsplit

from trendora.connectors.facebook.exceptions import (
    FacebookConfigurationError,
    FacebookResponseError,
)
from trendora.connectors.facebook.schemas import FacebookPostResource
from trendora.research.models import ResearchMetrics, ResearchReference

FACEBOOK_SOURCE_CODE = "facebook"


def normalize_facebook_posts(
    posts: Sequence[FacebookPostResource],
    *,
    collected_at: datetime,
) -> tuple[ResearchReference, ...]:
    """Map posts to references, preserving source order with 1-based ranks."""
    if collected_at is None or collected_at.utcoffset() is None:
        raise FacebookConfigurationError("collected_at must be timezone-aware")
    seen: set[str] = set()
    references: list[ResearchReference] = []
    for rank, post in enumerate(posts, start=1):
        post_id = post.id.strip()
        if not post_id:
            raise FacebookResponseError("Facebook post id must not be blank")
        if post_id in seen:
            raise FacebookResponseError(f"duplicate Facebook post id: {post_id}")
        seen.add(post_id)
        url = _valid_permalink(post.permalink_url)
        published_at = _parse_created_time(post.created_time)
        references.append(
            ResearchReference(
                source_code=FACEBOOK_SOURCE_CODE,
                content_external_id=post_id,
                collected_at=collected_at,
                url=url,
                title=None,
                description=post.message,
                published_at=published_at,
                channel_external_id=None,
                channel_title=None,
                market_context=None,
                market_basis=None,
                source_rank=rank,
                metrics=_to_metrics(post),
            )
        )
    return tuple(references)


def _to_metrics(post: FacebookPostResource) -> ResearchMetrics:
    shares = post.shares
    reactions = post.reactions
    comments = post.comments
    return ResearchMetrics(
        view_count=None,
        like_count=None,
        comment_count=comments.summary.total_count if comments and comments.summary else None,
        reaction_count=reactions.summary.total_count if reactions and reactions.summary else None,
        share_count=shares.count if shares else None,
    )


def _valid_permalink(value: str | None) -> str:
    if value is None:
        raise FacebookResponseError("Facebook post is missing an original permalink")
    url = value.strip()
    if any(char.isspace() for char in url):
        raise FacebookResponseError("Facebook post permalink must not contain whitespace")
    try:
        parsed = urlsplit(url)
    except ValueError:
        raise FacebookResponseError(
            "Facebook post permalink is malformed"
        ) from None
    if parsed.scheme.lower() not in ("http", "https"):
        raise FacebookResponseError("Facebook post permalink must be an HTTP(S) URL")
    if not parsed.hostname:
        raise FacebookResponseError("Facebook post permalink must include a hostname")
    return url


def _parse_created_time(value: str | None) -> datetime | None:
    if value is None:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise FacebookResponseError(
            "Facebook post created_time is malformed"
        ) from None
    if parsed.tzinfo is None:
        raise FacebookResponseError(
            "Facebook post created_time must be timezone-aware"
        )
    return parsed.astimezone(timezone.utc)