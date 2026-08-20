"""Stack Exchange orchestrator tests. Fake client and store; no live API."""

from datetime import datetime, timezone

import pytest

from trendora.connectors.stackexchange.connector import (
    DEFAULT_SITES,
    StackExchangeConnector,
    parse_sites,
    parse_tags,
)
from trendora.connectors.stackexchange.exceptions import (
    StackExchangeConfigurationError,
    StackExchangeHttpError,
)
from trendora.connectors.stackexchange.normalizer import NormalizedQuestion
from trendora.connectors.stackexchange.persistence import QuestionPersistResult
from trendora.connectors.stackexchange.schemas import QuestionResource
from tests.fixtures.stackexchange_responses import (
    QUESTION_DS_A,
    QUESTION_SO_A,
    QUESTION_SO_B,
    QUESTION_SO_C,
    SO_QUESTION_ID,
)

COLLECTED = datetime(2026, 8, 20, 21, 30, tzinfo=timezone.utc)


class FakeClient:
    def __init__(
        self,
        *,
        questions: dict[str, list[QuestionResource]] | None = None,
        site_errors: dict[str, Exception] | None = None,
    ) -> None:
        self.questions = questions or {}
        self.site_errors = site_errors or {}
        self.requests: list[tuple[str, int, tuple[str, ...]]] = []

    def list_questions(self, site: str, *, max_items: int, tags=()) -> list[QuestionResource]:
        self.requests.append((site, max_items, tuple(tags)))
        if site in self.site_errors:
            raise self.site_errors[site]
        return list(self.questions.get(site, []))[:max_items]


class FakeStore:
    def __init__(self) -> None:
        self.questions: list[NormalizedQuestion] = []

    def persist(self, question: NormalizedQuestion) -> QuestionPersistResult:
        self.questions.append(question)
        return QuestionPersistResult(
            content_item_created=True,
            content_item_updated=False,
            snapshots_inserted=len(question.snapshots),
        )


def _so_questions() -> list[QuestionResource]:
    return [
        QuestionResource.model_validate(QUESTION_SO_A),
        QuestionResource.model_validate(QUESTION_SO_B),
        QuestionResource.model_validate(QUESTION_SO_C),
    ]


def test_parse_sites_defaults_and_dedupes() -> None:
    assert parse_sites(None) == DEFAULT_SITES
    assert parse_sites("datascience, stackoverflow,datascience") == ("datascience", "stackoverflow")


def test_parse_sites_rejects_urls_domains_and_empty() -> None:
    with pytest.raises(StackExchangeConfigurationError, match="site slug"):
        parse_sites("https://stackoverflow.com")
    with pytest.raises(StackExchangeConfigurationError, match="site slug"):
        parse_sites("stackoverflow.com")
    with pytest.raises(StackExchangeConfigurationError, match="At least one"):
        parse_sites(" , , ")


def test_parse_tags_dedupes_and_rejects_more_than_five() -> None:
    assert parse_tags(None) == ()
    assert parse_tags("python, sql, python") == ("python", "sql")
    with pytest.raises(StackExchangeConfigurationError, match="At most 5"):
        parse_tags("a,b,c,d,e,f")


def test_ingest_fetches_configured_sites_in_stable_order() -> None:
    client = FakeClient(
        questions={
            "stackoverflow": [QuestionResource.model_validate(QUESTION_SO_A)],
            "datascience": [QuestionResource.model_validate(QUESTION_DS_A)],
        }
    )
    store = FakeStore()
    result = StackExchangeConnector(client, store, sites=DEFAULT_SITES, max_items=50).ingest(
        collected_at=COLLECTED
    )
    assert [site for site, _limit, _tags in client.requests] == ["stackoverflow", "datascience"]
    assert all(limit == 50 for _site, limit, _tags in client.requests)
    assert result.failed == []
    assert {row.external_id for row in result.succeeded} == {
        "stackoverflow:123",
        "datascience:123",
    }
    assert {row.external_id for row in store.questions} == {
        "stackoverflow:123",
        "datascience:123",
    }
    assert all(row.collected_at == COLLECTED for row in store.questions)


def test_duplicate_sites_are_requested_once() -> None:
    client = FakeClient(
        questions={"stackoverflow": [QuestionResource.model_validate(QUESTION_SO_A)]}
    )
    StackExchangeConnector(
        client,
        FakeStore(),
        sites=("stackoverflow", "stackoverflow"),
        max_items=10,
    ).ingest(collected_at=COLLECTED)
    assert [site for site, _limit, _tags in client.requests] == ["stackoverflow"]


