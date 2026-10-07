"""Shared planner API (P2A): post CRUD + assignment options.

Thin transport over ``trendora.planner``. Identity comes from
``require_member`` (verified claims + active membership); no route trusts a
request field for actor, creator, approval, or origin. Reads never select
draft text they do not need, writes pass the caller's full snapshot straight
through, and every planner service error keeps its own code.

POST and PUT on this router stream the request body through a local
131072-byte cap (shared ``BodyLimitRoute``) so an oversized draft is refused
before it reaches validation or the database; Content-Length is not trusted.
Other routers supply their own cap.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from trendora.api.auth import Member, get_utc_now, report_visible_from, require_member
from trendora.api.body_limit import BodyLimitRoute
from trendora.api.deps import get_session
from trendora.api.errors import ApiError
from trendora.planner import (
    PlannerCreateConflictError,
    PlannerMemberOption,
    PostCreate,
    PostRead,
    PostSummary,
    PostUpdate,
    PostVersionRequest,
    create_post,
    find_import_replay,
    get_post,
    import_post,
    list_assignees,
    list_posts,
    set_archived,
    update_post,
)
from trendora.planner_origin import (
    ImportOverflowError,
    ImportSelectionError,
    build_origin_sources,
    read_origin,
    resolve_selection,
)

BODY_LIMIT = 131_072


class PlannerRequestTooLargeError(ApiError):
    """Refused before validation: the streamed body exceeded the cap."""

    status_code = 413
    code = "planner_request_too_large"


class PlannerBodyLimitRoute(BodyLimitRoute):
    """APIRoute that reads POST/PUT bodies itself and enforces ``BODY_LIMIT``."""

    body_limit = BODY_LIMIT

    def too_large(self) -> Exception:
        return PlannerRequestTooLargeError("planner request body is too large")


planner_router = APIRouter(route_class=PlannerBodyLimitRoute)


@planner_router.get(
    "/api/v1/planner/members",
    response_model=list[PlannerMemberOption],
    summary="Assignment options",
    description="Active members for assignment, ordered by email. No flags.",
)
def read_planner_members(
    session: Session = Depends(get_session),
    _member: Member = Depends(require_member),
) -> list[PlannerMemberOption]:
    return list_assignees(session)


@planner_router.get(
    "/api/v1/planner/posts",
    response_model=list[PostSummary],
    summary="List planner posts",
    description="Shared summary rows for the active workspace. No draft text.",
)
def read_planner_posts(
    archived: bool = Query(False, description="Return archived posts instead."),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
    _member: Member = Depends(require_member),
) -> list[PostSummary]:
    return list_posts(session, archived=archived, limit=limit, offset=offset)


@planner_router.post(
    "/api/v1/planner/posts",
    summary="Create a planner post",
    description="Insert-once creation. A replayed request id returns 200 with "
    "the original id.",
)
def create_planner_post(
    payload: PostCreate,
    session: Session = Depends(get_session),
    member: Member = Depends(require_member),
) -> Response:
    post_id, created = create_post(session, actor_id=member.user_id, data=payload)
    return Response(
        content='{"id": "%s"}' % post_id,
        status_code=201 if created else 200,
        media_type="application/json",
    )


@planner_router.get(
    "/api/v1/planner/posts/{post_id}",
    response_model=PostRead,
    summary="Read one planner post",
    description="Full editable snapshot for a single shared post.",
)
def read_planner_post(
    post_id: UUID,
    session: Session = Depends(get_session),
    _member: Member = Depends(require_member),
) -> PostRead:
    return get_post(session, post_id=post_id)


@planner_router.put(
    "/api/v1/planner/posts/{post_id}",
    response_model=PostRead,
    summary="Replace a planner post",
    description="Full-snapshot replace behind one expected version. 409 when "
    "the version is stale or the post is archived.",
)
def replace_planner_post(
    post_id: UUID,
    payload: PostUpdate,
    session: Session = Depends(get_session),
    member: Member = Depends(require_member),
) -> PostRead:
    return update_post(
        session, actor_id=member.user_id, post_id=post_id, data=payload
    )


@planner_router.post(
    "/api/v1/planner/posts/{post_id}/archive",
    response_model=PostRead,
    summary="Archive a planner post",
    description="Soft archive behind one expected version.",
)
def archive_planner_post(
    post_id: UUID,
    payload: PostVersionRequest,
    session: Session = Depends(get_session),
    member: Member = Depends(require_member),
) -> PostRead:
    return set_archived(
        session,
        actor_id=member.user_id,
        post_id=post_id,
        expected_version=payload.expected_version,
        archived=True,
    )


@planner_router.post(
    "/api/v1/planner/posts/{post_id}/restore",
    response_model=PostRead,
    summary="Restore a planner post",
    description="Undo an archive behind one expected version.",
)
def restore_planner_post(
    post_id: UUID,
    payload: PostVersionRequest,
    session: Session = Depends(get_session),
    member: Member = Depends(require_member),
) -> PostRead:
    return set_archived(
        session,
        actor_id=member.user_id,
        post_id=post_id,
        expected_version=payload.expected_version,
        archived=False,
    )


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    report_id: UUID
    item_kind: Literal["idea", "brief"]
    item_index: int = Field(strict=True, ge=0)


class OriginSourceResponse(BaseModel):
    source_code: str
    content_external_id: str
    state: str
    url: str | None = None


class OriginResponse(BaseModel):
    report_id: str | None
    item_kind: str | None
    item_index: int | None
    parent_idea_index: int | None
    provenance: str
    context: dict[str, Any]
    sources: list[OriginSourceResponse]


class PlannerImportInvalidError(ApiError):
    status_code = 422
    code = "planner_import_invalid"


class PlannerImportNotFoundError(ApiError):
    status_code = 404
    code = "planner_report_not_found"


@planner_router.post(
    "/api/v1/planner/posts/import",
    summary="Import a research idea or brief",
    description=(
        "Resolve the selected item and its citation chain server-side, map it "
        "onto a new planner post, and record immutable origin. Insert-once on "
        "(actor, request_id)."
    ),
)
def import_planner_post(
    payload: ImportRequest,
    session: Session = Depends(get_session),
    member: Member = Depends(require_member),
    now: datetime = Depends(get_utc_now),
) -> Response:
    from trendora.research.repository import get_report_record_by_id

    selector = {
        "report_id": str(payload.report_id),
        "item_kind": payload.item_kind,
        "item_index": payload.item_index,
    }
    # Replay answers before the source is resolved again, so a lost response
    # can still be acknowledged after the report left the history window.
    try:
        existing = find_import_replay(
            session,
            actor_id=member.user_id,
            request_id=payload.request_id,
            selector=selector,
        )
    except PlannerCreateConflictError as exc:
        raise PlannerImportConflictError(str(exc)) from exc
    if existing is not None:
        return Response(
            content='{"id": "%s"}' % existing,
            status_code=200,
            media_type="application/json",
        )

    record = get_report_record_by_id(
        session,
        str(payload.report_id),
        visible_from=report_visible_from(member, now),
        lock_for_import=True,
    )
    if record is None or record.get("status") == "source_data_expired" or (
        record.get("report", {}).get("status") == "source_data_expired"
    ):
        raise PlannerImportNotFoundError("report is unknown or not accessible")
    snapshot = record["report"]
    try:
        fields, origin = resolve_selection(
            snapshot, item_kind=payload.item_kind, item_index=payload.item_index
        )
    except (ImportSelectionError, ImportOverflowError) as exc:
        raise PlannerImportInvalidError(str(exc)) from exc
    origin["provenance"] = record.get("snapshot_origin", "legacy_unclassified")
    sources = build_origin_sources(
        snapshot, origin, provenance=origin["provenance"], now=now,
        source_expires_at=record.get("source_expires_at"),
    )
    try:
        post_id, created = import_post(
            session,
            actor_id=member.user_id,
            request_id=payload.request_id,
            report_id=payload.report_id,
            item_kind=payload.item_kind,
            item_index=payload.item_index,
            fields=fields,
            origin=origin,
            origin_sources=sources,
        )
    except PlannerCreateConflictError as exc:
        raise PlannerImportConflictError(str(exc)) from exc
    return Response(
        content='{"id": "%s"}' % post_id,
        status_code=201 if created else 200,
        media_type="application/json",
    )


class PlannerImportConflictError(ApiError):
    status_code = 409
    code = "planner_create_conflict"


@planner_router.get(
    "/api/v1/planner/posts/{post_id}/origin",
    response_model=OriginResponse,
    summary="Read a post's research origin",
    description=(
        "Return the immutable import lineage with per-source state. Source "
        "detail is restricted by the caller's current report access."
    ),
)
def read_planner_origin(
    post_id: UUID,
    session: Session = Depends(get_session),
    member: Member = Depends(require_member),
    now: datetime = Depends(get_utc_now),
) -> OriginResponse:
    from trendora.research.repository import get_report_record_by_id

    post = get_post(session, post_id=post_id)
    # The report reference lives on the post origin; load it to decide access.
    from trendora.models.planner import PlannerPost

    row = session.get(PlannerPost, post_id)
    report_id = (row.origin or {}).get("report_id") if row and row.origin else None
    can_read_report = False
    if report_id:
        can_read_report = (
            get_report_record_by_id(
                session, report_id, visible_from=report_visible_from(member, now)
            )
            is not None
        )
    origin = read_origin(
        session, post_id=post_id, now=now, can_read_report=can_read_report
    )
    if origin is None:
        raise HTTPException(status_code=404, detail="Post origin not found")
    return OriginResponse(**origin)
