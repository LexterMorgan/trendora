"""Manual shared planner: input contracts, reads, and transactional mutations.

One deployment, one shared planner: every active member sees every post from
creation, archived rows included. Identity never comes from request data; the
route passes the actor it already authenticated, and every write re-checks
active membership inside its own transaction under ``FOR SHARE`` rows locked
in UUID order.

Writes are compare-and-swap on ``version``: a stale request is a conflict even
when its values now match, and an unchanged request is a no-op with no version
or activity increment. Creation is keyed on ``(created_by, create_request_id)``
with an immutable SHA-256 of the normalized payload, so a retry returns the
original id while a reused id with a different payload conflicts. Each real
mutation commits its single activity row in the same transaction and reports
success only after the commit. SQLAlchemy failures become a fixed 503 with the
driver detail kept in the cause chain.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import date, datetime
from typing import Iterator, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from trendora.api.errors import (
    ApiError,
    AuthInactiveError,
    AuthNotMemberError,
    DataUnavailableError,
)
from trendora.models.membership import Membership
from trendora.models.planner import PlannerPost, PlannerPostActivity

DATA_UNAVAILABLE_MESSAGE = "planner data is unavailable"

MAX_TITLE = 200
MAX_PLATFORM = 80
MAX_HOOK = 1000
MAX_LONG_TEXT = 20_000
MAX_ASSET_LINKS = 20
MAX_LINK_LENGTH = 2_048

EDITABLE_FIELDS = (
    "title",
    "platform",
    "caption",
    "hook",
    "creative_brief",
    "asset_links",
    "notes",
    "planned_date",
    "assignee_id",
)
CONTENT_FIELDS = (
    "title",
    "platform",
    "caption",
    "hook",
    "creative_brief",
    "asset_links",
)

SUMMARY_COLUMNS = (
    PlannerPost.id,
    PlannerPost.title,
    PlannerPost.platform,
    PlannerPost.status,
    PlannerPost.planned_date,
    PlannerPost.assignee_id,
    PlannerPost.version,
    PlannerPost.updated_at,
    PlannerPost.archived_at,
)

_CALENDAR_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_URL_SCHEMES = ("http", "https")


class PlannerPostNotFoundError(ApiError):
    status_code = 404
    code = "planner_post_not_found"


class PlannerVersionConflictError(ApiError):
    status_code = 409
    code = "planner_version_conflict"


class PlannerCreateConflictError(ApiError):
    status_code = 409
    code = "planner_create_conflict"


class PlannerPostArchivedError(ApiError):
    status_code = 409
    code = "planner_post_archived"


class PlannerAssigneeInvalidError(ApiError):
    status_code = 422
    code = "planner_assignee_invalid"


def _rollback_quietly(session: Session) -> None:
    try:
        session.rollback()
    except SQLAlchemyError:
        pass


@contextmanager
def _write_guard(session: Session) -> Iterator[None]:
    """Every rejection rolls back; driver failures become one fixed 503."""
    try:
        yield
    except SQLAlchemyError as exc:
        _rollback_quietly(session)
        raise DataUnavailableError(DATA_UNAVAILABLE_MESSAGE) from exc
    except Exception:
        _rollback_quietly(session)
        raise


def _calendar_date(value: object) -> object:
    """Exact ``YYYY-MM-DD`` only: no timestamps, no epochs, no shorthand."""
    if value is None:
        return None
    if isinstance(value, datetime):
        raise ValueError("planned_date must be an exact YYYY-MM-DD date")
    if isinstance(value, str):
        if not _CALENDAR_DATE.fullmatch(value):
            raise ValueError("planned_date must be an exact YYYY-MM-DD date")
        return date.fromisoformat(value)
    if isinstance(value, date):
        return value
    raise ValueError("planned_date must be an exact YYYY-MM-DD date")


def _asset_links(links: list[str]) -> list[str]:
    if len(links) > MAX_ASSET_LINKS:
        raise ValueError(f"at most {MAX_ASSET_LINKS} asset links are allowed")
    for link in links:
        if len(link) > MAX_LINK_LENGTH:
            raise ValueError(f"asset links are limited to {MAX_LINK_LENGTH} characters")
        parts = _split_url(link)
        if parts.scheme not in _URL_SCHEMES or not parts.hostname:
            raise ValueError("asset links must be http(s) URLs with a host")
        if parts.username is not None or parts.password is not None:
            raise ValueError("asset links must not embed credentials")
    return links


def _split_url(link: str):
    try:
        return urlsplit(link)
    except ValueError as exc:
        raise ValueError("asset links must be http(s) URLs with a host") from exc


class PostFields(BaseModel):
    """Complete editable snapshot. All keys are required; blank is valid."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=MAX_TITLE)
    platform: str = Field(max_length=MAX_PLATFORM)
    caption: str = Field(max_length=MAX_LONG_TEXT)
    hook: str = Field(max_length=MAX_HOOK)
    creative_brief: str = Field(max_length=MAX_LONG_TEXT)
    asset_links: list[str] = Field(max_length=MAX_ASSET_LINKS)
    notes: str = Field(max_length=MAX_LONG_TEXT)
    planned_date: date | None
    assignee_id: UUID | None

    @field_validator("title", "platform", mode="before")
    @classmethod
    def _trim_outer_whitespace(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("planned_date", mode="before")
    @classmethod
    def _exact_calendar_date(cls, value: object) -> object:
        return _calendar_date(value)

    @field_validator("asset_links")
    @classmethod
    def _bounded_http_links(cls, links: list[str]) -> list[str]:
        return _asset_links(links)


class PostCreate(PostFields):
    """Retry-safe creation payload. Status always starts as ``idea``."""

    request_id: UUID


class PostUpdate(PostFields):
    """Full snapshot replace, not a merge. P4 widens the status policy."""

    expected_version: int = Field(strict=True, gt=0)
    status: Literal["idea", "working"]


class PostVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(strict=True, gt=0)


class PostRead(BaseModel):
    id: UUID
    title: str
    platform: str
    caption: str
    hook: str
    creative_brief: str
    asset_links: list[str]
    notes: str
    planned_date: date | None
    assignee_id: UUID | None
    status: str
    version: int
    content_revision: int
    created_by: UUID
    updated_by: UUID
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


class PostSummary(BaseModel):
    id: UUID
    title: str
    platform: str
    status: str
    planned_date: date | None
    assignee_id: UUID | None
    version: int
    updated_at: datetime
    archived_at: datetime | None


class PlannerMemberOption(BaseModel):
    user_id: UUID
    email: str


def _payload_hash(data: PostFields) -> str:
    """SHA-256 over normalized creation fields only, in canonical JSON."""
    canonical = {
        "asset_links": list(data.asset_links),
        "assignee_id": str(data.assignee_id) if data.assignee_id else None,
        "caption": data.caption,
        "creative_brief": data.creative_brief,
        "hook": data.hook,
        "notes": data.notes,
        "platform": data.platform,
        "planned_date": data.planned_date.isoformat() if data.planned_date else None,
        "title": data.title,
    }
    encoded = json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _lock_members(
    session: Session, ids: Iterable[UUID | None]
) -> dict[UUID, Membership]:
    """Lock actor and assignee ``FOR SHARE`` in UUID order, then reload them.

    ``populate_existing`` refreshes anything already in the identity map: the
    row we just locked, not the state a previous statement happened to load.
    """
    wanted = sorted({member_id for member_id in ids if member_id is not None})
    if not wanted:
        return {}
    result = session.execute(
        select(Membership)
        .where(Membership.user_id.in_(wanted))
        .order_by(Membership.user_id.asc())
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    members = result.scalars().all()
    return {member.user_id: member for member in members}


def _require_actor(members: dict[UUID, Membership], actor_id: UUID) -> None:
    row = members.get(actor_id)
    if row is None:
        raise AuthNotMemberError("no membership exists for this user")
    if not row.active:
        raise AuthInactiveError("membership is inactive")


def _require_assignee(members: dict[UUID, Membership], assignee_id: UUID | None) -> None:
    if assignee_id is None:
        return
    row = members.get(assignee_id)
    if row is None or not row.active:
        raise PlannerAssigneeInvalidError("assignee must be an active member")


def _load_post(session: Session, post_id: UUID) -> PlannerPost:
    row = session.execute(
        select(PlannerPost).where(PlannerPost.id == post_id)
    ).scalar_one_or_none()
    if row is None:
        raise PlannerPostNotFoundError("planner post not found")
    return row


def _fresh_post(session: Session, post_id: UUID) -> PlannerPost | None:
    return session.execute(
        select(PlannerPost)
        .where(PlannerPost.id == post_id)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()


def _resolve_failed_write(
    session: Session, post_id: UUID, *, must_be_archived: bool
) -> None:
    fresh = _fresh_post(session, post_id)
    if fresh is None:
        raise PlannerPostNotFoundError("planner post not found")
    if not must_be_archived and fresh.archived_at is not None:
        raise PlannerPostArchivedError("planner post is archived")
    raise PlannerVersionConflictError("post version does not match")


def _read(row: PlannerPost) -> PostRead:
    return PostRead(
        id=row.id,
        title=row.title,
        platform=row.platform,
        caption=row.caption,
        hook=row.hook,
        creative_brief=row.creative_brief,
        asset_links=list(row.asset_links),
        notes=row.notes,
        planned_date=row.planned_date,
        assignee_id=row.assignee_id,
        status=row.status,
        version=row.version,
        content_revision=row.content_revision,
        created_by=row.created_by,
        updated_by=row.updated_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
        archived_at=row.archived_at,
    )


def _summary(row) -> PostSummary:
    return PostSummary(
        id=row[0],
        title=row[1],
        platform=row[2],
        status=row[3],
        planned_date=row[4],
        assignee_id=row[5],
        version=row[6],
        updated_at=row[7],
        archived_at=row[8],
    )


def _replayed_creation(
    session: Session, *, actor_id: UUID, request_id: UUID, digest: str
) -> UUID | None:
    """Stored id when ``(actor, request_id)`` already committed, else ``None``.

    A committed key carrying a different payload is a conflict, never a replay.
    """
    stored = session.execute(
        select(PlannerPost).where(
            PlannerPost.created_by == actor_id,
            PlannerPost.create_request_id == request_id,
        )
    ).scalar_one_or_none()
    if stored is None:
        return None
    if stored.create_payload_hash != digest:
        raise PlannerCreateConflictError(
            "creation request conflicts with an existing post"
        )
    return stored.id


def create_post(
    session: Session, *, actor_id: UUID, data: PostCreate
) -> tuple[UUID, bool]:
    """Insert once per ``(actor, request_id)``; ``False`` means a replay."""
    with _write_guard(session):
        members = _lock_members(session, (actor_id, data.assignee_id))
        _require_actor(members, actor_id)
        digest = _payload_hash(data)
        # Replay answers before assignment rules: the row is already
        # committed and its assignee may have been deactivated since.
        replayed = _replayed_creation(
            session, actor_id=actor_id, request_id=data.request_id, digest=digest
        )
        if replayed is not None:
            return replayed, False
        _require_assignee(members, data.assignee_id)
        new_id = session.execute(
            pg_insert(PlannerPost)
            .values(
                title=data.title,
                platform=data.platform,
                caption=data.caption,
                hook=data.hook,
                creative_brief=data.creative_brief,
                asset_links=data.asset_links,
                notes=data.notes,
                planned_date=data.planned_date,
                assignee_id=data.assignee_id,
                status="idea",
                created_by=actor_id,
                updated_by=actor_id,
                create_request_id=data.request_id,
                create_payload_hash=digest,
            )
            .on_conflict_do_nothing(index_elements=["created_by", "create_request_id"])
            .returning(PlannerPost.id)
        ).scalar_one_or_none()
        if new_id is None:
            # Lost the race to a concurrent identical creation: that commit is
            # visible now, so replay it or report the conflicting payload.
            replayed = _replayed_creation(
                session, actor_id=actor_id, request_id=data.request_id, digest=digest
            )
            if replayed is not None:
                return replayed, False
            raise PlannerCreateConflictError(
                "creation request conflicts with an existing post"
            )
        session.add(
            PlannerPostActivity(
                post_id=new_id,
                actor_id=actor_id,
                event_type="created",
                details={"version": 1, "status": "idea"},
            )
        )
        session.flush()
        session.commit()
        return new_id, True


def _import_selector_hash(selector: dict) -> str:
    """Marker-prefixed hash so an import can never collide with a manual create."""
    canonical = {"operation": "research_import", **selector}
    encoded = json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def find_import_replay(
    session: Session,
    *,
    actor_id: UUID,
    request_id: UUID,
    selector: dict,
) -> UUID | None:
    """Committed post id for a matching import selector, else ``None``.

    Raises ``PlannerCreateConflictError`` when the key exists with a different
    selector. Used by the route to acknowledge a replay before resolving an
    aged-out source again.
    """
    digest = _import_selector_hash(selector)
    return _replayed_creation(
        session, actor_id=actor_id, request_id=request_id, digest=digest
    )


def import_post(
    session: Session,
    *,
    actor_id: UUID,
    request_id: UUID,
    report_id: UUID,
    item_kind: str,
    item_index: int,
    fields: dict,
    origin: dict,
    origin_sources: list,
) -> tuple[UUID, bool]:
    """Insert one imported post with its origin and one created activity.

    Reuses the planner idempotency contract: the key is ``(actor, request_id)``
    and the digest carries an import-operation marker. A matching replay
    returns the original post id before any source is resolved again.
    """
    with _write_guard(session):
        members = _lock_members(session, (actor_id,))
        _require_actor(members, actor_id)
        selector = {
            "report_id": str(report_id),
            "item_kind": item_kind,
            "item_index": item_index,
        }
        digest = _import_selector_hash(selector)
        replayed = _replayed_creation(
            session, actor_id=actor_id, request_id=request_id, digest=digest
        )
        if replayed is not None:
            return replayed, False
        new_id = session.execute(
            pg_insert(PlannerPost)
            .values(
                title=fields["title"],
                platform="",
                caption="",
                hook=fields["hook"],
                creative_brief=fields["creative_brief"],
                asset_links=[],
                notes="",
                planned_date=None,
                assignee_id=None,
                status="idea",
                created_by=actor_id,
                updated_by=actor_id,
                create_request_id=request_id,
                create_payload_hash=digest,
                origin={**origin, "report_id": str(report_id)},
            )
            .on_conflict_do_nothing(index_elements=["created_by", "create_request_id"])
            .returning(PlannerPost.id)
        ).scalar_one_or_none()
        if new_id is None:
            replayed = _replayed_creation(
                session, actor_id=actor_id, request_id=request_id, digest=digest
            )
            if replayed is not None:
                return replayed, False
            raise PlannerCreateConflictError(
                "creation request conflicts with an existing post"
            )
        from trendora.planner_origin import persist_origin_sources

        persist_origin_sources(session, post_id=new_id, sources=origin_sources)
        session.add(
            PlannerPostActivity(
                post_id=new_id,
                actor_id=actor_id,
                event_type="created",
                details={"version": 1, "status": "idea", "source": "research_import"},
            )
        )
        session.flush()
        session.commit()
        return new_id, True


def get_post(session: Session, *, post_id: UUID) -> PostRead:
    with _write_guard(session):
        return _read(_load_post(session, post_id))


def list_posts(
    session: Session, *, archived: bool, limit: int, offset: int
) -> list[PostSummary]:
    """Summary rows only; full draft text is never selected for a list."""
    with _write_guard(session):
        state = PlannerPost.archived_at.is_not(None) if archived else PlannerPost.archived_at.is_(None)
        rows = session.execute(
            select(*SUMMARY_COLUMNS)
            .where(state)
            .order_by(PlannerPost.updated_at.desc(), PlannerPost.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return [_summary(row) for row in rows]


def update_post(
    session: Session, *, actor_id: UUID, post_id: UUID, data: PostUpdate
) -> PostRead:
    """Full-snapshot replace behind one atomic version predicate."""
    with _write_guard(session):
        members = _lock_members(session, (actor_id, data.assignee_id))
        _require_actor(members, actor_id)
        current = _load_post(session, post_id)
        if current.archived_at is not None:
            raise PlannerPostArchivedError("planner post is archived")
        if data.assignee_id is not None and data.assignee_id != current.assignee_id:
            _require_assignee(members, data.assignee_id)

        changed = [
            field
            for field in EDITABLE_FIELDS
            if getattr(current, field) != getattr(data, field)
        ]
        if data.status != current.status:
            changed.append("status")
        if not changed:
            confirmed = session.execute(
                select(PlannerPost).where(
                    PlannerPost.id == post_id,
                    PlannerPost.version == data.expected_version,
                )
            ).scalar_one_or_none()
            if confirmed is None:
                raise PlannerVersionConflictError("post version does not match")
            return _read(confirmed)

        content_changed = any(field in CONTENT_FIELDS for field in changed)
        row = session.execute(
            update(PlannerPost)
            .where(
                PlannerPost.id == post_id,
                PlannerPost.version == data.expected_version,
                PlannerPost.archived_at.is_(None),
            )
            .values(
                title=data.title,
                platform=data.platform,
                caption=data.caption,
                hook=data.hook,
                creative_brief=data.creative_brief,
                asset_links=data.asset_links,
                notes=data.notes,
                planned_date=data.planned_date,
                assignee_id=data.assignee_id,
                status=data.status,
                updated_by=actor_id,
                version=data.expected_version + 1,
                content_revision=current.content_revision + (1 if content_changed else 0),
            )
            .returning(PlannerPost)
        ).scalar_one_or_none()
        if row is None:
            _resolve_failed_write(session, post_id, must_be_archived=False)
        # Serialize before commit: commit expires the row, and the reload it
        # would trigger could fail or show a later state than what we wrote.
        snapshot = _read(row)
        session.add(
            PlannerPostActivity(
                post_id=post_id,
                actor_id=actor_id,
                event_type="updated",
                details={"fields": changed, "version": row.version, "status": row.status},
            )
        )
        session.flush()
        session.commit()
        return snapshot


def set_archived(
    session: Session,
    *,
    actor_id: UUID,
    post_id: UUID,
    expected_version: int,
    archived: bool,
) -> PostRead:
    """Archive or restore behind one atomic version and archive predicate."""
    with _write_guard(session):
        members = _lock_members(session, (actor_id,))
        _require_actor(members, actor_id)
        current = _load_post(session, post_id)
        if (current.archived_at is not None) == archived:
            confirmed = session.execute(
                select(PlannerPost).where(
                    PlannerPost.id == post_id,
                    PlannerPost.version == expected_version,
                )
            ).scalar_one_or_none()
            if confirmed is None:
                raise PlannerVersionConflictError("post version does not match")
            return _read(confirmed)

        state = (
            PlannerPost.archived_at.is_(None)
            if archived
            else PlannerPost.archived_at.is_not(None)
        )
        row = session.execute(
            update(PlannerPost)
            .where(
                PlannerPost.id == post_id,
                PlannerPost.version == expected_version,
                state,
            )
            .values(
                archived_at=func.now() if archived else None,
                updated_by=actor_id,
                version=expected_version + 1,
            )
            .returning(PlannerPost)
        ).scalar_one_or_none()
        if row is None:
            _resolve_failed_write(session, post_id, must_be_archived=archived)
        snapshot = _read(row)
        session.add(
            PlannerPostActivity(
                post_id=post_id,
                actor_id=actor_id,
                event_type="archived" if archived else "restored",
                details={
                    "fields": [],
                    "version": row.version,
                    "archived": archived,
                },
            )
        )
        session.flush()
        session.commit()
        return snapshot


def list_assignees(session: Session) -> list[PlannerMemberOption]:
    """Active members only, sorted by email then uuid. No permission flags."""
    with _write_guard(session):
        rows = session.execute(
            select(Membership.user_id, Membership.email)
            .where(Membership.active.is_(True))
            .order_by(Membership.email.asc(), Membership.user_id.asc())
        ).all()
        return [PlannerMemberOption(user_id=row[0], email=row[1]) for row in rows]
