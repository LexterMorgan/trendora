"""GitHub normalization tests. No HTTP and no database."""

from datetime import datetime, timezone

import pytest

from trendora.connectors.github.exceptions import GitHubItemError
from trendora.connectors.github.normalizer import CONTENT_TYPE_REPOSITORY, normalize_repository
from trendora.connectors.github.schemas import RepositoryResource
from tests.fixtures.github_responses import (
    REPO_A,
    REPO_A_FULL_NAME,
    REPO_B,
    REPO_MALFORMED_METRICS,
    REPO_MISSING_IDENTITY,
)

COLLECTED = datetime(2026, 8, 20, 21, 45, tzinfo=timezone.utc)


def test_valid_repository_normalization() -> None:
    item = RepositoryResource.model_validate(REPO_A)
    repo = normalize_repository(item, collected_at=COLLECTED)
    assert repo.external_id == REPO_A_FULL_NAME
    assert repo.content_type == CONTENT_TYPE_REPOSITORY
    assert repo.title == "hello-world"
    assert repo.url == "https://github.com/octocat/hello-world"
    assert repo.description == "My first repository on GitHub!"
    assert repo.published_at == datetime(2011, 1, 26, 19, 1, 12, tzinfo=timezone.utc)
    assert repo.published_at is not None and repo.published_at.tzinfo is not None
    assert repo.source_metadata["github_id"] == 1296269
    assert repo.source_metadata["full_name"] == REPO_A_FULL_NAME
    assert repo.source_metadata["owner_login"] == "octocat"
    assert repo.source_metadata["html_url"] == repo.url
    assert repo.source_metadata["language"] == "Python"
    assert repo.source_metadata["visibility"] == "public"
    assert repo.source_metadata["default_branch"] == "main"
    assert repo.source_metadata["archived"] is False
    assert repo.source_metadata["disabled"] is False
    assert repo.source_metadata["topics"] == ["python", "machine-learning", "llm"]
    assert repo.source_metadata["license"]["spdx_id"] == "MIT"
    assert "topic_ids" not in repo.source_metadata
    metrics = {row.metric_name: row.metric_value for row in repo.snapshots}
    assert metrics == {
        "stargazer_count": 100,
        "fork_count": 20,
        "open_issue_count": 5,
        "watcher_count": 8,
    }
    watcher = next(row for row in repo.snapshots if row.metric_name == "watcher_count")
    assert watcher.source_metadata == {"gh_field": "subscribers_count"}
    assert all(row.collected_at == COLLECTED for row in repo.snapshots)
    assert all(row.subject == "content_item" for row in repo.snapshots)


def test_nullable_fields_and_zero_metrics_are_preserved() -> None:
    item = RepositoryResource.model_validate(REPO_B)
    repo = normalize_repository(item, collected_at=COLLECTED)
    assert repo.external_id == "example/ml-lib"
    assert repo.description is None
    assert "description" not in repo.source_metadata
    assert "language" not in repo.source_metadata
    assert "license" not in repo.source_metadata
    assert repo.source_metadata["topics"] == []
    assert "pushed_at" not in repo.source_metadata
    metrics = {row.metric_name: row.metric_value for row in repo.snapshots}
    assert metrics == {
        "stargazer_count": 0,
        "fork_count": 0,
        "open_issue_count": 0,
        "watcher_count": 0,
    }


def test_malformed_numeric_metrics_are_skipped() -> None:
    item = RepositoryResource.model_validate(REPO_MALFORMED_METRICS)
    repo = normalize_repository(item, collected_at=COLLECTED)
    metrics = {row.metric_name: row.metric_value for row in repo.snapshots}
    assert metrics == {"open_issue_count": 4}


def test_missing_identity_is_rejected() -> None:
    item = RepositoryResource.model_validate(REPO_MISSING_IDENTITY)
    with pytest.raises(GitHubItemError, match="identity"):
        normalize_repository(item, collected_at=COLLECTED)


def test_naive_collected_at_is_rejected() -> None:
    item = RepositoryResource.model_validate(REPO_A)
    with pytest.raises(ValueError, match="timezone-aware"):
        normalize_repository(item, collected_at=datetime(2026, 8, 20, 21, 45))
