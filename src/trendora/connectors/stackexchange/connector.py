"""Orchestrate Stack Exchange fetch → normalize → persist for selected sites."""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from trendora.connectors.base import ChannelIngestionOutcome, IngestionResult
from trendora.connectors.stackexchange.client import StackExchangeClient
from trendora.connectors.stackexchange.exceptions import (
    StackExchangeApiError,
    StackExchangeConfigurationError,
    StackExchangeHttpError,
    StackExchangeItemError,
    StackExchangeResponseError,
)
from trendora.connectors.stackexchange.normalizer import (
    DEFAULT_MAX_ITEMS_PER_SITE,
    DEFAULT_SITES,
    MAX_TAGS,
    NormalizedQuestion,
    normalize_question,
    question_external_id,
)
from trendora.connectors.stackexchange.persistence import QuestionPersistResult, persist_question
from trendora.connectors.stackexchange.schemas import QuestionResource
from trendora.db.session import get_session_factory

logger = logging.getLogger("trendora.connectors.stackexchange")

_SITE_RE = re.compile(r"^[a-z0-9-]+$")
_FETCH_ERRORS = (
    StackExchangeHttpError,
    StackExchangeResponseError,
    StackExchangeApiError,
    StackExchangeItemError,
)


class StackExchangeDataSource(Protocol):
    def list_questions(
        self,
        site: str,
        *,
        max_items: int,
        tags: Sequence[str] = (),
    ) -> list[QuestionResource]: ...


class QuestionStore(Protocol):
    def persist(self, question: NormalizedQuestion) -> QuestionPersistResult: ...


class SqlAlchemyQuestionStore:
    """One transaction per question. Does not span the whole site run."""

    def __init__(self, session_factory: sessionmaker[Session] | None = None) -> None:
        self._session_factory = session_factory or get_session_factory()

    def persist(self, question: NormalizedQuestion) -> QuestionPersistResult:
        session = self._session_factory()
        try:
            result = persist_question(session, question)
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def parse_sites(value: str | Sequence[str] | None) -> tuple[str, ...]:
    """Return unique Stack Exchange site slugs in first-seen order.

    ``None`` selects stackoverflow and datascience. URLs and domain names are
    rejected; they are not converted into site identifiers.
    """

    if value is None:
        return DEFAULT_SITES
    if isinstance(value, str):
        tokens = value.split(",")
    else:
        tokens = list(value)

    seen: set[str] = set()
    ordered: list[str] = []
    for raw in tokens:
        token = raw.strip().lower()
        if not token:
            continue
        if not _SITE_RE.fullmatch(token) or "." in token or "/" in token or ":" in token:
            raise StackExchangeConfigurationError(
                f"Invalid Stack Exchange site {raw!r}. Use a site slug such as "
                "'stackoverflow' or 'datascience', not a URL or domain name."
            )
        if token in seen:
            continue
        seen.add(token)
        ordered.append(token)
    if not ordered:
        raise StackExchangeConfigurationError(
            "At least one Stack Exchange site is required (for example stackoverflow)."
        )
    return tuple(ordered)


def parse_tags(value: str | Sequence[str] | None) -> tuple[str, ...]:
    """Return unique tags in first-seen order. At most five tags are allowed."""

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
        if token in seen:
            continue
        seen.add(token)
        ordered.append(token)
    if len(ordered) > MAX_TAGS:
        raise StackExchangeConfigurationError(
            f"At most {MAX_TAGS} tags are allowed (Stack Exchange tagged= limit)."
        )
    return tuple(ordered)


