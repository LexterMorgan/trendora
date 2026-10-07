"""origin source collection time may be unresolved (P3 correction)

Revision ID: 0007_origin_collected_at_nullable
Revises: 0006_planner_research_origin
Create Date: 2026-10-02

A source reference whose original collection time cannot be trusted (missing,
malformed, future, or drawn from a client-supplied snapshot) keeps its identity
but records no collection time. ``collected_at`` becomes nullable so this
unresolved status is honest; ``expires_at`` still bounds any cleanup. No row is
rewritten and the authored post is untouched.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_origin_collected_at_nullable"
down_revision: Union[str, Sequence[str], None] = "0006_planner_research_origin"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "planner_post_origin_sources"


def upgrade() -> None:
    # This revision exceeds Alembic's default 32-character version column.
    op.alter_column(
        "alembic_version", "version_num",
        existing_type=sa.String(32), type_=sa.String(64),
    )
    op.alter_column(
        TABLE,
        "collected_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )


def downgrade() -> None:
    # Keep the wider version column: Alembic updates it after this function.
    # Unresolved rows have no collection time; backfill with the expiry bound
    # so the column can be made NOT NULL again.
    op.execute(
        sa.text(f"UPDATE {TABLE} SET collected_at = expires_at WHERE collected_at IS NULL")
    )
    op.alter_column(
        TABLE,
        "collected_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )
