"""CLI tests for Hacker News ingestion. No live API."""

import pytest

from trendora.config import reset_settings_cache
from trendora.connectors.base import ChannelIngestionOutcome, IngestionResult
from trendora.connectors.hackernews.cli import main


def _db_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://trendora:trendora@localhost:5432/trendora",
    )
    reset_settings_cache()


def test_cli_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    _db_env(monkeypatch)
    called: dict[str, object] = {}

    class FakeConnector:
        def ingest(self):
            called["ingest"] = True
            return IngestionResult(source_code="hacker_news", watchlist_size=3)

    def fake_build(**kwargs):
        called["kwargs"] = kwargs
        return FakeConnector()

    monkeypatch.setattr("trendora.connectors.hackernews.cli.build_hackernews_connector", fake_build)
    assert main([]) == 0
    assert called["ingest"] is True
    assert called["kwargs"]["feeds"] == ("topstories", "newstories", "beststories")
    assert called["kwargs"]["max_items"] == 50


def test_cli_custom_feeds_and_max_items(monkeypatch: pytest.MonkeyPatch) -> None:
    _db_env(monkeypatch)
    called: dict[str, object] = {}

    class FakeConnector:
        def ingest(self):
            return IngestionResult(source_code="hacker_news", watchlist_size=1)

    def fake_build(**kwargs):
        called["kwargs"] = kwargs
        return FakeConnector()

    monkeypatch.setattr("trendora.connectors.hackernews.cli.build_hackernews_connector", fake_build)
    assert main(["--feeds", "beststories,topstories", "--max-items", "5"]) == 0
    assert called["kwargs"]["feeds"] == ("beststories", "topstories")
    assert called["kwargs"]["max_items"] == 5


def test_cli_invalid_feed(monkeypatch: pytest.MonkeyPatch) -> None:
    _db_env(monkeypatch)
    assert main(["--feeds", "askstories"]) == 2


def test_cli_invalid_max_items(monkeypatch: pytest.MonkeyPatch) -> None:
    _db_env(monkeypatch)
    assert main(["--max-items", "0"]) == 2


def test_cli_failure_summary_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    _db_env(monkeypatch)

    class FakeConnector:
        def ingest(self):
            result = IngestionResult(source_code="hacker_news", watchlist_size=1)
            result.outcomes.append(ChannelIngestionOutcome(external_id="1001", error="missing"))
            return result

    monkeypatch.setattr(
        "trendora.connectors.hackernews.cli.build_hackernews_connector",
        lambda **kwargs: FakeConnector(),
    )
    assert main([]) == 1