class StackExchangeConnector:
    source_code = "stack_exchange"

    def __init__(
        self,
        client: StackExchangeDataSource,
        store: QuestionStore,
        *,
        sites: Sequence[str] | None = None,
        max_items: int = DEFAULT_MAX_ITEMS_PER_SITE,
        tags: Sequence[str] | None = None,
    ) -> None:
        self._client = client
        self._store = store
        self._sites = parse_sites(sites)
        if max_items < 1:
            raise StackExchangeConfigurationError("max items per site must be >= 1")
        self._max_items = max_items
        self._tags = parse_tags(tags)

    def ingest(self, *, collected_at: datetime | None = None) -> IngestionResult:
        if collected_at is not None and collected_at.tzinfo is None:
            raise ValueError("collected_at must be timezone-aware")
        run_collected_at = collected_at or datetime.now(timezone.utc)

        logger.info(
            "stackexchange.ingest.start sites=%s max_items=%s tags=%s",
            ",".join(self._sites),
            self._max_items,
            ",".join(self._tags),
        )
        result = IngestionResult(source_code=self.source_code, watchlist_size=len(self._sites))
        attempted = 0

        for site in self._sites:
            try:
                questions = self._client.list_questions(
                    site,
                    max_items=self._max_items,
                    tags=self._tags,
                )
            except _FETCH_ERRORS as exc:
                logger.error("stackexchange.ingest.site_failed site=%s error=%s", site, exc)
                result.outcomes.append(ChannelIngestionOutcome(external_id=site, error=str(exc)))
                continue

            logger.info(
                "stackexchange.site_collected site=%s items=%s max_items=%s",
                site,
                len(questions),
                self._max_items,
            )
            if not questions:
                continue

            for question in questions:
                attempted += 1
                try:
                    outcome = self._ingest_one(site, question, run_collected_at)
                except IntegrityError:
                    logger.exception(
                        "stackexchange.ingest.integrity_error site=%s question_id=%s",
                        site,
                        question.question_id,
                    )
                    raise
                except SQLAlchemyError:
                    logger.exception(
                        "stackexchange.ingest.database_error site=%s question_id=%s",
                        site,
                        question.question_id,
                    )
                    raise
                if outcome is None:
                    continue
                result.outcomes.append(outcome)
                if outcome.ok:
                    logger.info(
                        "stackexchange.question_ok site=%s question_id=%s snapshots=%s",
                        site,
                        question.question_id,
                        outcome.snapshots_inserted,
                    )
                else:
                    logger.error(
                        "stackexchange.question_failed site=%s question_id=%s error=%s",
                        site,
                        question.question_id,
                        outcome.error,
                    )

        result.watchlist_size = attempted or len(self._sites)
        logger.info(
            "stackexchange.complete succeeded=%s failed=%s snapshots=%s",
            len(result.succeeded),
            len(result.failed),
            result.snapshots_inserted,
        )
        return result

    def _ingest_one(
        self,
        site: str,
        question: QuestionResource,
        collected_at: datetime,
    ) -> ChannelIngestionOutcome | None:
        external_id = question_external_id(site, question.question_id)
        try:
            normalized = normalize_question(question, site=site, collected_at=collected_at)
            persisted = self._store.persist(normalized)
        except StackExchangeItemError as exc:
            logger.warning(
                "stackexchange.question_failed site=%s question_id=%s error=%s",
                site,
                question.question_id,
                exc,
            )
            return None
        except _FETCH_ERRORS as exc:
            return ChannelIngestionOutcome(external_id=external_id, error=str(exc))

        return ChannelIngestionOutcome(
            external_id=external_id,
            content_items_upserted=1,
            snapshots_inserted=persisted.snapshots_inserted,
        )


def build_stackexchange_connector(
    *,
    sites: Sequence[str] | None = None,
    max_items: int = DEFAULT_MAX_ITEMS_PER_SITE,
    tags: Sequence[str] | None = None,
    api_key: str | None = None,
    client: StackExchangeDataSource | None = None,
    store: QuestionStore | None = None,
    http_client=None,
) -> StackExchangeConnector:
    se_client: StackExchangeDataSource
    if client is not None:
        se_client = client
    else:
        se_client = StackExchangeClient(api_key=api_key, http_client=http_client)
    return StackExchangeConnector(
        se_client,
        store or SqlAlchemyQuestionStore(),
        sites=sites,
        max_items=max_items,
        tags=tags,
    )
