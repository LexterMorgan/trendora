"""Report save and recovery (P3 Slice A).

Generation returns the report even when persistence fails. This module adds an
explicit, idempotent save that can be retried with the same request key without
repeating research or AI, plus an authenticated recovery path that acknowledges
a previously committed save.

Identity comes from ``require_member``. The snapshot is validated strictly and
fingerprinted canonically before it is trusted. A matching committed row is
returned as-is; a different snapshot under the same key conflicts. A matching
replay outside the viewer's history window returns identity and classification
only, never the snapshot body.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from trendora.api.auth import Member, require_member
from trendora.api.body_limit import BodyLimitRoute
from trendora.api.deps import get_session
from trendora.api.errors import (
    ApiError,
    AuthInactiveError,
    AuthNotMemberError,
    DataUnavailableError,
)
from trendora.api.report_snapshot import (
    SCHEMA_VERSION,
    ReportSnapshot,
    snapshot_fingerprint,
)
from trendora.models.membership import Membership
from trendora.config import get_settings
from trendora.research.repository import (
    ReportRecoveryInvalidError,
    ReportSaveConflictError,
    ReportSourceExpiredError,
    find_report_by_key,
    save_report_snapshot,
)

REPORT_SAVE_BODY_LIMIT = 8_388_608


class ReportSaveConflictErrorApi(ApiError):
    status_code = 409
    code = "report_save_conflict"


class ReportSaveTooLargeError(ApiError):
    status_code = 413
    code = "report_request_too_large"


class ReportSaveInvalidError(ApiError):
    status_code = 422
    code = "invalid_report_snapshot"


class ReportExpiredError(ApiError):
    status_code = 410
    code = "report_expired"


class ReportSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(strict=True)
    request_id: UUID
    snapshot: dict[str, Any]
    recovery_receipt: str | None = Field(default=None, max_length=2_048)


class PersistenceOutcome(BaseModel):
    status: str
    request_id: str | None
    report_id: str | None
    snapshot_origin: str
    error_code: str | None


class Acknowledgment:
    """Immutable acknowledgment copied from the row before the transaction ends.

    Reading ORM attributes after commit/rollback can trigger a reload on an
    expired or detached instance, so the values the response needs are copied
    while the transaction is still open.
    """

    __slots__ = ("report_id", "snapshot_origin", "created")

    def __init__(self, *, report_id: str, snapshot_origin: str, created: bool) -> None:
        self.report_id = report_id
        self.snapshot_origin = snapshot_origin
        self.created = created


class ReportSaveResponse(BaseModel):
    persistence: PersistenceOutcome
    snapshot: dict[str, Any] | None = None


@contextmanager
def _write_guard(session: Session) -> Iterator[None]:
    """Roll back on rejection; driver failures become one fixed 503."""
    try:
        yield
    except SQLAlchemyError as exc:
        _rollback_quietly(session)
        raise DataUnavailableError("report save is unavailable") from exc
    except Exception:
        _rollback_quietly(session)
        raise


def _rollback_quietly(session: Session) -> None:
    try:
        session.rollback()
    except SQLAlchemyError:
        pass


def _lock_membership(session: Session, actor_id: UUID) -> Membership:
    """Re-check active membership inside the write transaction."""
    row = session.execute(
        select(Membership)
        .where(Membership.user_id == actor_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if row is None:
        raise AuthNotMemberError("no membership exists for this user")
    if not row.active:
        raise AuthInactiveError("membership is inactive")
    return row


def _validate(body: ReportSaveRequest) -> ReportSnapshot:
    if body.schema_version != SCHEMA_VERSION:
        raise ReportSaveInvalidError("unsupported snapshot schema version")
    try:
        return ReportSnapshot.model_validate(body.snapshot)
    except ValidationError as exc:
        raise ReportSaveInvalidError("report snapshot failed validation") from exc


def _metadata(snapshot: dict[str, Any]) -> dict[str, Any]:
    query = (snapshot.get("research") or {}).get("query") or {}
    return {
        "topic": query.get("topic") or "untitled",
        "markets": list(query.get("markets") or []),
        "source_codes": list(query.get("sources") or []),
        "date_from": query.get("date_from"),
        "date_to": query.get("date_to"),
    }


def save_report_for_actor(
    session: Session, *, actor_id: UUID, body: ReportSaveRequest
) -> Acknowledgment:
    """Validate, fingerprint, and commit one snapshot for ``(actor, key)``.

    Returns an :class:`Acknowledgment` whose values were copied while the
    transaction was still open, so the caller never reads an expired ORM
    attribute. A replay or conflict rolls back only this unit of work; the
    membership lock is released by that rollback, which is correct because the
    authorization decision has already been made and no write was committed.
    """
    snapshot = _validate(body).model_dump(mode="json")
    fingerprint = snapshot_fingerprint(snapshot)
    metadata = _metadata(snapshot)

    with _write_guard(session):
        _lock_membership(session, actor_id)
        try:
            record, created = save_report_snapshot(
                session,
                actor_id=actor_id,
                request_id=body.request_id,
                snapshot=snapshot,
                fingerprint=fingerprint,
                origin="client_supplied",
                recovery_receipt=body.recovery_receipt,
                signing_key=getattr(get_settings(), "report_recovery_signing_key", None),
                status=str(snapshot.get("status") or "completed"),
                **metadata,
            )
        except ReportSaveConflictError as exc:
            raise ReportSaveConflictErrorApi(str(exc)) from exc
        except ReportRecoveryInvalidError as exc:
            raise ReportSaveInvalidError("report recovery evidence could not be verified") from exc
        except ReportSourceExpiredError as exc:
            raise ReportExpiredError(
                "This source data has expired or its collection date cannot be verified. "
                "It cannot be saved under a new key."
            ) from exc
        # Copy the acknowledgment before commit/rollback expires the instance.
        acknowledgment = Acknowledgment(
            report_id=str(record.id),
            snapshot_origin=record.snapshot_origin,
            created=created,
        )
        if created:
            session.commit()
        else:
            session.rollback()
    return acknowledgment


def outcome_for(
    acknowledgment: Acknowledgment, *, request_id: UUID
) -> PersistenceOutcome:
    return PersistenceOutcome(
        status="saved",
        request_id=str(request_id),
        report_id=acknowledgment.report_id,
        snapshot_origin=acknowledgment.snapshot_origin,
        error_code=None,
    )


class ReportSaveBodyLimitRoute(BodyLimitRoute):
    """8 MiB streamed cap for the full report snapshot envelope."""

    body_limit = REPORT_SAVE_BODY_LIMIT

    def too_large(self) -> Exception:
        return ReportSaveTooLargeError("report snapshot is too large")


report_save_router = APIRouter(route_class=ReportSaveBodyLimitRoute)


@report_save_router.post(
    "/api/v1/research/reports/save",
    response_model=ReportSaveResponse,
    summary="Save or recover a report snapshot",
    description=(
        "Idempotent save keyed on (actor, request_id). A matching committed "
        "snapshot returns its identity; a different snapshot conflicts. "
        "Validates strictly and never runs research or AI."
    ),
)
def save_report(
    body: ReportSaveRequest,
    session: Session = Depends(get_session),
    member: Member = Depends(require_member),
) -> Any:
    acknowledgment = save_report_for_actor(
        session, actor_id=member.user_id, body=body
    )
    response = ReportSaveResponse(
        persistence=outcome_for(acknowledgment, request_id=body.request_id)
    )
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=201 if acknowledgment.created else 200,
        content=response.model_dump(mode="json"),
    )


__all__ = [
    "REPORT_SAVE_BODY_LIMIT",
    "ReportSaveRequest",
    "ReportSaveResponse",
    "PersistenceOutcome",
    "ReportSaveConflictErrorApi",
    "ReportSaveTooLargeError",
    "ReportSaveInvalidError",
    "report_save_router",
    "save_report_for_actor",
    "find_report_by_key",
]
