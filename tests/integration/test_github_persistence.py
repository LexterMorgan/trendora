"""PostgreSQL persistence tests for GitHub ingestion.

These tests roll back and never call the GitHub API. Assertions are scoped to
fixture external IDs.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session, sessionmaker

from trendora.config import reset_settings_cache
from trendora.connectors.github.connector import GitHubConnector
from trendora.connectors.github.normalizer import NormalizedRepository
from trendora.connectors.github.persistence import persist_repository
from trendora.connectors.github.schemas import RepositoryResource
from trendora.db.session import get_engine, reset_engine
from trendora.models import ContentItem, ContentItemTopic, MetricSnapshot, Publisher
from trendora.reference import SOURCE_IDS
from tests.fixtures.github_responses import REPO_A, REPO_A_FULL_NAME, REPO_B, REPO_B_FULL_NAME

pytestmark = pytest.mark.integration

COLLECTED = datetime(2026, 8, 20, 22, 0, tzinfo=timezone.utc)
COLLECTED_LATER = datetime(2026, 8, 20, 23, 0, tzinfo=timezone.utc)
GH_SOURCE = SOURCE_IDS["github"]


@pytest.fixture
def db_session(database_url: str) -> Session:
    assert database_url
    reset_settings_cache()
    reset_engine()
    engine = get_engine()
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(bind=connection, autoflush=False, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        reset_engine()
        reset_settings_cache()


class _SessionStore:
    def __init__(self, session: Session) -> None:
        self._session = session

    def persist(self, repository: NormalizedRepository):
        return persist_repository(self._session, repository)


class _FakeClient:
    def __init__(self, repos: dict[str, RepositoryResource]) -> None:
        self.repos = repos

    def get_repository(self, owner: str, repo: str) -> RepositoryResource:
        return self.repos[f"{owner}/{repo}"]


def _ingest(session: Session, *, collected_at: datetime, full_names: tuple[str, ...]) -> None:
    resources = {
        REPO_A_FULL_NAME: RepositoryResource.model_validate(REPO_A),
        REPO_B_FULL_NAME: RepositoryResource.model_validate(REPO_B),
    }
    connector = GitHubConnector(
        _FakeClient(resources),
        _SessionStore(session),
        repositories=full_names,
        max_items=50,
    )
    result = connector.ingest(collected_at=collected_at)
    session.flush()
    assert result.failed == []


def _content(session: Session, external_id: str) -> ContentItem | None:
    return (
        session.query(ContentItem)
        .filter(
            ContentItem.source_id == GH_SOURCE,
            ContentItem.external_id == external_id,
        )
        .one_or_none()
    )


def test_new_repository_creates_content_without_publisher_or_market(db_session: Session) -> None:
    _ingest(db_session, collected_at=COLLECTED, full_names=(REPO_A_FULL_NAME,))
    repo = _content(db_session, REPO_A_FULL_NAME)
    assert repo is not None
    assert repo.content_type == "repository"
    assert repo.publisher_id is None
    assert repo.market_id is None
    assert repo.source_metadata["github_id"] == 1296269
    assert repo.source_metadata["full_name"] == REPO_A_FULL_NAME
    assert repo.source_metadata["owner_login"] == "octocat"
    assert repo.source_metadata["topics"] == ["python", "machine-learning", "llm"]
    assert repo.source_metadata["language"] == "Python"

    publishers = (
        db_session.query(Publisher)
        .filter(Publisher.source_id == GH_SOURCE, Publisher.external_id.in_(["octocat", "1"]))
        .all()
    )
    assert publishers == []

    snapshots = (
        db_session.query(MetricSnapshot).filter(MetricSnapshot.content_item_id == repo.id).all()
    )
    names = {row.metric_name: row.metric_value for row in snapshots}
    assert names["stargazer_count"] == 100
    assert names["fork_count"] == 20
    assert names["open_issue_count"] == 5
    assert names["watcher_count"] == 8
    assert all(row.publisher_id is None for row in snapshots)
    assert all(row.retention_policy_id is None for row in snapshots)
    assert {row.collected_at for row in snapshots} == {COLLECTED}

    topic_links = (
        db_session.query(ContentItemTopic)
        .filter(ContentItemTopic.content_item_id == repo.id)
        .all()
    )
    assert topic_links == []


def test_reingest_same_collected_at_is_idempotent_and_later_appends(db_session: Session) -> None:
    _ingest(db_session, collected_at=COLLECTED, full_names=(REPO_A_FULL_NAME,))
    first = _content(db_session, REPO_A_FULL_NAME)
    assert first is not None
    first_count = (
        db_session.query(MetricSnapshot).filter(MetricSnapshot.content_item_id == first.id).count()
    )
    assert first_count > 0

    _ingest(db_session, collected_at=COLLECTED, full_names=(REPO_A_FULL_NAME,))
    identities = (
        db_session.query(ContentItem)
        .filter(ContentItem.source_id == GH_SOURCE, ContentItem.external_id == REPO_A_FULL_NAME)
        .all()
    )
    assert len(identities) == 1
    assert (
        db_session.query(MetricSnapshot).filter(MetricSnapshot.content_item_id == first.id).count()
        == first_count
    )

    _ingest(db_session, collected_at=COLLECTED_LATER, full_names=(REPO_A_FULL_NAME,))
    assert (
        db_session.query(MetricSnapshot).filter(MetricSnapshot.content_item_id == first.id).count()
        == first_count * 2
    )


def test_two_repositories_remain_distinct_identities(db_session: Session) -> None:
    _ingest(
        db_session,
        collected_at=COLLECTED,
        full_names=(REPO_A_FULL_NAME, REPO_B_FULL_NAME),
    )
    first = _content(db_session, REPO_A_FULL_NAME)
    second = _content(db_session, REPO_B_FULL_NAME)
    assert first is not None and second is not None
    assert first.id != second.id
    assert first.publisher_id is None and second.publisher_id is None
    assert first.market_id is None and second.market_id is None
    assert second.source_metadata["topics"] == []
