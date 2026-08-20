"""Orchestrate GitHub fetch → normalize → persist for explicit repositories."""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from trendora.connectors.base import ChannelIngestionOutcome, IngestionResult
from trendora.connectors.github.client import GitHubClient
from trendora.connectors.github.exceptions import (
    GitHubApiError,
    GitHubConfigurationError,
    GitHubHttpError,
    GitHubItemError,
    GitHubResponseError,
)
from trendora.connectors.github.normalizer import (
    DEFAULT_MAX_ITEMS,
    NormalizedRepository,
    normalize_repository,
)
from trendora.connectors.github.persistence import RepositoryPersistResult, persist_repository
from trendora.connectors.github.schemas import RepositoryResource
from trendora.db.session import get_session_factory

logger = logging.getLogger("trendora.connectors.github")

_REPO_RE = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?/[A-Za-z0-9._-]+$"
)
_FETCH_ERRORS = (
    GitHubHttpError,
    GitHubResponseError,
    GitHubApiError,
    GitHubItemError,
)


class GitHubDataSource(Protocol):
    def get_repository(self, owner: str, repo: str) -> RepositoryResource: ...


class RepositoryStore(Protocol):
    def persist(self, repository: NormalizedRepository) -> RepositoryPersistResult: ...


class SqlAlchemyRepositoryStore:
    """One transaction per repository. Does not span the whole run."""

    def __init__(self, session_factory: sessionmaker[Session] | None = None) -> None:
        self._session_factory = session_factory or get_session_factory()

    def persist(self, repository: NormalizedRepository) -> RepositoryPersistResult:
        session = self._session_factory()
        try:
            result = persist_repository(session, repository)
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def parse_repositories(value: str | Sequence[str] | None) -> tuple[str, ...]:
    """Return unique owner/repo identifiers in first-seen order.

    URLs, handles, and search syntax are rejected. Empty input yields an empty
    tuple so callers can decide whether a list is required.
    """

    if value is None:
        return ()
    if isinstance(value, str):
        tokens = value.split(",")
    else:
        tokens = list(value)

    seen: set[str] = set()
    ordered: list[str] = []
    for raw in tokens:
        token = raw.strip()
        if not token:
            continue
        if _is_rejected_identifier(token) or not _REPO_RE.fullmatch(token):
            raise GitHubConfigurationError(
                f"Invalid GitHub repository {raw!r}. Use owner/repository "
                "(for example openai/openai-python), not a URL, handle, or search query."
            )
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(token)
    return tuple(ordered)


def _is_rejected_identifier(token: str) -> bool:
    lowered = token.lower()
    if "://" in token or lowered.startswith("github.com/") or lowered.startswith("www.github.com/"):
        return True
    if token.startswith("@") or " " in token or ":" in token or "?" in token:
        return True
    return False


def split_repository(full_name: str) -> tuple[str, str]:
    owner, repo = full_name.split("/", 1)
    return owner, repo


class GitHubConnector:
    source_code = "github"

    def __init__(
        self,
        client: GitHubDataSource,
        store: RepositoryStore,
        *,
        repositories: Sequence[str],
        max_items: int = DEFAULT_MAX_ITEMS,
    ) -> None:
        parsed = parse_repositories(repositories)
        if not parsed:
            raise GitHubConfigurationError(
                "At least one GitHub repository is required (owner/repository)."
            )
        if max_items < 1:
            raise GitHubConfigurationError("max items must be >= 1")
        self._client = client
        self._store = store
        self._repositories = parsed[:max_items]
        self._max_items = max_items

    def ingest(self, *, collected_at: datetime | None = None) -> IngestionResult:
        if collected_at is not None and collected_at.tzinfo is None:
            raise ValueError("collected_at must be timezone-aware")
        run_collected_at = collected_at or datetime.now(timezone.utc)

        logger.info(
            "github.ingest.start repos=%s max_items=%s",
            ",".join(self._repositories),
            self._max_items,
        )
        result = IngestionResult(
            source_code=self.source_code,
            watchlist_size=len(self._repositories),
        )

        for full_name in self._repositories:
            owner, repo = split_repository(full_name)
            try:
                outcome = self._ingest_one(owner, repo, run_collected_at)
            except IntegrityError:
                logger.exception("github.ingest.integrity_error repo=%s", full_name)
                raise
            except SQLAlchemyError:
                logger.exception("github.ingest.database_error repo=%s", full_name)
                raise
            result.outcomes.append(outcome)
            if outcome.ok:
                logger.info(
                    "github.repo_ok repo=%s snapshots=%s",
                    outcome.external_id,
                    outcome.snapshots_inserted,
                )
            else:
                logger.error(
                    "github.repo_failed repo=%s error=%s",
                    full_name,
                    outcome.error,
                )

        logger.info(
            "github.complete succeeded=%s failed=%s snapshots=%s",
            len(result.succeeded),
            len(result.failed),
            result.snapshots_inserted,
        )
        return result

    def _ingest_one(
        self,
        owner: str,
        repo: str,
        collected_at: datetime,
    ) -> ChannelIngestionOutcome:
        full_name = f"{owner}/{repo}"
        try:
            resource = self._client.get_repository(owner, repo)
            normalized = normalize_repository(resource, collected_at=collected_at)
            persisted = self._store.persist(normalized)
        except _FETCH_ERRORS as exc:
            return ChannelIngestionOutcome(external_id=full_name, error=str(exc))

        return ChannelIngestionOutcome(
            external_id=normalized.external_id,
            content_items_upserted=1,
            snapshots_inserted=persisted.snapshots_inserted,
        )


def build_github_connector(
    *,
    repositories: Sequence[str],
    max_items: int = DEFAULT_MAX_ITEMS,
    token: str | None = None,
    client: GitHubDataSource | None = None,
    store: RepositoryStore | None = None,
    http_client=None,
) -> GitHubConnector:
    gh_client: GitHubDataSource
    if client is not None:
        gh_client = client
    else:
        gh_client = GitHubClient(token=token, http_client=http_client)
    return GitHubConnector(
        gh_client,
        store or SqlAlchemyRepositoryStore(),
        repositories=repositories,
        max_items=max_items,
    )
