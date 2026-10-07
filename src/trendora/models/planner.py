"""Manual shared planner posts and their append-only activity (P2A).

Posts are editable working drafts, never research snapshots: no origin, no
citation payload, no approval or publication columns. ``version`` guards every
mutation, ``content_revision`` tracks text that would invalidate a future
approval, and ``create_request_id`` plus ``create_payload_hash`` make creation
retry-safe. Archive is a timestamp, not a status. All membership references
are plain foreign keys with no cascade: deactivated and historical members stay
resolvable.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from trendora.db.base import Base, TimestampMixin

POST_STATUSES = ("idea", "working")
ACTIVITY_EVENTS = ("created", "updated", "archived", "restored")


class PlannerPost(TimestampMixin, Base):
    """One shared manual post. Both editors see every row from creation."""

    __tablename__ = "planner_posts"
    __table_args__ = (
        CheckConstraint("status IN ('idea', 'working')", name="status"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint("content_revision > 0", name="content_revision_positive"),
        UniqueConstraint(
            "created_by",
            "create_request_id",
            name="uq_planner_posts_created_by",
        ),
        Index("ix_planner_posts_updated_at", "updated_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    platform: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("''")
    )
    caption: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("''")
    )
    hook: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    creative_brief: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("''")
    )
    asset_links: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    notes: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    planned_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'idea'")
    )
    assignee_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("memberships.user_id"), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    content_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    created_by: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("memberships.user_id"), nullable=False
    )
    updated_by: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("memberships.user_id"), nullable=False
    )
    create_request_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    create_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Immutable import lineage: selected item, parent context, and the report
    # identity it came from. NULL for manually created posts. User edits never
    # rewrite this column.
    origin: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class PlannerPostOriginSource(Base):
    """Minimal source-reference sidecar for an imported post's origin.

    Holds only what the origin view needs to attribute a citation: source
    code, external id, URL, and the trusted original collection time. Raw API
    metadata (titles, descriptions, statistics) is never copied here. Rows may
    be deleted by expiry cleanup; the authored post is untouched.
    """

    __tablename__ = "planner_post_origin_sources"

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    post_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("planner_posts.id"), nullable=False
    )
    source_code: Mapped[str] = mapped_column(Text, nullable=False)
    content_external_id: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # NULL means the collection time could not be trusted (missing, malformed,
    # future, or from a client-supplied snapshot). Expiry never manufactures a
    # collection time for these rows.
    collected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PlannerPostActivity(Base):
    """Append-only decision log: field names and outcomes, never draft text."""

    __tablename__ = "planner_post_activity"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('created', 'updated', 'archived', 'restored')",
            name="event_type",
        ),
        Index("ix_planner_post_activity_post_id", "post_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    post_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("planner_posts.id"), nullable=False
    )
    actor_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("memberships.user_id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
