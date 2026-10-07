"""Persisted research reports (M28A). Append-only snapshots; no read endpoints yet."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Date, DateTime, String, Text, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from trendora.db.base import Base

SNAPSHOT_ORIGINS = ("server_generated", "client_supplied", "legacy_unclassified")


class ResearchReportRecord(Base):
    """Append-only record for persisted research reports. No updated_at, immutable rows."""

    __tablename__ = "research_reports"

    id: Mapped[Uuid] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)  # "completed" or "no_evidence"
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    markets: Mapped[list[str]] = mapped_column(JSONB, nullable=False)  # ["SG", "ID"]
    source_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)  # ["youtube"]
    date_from: Mapped[date] = mapped_column(Date, nullable=False)
    date_to: Mapped[date] = mapped_column(Date, nullable=False)
    report: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)  # full snapshot
    created_by: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    save_request_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    snapshot_origin: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'legacy_unclassified'"),
    )
