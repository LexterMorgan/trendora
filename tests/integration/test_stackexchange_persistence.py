"""PostgreSQL persistence tests for Stack Exchange ingestion.

These tests roll back and never call the Stack Exchange API. Assertions are
scoped to fixture external IDs.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session, sessionmaker

from trendora.config import reset_settings_cache
from trendora.connectors.stackexchange.connector import StackExchangeConnector
from trendora.connectors.stackexchange.normalizer import NormalizedQuestion, question_external_id
from trendora.connectors.stackexchange.persistence import persist_question
from trendora.connectors.stackexchange.schemas import QuestionResource
from trendora.db.session import get_engine, reset_engine
from trendora.models import ContentItem, ContentItemTopic, MetricSnapshot, Publisher
from trendora.reference import SOURCE_IDS
from tests.fixtures.stackexchange_responses import (
    QUESTION_DS_A,
    QUESTION_SO_A,
    SO_QUESTION_ID,
)

pytestmark = pytest.mark.integration

COLLECTED = datetime(2026, 8, 20, 22, 0, tzinfo=timezone.utc)
COLLECTED_LATER = datetime(2026, 8, 20, 23, 0, tzinfo=timezone.utc)
SE_SOURCE = SOURCE_IDS["stack_exchange"]
SO_EXTERNAL = question_external_id("stackoverflow", SO_QUESTION_ID)
DS_EXTERNAL = question_external_id("datascience", SO_QUESTION_ID)


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

    def persist(self, question: NormalizedQuestion):
        return persist_question(self._session, question)


class _FakeClient:
    def __init__(self, questions: dict[str, list[QuestionResource]]) -> None:
        self.questions = questions

    def list_questions(self, site: str, *, max_items: int, tags=()) -> list[QuestionResource]:
        return list(self.questions.get(site, []))[:max_items]


def _ingest(
    session: Session,
    *,
    collected_at: datetime,
    questions: dict[str, list[QuestionResource]],
) -> None:
    connector = StackExchangeConnector(
        _FakeClient(questions),
        _SessionStore(session),
        sites=tuple(questions),
        max_items=50,
    )
    result = connector.ingest(collected_at=collected_at)
    session.flush()
    assert result.failed == []


def _content(session: Session, external_id: str) -> ContentItem | None:
    return (
        session.query(ContentItem)
        .filter(
            ContentItem.source_id == SE_SOURCE,
            ContentItem.external_id == external_id,
        )
        .one_or_none()
    )


def test_new_question_creates_content_identity_without_publisher_or_market(
    db_session: Session,
) -> None:
    _ingest(
        db_session,
        collected_at=COLLECTED,
        questions={"stackoverflow": [QuestionResource.model_validate(QUESTION_SO_A)]},
    )
    question = _content(db_session, SO_EXTERNAL)
    assert question is not None
    assert question.content_type == "question"
    assert question.publisher_id is None
    assert question.market_id is None
    assert question.source_metadata["site"] == "stackoverflow"
    assert question.source_metadata["question_id"] == SO_QUESTION_ID
    assert question.source_metadata["tags"] == ["python", "pandas"]
    assert question.source_metadata["owner"]["display_name"] == "alice"

    publishers = (
        db_session.query(Publisher)
        .filter(
            Publisher.source_id == SE_SOURCE,
            Publisher.external_id.in_(["42", "alice"]),
        )
        .all()
    )
    assert publishers == []

    snapshots = (
        db_session.query(MetricSnapshot)
        .filter(MetricSnapshot.content_item_id == question.id)
        .all()
    )
    names = {row.metric_name: row.metric_value for row in snapshots}
    assert names["score"] == 12
    assert names["view_count"] == 400
    assert names["answer_count"] == 3
    assert all(row.publisher_id is None for row in snapshots)
    assert all(row.retention_policy_id is None for row in snapshots)
    assert {row.collected_at for row in snapshots} == {COLLECTED}


def test_reingest_same_collected_at_is_idempotent_and_later_appends(db_session: Session) -> None:
    payload = {"stackoverflow": [QuestionResource.model_validate(QUESTION_SO_A)]}
    _ingest(db_session, collected_at=COLLECTED, questions=payload)
    first = _content(db_session, SO_EXTERNAL)
    assert first is not None
    first_count = (
        db_session.query(MetricSnapshot).filter(MetricSnapshot.content_item_id == first.id).count()
    )
    assert first_count > 0

    _ingest(db_session, collected_at=COLLECTED, questions=payload)
    identities = (
        db_session.query(ContentItem)
        .filter(
            ContentItem.source_id == SE_SOURCE,
            ContentItem.external_id == SO_EXTERNAL,
        )
        .all()
    )
    assert len(identities) == 1
    assert (
        db_session.query(MetricSnapshot).filter(MetricSnapshot.content_item_id == first.id).count()
        == first_count
    )

    _ingest(db_session, collected_at=COLLECTED_LATER, questions=payload)
    assert (
        db_session.query(MetricSnapshot).filter(MetricSnapshot.content_item_id == first.id).count()
        == first_count * 2
    )


def test_same_numeric_question_id_on_two_sites_is_two_identities(db_session: Session) -> None:
    _ingest(
        db_session,
        collected_at=COLLECTED,
        questions={
            "stackoverflow": [QuestionResource.model_validate(QUESTION_SO_A)],
            "datascience": [QuestionResource.model_validate(QUESTION_DS_A)],
        },
    )
    so = _content(db_session, SO_EXTERNAL)
    ds = _content(db_session, DS_EXTERNAL)
    assert so is not None and ds is not None
    assert so.id != ds.id
    assert so.source_metadata["question_id"] == ds.source_metadata["question_id"] == 123
    assert so.source_metadata["site"] == "stackoverflow"
    assert ds.source_metadata["site"] == "datascience"
    assert so.publisher_id is None and ds.publisher_id is None
    assert so.market_id is None and ds.market_id is None


def test_tags_stay_in_source_metadata_and_do_not_create_topics(db_session: Session) -> None:
    _ingest(
        db_session,
        collected_at=COLLECTED,
        questions={"stackoverflow": [QuestionResource.model_validate(QUESTION_SO_A)]},
    )
    question = _content(db_session, SO_EXTERNAL)
    assert question is not None
    assert question.source_metadata["tags"] == ["python", "pandas"]
    topic_links = (
        db_session.query(ContentItemTopic)
        .filter(ContentItemTopic.content_item_id == question.id)
        .all()
    )
    assert topic_links == []
