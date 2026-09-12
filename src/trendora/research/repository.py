"""Data access layer for persisted research reports (M28B)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from trendora.models.research import ResearchReportRecord


def get_report_records(
    session: Session,
    *,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """List persisted report records with metadata only.

    Returns two values:
    - list of summary dicts (id, created_at, status, topic, markets,
      source_codes, date range)
    - total count across all pages (for pagination)

    Ordered by ``created_at`` DESC (newest first).
    """
    total_count = session.query(ResearchReportRecord).count()
    records = (
        session.query(ResearchReportRecord)
        .order_by(ResearchReportRecord.created_at.desc())
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
        }
        for record in records
    ]
    return summaries, total_count


def get_report_record_by_id(session: Session, report_id: str) -> dict[str, Any] | None:
    """Fetch a full report snapshot by UUID string; ``None`` when absent/invalid."""
    try:
        uuid_id = UUID(report_id)
    except (ValueError, AttributeError):
        return None

    record = (
        session.query(ResearchReportRecord)
        .filter(ResearchReportRecord.id == uuid_id)
        .first()
    )
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
        "report": record.report,
    }
