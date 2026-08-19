"""PostgreSQL integration tests. Skipped unless DATABASE_URL is configured."""

import os

import pytest
from sqlalchemy import inspect, text

from trendora.config import reset_settings_cache
from trendora.db.session import get_engine, reset_engine

pytestmark = pytest.mark.integration


def _database_url() -> str | None:
    return os.environ.get("DATABASE_URL") or os.environ.get("TRENDORA_TEST_DATABASE_URL")


@pytest.fixture
def engine():
    if not _database_url():
        pytest.skip("DATABASE_URL is not configured")
    reset_settings_cache()
    reset_engine()
    try:
        yield get_engine()
    finally:
        reset_engine()
        reset_settings_cache()


def test_postgres_connectivity(engine) -> None:
    with engine.connect() as connection:
        value = connection.execute(text("select current_database()")).scalar_one()
        assert value
        version = connection.execute(text("show server_version")).scalar_one()
        assert version


def test_application_tables_exist(engine) -> None:
    inspector = inspect(engine)
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


def test_alembic_revision(engine) -> None:
    with engine.connect() as connection:
        revision = connection.execute(text("select version_num from alembic_version")).scalar_one()
        assert revision == "0001_initial_schema"
