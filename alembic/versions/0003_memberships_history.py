"""memberships, permission history, RLS, and per-role revokes (Gate A)

Revision ID: 0003_memberships_history
Revises: 0002_research_reports
Create Date: 2026-09-29
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_memberships_history"
down_revision: Union[str, Sequence[str], None] = "0002_research_reports"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RLS_TABLES = (
    "memberships",
    "membership_permission_history",
    "research_reports",
)
ROLES = ("anon", "authenticated")


def _enable_row_level_security() -> None:
    # RLS with no policies: PostgREST anon/authenticated get nothing from
    # these tables; the table owner (and service_role) still can.
    for table_name in RLS_TABLES:
        op.execute(sa.text(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY"))


def _revoke_role_grants() -> None:
    # Supabase grants new tables to anon/authenticated by default, including
    # research_reports created before this revision. Revoke each role only if
    # it exists: on plain Postgres neither role exists and the revoke is
    # skipped; on Supabase both exist and both are emptied.
    tables = ", ".join(f"'{name}'" for name in RLS_TABLES)
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
        "memberships",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column(
            "active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "is_admin",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "can_approve",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("user_id", name="pk_memberships"),
        sa.UniqueConstraint("email", name="uq_memberships_email"),
    )
    op.create_table(
        "membership_permission_history",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("before", postgresql.JSONB(), nullable=False),
        sa.Column("after", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_membership_permission_history"),
    )
    op.create_index(
        "ix_membership_permission_history_actor_id",
        "membership_permission_history",
        ["actor_id"],
    )
    op.create_index(
        "ix_membership_permission_history_subject_id",
        "membership_permission_history",
        ["subject_id"],
    )
    op.create_index(
        "ix_membership_permission_history_created_at",
        "membership_permission_history",
        ["created_at"],
    )
    _enable_row_level_security()
    _revoke_role_grants()


def downgrade() -> None:
    # Deliberate data loss: membership and permission history exist only in
    # these two tables. research_reports and its RLS stay exactly as they are.
    op.drop_table("membership_permission_history")
    op.drop_table("memberships")
