"""Typed GitHub REST repository shapes used after JSON decode.

Unknown API fields are ignored. Per-metric numeric parsing happens in the
normalizer so one bad statistic does not drop an entire repository.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class _IgnoreExtra(BaseModel):
    model_config = ConfigDict(extra="ignore")


class OwnerResource(_IgnoreExtra):
    login: str | None = None
    id: int | None = None


class LicenseResource(_IgnoreExtra):
    key: str | None = None
    name: str | None = None
    spdx_id: str | None = None


class RepositoryResource(_IgnoreExtra):
    id: Any = None
    name: str | None = None
    full_name: str | None = None
    html_url: str | None = None
    description: Any = None
    language: str | None = None
    visibility: str | None = None
    private: Any = None
    default_branch: str | None = None
    archived: Any = None
    disabled: Any = None
    topics: Any = None
    license: Any = None
    created_at: Any = None
    updated_at: Any = None
    pushed_at: Any = None
    stargazers_count: Any = None
    forks_count: Any = None
    open_issues_count: Any = None
    watchers_count: Any = None
    subscribers_count: Any = None
    owner: Any = None