def test_empty_site_results_do_not_fail_the_run() -> None:
    client = FakeClient(questions={"stackoverflow": [], "datascience": []})
    result = StackExchangeConnector(client, FakeStore(), sites=DEFAULT_SITES, max_items=10).ingest(
        collected_at=COLLECTED
    )
    assert result.failed == []
    assert result.succeeded == []
    assert [site for site, _limit, _tags in client.requests] == ["stackoverflow", "datascience"]


def test_max_items_and_tags_are_forwarded_per_site() -> None:
    client = FakeClient(questions={"stackoverflow": _so_questions()})
    result = StackExchangeConnector(
        client,
        FakeStore(),
        sites=("stackoverflow",),
        max_items=2,
        tags=("python", "sql"),
    ).ingest(collected_at=COLLECTED)
    assert client.requests == [("stackoverflow", 2, ("python", "sql"))]
    assert [row.external_id for row in result.succeeded] == [
        "stackoverflow:123",
        "stackoverflow:456",
    ]


def test_partial_site_failure_continues() -> None:
    client = FakeClient(
        questions={
            "stackoverflow": [QuestionResource.model_validate(QUESTION_SO_A)],
            "datascience": [QuestionResource.model_validate(QUESTION_DS_A)],
        },
        site_errors={"datascience": StackExchangeHttpError("boom", status_code=500)},
    )
    store = FakeStore()
    result = StackExchangeConnector(
        client,
        store,
        sites=("stackoverflow", "datascience", "stackoverflow"),
        max_items=10,
    ).ingest(collected_at=COLLECTED)
    assert [row.external_id for row in result.failed] == ["datascience"]
    assert [row.external_id for row in result.succeeded] == ["stackoverflow:123"]
    assert [row.external_id for row in store.questions] == ["stackoverflow:123"]


def test_one_collected_at_is_used_for_the_entire_run() -> None:
    client = FakeClient(
        questions={
            "stackoverflow": [QuestionResource.model_validate(QUESTION_SO_A)],
            "datascience": [QuestionResource.model_validate(QUESTION_DS_A)],
        }
    )
    store = FakeStore()
    StackExchangeConnector(client, store, sites=DEFAULT_SITES, max_items=10).ingest(
        collected_at=COLLECTED
    )
    assert {row.collected_at for row in store.questions} == {COLLECTED}
    assert all(snap.collected_at == COLLECTED for row in store.questions for snap in row.snapshots)


def test_malformed_question_is_skipped_and_others_continue() -> None:
    store = FakeStore()
    malformed = QuestionResource.model_validate({**QUESTION_SO_A, "question_id": 0})
    valid = QuestionResource.model_validate(QUESTION_SO_B)
    result = StackExchangeConnector(
        FakeClient(questions={"stackoverflow": [malformed, valid]}),
        store,
        sites=("stackoverflow",),
    ).ingest(collected_at=COLLECTED)
    assert result.failed == []
    assert [row.external_id for row in result.succeeded] == ["stackoverflow:456"]
    assert [row.external_id for row in store.questions] == ["stackoverflow:456"]


def test_no_publisher_or_topic_fields_are_created() -> None:
    store = FakeStore()
    StackExchangeConnector(
        FakeClient(questions={"stackoverflow": [QuestionResource.model_validate(QUESTION_SO_A)]}),
        store,
        sites=("stackoverflow",),
    ).ingest(collected_at=COLLECTED)
    question = store.questions[0]
    assert "publisher_id" not in question.source_metadata
    assert "topics" not in question.source_metadata
    assert question.source_metadata["tags"] == ["python", "pandas"]
    assert not hasattr(store, "publishers")
    assert not hasattr(store, "topics")


def test_connector_does_not_call_search_answers_or_users() -> None:
    client = FakeClient(
        questions={"stackoverflow": [QuestionResource.model_validate(QUESTION_SO_A)]}
    )
    StackExchangeConnector(client, FakeStore(), sites=("stackoverflow",)).ingest(
        collected_at=COLLECTED
    )
    assert not hasattr(client, "search")
    assert not hasattr(client, "list_answers")
    assert not hasattr(client, "list_users")
    assert not hasattr(client, "schedule")


def test_cross_site_question_id_collision_is_not_collapsed() -> None:
    store = FakeStore()
    StackExchangeConnector(
        FakeClient(
            questions={
                "stackoverflow": [QuestionResource.model_validate(QUESTION_SO_A)],
                "datascience": [QuestionResource.model_validate(QUESTION_DS_A)],
            }
        ),
        store,
        sites=("stackoverflow", "datascience"),
    ).ingest(collected_at=COLLECTED)
    ids = [row.external_id for row in store.questions]
    assert ids == ["stackoverflow:123", "datascience:123"]
    assert store.questions[0].source_metadata["question_id"] == 123
    assert store.questions[1].source_metadata["question_id"] == 123
