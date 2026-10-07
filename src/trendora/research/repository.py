"""Data access layer for persisted research reports (M28B).

``visible_from`` implements the Gate A rolling visibility window: rows with
``created_at >= visible_from`` are visible, ``None`` means no lower bound
(admins). The filter is applied before counting and before pagination, so
totals and offsets only ever describe visible rows. Direct-ID reads apply the
same rule, so a listed row is fetchable and a hidden row is not.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from trendora.models.research import ResearchReportRecord


class ReportSaveConflictError(Exception):
    """Same actor and key already committed a different snapshot."""


class ReportSourceExpiredError(Exception):
    """A new key cannot restore expired source material."""


class ReportRecoveryInvalidError(Exception):
    """A new source-bearing recovery lacks matching server evidence."""


def _record_fingerprint(record: ResearchReportRecord) -> str | None:
    return record.payload_hash


def find_report_by_key(
    session: Session, *, actor_id: UUID, request_id: UUID
) -> ResearchReportRecord | None:
    """Return the committed row for ``(actor, key)`` when one exists."""
    return session.execute(
        select(ResearchReportRecord).where(
            ResearchReportRecord.created_by == actor_id,
            ResearchReportRecord.save_request_id == request_id,
        )
    ).scalar_one_or_none()


def insert_report_snapshot(
    session: Session,
    *,
    snapshot: dict[str, Any],
    fingerprint: str,
    topic: str,
    markets: list[str],
    source_codes: list[str],
    date_from: Any,
    date_to: Any,
    status: str,
    origin: str,
    request_id: UUID,
    created_by: UUID | None,
    source_expires_at: datetime | None = None,
) -> ResearchReportRecord:
    """Append one server-generated report snapshot for an authenticated actor.

    The actor and request key are recorded so a later recovery by the same
    authenticated actor finds this row and acknowledges it instead of inserting
    a duplicate. The row is still append-only: ``find_report_by_key`` is the
    idempotency read used by recovery.
    """
    record = ResearchReportRecord(
        status=status,
        topic=topic,
        markets=markets,
        source_codes=source_codes,
        date_from=date_from,
        date_to=date_to,
        report=snapshot,
        created_by=created_by,
        save_request_id=request_id,
        payload_hash=fingerprint,
        snapshot_origin=origin,
        source_expires_at=source_expires_at,
    )
    session.add(record)
    session.flush()
    return record


def save_report_snapshot(
    session: Session,
    *,
    actor_id: UUID,
    request_id: UUID,
    snapshot: dict[str, Any],
    fingerprint: str,
    topic: str,
    markets: list[str],
    source_codes: list[str],
    date_from: Any,
    date_to: Any,
    status: str,
    origin: str,
    recovery_receipt: str | None = None,
    signing_key: str | None = None,
) -> tuple[ResearchReportRecord, bool]:
    """Insert one report snapshot once per ``(actor, key)``.

    Returns ``(record, created)``. A replay with the same fingerprint returns
    the stored row (``created=False``); a different fingerprint raises
    ``ReportSaveConflictError``. Concurrent duplicates are caught by the unique
    constraint and resolved by re-reading the winner.

    The insert runs inside a SAVEPOINT, so losing the race rolls back only the
    savepoint. The caller's membership lock and outer transaction survive; a
    plain ``rollback()`` here would silently drop the membership protection.
    """
    existing = find_report_by_key(session, actor_id=actor_id, request_id=request_id)
    if existing is not None:
        if _record_fingerprint(existing) != fingerprint:
            raise ReportSaveConflictError("report save conflicts with an existing save")
        return existing, False

    source_expires_at = None
    if origin == "client_supplied":
        from trendora.research.recovery import (
            RecoveryReceiptError, RecoveryReceiptExpiredError, verify_recovery_receipt,
        )
        from trendora.retention import report_sources_expired

        now = datetime.now(timezone.utc)
        if report_sources_expired(snapshot, provenance="client_supplied", now=now):
            try:
                source_expires_at = verify_recovery_receipt(
                    recovery_receipt, actor_id=actor_id, request_id=request_id,
                    fingerprint=fingerprint, signing_key=signing_key, now=now,
                )
            except RecoveryReceiptExpiredError as exc:
                raise ReportSourceExpiredError("original source deadline has expired") from exc
            except RecoveryReceiptError as exc:
                raise ReportRecoveryInvalidError("report recovery evidence could not be verified") from exc
            if report_sources_expired(
                snapshot, provenance=origin, now=now, source_expires_at=source_expires_at,
            ):
                raise ReportSourceExpiredError("original source deadline is unavailable or expired")

    record = ResearchReportRecord(
        status=status,
        topic=topic,
        markets=markets,
        source_codes=source_codes,
        date_from=date_from,
        date_to=date_to,
        report=snapshot,
        created_by=actor_id,
        save_request_id=request_id,
        payload_hash=fingerprint,
        snapshot_origin=origin,
        source_expires_at=source_expires_at,
    )
    try:
        with session.begin_nested():
            session.add(record)
    except IntegrityError:
        # Lost the race to a concurrent save: re-read the winner under the
        # caller's still-held membership lock.
        winner = find_report_by_key(session, actor_id=actor_id, request_id=request_id)
        if winner is not None and _record_fingerprint(winner) == fingerprint:
            return winner, False
        raise ReportSaveConflictError(
            "report save conflicts with an existing save"
        ) from None
    return record, True


def get_report_records(
    session: Session,
    *,
    limit: int = 50,
    offset: int = 0,
    visible_from: datetime | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """List persisted report records with metadata only.

    Returns two values:
    - list of summary dicts (id, created_at, status, topic, markets,
      source_codes, date range)
    - total count of *visible* records across all pages (for pagination)

    Ordered by ``created_at`` DESC (newest first), ``id`` DESC as the
    tiebreak for identical timestamps.
    """
    query = session.query(ResearchReportRecord)
    if visible_from is not None:
        query = query.filter(ResearchReportRecord.created_at >= visible_from)
    total_count = query.count()
    records = (
        query.order_by(
            ResearchReportRecord.created_at.desc(), ResearchReportRecord.id.desc()
        )
        .offset(offset)
        .limit(limit)
        .all()
    )
    summaries = [
        {
            "id": str(record.id),
            "created_at": record.created_at.isoformat(),
            "status": record.status,
            "topic": record.topic,
            "markets": record.markets,
            "source_codes": record.source_codes,
            "date_from": record.date_from.isoformat(),
            "date_to": record.date_to.isoformat(),
            "snapshot_origin": record.snapshot_origin,
        }
        for record in records
    ]
    return summaries, total_count


def get_report_record_by_id(
    session: Session,
    report_id: str,
    *,
    visible_from: datetime | None = None,
    lock_for_import: bool = False,
) -> dict[str, Any] | None:
    """Fetch a full report snapshot by UUID string; ``None`` when absent,
    invalid, or outside the caller's visibility window.

    Imports hold a shared row lock until their existing transaction commits,
    so expiry cannot scrub a report and then have an import restore its old
    source material. Ordinary reads keep their existing behavior.
    """
    try:
        uuid_id = UUID(report_id)
    except (ValueError, AttributeError):
        return None

    query = session.query(ResearchReportRecord).filter(
        ResearchReportRecord.id == uuid_id
    )
    if visible_from is not None:
        query = query.filter(ResearchReportRecord.created_at >= visible_from)
    if lock_for_import:
        query = query.with_for_update(read=True).execution_options(populate_existing=True)
    record = query.first()
    if record is None:
        return None

    return {
        "id": str(record.id),
        "created_at": record.created_at.isoformat(),
        "status": record.status,
        "topic": record.topic,
        "markets": record.markets,
        "source_codes": record.source_codes,
        "date_from": record.date_from.isoformat(),
        "date_to": record.date_to.isoformat(),
        "snapshot_origin": record.snapshot_origin,
        "source_expires_at": getattr(record, "source_expires_at", None),
        "report": record.report,
    }
