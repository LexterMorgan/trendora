"""Catalog tables: sources, markets, topics, retention policies."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Integer, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from trendora.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from trendora.models.entities import ContentItem, ContentItemTopic, Publisher
    from trendora.models.metrics import MetricSnapshot


class Source(TimestampMixin, Base):
    """External platform registry. Not a connector implementation."""

    __tablename__ = "sources"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    classification: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    publishers: Mapped[list[Publisher]] = relationship(back_populates="source")
    content_items: Mapped[list[ContentItem]] = relationship(back_populates="source")
    metric_snapshots: Mapped[list[MetricSnapshot]] = relationship(back_populates="source")


class Market(TimestampMixin, Base):
    """Primary geographic markets (ISO 3166-1 alpha-2)."""

    __tablename__ = "markets"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)

    publishers: Mapped[list[Publisher]] = relationship(back_populates="market")
    content_items: Mapped[list[ContentItem]] = relationship(back_populates="market")


class Topic(TimestampMixin, Base):
    """Technology / education topic taxonomy."""

    __tablename__ = "topics"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    content_links: Mapped[list[ContentItemTopic]] = relationship(back_populates="topic")


class RetentionPolicy(TimestampMixin, Base):
    """Documented retention hooks. Jobs are not implemented in Milestone 1."""

    __tablename__ = "retention_policies"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    applies_to: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    metric_snapshots: Mapped[list[MetricSnapshot]] = relationship(
        back_populates="retention_policy"
    )
