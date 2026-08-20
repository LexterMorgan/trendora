"""Typed Stack Exchange API v2.x shapes used after JSON decode.

Unknown API fields are ignored. Per-metric numeric parsing happens in the
normalizer so one bad statistic does not drop an entire question.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _IgnoreExtra(BaseModel):
    model_config = ConfigDict(extra="ignore")


class OwnerResource(_IgnoreExtra):
    user_id: int | None = None
    display_name: str | None = None


class QuestionResource(_IgnoreExtra):
    question_id: int
    title: str | None = None
    link: str | None = None
    score: Any = None
    view_count: Any = None
    answer_count: Any = None
    creation_date: Any = None
    last_activity_date: Any = None
    tags: Any = None
    is_answered: Any = None
    accepted_answer_id: Any = None
    owner: Any = None
    content_license: str | None = None
    body: str | None = None


class QuestionsWrapper(_IgnoreExtra):
    items: list[Any] = Field(default_factory=list)
    has_more: bool = False
    quota_max: int | None = None
    quota_remaining: int | None = None
    backoff: Any = None
    error_id: int | None = None
    error_message: str | None = None
    error_name: str | None = None
