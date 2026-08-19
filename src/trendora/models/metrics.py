"""Time-series metric observations. Values are never overwritten in place."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from trendora.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from trendora.models.catalog import RetentionPolicy, Source
    from trendora.models.entities import ContentItem, Publisher


class MetricSnapshot(TimestampMixin, Base):
    """One collected observation of a single metric for content or a publisher."""

    __tablename__ = "metric_snapshots"
    __table_args__ = (
        CheckConstraint(
            "(content_item_id IS NOT NULL AND publisher_id IS NULL) "
            "OR (content_item_id IS NULL AND publisher_id IS NOT NULL)",
            name="subject_xor",
        ),
        Index(
            "uq_metric_snapshots_content_metric_collected",
            "content_item_id",
            "metric_name",
            "collected_at",
            unique=True,
            postgresql_where=text("content_item_id IS NOT NULL"),
        ),
        Index(
            "uq_metric_snapshots_publisher_metric_collected",
            "publisher_id",
            "metric_name",
            "collected_at",
            unique=True,
            postgresql_where=text("publisher_id IS NOT NULL"),
        ),
        Index("ix_metric_snapshots_observed_at", "observed_at"),
        Index("ix_metric_snapshots_retain_until", "retain_until"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("sources.id"), nullable=False, index=True
    )
    content_item_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("content_items.id"), nullable=True
    )
    publisher_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("publishers.id"), nullable=True
    )
    metric_name: Mapped[str] = mapped_column(Text, nullable=False)
    metric_value: Mapped[int] = mapped_column(BigInteger, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    retention_policy_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("retention_policies.id"), nullable=True, index=True
    )
    retain_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    source: Mapped[Source] = relationship(back_populates="metric_snapshots")
    content_item: Mapped[ContentItem | None] = relationship(back_populates="metric_snapshots")
    publisher: Mapped[Publisher | None] = relationship(back_populates="metric_snapshots")
    retention_policy: Mapped[RetentionPolicy | None] = relationship(
        back_populates="metric_snapshots"
    )
