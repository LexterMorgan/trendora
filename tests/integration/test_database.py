"""PostgreSQL integration tests. Skipped unless TRENDORA_TEST_DATABASE_URL is configured."""

import pytest
from sqlalchemy import inspect, text

pytestmark = pytest.mark.integration


def test_postgres_connectivity(test_engine) -> None:
    with test_engine.connect() as connection:
        value = connection.execute(text("select current_database()")).scalar_one()
        assert value
        version = connection.execute(text("show server_version")).scalar_one()
        assert version


def test_application_tables_exist(test_engine) -> None:
    inspector = inspect(test_engine)
    tables = set(inspector.get_table_names(schema="public"))
    expected = {
        "sources",
        "markets",
        "topics",
        "retention_policies",
        "publishers",
        "content_items",
        "content_item_topics",
        "metric_snapshots",
        "alembic_version",
    }
    missing = expected - tables
    assert not missing, f"missing tables: {sorted(missing)}"


def test_alembic_revision(test_engine) -> None:
    with test_engine.connect() as connection:
        revision = connection.execute(text("select version_num from alembic_version")).scalar_one()
        assert revision == "0008_report_source_expiry"
