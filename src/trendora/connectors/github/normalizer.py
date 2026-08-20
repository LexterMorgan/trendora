"""Map GitHub repositories onto Trendora domain records. No HTTP. No Session."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from trendora.connectors.github.exceptions import GitHubItemError
from trendora.connectors.github.schemas import LicenseResource, OwnerResource, RepositoryResource

GH_SOURCE_CODE = "github"
CONTENT_TYPE_REPOSITORY = "repository"
DEFAULT_MAX_ITEMS = 50


@dataclass(frozen=True)
class NormalizedSnapshot:
    metric_name: str
    metric_value: int
    observed_at: datetime
    collected_at: datetime
    subject: Literal["content_item"] = "content_item"
    source_metadata: dict[str, Any] | None = None
    retention_policy_code: str | None = None
    retain_until: datetime | None = None


@dataclass(frozen=True)
class NormalizedRepository:
    external_id: str
    content_type: str
    title: str | None
    description: str | None
    url: str | None
    published_at: datetime | None
    source_metadata: dict[str, Any]
    snapshots: tuple[NormalizedSnapshot, ...]
    collected_at: datetime
    retain_until: datetime | None = None


def normalize_repository(
    item: RepositoryResource,
    *,
    collected_at: datetime,
) -> NormalizedRepository:
    if collected_at.tzinfo is None:
        raise ValueError("collected_at must be timezone-aware")

    external_id = _external_id(item)
    description = item.description if isinstance(item.description, str) else None
    description = (description or "").strip() or None
    return NormalizedRepository(
        external_id=external_id,
        content_type=CONTENT_TYPE_REPOSITORY,
        title=(item.name or "").strip() or external_id.split("/")[-1],
        description=description,
        url=_canonical_link(item.html_url),
        published_at=parse_github_datetime(item.created_at),
        source_metadata=_source_metadata(item, external_id=external_id),
        snapshots=_repository_snapshots(item, collected_at=collected_at),
        collected_at=collected_at,
    )


def parse_count(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    if parsed < 0:
        return None
    return parsed


def parse_github_datetime(value: object) -> datetime | None:
    if not value or not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _external_id(item: RepositoryResource) -> str:
    full_name = (item.full_name or "").strip()
    if full_name.count("/") == 1 and not full_name.startswith("/") and not full_name.endswith("/"):
        return full_name
    owner = _owner(item.owner)
    name = (item.name or "").strip()
    login = (owner or {}).get("login")
    if isinstance(login, str) and login.strip() and name:
        return f"{login.strip()}/{name}"
    raise GitHubItemError("GitHub repository is missing owner/repository identity")


def _canonical_link(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    link = value.strip()
    if not (link.startswith("https://") or link.startswith("http://")):
        return None
    return link


def _source_metadata(item: RepositoryResource, *, external_id: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {"full_name": external_id}
    github_id = parse_count(item.id)
    if github_id is not None and github_id > 0:
        metadata["github_id"] = github_id
    owner = _owner(item.owner)
    if owner is not None and owner.get("login"):
        metadata["owner_login"] = owner["login"]
    url = _canonical_link(item.html_url)
    if url is not None:
        metadata["html_url"] = url
    description = item.description if isinstance(item.description, str) else None
    description = (description or "").strip() or None
    if description is not None:
        metadata["description"] = description
    language = (item.language or "").strip() if isinstance(item.language, str) else ""
    if language:
        metadata["language"] = language
    visibility = _visibility(item)
    if visibility is not None:
        metadata["visibility"] = visibility
    default_branch = (item.default_branch or "").strip() if isinstance(item.default_branch, str) else ""
    if default_branch:
        metadata["default_branch"] = default_branch
    if isinstance(item.archived, bool):
        metadata["archived"] = item.archived
    if isinstance(item.disabled, bool):
        metadata["disabled"] = item.disabled
    topics = _topics(item.topics)
    if topics is not None:
        metadata["topics"] = topics
    license_payload = _license(item.license)
    if license_payload is not None:
        metadata["license"] = license_payload
    created_at = parse_github_datetime(item.created_at)
    if created_at is not None:
        metadata["created_at"] = created_at.isoformat()
    updated_at = parse_github_datetime(item.updated_at)
    if updated_at is not None:
        metadata["updated_at"] = updated_at.isoformat()
    pushed_at = parse_github_datetime(item.pushed_at)
    if pushed_at is not None:
        metadata["pushed_at"] = pushed_at.isoformat()
    return metadata


def _owner(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    try:
        owner = value if isinstance(value, OwnerResource) else OwnerResource.model_validate(value)
    except Exception:
        return None
    payload: dict[str, Any] = {}
    login = (owner.login or "").strip()
    if login:
        payload["login"] = login
    if isinstance(owner.id, int) and not isinstance(owner.id, bool) and owner.id > 0:
        payload["id"] = owner.id
    return payload or None


def _visibility(item: RepositoryResource) -> str | None:
    if isinstance(item.visibility, str) and item.visibility.strip():
        return item.visibility.strip()
    if isinstance(item.private, bool):
        return "private" if item.private else "public"
    return None


def _topics(value: object) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        return None
    ordered: list[str] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, str):
            continue
        token = raw.strip()
        if not token or token in seen:
            continue
        seen.add(token)
        ordered.append(token)
    return ordered


def _license(value: object) -> dict[str, str] | None:
    if value is None:
        return None
    try:
        license_row = (
            value if isinstance(value, LicenseResource) else LicenseResource.model_validate(value)
        )
    except Exception:
        return None
    payload: dict[str, str] = {}
    for field_name in ("key", "spdx_id", "name"):
        raw = getattr(license_row, field_name)
        if isinstance(raw, str) and raw.strip():
            payload[field_name] = raw.strip()
    return payload or None


def _repository_snapshots(
    item: RepositoryResource,
    *,
    collected_at: datetime,
) -> tuple[NormalizedSnapshot, ...]:
    fields: list[tuple[str, str, object]] = [
        ("stargazers_count", "stargazer_count", item.stargazers_count),
        ("forks_count", "fork_count", item.forks_count),
        ("open_issues_count", "open_issue_count", item.open_issues_count),
    ]
    if parse_count(item.subscribers_count) is not None:
        fields.append(("subscribers_count", "watcher_count", item.subscribers_count))
    else:
        fields.append(("watchers_count", "watcher_count", item.watchers_count))
    rows: list[NormalizedSnapshot] = []
    for gh_field, metric_name, raw in fields:
        parsed = parse_count(raw)
        if parsed is None:
            continue
        rows.append(
            NormalizedSnapshot(
                metric_name=metric_name,
                metric_value=parsed,
                observed_at=collected_at,
                collected_at=collected_at,
                source_metadata={"gh_field": gh_field},
            )
        )
    return tuple(rows)
