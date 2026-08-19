"""Initial Trendora application schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-08-18
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from trendora.reference import (
    MARKET_IDS,
    MARKETS,
    RETENTION_POLICIES,
    RETENTION_POLICY_IDS,
    SOURCE_IDS,
    SOURCES,
    TOPIC_IDS,
    TOPICS,
)

revision: str = "0001_initial_schema"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APP_TABLES = (
    "metric_snapshots",
    "content_item_topics",
    "content_items",
    "publishers",
    "retention_policies",
    "topics",
    "markets",
    "sources",
)


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("classification", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_sources"),
        sa.UniqueConstraint("code", name="uq_sources_code"),
    )

    op.create_table(
        "markets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_markets"),
        sa.UniqueConstraint("code", name="uq_markets_code"),
    )

    op.create_table(
        "topics",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_topics"),
        sa.UniqueConstraint("code", name="uq_topics_code"),
    )

    op.create_table(
        "retention_policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=True),
        sa.Column("applies_to", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_retention_policies"),
        sa.UniqueConstraint("code", name="uq_retention_policies_code"),
    )

    op.create_table(
        "publishers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("market_id", sa.Uuid(), nullable=True),
        sa.Column("source_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("retain_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"], name="fk_publishers_market_id_markets"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], name="fk_publishers_source_id_sources"),
        sa.PrimaryKeyConstraint("id", name="pk_publishers"),
        sa.UniqueConstraint("source_id", "external_id", name="uq_publishers_source_external_id"),
    )
    op.create_index("ix_publishers_source_id", "publishers", ["source_id"])
    op.create_index("ix_publishers_market_id", "publishers", ["market_id"])
    op.create_index("ix_publishers_retain_until", "publishers", ["retain_until"])

    op.create_table(
        "content_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("publisher_id", sa.Uuid(), nullable=True),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("market_id", sa.Uuid(), nullable=True),
        sa.Column("source_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("retain_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"], name="fk_content_items_market_id_markets"),
        sa.ForeignKeyConstraint(["publisher_id"], ["publishers.id"], name="fk_content_items_publisher_id_publishers"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], name="fk_content_items_source_id_sources"),
        sa.PrimaryKeyConstraint("id", name="pk_content_items"),
        sa.UniqueConstraint("source_id", "external_id", name="uq_content_items_source_external_id"),
    )
    op.create_index("ix_content_items_source_id", "content_items", ["source_id"])
    op.create_index("ix_content_items_publisher_id", "content_items", ["publisher_id"])
    op.create_index("ix_content_items_market_id", "content_items", ["market_id"])
    op.create_index("ix_content_items_retain_until", "content_items", ["retain_until"])

    op.create_table(
        "content_item_topics",
        sa.Column("content_item_id", sa.Uuid(), nullable=False),
        sa.Column("topic_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["content_item_id"], ["content_items.id"], name="fk_content_item_topics_content_item_id_content_items"
        ),
        sa.ForeignKeyConstraint(["topic_id"], ["topics.id"], name="fk_content_item_topics_topic_id_topics"),
        sa.PrimaryKeyConstraint("content_item_id", "topic_id", name="pk_content_item_topics"),
    )

    op.create_table(
        "metric_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("content_item_id", sa.Uuid(), nullable=True),
        sa.Column("publisher_id", sa.Uuid(), nullable=True),
        sa.Column("metric_name", sa.Text(), nullable=False),
        sa.Column("metric_value", sa.BigInteger(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("retention_policy_id", sa.Uuid(), nullable=True),
        sa.Column("retain_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(content_item_id IS NOT NULL AND publisher_id IS NULL) "
            "OR (content_item_id IS NULL AND publisher_id IS NOT NULL)",
            name="subject_xor",
        ),
        sa.ForeignKeyConstraint(
            ["content_item_id"], ["content_items.id"], name="fk_metric_snapshots_content_item_id_content_items"
        ),
        sa.ForeignKeyConstraint(
            ["publisher_id"], ["publishers.id"], name="fk_metric_snapshots_publisher_id_publishers"
        ),
        sa.ForeignKeyConstraint(
            ["retention_policy_id"],
            ["retention_policies.id"],
            name="fk_metric_snapshots_retention_policy_id_retention_policies",
        ),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], name="fk_metric_snapshots_source_id_sources"),
        sa.PrimaryKeyConstraint("id", name="pk_metric_snapshots"),
    )
    op.create_index("ix_metric_snapshots_source_id", "metric_snapshots", ["source_id"])
    op.create_index("ix_metric_snapshots_retention_policy_id", "metric_snapshots", ["retention_policy_id"])
    op.create_index("ix_metric_snapshots_observed_at", "metric_snapshots", ["observed_at"])
    op.create_index("ix_metric_snapshots_retain_until", "metric_snapshots", ["retain_until"])
    op.create_index(
        "uq_metric_snapshots_content_metric_collected",
        "metric_snapshots",
        ["content_item_id", "metric_name", "collected_at"],
        unique=True,
        postgresql_where=sa.text("content_item_id IS NOT NULL"),
    )
    op.create_index(
        "uq_metric_snapshots_publisher_metric_collected",
        "metric_snapshots",
        ["publisher_id", "metric_name", "collected_at"],
        unique=True,
        postgresql_where=sa.text("publisher_id IS NOT NULL"),
    )

    _seed_reference_data()
    _enable_row_level_security()


def _seed_reference_data() -> None:
    sources = sa.table(
        "sources",
        sa.column("id", sa.Uuid()),
        sa.column("code", sa.Text()),
        sa.column("name", sa.Text()),
        sa.column("classification", sa.Text()),
        sa.column("notes", sa.Text()),
    )
    op.bulk_insert(
        sources,
        [
            {
                "id": SOURCE_IDS[row["code"]],
                "code": row["code"],
                "name": row["name"],
                "classification": row["classification"],
                "notes": row["notes"],
            }
            for row in SOURCES
        ],
    )

    markets = sa.table(
        "markets",
        sa.column("id", sa.Uuid()),
        sa.column("code", sa.Text()),
        sa.column("name", sa.Text()),
    )
    op.bulk_insert(
        markets,
        [
            {"id": MARKET_IDS[row["code"]], "code": row["code"], "name": row["name"]}
            for row in MARKETS
        ],
    )

    topics = sa.table(
        "topics",
        sa.column("id", sa.Uuid()),
        sa.column("code", sa.Text()),
        sa.column("name", sa.Text()),
    )
    op.bulk_insert(
        topics,
        [{"id": TOPIC_IDS[row["code"]], "code": row["code"], "name": row["name"]} for row in TOPICS],
    )

    policies = sa.table(
        "retention_policies",
        sa.column("id", sa.Uuid()),
        sa.column("code", sa.Text()),
        sa.column("name", sa.Text()),
        sa.column("retention_days", sa.Integer()),
        sa.column("applies_to", sa.Text()),
        sa.column("notes", sa.Text()),
    )
    op.bulk_insert(
        policies,
        [
            {
                "id": RETENTION_POLICY_IDS[row["code"]],  # type: ignore[index]
                "code": row["code"],
                "name": row["name"],
                "retention_days": row["retention_days"],
                "applies_to": row["applies_to"],
                "notes": row["notes"],
            }
            for row in RETENTION_POLICIES
        ],
    )


def _enable_row_level_security() -> None:
    # PostgreSQL RLS with no policies: PostgREST anon/authenticated cannot read
    # these tables. Table owners (and Supabase service_role) still can. This is
    # not a Supabase-only API; it is a Postgres privilege boundary.
    for table_name in (
        "sources",
        "markets",
        "topics",
        "retention_policies",
        "publishers",
        "content_items",
        "content_item_topics",
        "metric_snapshots",
    ):
        op.execute(sa.text(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE alembic_version ENABLE ROW LEVEL SECURITY"))


def downgrade() -> None:
    for table_name in APP_TABLES:
        op.drop_table(table_name)
