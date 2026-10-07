"""Admin membership API (Gate A): list members, permission history, patch flags.

Identity and authority come from ``require_admin``; mutations go through
``apply_member_patch``, which holds a table-level serialization lock, then
re-reads and re-authorizes the actor before touching anything. Every
rejection rolls back, so a failed patch leaves neither a mutation nor a
history row. SQLAlchemy failures become a sanitized 503 ``data_unavailable``;
authorization, validation, and invariant errors keep their own statuses.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from trendora.api.auth import Member, require_admin
from trendora.api.deps import get_session
from trendora.api.errors import (
    AuthForbiddenAdminError,
    AuthInactiveError,
    AuthNotMemberError,
    DataUnavailableError,
    LastAdminError,
    MemberNotFoundError,
)
from trendora.models.membership import Membership, MembershipPermissionHistory

_PATCHABLE_FIELDS = ("active", "is_admin", "can_approve")
_DATA_UNAVAILABLE_MESSAGE = "membership data is unavailable"


def _rollback_quietly(session: Session) -> None:
    """Roll back, swallowing a failed rollback on an already-broken session."""
    try:
        session.rollback()
    except SQLAlchemyError:
        pass


class MemberPatch(BaseModel):
    """Partial membership update. Omitted fields stay unchanged."""

    model_config = ConfigDict(extra="forbid", strict=True)

    active: bool | None = None
    is_admin: bool | None = None
    can_approve: bool | None = None


class MemberResponse(BaseModel):
    user_id: str
    email: str
    active: bool
    is_admin: bool
    can_approve: bool


class PermissionHistoryResponse(BaseModel):
    id: int
    actor_id: str
    subject_id: str
    before: dict[str, Any]
    after: dict[str, Any]
    created_at: str


def _member_dict(row: Membership) -> dict[str, Any]:
    return {
        "user_id": str(row.user_id),
        "email": row.email,
        "active": row.active,
        "is_admin": row.is_admin,
        "can_approve": row.can_approve,
    }


def list_members(session: Session) -> list[dict[str, Any]]:
    try:
        rows = session.scalars(select(Membership).order_by(Membership.email.asc())).all()
    except SQLAlchemyError as exc:
        raise DataUnavailableError(_DATA_UNAVAILABLE_MESSAGE) from exc
    return [_member_dict(row) for row in rows]


def list_permission_history(
    session: Session, *, limit: int = 100, offset: int = 0
) -> list[dict[str, Any]]:
    try:
        rows = session.scalars(
            select(MembershipPermissionHistory)
            .order_by(
                MembershipPermissionHistory.created_at.desc(),
                MembershipPermissionHistory.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        ).all()
    except SQLAlchemyError as exc:
        raise DataUnavailableError(_DATA_UNAVAILABLE_MESSAGE) from exc
    return [
        {
            "id": row.id,
            "actor_id": str(row.actor_id),
            "subject_id": str(row.subject_id),
            "before": row.before,
            "after": row.after,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


def apply_member_patch(
    session: Session,
    *,
    actor_id: UUID,
    subject_id: UUID,
    changes: dict[str, Any],
) -> Member:
    """Apply one membership change under the serialization lock.

    Sequence: lock ``memberships`` EXCLUSIVE, re-read and re-authorize the
    actor, mutate, check the last-admin invariant, insert history, commit.
    Rejections and database failures roll everything back: authorization and
    invariant errors keep their statuses, SQLAlchemy failures become a
    sanitized 503. Re-reading after the lock relies on the default READ
    COMMITTED isolation; raise isolation only with a matching recheck story.
    """
    try:
        session.execute(text("LOCK TABLE memberships IN EXCLUSIVE MODE"))
        session.expire_all()
        actor = session.get(Membership, actor_id)
        if actor is None:
            raise AuthNotMemberError("no membership exists for this user")
        if not actor.active:
            raise AuthInactiveError("membership is inactive")
        if not actor.is_admin:
            raise AuthForbiddenAdminError("administrator access required")
        subject = session.get(Membership, subject_id)
        if subject is None:
            raise MemberNotFoundError("no membership exists for this user")

        before: dict[str, Any] = {}
        after: dict[str, Any] = {}
        for field in _PATCHABLE_FIELDS:
            if field not in changes:
                continue
            new_value = changes[field]
            old_value = getattr(subject, field)
            if old_value == new_value:
                continue
            before[field] = old_value
            after[field] = new_value
            setattr(subject, field, new_value)

        if after:
            session.flush()
            active_admins = session.scalar(
                select(func.count())
                .select_from(Membership)
                .where(Membership.active.is_(True), Membership.is_admin.is_(True))
            )
            if not active_admins:
                raise LastAdminError("at least one active administrator must remain")
            session.add(
                MembershipPermissionHistory(
                    actor_id=actor_id,
                    subject_id=subject_id,
                    before=before,
                    after=after,
                )
            )
        session.commit()
    except SQLAlchemyError as exc:
        _rollback_quietly(session)
        raise DataUnavailableError(_DATA_UNAVAILABLE_MESSAGE) from exc
    except Exception:
        _rollback_quietly(session)
        raise

    return Member(
        user_id=subject.user_id,
        email=subject.email,
        active=subject.active,
        is_admin=subject.is_admin,
        can_approve=subject.can_approve,
    )


admin_router = APIRouter()


@admin_router.get(
    "/api/v1/admin/members",
    response_model=list[MemberResponse],
    summary="List memberships",
    description="Admin-only list of local membership rows, ordered by email.",
    dependencies=[Depends(require_admin)],
)
def admin_list_members(
    session: Session = Depends(get_session),
) -> list[MemberResponse]:
    return [MemberResponse(**row) for row in list_members(session)]


@admin_router.get(
    "/api/v1/admin/members/permission-history",
    response_model=list[PermissionHistoryResponse],
    summary="List permission history",
    description=(
        "Admin-only append-only log of accepted membership changes, newest "
        "first. Only rows produced by accepted patches appear here."
    ),
    dependencies=[Depends(require_admin)],
)
def admin_permission_history(
    limit: int = Query(default=100, ge=1, le=500, description="Max rows to return"),
    offset: int = Query(default=0, ge=0, description="Offset for pagination"),
    session: Session = Depends(get_session),
) -> list[PermissionHistoryResponse]:
    return [
        PermissionHistoryResponse(**row)
        for row in list_permission_history(session, limit=limit, offset=offset)
    ]


@admin_router.patch(
    "/api/v1/admin/members/{user_id}",
    response_model=MemberResponse,
    summary="Update membership flags",
    description=(
        "Admin-only partial update of active / is_admin / can_approve. "
        "Omitted fields stay unchanged. Rejected when it would remove the "
        "last active administrator (409 last_admin_protected)."
    ),
)
def admin_patch_member(
    user_id: UUID,
    patch: MemberPatch,
    admin: Member = Depends(require_admin),
    session: Session = Depends(get_session),
) -> MemberResponse:
    changes = patch.model_dump(exclude_none=True)
    member = apply_member_patch(
        session,
        actor_id=admin.user_id,
        subject_id=user_id,
        changes=changes,
    )
    return MemberResponse(
        user_id=str(member.user_id),
        email=member.email,
        active=member.active,
        is_admin=member.is_admin,
        can_approve=member.can_approve,
    )
