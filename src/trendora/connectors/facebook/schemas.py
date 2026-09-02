"""Strict Facebook Graph API public Page resource shapes (M25A).

Fields are exactly what Trendora requests — nothing extra is accepted
(``extra="forbid"``). Optional metrics default to ``None``; source zero stays
zero; counts must be non-negative. Reactions are reactions, never likes; no
derived metrics are computed here. ``paging`` lives on the top-level posts
response, not on individual posts.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FacebookPagingCursors(_Strict):
    before: str | None = None
    after: str | None = None


class FacebookPaging(_Strict):
    cursors: FacebookPagingCursors | None = None
    next: str | None = None
    previous: str | None = None


class FacebookPageFrom(_Strict):
    id: str | None = None
    name: str | None = None


class FacebookShares(_Strict):
    count: int | None = Field(default=None, ge=0)


class FacebookSummary(_Strict):
    total_count: int | None = Field(default=None, ge=0)


class FacebookReactions(_Strict):
    summary: FacebookSummary | None = None


class FacebookComments(_Strict):
    summary: FacebookSummary | None = None


class FacebookPostResource(_Strict):
    """One public Facebook Page post with only the requested fields."""

    id: str
    message: str | None = None
    created_time: str | None = None
    permalink_url: str | None = None
    from_: FacebookPageFrom | None = Field(default=None, alias="from")
    shares: FacebookShares | None = None
    reactions: FacebookReactions | None = None
    comments: FacebookComments | None = None

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class FacebookPostsResponse(_Strict):
    """Top-level posts list response: data plus optional pagination cursors."""

    data: list[FacebookPostResource]
    paging: FacebookPaging | None = None