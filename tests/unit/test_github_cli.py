"""CLI tests for GitHub ingestion. No live API."""

import pytest

from trendora.config import Settings, reset_settings_cache
from trendora.connectors.base import ChannelIngestionOutcome, IngestionResult
from trendora.connectors.github.cli import main
from tests.fixtures.github_responses import REPO_A_FULL_NAME, REPO_B_FULL_NAME


def _db_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://trendora:trendora@localhost:5432/trendora",
    )
    monkeypatch.setenv("GITHUB_TOKEN", "")
    monkeypatch.setenv("GITHUB_REPOSITORIES", f"{REPO_A_FULL_NAME},{REPO_B_FULL_NAME}")
    reset_settings_cache()


def test_settings_github_token_is_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://trendora:trendora@localhost:5432/trendora",
    )
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORIES", raising=False)
    settings = Settings(_env_file=None)
    assert settings.github_token is None
    assert settings.github_repositories == []


def test_settings_parse_github_repositories(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://trendora:trendora@localhost:5432/trendora",
    )
    monkeypatch.setenv("GITHUB_REPOSITORIES", f" {REPO_A_FULL_NAME}, {REPO_B_FULL_NAME}, {REPO_A_FULL_NAME} ")
    settings = Settings(_env_file=None)
    assert settings.github_repositories == [REPO_A_FULL_NAME, REPO_B_FULL_NAME]


def test_cli_uses_configured_repository_list(monkeypatch: pytest.MonkeyPatch) -> None:
    _db_env(monkeypatch)
    called: dict[str, object] = {}

    class FakeConnector:
        def ingest(self):
            called["ingest"] = True
            return IngestionResult(source_code="github", watchlist_size=2)

    def fake_build(**kwargs):
        called["kwargs"] = kwargs
        return FakeConnector()

    monkeypatch.setattr("trendora.connectors.github.cli.build_github_connector", fake_build)
    assert main([]) == 0
    assert called["ingest"] is True
    assert called["kwargs"]["repositories"] == (REPO_A_FULL_NAME, REPO_B_FULL_NAME)
    assert called["kwargs"]["max_items"] == 50
    assert called["kwargs"]["token"] is None


def test_cli_repos_override_config(monkeypatch: pytest.MonkeyPatch) -> None:
    _db_env(monkeypatch)
    called: dict[str, object] = {}

    class FakeConnector:
        def ingest(self):
            return IngestionResult(source_code="github", watchlist_size=1)

    def fake_build(**kwargs):
        called["kwargs"] = kwargs
        return FakeConnector()

    monkeypatch.setattr("trendora.connectors.github.cli.build_github_connector", fake_build)
    assert main(["--repos", REPO_A_FULL_NAME, "--max-items", "1"]) == 0
    assert called["kwargs"]["repositories"] == (REPO_A_FULL_NAME,)
    assert called["kwargs"]["max_items"] == 1


def test_cli_missing_repository_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://trendora:trendora@localhost:5432/trendora",
    )
    monkeypatch.setenv("GITHUB_TOKEN", "")
    monkeypatch.setenv("GITHUB_REPOSITORIES", "")
    reset_settings_cache()
    assert main([]) == 2


def test_cli_malformed_repository_identifier(monkeypatch: pytest.MonkeyPatch) -> None:
    _db_env(monkeypatch)
    assert main(["--repos", "https://github.com/octocat/hello-world"]) == 2
    assert main(["--repos", "@octocat"]) == 2


def test_cli_missing_token_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    _db_env(monkeypatch)
    called: dict[str, object] = {}

    class FakeConnector:
        def ingest(self):
            return IngestionResult(source_code="github", watchlist_size=1)

    def fake_build(**kwargs):
        called["kwargs"] = kwargs
        return FakeConnector()

    monkeypatch.setattr("trendora.connectors.github.cli.build_github_connector", fake_build)
    assert main(["--repos", REPO_A_FULL_NAME]) == 0
    assert called["kwargs"]["token"] is None


def test_cli_invalid_max_items(monkeypatch: pytest.MonkeyPatch) -> None:
    _db_env(monkeypatch)
    assert main(["--max-items", "0"]) == 2


def test_cli_failure_summary_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    _db_env(monkeypatch)

    class FakeConnector:
        def ingest(self):
            result = IngestionResult(source_code="github", watchlist_size=1)
            result.outcomes.append(ChannelIngestionOutcome(external_id=REPO_A_FULL_NAME, error="boom"))
            return result

    monkeypatch.setattr(
        "trendora.connectors.github.cli.build_github_connector",
        lambda **kwargs: FakeConnector(),
    )
    assert main([]) == 1
