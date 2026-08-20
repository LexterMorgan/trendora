"""Map Stack Exchange questions onto Trendora domain records. No HTTP. No Session."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from trendora.connectors.stackexchange.exceptions import StackExchangeItemError
from trendora.connectors.stackexchange.schemas import OwnerResource, QuestionResource

SE_SOURCE_CODE = "stack_exchange"
CONTENT_TYPE_QUESTION = "question"

DEFAULT_SITES: tuple[str, ...] = ("stackoverflow", "datascience")
DEFAULT_MAX_ITEMS_PER_SITE = 50
MAX_TAGS = 5


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
class NormalizedQuestion:
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


def question_external_id(site: str, question_id: int) -> str:
    """Site-scoped identity. Stack Exchange question IDs are not global."""

    return f"{site}:{question_id}"


def normalize_question(
    item: QuestionResource,
    *,
    site: str,
    collected_at: datetime,
) -> NormalizedQuestion:
    if collected_at.tzinfo is None:
        raise ValueError("collected_at must be timezone-aware")
    if item.question_id < 1:
        raise StackExchangeItemError("Stack Exchange question is missing a valid question_id")

    metadata = _source_metadata(item, site=site)
    return NormalizedQuestion(
        external_id=question_external_id(site, item.question_id),
        content_type=CONTENT_TYPE_QUESTION,
        title=(item.title or "").strip() or None,
        description=None,
        url=_canonical_link(item.link),
        published_at=_unix_time(item.creation_date),
        source_metadata=metadata,
        snapshots=_question_snapshots(item, collected_at=collected_at),
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


def _canonical_link(value: str | None) -> str | None:
    if not value or not str(value).strip():
        return None
    link = str(value).strip()
    if not (link.startswith("https://") or link.startswith("http://")):
        return None
    return link


def _unix_time(value: object) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc)


def _source_metadata(item: QuestionResource, *, site: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "site": site,
        "question_id": item.question_id,
    }
    tags = _tags(item.tags)
    if tags is not None:
        metadata["tags"] = tags
    if isinstance(item.is_answered, bool):
        metadata["is_answered"] = item.is_answered
    answer_count = parse_count(item.answer_count)
    if answer_count is not None:
        metadata["answer_count"] = answer_count
    accepted = parse_count(item.accepted_answer_id)
    if accepted is not None and accepted > 0:
        metadata["accepted_answer_id"] = accepted
    owner = _owner(item.owner)
    if owner is not None:
        metadata["owner"] = owner
    license_name = (item.content_license or "").strip()
    if license_name:
        metadata["content_license"] = license_name
    last_activity = _unix_time(item.last_activity_date)
    if last_activity is not None:
        metadata["last_activity_date"] = last_activity.isoformat()
    return metadata


def _tags(value: object) -> list[str] | None:
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


def _owner(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    try:
        owner = value if isinstance(value, OwnerResource) else OwnerResource.model_validate(value)
    except Exception:
        return None
    payload: dict[str, Any] = {}
    if isinstance(owner.user_id, int) and not isinstance(owner.user_id, bool) and owner.user_id > 0:
        payload["user_id"] = owner.user_id
    display = (owner.display_name or "").strip()
    if display:
        payload["display_name"] = display
    return payload or None


def _question_snapshots(
    item: QuestionResource,
    *,
    collected_at: datetime,
) -> tuple[NormalizedSnapshot, ...]:
    rows: list[NormalizedSnapshot] = []
    for field_name, metric_name in (
        ("score", "score"),
        ("view_count", "view_count"),
        ("answer_count", "answer_count"),
    ):
        parsed = parse_count(getattr(item, field_name))
        if parsed is None:
            continue
        rows.append(
            NormalizedSnapshot(
                metric_name=metric_name,
                metric_value=parsed,
                observed_at=collected_at,
                collected_at=collected_at,
                source_metadata={"se_field": field_name},
            )
        )
    return tuple(rows)
