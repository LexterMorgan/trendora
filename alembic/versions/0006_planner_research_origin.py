"""planner research origin: immutable import lineage and source sidecar (P3)

Revision ID: 0006_planner_research_origin
Revises: 0005_report_save_recovery
Create Date: 2026-10-02

Additive: planner_posts gains a nullable immutable origin snapshot, and a new
planner_post_origin_sources sidecar holds minimal source references with their
own expiry. Existing rows keep NULL origin. RLS and the existing grants are
left intact; the new table is protected the same way as the other planner
tables.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_planner_research_origin"
down_revision: Union[str, Sequence[str], None] = "0005_report_save_recovery"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "planner_post_origin_sources"
ROLES = ("anon", "authenticated")


def _protect_new_table() -> None:
    op.execute(
        sa.text(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    )
    op.execute(sa.text(f"REVOKE ALL ON public.{TABLE} FROM PUBLIC"))
    for role in ROLES:
        op.execute(
            sa.text(
                f"""
DO $revoke$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
        EXECUTE format('REVOKE ALL ON public.{TABLE} FROM {role}');
    END IF;
END
$revoke$;
"""
            )
        )


def upgrade() -> None:
    op.add_column(
        "planner_posts",
        sa.Column("origin", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_table(
        TABLE,
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column("source_code", sa.Text(), nullable=False),
        sa.Column("content_external_id", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=f"pk_{TABLE}"),
        sa.ForeignKeyConstraint(
            ["post_id"],
            ["planner_posts.id"],
            name=f"fk_{TABLE}_post_id_planner_posts",
        ),
        sa.CheckConstraint("retention_days > 0", name="retention_positive"),
        sa.UniqueConstraint(
            "post_id",
            "source_code",
            "content_external_id",
            name=f"uq_{TABLE}_post_id",
        ),
    )
    op.create_index(
        f"ix_{TABLE}_expires_at",
        TABLE,
        ["expires_at"],
    )
    _protect_new_table()


def downgrade() -> None:
    op.drop_index(f"ix_{TABLE}_expires_at", table_name=TABLE)
    op.drop_table(TABLE)
    op.drop_column("planner_posts", "origin")
