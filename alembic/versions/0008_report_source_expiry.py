"""Trusted original report source expiry, independent of provenance.

Revision ID: 0008_report_source_expiry
Revises: 0007_origin_collected_at_nullable
Create Date: 2026-10-07

Existing rows remain NULL. No collection date, report identity, fingerprint,
or provenance is rewritten, and unverified recoveries gain no new lifetime.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_report_source_expiry"
down_revision: Union[str, Sequence[str], None] = "0007_origin_collected_at_nullable"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "research_reports",
        sa.Column("source_expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("research_reports", "source_expires_at")
