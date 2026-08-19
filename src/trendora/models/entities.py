"""Publishers (channels/accounts) and content items."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Text, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from trendora.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from trendora.models.catalog import Market, Source, Topic
    from trendora.models.metrics import MetricSnapshot


class Publisher(TimestampMixin, Base):
    """Source-local entity: YouTube channel, GitHub owner, HN user, etc."""

    __tablename__ = "publishers"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_publishers_source_external_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("sources.id"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    market_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("markets.id"), nullable=True, index=True
    )
    source_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    retain_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    source: Mapped[Source] = relationship(back_populates="publishers")
    market: Mapped[Market | None] = relationship(back_populates="publishers")
    content_items: Mapped[list[ContentItem]] = relationship(back_populates="publisher")
    metric_snapshots: Mapped[list[MetricSnapshot]] = relationship(back_populates="publisher")


class ContentItem(TimestampMixin, Base):
    """Canonical content record (video, story, question, repository, article)."""

    __tablename__ = "content_items"
    __table_args__ = (
        UniqueConstraint(
            "source_id", "external_id", name="uq_content_items_source_external_id"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("sources.id"), nullable=False, index=True
    )
    publisher_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("publishers.id"), nullable=True, index=True
    )
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    market_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("markets.id"), nullable=True, index=True
    )
    source_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    retain_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    source: Mapped[Source] = relationship(back_populates="content_items")
    publisher: Mapped[Publisher | None] = relationship(back_populates="content_items")
    market: Mapped[Market | None] = relationship(back_populates="content_items")
    topic_links: Mapped[list[ContentItemTopic]] = relationship(back_populates="content_item")
    metric_snapshots: Mapped[list[MetricSnapshot]] = relationship(back_populates="content_item")


class ContentItemTopic(Base):
    """Many-to-many link between content items and topics."""

    __tablename__ = "content_item_topics"

    content_item_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("content_items.id"), primary_key=True
    )
    topic_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("topics.id"), primary_key=True)

    content_item: Mapped[ContentItem] = relationship(back_populates="topic_links")
    topic: Mapped[Topic] = relationship(back_populates="content_links")
