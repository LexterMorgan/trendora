"""Unit tests for environment configuration."""

import pytest
from pydantic import ValidationError

from trendora.config import Settings, get_settings, reset_settings_cache


def test_settings_require_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_load_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://trendora:trendora@localhost:5432/trendora",
    )
    settings = Settings(_env_file=None)
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.app_env == "development"


def test_settings_normalize_postgresql_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@db.example:5432/postgres")
    settings = Settings(_env_file=None)
    assert settings.database_url.startswith("postgresql+psycopg://")


def test_settings_normalize_postgres_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgres://user:pass@db.example:5432/postgres")
    settings = Settings(_env_file=None)
    assert settings.database_url.startswith("postgresql+psycopg://")


def test_settings_reject_non_postgres_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite:///tmp.db")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_get_settings_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://u:p@localhost:5432/db",
    )
    reset_settings_cache()
    first = get_settings()
    second = get_settings()
    assert first is second
    reset_settings_cache()
