"""GitHub orchestrator tests. Fake client and store; no live API."""

from datetime import datetime, timezone

import pytest

from trendora.connectors.github.connector import GitHubConnector, parse_repositories
from trendora.connectors.github.exceptions import GitHubConfigurationError, GitHubHttpError
from trendora.connectors.github.normalizer import NormalizedRepository
from trendora.connectors.github.persistence import RepositoryPersistResult
from trendora.connectors.github.schemas import RepositoryResource
from tests.fixtures.github_responses import REPO_A, REPO_A_FULL_NAME, REPO_B, REPO_B_FULL_NAME

COLLECTED = datetime(2026, 8, 20, 21, 45, tzinfo=timezone.utc)


class FakeClient:
    def __init__(
        self,
        *,
        repos: dict[str, RepositoryResource] | None = None,
        errors: dict[str, Exception] | None = None,
    ) -> None:
        self.repos = repos or {}
        self.errors = errors or {}
        self.requests: list[tuple[str, str]] = []

    def get_repository(self, owner: str, repo: str) -> RepositoryResource:
        self.requests.append((owner, repo))
        full_name = f"{owner}/{repo}"
        if full_name in self.errors:
            raise self.errors[full_name]
        resource = self.repos.get(full_name)
        if resource is None:
            raise GitHubHttpError(f"missing {full_name}", status_code=404)
        return resource


class FakeStore:
    def __init__(self) -> None:
        self.repositories: list[NormalizedRepository] = []

    def persist(self, repository: NormalizedRepository) -> RepositoryPersistResult:
        self.repositories.append(repository)
        return RepositoryPersistResult(
            content_item_created=True,
            content_item_updated=False,
            snapshots_inserted=len(repository.snapshots),
        )


def _resources() -> dict[str, RepositoryResource]:
    return {
        REPO_A_FULL_NAME: RepositoryResource.model_validate(REPO_A),
        REPO_B_FULL_NAME: RepositoryResource.model_validate(REPO_B),
    }


def test_parse_repositories_trims_dedupes_and_rejects_junk() -> None:
    assert parse_repositories(None) == ()
    assert parse_repositories(" octocat/hello-world , example/ml-lib, octocat/hello-world ") == (
        "octocat/hello-world",
        "example/ml-lib",
    )
    with pytest.raises(GitHubConfigurationError, match="owner/repository"):
        parse_repositories("https://github.com/octocat/hello-world")
    with pytest.raises(GitHubConfigurationError, match="owner/repository"):
        parse_repositories("github.com/octocat/hello-world")
    with pytest.raises(GitHubConfigurationError, match="owner/repository"):
        parse_repositories("@octocat")
    with pytest.raises(GitHubConfigurationError, match="owner/repository"):
        parse_repositories("org:openai")
    with pytest.raises(GitHubConfigurationError, match="owner/repository"):
        parse_repositories("octocat")


def test_configured_repositories_are_ingested_in_order() -> None:
    store = FakeStore()
    client = FakeClient(repos=_resources())
    result = GitHubConnector(
        client,
        store,
        repositories=(REPO_A_FULL_NAME, REPO_B_FULL_NAME),
        max_items=50,
    ).ingest(collected_at=COLLECTED)
    assert client.requests == [("octocat", "hello-world"), ("example", "ml-lib")]
    assert result.failed == []
    assert [row.external_id for row in result.succeeded] == [REPO_A_FULL_NAME, REPO_B_FULL_NAME]
    assert [row.external_id for row in store.repositories] == [REPO_A_FULL_NAME, REPO_B_FULL_NAME]
    assert all(row.collected_at == COLLECTED for row in store.repositories)


def test_duplicate_identifiers_are_fetched_once() -> None:
    client = FakeClient(repos=_resources())
    GitHubConnector(
        client,
        FakeStore(),
        repositories=(REPO_A_FULL_NAME, REPO_A_FULL_NAME),
        max_items=10,
    ).ingest(collected_at=COLLECTED)
    assert client.requests == [("octocat", "hello-world")]


def test_max_items_caps_the_explicit_list() -> None:
    client = FakeClient(repos=_resources())
    result = GitHubConnector(
        client,
        FakeStore(),
        repositories=(REPO_A_FULL_NAME, REPO_B_FULL_NAME),
        max_items=1,
    ).ingest(collected_at=COLLECTED)
    assert client.requests == [("octocat", "hello-world")]
    assert [row.external_id for row in result.succeeded] == [REPO_A_FULL_NAME]


def test_one_repository_failure_does_not_stop_others() -> None:
    client = FakeClient(
        repos=_resources(),
        errors={REPO_A_FULL_NAME: GitHubHttpError("boom", status_code=500)},
    )
    store = FakeStore()
    result = GitHubConnector(
        client,
        store,
        repositories=(REPO_A_FULL_NAME, REPO_B_FULL_NAME),
        max_items=10,
    ).ingest(collected_at=COLLECTED)
    assert [row.external_id for row in result.failed] == [REPO_A_FULL_NAME]
    assert [row.external_id for row in result.succeeded] == [REPO_B_FULL_NAME]
    assert [row.external_id for row in store.repositories] == [REPO_B_FULL_NAME]


def test_one_collected_at_is_used_for_the_entire_run() -> None:
    store = FakeStore()
    GitHubConnector(
        FakeClient(repos=_resources()),
        store,
        repositories=(REPO_A_FULL_NAME, REPO_B_FULL_NAME),
    ).ingest(collected_at=COLLECTED)
    assert {row.collected_at for row in store.repositories} == {COLLECTED}
    assert all(snap.collected_at == COLLECTED for row in store.repositories for snap in row.snapshots)


def test_connector_does_not_discover_or_search() -> None:
    client = FakeClient(repos=_resources())
    GitHubConnector(client, FakeStore(), repositories=(REPO_A_FULL_NAME,)).ingest(
        collected_at=COLLECTED
    )
    assert not hasattr(client, "search")
    assert not hasattr(client, "list_commits")
    assert not hasattr(client, "list_issues")
    assert not hasattr(client, "list_pulls")
    assert client.requests == [("octocat", "hello-world")]


def test_empty_repository_list_is_configuration_error() -> None:
    with pytest.raises(GitHubConfigurationError, match="At least one"):
        GitHubConnector(FakeClient(), FakeStore(), repositories=())
