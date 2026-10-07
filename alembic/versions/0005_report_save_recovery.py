"""report save recovery: actor/key identity, fingerprint, provenance (P3)

Revision ID: 0005_report_save_recovery
Revises: 0004_planner_posts
Create Date: 2026-10-02

Additive: research_reports gains the identity and fingerprint needed to make
saves idempotent and to classify a recovered snapshot. Existing rows keep
NULL actor/key and the ``legacy_unclassified`` provenance. No row is rewritten
and no timestamp is reset.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_report_save_recovery"
down_revision: Union[str, Sequence[str], None] = "0004_planner_posts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PROVENANCE_VALUES = ("server_generated", "client_supplied", "legacy_unclassified")


def upgrade() -> None:
    op.add_column(
        "research_reports",
        sa.Column("created_by", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "research_reports",
        sa.Column("save_request_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "research_reports",
        sa.Column("payload_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "research_reports",
        sa.Column(
            "snapshot_origin",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'legacy_unclassified'"),
        ),
    )
    op.create_check_constraint(
        "ck_research_reports_snapshot_origin",
        "research_reports",
        "snapshot_origin IN ('server_generated', 'client_supplied', 'legacy_unclassified')",
    )
    # One committed save per (actor, key). NULL actor/key rows (legacy) are
    # exempt because Postgres treats NULLs as distinct in a unique index.
    op.create_unique_constraint(
        "uq_research_reports_created_by_request",
        "research_reports",
        ["created_by", "save_request_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_research_reports_created_by_request",
        "research_reports",
        type_="unique",
    )
    op.drop_constraint(
        "ck_research_reports_snapshot_origin",
        "research_reports",
        type_="check",
    )
    op.drop_column("research_reports", "snapshot_origin")
    op.drop_column("research_reports", "payload_hash")
    op.drop_column("research_reports", "save_request_id")
    op.drop_column("research_reports", "created_by")
