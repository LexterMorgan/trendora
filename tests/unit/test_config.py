"""Unit tests for environment configuration."""

import pytest
from pydantic import ValidationError

from trendora.config import Settings, get_settings, reset_settings_cache
from tests.fixtures.youtube_responses import CHANNEL_A, CHANNEL_B

_DB_URL = "postgresql+psycopg://trendora:trendora@localhost:5432/trendora"


def _database_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", _DB_URL)


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


def test_settings_parse_comma_separated_channel_ids_as_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _database_env(monkeypatch)
    monkeypatch.setenv("YOUTUBE_CHANNEL_IDS", f"{CHANNEL_A},{CHANNEL_B}")
    settings = Settings(_env_file=None)
    assert settings.youtube_channel_ids == [CHANNEL_A, CHANNEL_B]
    assert isinstance(settings.youtube_channel_ids, list)
    assert len(settings.youtube_channel_ids) == 2


def test_settings_trim_channel_id_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    _database_env(monkeypatch)
    monkeypatch.setenv("YOUTUBE_CHANNEL_IDS", f"  {CHANNEL_A} , {CHANNEL_B}  ")
    settings = Settings(_env_file=None)
    assert settings.youtube_channel_ids == [CHANNEL_A, CHANNEL_B]


def test_settings_drop_duplicate_channel_ids_preserving_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _database_env(monkeypatch)
    monkeypatch.setenv(
        "YOUTUBE_CHANNEL_IDS",
        f"{CHANNEL_A},{CHANNEL_B},{CHANNEL_A},{CHANNEL_B}",
    )
    settings = Settings(_env_file=None)
    assert settings.youtube_channel_ids == [CHANNEL_A, CHANNEL_B]


def test_settings_reject_malformed_channel_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    _database_env(monkeypatch)
    monkeypatch.setenv("YOUTUBE_CHANNEL_IDS", f"{CHANNEL_A},@handle")
    with pytest.raises(ValidationError, match="UC"):
        Settings(_env_file=None)


def test_settings_empty_watchlist_is_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    _database_env(monkeypatch)
    monkeypatch.delenv("YOUTUBE_CHANNEL_IDS", raising=False)
    settings = Settings(_env_file=None)
    assert settings.youtube_channel_ids == []
    assert len(settings.youtube_channel_ids) == 0


def test_settings_blank_env_watchlist_is_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    _database_env(monkeypatch)
    monkeypatch.setenv("YOUTUBE_CHANNEL_IDS", "  ,  ")
    settings = Settings(_env_file=None)
    assert settings.youtube_channel_ids == []
