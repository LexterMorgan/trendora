"""Membership and permission history (Gate A).

Rows are provisioned by the owner (SQL or dashboard invite flow); the API
never creates members. Append-only permission history records every accepted
membership change alongside the mutation that produced it.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, DateTime, Identity, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from trendora.db.base import Base, TimestampMixin


class Membership(TimestampMixin, Base):
    """One authorized user. Identity comes from Supabase; flags gate access."""

    __tablename__ = "memberships"

    user_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    is_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    can_approve: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )


class MembershipPermissionHistory(Base):
    """Append-only record of accepted membership changes."""

    __tablename__ = "membership_permission_history"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    actor_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    subject_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    before: Mapped[dict] = mapped_column(JSONB, nullable=False)
    after: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )
