"""Model metadata and constraint tests. No database connection required."""

from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.dialects import postgresql

from trendora.db.base import Base
from trendora.models import (
    ContentItem,
    ContentItemTopic,
    Market,
    MetricSnapshot,
    Publisher,
    RetentionPolicy,
    Source,
    Topic,
)


EXPECTED_TABLES = {
    "sources",
    "markets",
    "topics",
    "retention_policies",
    "publishers",
    "content_items",
    "content_item_topics",
    "metric_snapshots",
}


def test_all_models_are_registered() -> None:
    assert EXPECTED_TABLES <= set(Base.metadata.tables)


def test_source_and_market_codes_are_unique() -> None:
    assert any(c.name == "uq_sources_code" or _is_unique_on(Source, "code") for c in Source.__table__.constraints)
    assert _is_unique_on(Market, "code")
    assert _is_unique_on(Topic, "code")
    assert _is_unique_on(RetentionPolicy, "code")


def test_publisher_unique_per_source() -> None:
    names = {c.name for c in Publisher.__table__.constraints if isinstance(c, UniqueConstraint)}
    assert "uq_publishers_source_external_id" in names


def test_content_item_unique_per_source() -> None:
    names = {c.name for c in ContentItem.__table__.constraints if isinstance(c, UniqueConstraint)}
    assert "uq_content_items_source_external_id" in names


def test_metric_snapshot_requires_exactly_one_subject() -> None:
    checks = [c for c in MetricSnapshot.__table__.constraints if isinstance(c, CheckConstraint)]
    assert any("content_item_id" in str(c.sqltext) and "publisher_id" in str(c.sqltext) for c in checks)


def test_metric_snapshot_partial_unique_indexes() -> None:
    index_names = {index.name for index in MetricSnapshot.__table__.indexes}
    assert "uq_metric_snapshots_content_metric_collected" in index_names
    assert "uq_metric_snapshots_publisher_metric_collected" in index_names


def test_observational_columns_are_timezone_aware() -> None:
    assert ContentItem.__table__.c.published_at.type.timezone is True
    assert MetricSnapshot.__table__.c.observed_at.type.timezone is True
    assert MetricSnapshot.__table__.c.collected_at.type.timezone is True
    assert MetricSnapshot.__table__.c.retain_until.type.timezone is True
    assert Publisher.__table__.c.retain_until.type.timezone is True


def test_source_specific_payload_uses_jsonb() -> None:
    assert isinstance(Publisher.__table__.c.source_metadata.type, postgresql.JSONB)
    assert isinstance(ContentItem.__table__.c.source_metadata.type, postgresql.JSONB)
    assert isinstance(MetricSnapshot.__table__.c.source_metadata.type, postgresql.JSONB)


def test_content_item_topic_composite_primary_key() -> None:
    pk = {col.name for col in ContentItemTopic.__table__.primary_key.columns}
    assert pk == {"content_item_id", "topic_id"}


def test_foreign_keys_point_at_catalog() -> None:
    publisher_fks = {fk.target_fullname for fk in Publisher.__table__.foreign_keys}
    assert "sources.id" in publisher_fks
    assert "markets.id" in publisher_fks
    snapshot_fks = {fk.target_fullname for fk in MetricSnapshot.__table__.foreign_keys}
    assert "sources.id" in snapshot_fks
    assert "content_items.id" in snapshot_fks
    assert "publishers.id" in snapshot_fks
    assert "retention_policies.id" in snapshot_fks


def _is_unique_on(model, column_name: str) -> bool:
    for constraint in model.__table__.constraints:
        if isinstance(constraint, UniqueConstraint) and [c.name for c in constraint.columns] == [column_name]:
            return True
    return model.__table__.c[column_name].unique is True
