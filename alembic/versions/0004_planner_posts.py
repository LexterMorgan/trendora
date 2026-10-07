"""planner_posts and planner_post_activity, RLS, and per-role revokes (P2A)

Revision ID: 0004_planner_posts
Revises: 0003_memberships_history
Create Date: 2026-10-01

Additive only: two new tables and their access protection. Downgrade destroys
every planner record, so it must never run against real drafts without a
separate owner approval. Memberships, permission history, and research
snapshots are untouched in both directions.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_planner_posts"
down_revision: Union[str, Sequence[str], None] = "0003_memberships_history"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PLANNER_TABLES = ("planner_posts", "planner_post_activity")
ROLES = ("anon", "authenticated")


def _protect_new_tables() -> None:
    # RLS with no policies plus explicit revokes: the trusted backend keeps
    # access through its own role, while PostgREST browser roles get nothing.
    for table_name in PLANNER_TABLES:
        op.execute(sa.text(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY"))
    tables = ", ".join(f"'{name}'" for name in PLANNER_TABLES)
    op.execute(
        sa.text(
            "REVOKE ALL ON public.planner_posts, public.planner_post_activity "
            "FROM PUBLIC"
        )
    )
    for role in ROLES:
        op.execute(
            sa.text(
                f"""
DO $revoke$
DECLARE t text;
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
        FOREACH t IN ARRAY ARRAY[{tables}] LOOP
            EXECUTE format('REVOKE ALL ON public.%I FROM {role}', t);
        END LOOP;
    END IF;
END
$revoke$;
"""
            )
        )


def upgrade() -> None:
    op.create_table(
        "planner_posts",
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("platform", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("caption", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("hook", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "creative_brief", sa.Text(), server_default=sa.text("''"), nullable=False
        ),
        sa.Column(
            "asset_links",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("planned_date", sa.Date(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'idea'"), nullable=False),
        sa.Column("assignee_id", sa.Uuid(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "content_revision", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.Column("create_request_id", sa.Uuid(), nullable=False),
        sa.Column("create_payload_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_planner_posts"),
        sa.UniqueConstraint(
            "created_by", "create_request_id", name="uq_planner_posts_created_by"
        ),
        sa.CheckConstraint("status IN ('idea', 'working')", name="status"),
        sa.CheckConstraint("version > 0", name="version_positive"),
        sa.CheckConstraint("content_revision > 0", name="content_revision_positive"),
        sa.ForeignKeyConstraint(
            ["assignee_id"],
            ["memberships.user_id"],
            name="fk_planner_posts_assignee_id_memberships",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["memberships.user_id"],
            name="fk_planner_posts_created_by_memberships",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["memberships.user_id"],
            name="fk_planner_posts_updated_by_memberships",
        ),
    )
    op.create_index(
        "ix_planner_posts_updated_at", "planner_posts", ["updated_at", "id"]
    )
    op.create_table(
        "planner_post_activity",
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_planner_post_activity"),
        sa.CheckConstraint(
            "event_type IN ('created', 'updated', 'archived', 'restored')",
            name="event_type",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["memberships.user_id"],
            name="fk_planner_post_activity_actor_id_memberships",
        ),
        sa.ForeignKeyConstraint(
            ["post_id"],
            ["planner_posts.id"],
            name="fk_planner_post_activity_post_id_planner_posts",
        ),
    )
    op.create_index(
        "ix_planner_post_activity_post_id",
        "planner_post_activity",
        ["post_id", "created_at", "id"],
    )
    _protect_new_tables()


def downgrade() -> None:
    # Deliberate data loss: planner posts and activity exist only here.
    # Memberships, permission history, and research reports stay untouched.
    op.drop_table("planner_post_activity")
    op.drop_table("planner_posts")
