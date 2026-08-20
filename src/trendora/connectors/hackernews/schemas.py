"""Typed Hacker News Firebase item shapes used after JSON decode."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _IgnoreExtra(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ItemResource(_IgnoreExtra):
    id: int
    type: str | None = None
    by: str | None = None
    time: int | None = None
    title: str | None = None
    url: str | None = None
    text: str | None = None
    score: int | None = None
    descendants: int | None = None
    kids: list[int] | None = None
    deleted: bool = False
    dead: bool = False
    parent: int | None = None
