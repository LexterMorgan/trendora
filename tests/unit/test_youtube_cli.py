"""CLI and settings tests for YouTube ingestion. No live API."""

import pytest
from pydantic import ValidationError

from trendora.config import Settings, reset_settings_cache
from trendora.connectors.base import IngestionResult
from trendora.connectors.youtube.cli import main
from tests.fixtures.youtube_responses import CHANNEL_A, CHANNEL_B


def _db_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://trendora:trendora@localhost:5432/trendora",
    )
    reset_settings_cache()


def test_settings_youtube_fields_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    _db_env(monkeypatch)
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.delenv("YOUTUBE_CHANNEL_IDS", raising=False)
    monkeypatch.delenv("YOUTUBE_MAX_VIDEOS_PER_CHANNEL", raising=False)
    settings = Settings(_env_file=None)
    assert settings.youtube_api_key is None
    assert settings.youtube_channel_ids == []
    assert settings.youtube_max_videos_per_channel == 50


def test_settings_blank_api_key_becomes_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _db_env(monkeypatch)
    monkeypatch.setenv("YOUTUBE_API_KEY", "  ")
    settings = Settings(_env_file=None)
    assert settings.youtube_api_key is None


def test_settings_load_watchlist_and_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    _db_env(monkeypatch)
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key-not-real")
    monkeypatch.setenv("YOUTUBE_CHANNEL_IDS", f"{CHANNEL_A},{CHANNEL_B}")
    monkeypatch.setenv("YOUTUBE_MAX_VIDEOS_PER_CHANNEL", "25")
    settings = Settings(_env_file=None)
    assert settings.youtube_api_key == "test-key-not-real"
    assert settings.youtube_channel_ids == [CHANNEL_A, CHANNEL_B]
    assert settings.youtube_max_videos_per_channel == 25


def test_settings_reject_zero_max_videos(monkeypatch: pytest.MonkeyPatch) -> None:
    _db_env(monkeypatch)
    monkeypatch.setenv("YOUTUBE_MAX_VIDEOS_PER_CHANNEL", "0")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_cli_missing_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _db_env(monkeypatch)
    monkeypatch.setenv("YOUTUBE_API_KEY", "")
    assert main([]) == 2


def test_cli_empty_watchlist(monkeypatch: pytest.MonkeyPatch) -> None:
    _db_env(monkeypatch)
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key-not-real")
    monkeypatch.setenv("YOUTUBE_CHANNEL_IDS", "")
    assert main([]) == 2


def test_cli_invalid_channel_id(monkeypatch: pytest.MonkeyPatch) -> None:
    _db_env(monkeypatch)
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key-not-real")
    assert main(["--channel-ids", "@handle"]) == 2


def test_cli_invokes_ingest(monkeypatch: pytest.MonkeyPatch) -> None:
    _db_env(monkeypatch)
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key-not-real")
    monkeypatch.setenv("YOUTUBE_CHANNEL_IDS", CHANNEL_A)
    called: dict[str, object] = {}

    class FakeConnector:
        def ingest(self):
            called["ingest"] = True
            return IngestionResult(source_code="youtube", watchlist_size=1)

    def fake_build(**kwargs):
        called["kwargs"] = kwargs
        return FakeConnector()

    monkeypatch.setattr("trendora.connectors.youtube.cli.build_youtube_connector", fake_build)
    assert main(["--max-videos", "3"]) == 0
    assert called["ingest"] is True
    assert called["kwargs"]["max_videos_per_channel"] == 3
    assert called["kwargs"]["api_key"] == "test-key-not-real"
    assert called["kwargs"]["watchlist"] == (CHANNEL_A,)


def test_cli_most_popular_does_not_require_watchlist(monkeypatch: pytest.MonkeyPatch) -> None:
    _db_env(monkeypatch)
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key-not-real")
    monkeypatch.setenv("YOUTUBE_CHANNEL_IDS", "")
    called: dict[str, object] = {}

    class FakeConnector:
        def ingest(self):
            called["ingest"] = True
            return IngestionResult(source_code="youtube", watchlist_size=6)

    def fake_build(**kwargs):
        called["kwargs"] = kwargs
        return FakeConnector()

    monkeypatch.setattr(
        "trendora.connectors.youtube.cli.build_most_popular_connector",
        fake_build,
    )

    def fail_watchlist(**kwargs):
        raise AssertionError("watchlist connector must not run for most-popular")

    monkeypatch.setattr("trendora.connectors.youtube.cli.build_youtube_connector", fail_watchlist)
    assert main(["most-popular"]) == 0
    assert called["ingest"] is True
    assert called["kwargs"]["api_key"] == "test-key-not-real"
    assert called["kwargs"]["region_codes"] == ("ID", "TH", "MY", "SG", "VN", "PH")
    assert called["kwargs"]["max_videos_per_market"] == 50


def test_cli_most_popular_markets_and_max_videos(monkeypatch: pytest.MonkeyPatch) -> None:
    _db_env(monkeypatch)
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key-not-real")
    called: dict[str, object] = {}

    class FakeConnector:
        def ingest(self):
            return IngestionResult(source_code="youtube", watchlist_size=2)

    def fake_build(**kwargs):
        called["kwargs"] = kwargs
        return FakeConnector()

    monkeypatch.setattr(
        "trendora.connectors.youtube.cli.build_most_popular_connector",
        fake_build,
    )
    assert main(["most-popular", "--markets", "ID,SG", "--max-videos", "20"]) == 0
    assert called["kwargs"]["region_codes"] == ("ID", "SG")
    assert called["kwargs"]["max_videos_per_market"] == 20


def test_cli_most_popular_rejects_unknown_market(monkeypatch: pytest.MonkeyPatch) -> None:
    _db_env(monkeypatch)
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key-not-real")
    assert main(["most-popular", "--markets", "US"]) == 2


def test_cli_most_popular_missing_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _db_env(monkeypatch)
    monkeypatch.setenv("YOUTUBE_API_KEY", "")
    assert main(["most-popular"]) == 2
