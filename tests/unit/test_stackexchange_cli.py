"""CLI tests for Stack Exchange ingestion. No live API."""

import pytest

from trendora.config import Settings, reset_settings_cache
from trendora.connectors.base import ChannelIngestionOutcome, IngestionResult
from trendora.connectors.stackexchange.cli import main
from trendora.connectors.stackexchange.normalizer import DEFAULT_SITES


def _db_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://trendora:trendora@localhost:5432/trendora",
    )
    monkeypatch.setenv("STACKEXCHANGE_API_KEY", "")
    reset_settings_cache()


def test_settings_stackexchange_api_key_is_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://trendora:trendora@localhost:5432/trendora",
    )
    monkeypatch.delenv("STACKEXCHANGE_API_KEY", raising=False)
    settings = Settings(_env_file=None)
    assert settings.stackexchange_api_key is None


def test_settings_blank_stackexchange_api_key_becomes_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://trendora:trendora@localhost:5432/trendora",
    )
    monkeypatch.setenv("STACKEXCHANGE_API_KEY", "  ")
    settings = Settings(_env_file=None)
    assert settings.stackexchange_api_key is None


def test_cli_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    _db_env(monkeypatch)
    called: dict[str, object] = {}

    class FakeConnector:
        def ingest(self):
            called["ingest"] = True
            return IngestionResult(source_code="stack_exchange", watchlist_size=2)

    def fake_build(**kwargs):
        called["kwargs"] = kwargs
        return FakeConnector()

    monkeypatch.setattr(
        "trendora.connectors.stackexchange.cli.build_stackexchange_connector",
        fake_build,
    )
    assert main([]) == 0
    assert called["ingest"] is True
    assert called["kwargs"]["sites"] == DEFAULT_SITES
    assert called["kwargs"]["max_items"] == 50
    assert called["kwargs"]["tags"] == ()
    assert called["kwargs"]["api_key"] is None


def test_cli_custom_sites_max_items_and_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    _db_env(monkeypatch)
    called: dict[str, object] = {}

    class FakeConnector:
        def ingest(self):
            return IngestionResult(source_code="stack_exchange", watchlist_size=1)

    def fake_build(**kwargs):
        called["kwargs"] = kwargs
        return FakeConnector()

    monkeypatch.setattr(
        "trendora.connectors.stackexchange.cli.build_stackexchange_connector",
        fake_build,
    )
    assert main(
        ["--sites", "stackoverflow,datascience", "--max-items", "10", "--tags", "python,sql"]
    ) == 0
    assert called["kwargs"]["sites"] == ("stackoverflow", "datascience")
    assert called["kwargs"]["max_items"] == 10
    assert called["kwargs"]["tags"] == ("python", "sql")


def test_cli_duplicate_sites_are_deduped(monkeypatch: pytest.MonkeyPatch) -> None:
    _db_env(monkeypatch)
    called: dict[str, object] = {}

    class FakeConnector:
        def ingest(self):
            return IngestionResult(source_code="stack_exchange", watchlist_size=1)

    def fake_build(**kwargs):
        called["kwargs"] = kwargs
        return FakeConnector()

    monkeypatch.setattr(
        "trendora.connectors.stackexchange.cli.build_stackexchange_connector",
        fake_build,
    )
    assert main(["--sites", "stackoverflow, stackoverflow"]) == 0
    assert called["kwargs"]["sites"] == ("stackoverflow",)


def test_cli_invalid_site(monkeypatch: pytest.MonkeyPatch) -> None:
    _db_env(monkeypatch)
    assert main(["--sites", "stackoverflow.com"]) == 2
    assert main(["--sites", "https://stackoverflow.com"]) == 2


def test_cli_empty_site(monkeypatch: pytest.MonkeyPatch) -> None:
    _db_env(monkeypatch)
    assert main(["--sites", " , "]) == 2


def test_cli_more_than_five_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    _db_env(monkeypatch)
    assert main(["--tags", "a,b,c,d,e,f"]) == 2


def test_cli_invalid_max_items(monkeypatch: pytest.MonkeyPatch) -> None:
    _db_env(monkeypatch)
    assert main(["--max-items", "0"]) == 2


def test_cli_does_not_require_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _db_env(monkeypatch)

    class FakeConnector:
        def ingest(self):
            return IngestionResult(source_code="stack_exchange", watchlist_size=1)

    monkeypatch.setattr(
        "trendora.connectors.stackexchange.cli.build_stackexchange_connector",
        lambda **kwargs: FakeConnector(),
    )
    assert main(["--sites", "stackoverflow", "--max-items", "5"]) == 0


def test_cli_failure_summary_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    _db_env(monkeypatch)

    class FakeConnector:
        def ingest(self):
            result = IngestionResult(source_code="stack_exchange", watchlist_size=1)
            result.outcomes.append(ChannelIngestionOutcome(external_id="datascience", error="boom"))
            return result

    monkeypatch.setattr(
        "trendora.connectors.stackexchange.cli.build_stackexchange_connector",
        lambda **kwargs: FakeConnector(),
    )
    assert main([]) == 1
