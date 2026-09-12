"""Persisted research reports (M28A). Append-only snapshots; no read endpoints yet."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import DateTime, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from trendora.db.base import Base


class ResearchReportRecord(Base):
    """Append-only record for persisted research reports. No updated_at, immutable rows."""

    __tablename__ = "research_reports"

    id: Mapped[Uuid] = mapped_column(
        Uuid,
        primary_key=True,
        server_default="gen_random_uuid()",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default="now()",
        nullable=False,
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)  # "completed" or "no_evidence"
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    markets: Mapped[list[str]] = mapped_column(JSONB, nullable=False)  # ["SG", "ID"]
    source_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)  # ["youtube"]
    date_from: Mapped[date] = mapped_column(DateTime(timezone=False), nullable=False)
    date_to: Mapped[date] = mapped_column(DateTime(timezone=False), nullable=False)
    report: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)  # full snapshot
