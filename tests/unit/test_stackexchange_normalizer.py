"""Stack Exchange normalization tests. No HTTP and no database."""

from datetime import datetime, timezone

import pytest

from trendora.connectors.stackexchange.normalizer import (
    CONTENT_TYPE_QUESTION,
    question_external_id,
    normalize_question,
)
from trendora.connectors.stackexchange.schemas import QuestionResource
from tests.fixtures.stackexchange_responses import (
    QUESTION_DS_A,
    QUESTION_MALFORMED_STATS,
    QUESTION_SO_A,
    QUESTION_SO_C,
    SO_QUESTION_ID,
)

COLLECTED = datetime(2026, 8, 20, 21, 0, tzinfo=timezone.utc)


def test_valid_question_normalization() -> None:
    item = QuestionResource.model_validate(QUESTION_SO_A)
    question = normalize_question(item, site="stackoverflow", collected_at=COLLECTED)
    assert question.external_id == question_external_id("stackoverflow", SO_QUESTION_ID)
    assert question.external_id == "stackoverflow:123"
    assert question.content_type == CONTENT_TYPE_QUESTION
    assert question.title == "How do I groupby in pandas?"
    assert question.url == QUESTION_SO_A["link"]
    assert question.description is None
    assert question.published_at == datetime(2007, 4, 4, 19, 16, 40, tzinfo=timezone.utc)
    assert question.published_at is not None and question.published_at.tzinfo is not None
    assert question.source_metadata["site"] == "stackoverflow"
    assert question.source_metadata["question_id"] == SO_QUESTION_ID
    assert question.source_metadata["tags"] == ["python", "pandas"]
    assert question.source_metadata["is_answered"] is True
    assert question.source_metadata["answer_count"] == 3
    assert question.source_metadata["accepted_answer_id"] == 999
    assert question.source_metadata["owner"] == {"user_id": 42, "display_name": "alice"}
    assert question.source_metadata["content_license"] == "CC BY-SA 4.0"
    assert "topic" not in question.source_metadata
    assert "topics" not in question.source_metadata
    metrics = {row.metric_name: row.metric_value for row in question.snapshots}
    assert metrics == {"score": 12, "view_count": 400, "answer_count": 3}
    assert all(row.collected_at == COLLECTED for row in question.snapshots)
    assert all(row.subject == "content_item" for row in question.snapshots)


def test_cross_site_question_ids_use_site_prefixed_external_id() -> None:
    so = normalize_question(
        QuestionResource.model_validate(QUESTION_SO_A),
        site="stackoverflow",
        collected_at=COLLECTED,
    )
    ds = normalize_question(
        QuestionResource.model_validate(QUESTION_DS_A),
        site="datascience",
        collected_at=COLLECTED,
    )
    assert so.source_metadata["question_id"] == ds.source_metadata["question_id"] == 123
    assert so.external_id == "stackoverflow:123"
    assert ds.external_id == "datascience:123"
    assert so.external_id != ds.external_id


def test_missing_owner_and_accepted_answer_are_omitted() -> None:
    item = QuestionResource.model_validate(QUESTION_SO_C)
    question = normalize_question(item, site="stackoverflow", collected_at=COLLECTED)
    assert "owner" not in question.source_metadata
    assert "accepted_answer_id" not in question.source_metadata
    assert question.source_metadata["is_answered"] is False
    metrics = {row.metric_name: row.metric_value for row in question.snapshots}
    assert metrics["score"] == 0
    assert metrics["view_count"] == 9
    assert metrics["answer_count"] == 0


def test_malformed_numeric_metrics_are_skipped() -> None:
    item = QuestionResource.model_validate(QUESTION_MALFORMED_STATS)
    question = normalize_question(item, site="stackoverflow", collected_at=COLLECTED)
    metrics = {row.metric_name: row.metric_value for row in question.snapshots}
    assert "score" not in metrics
    assert "view_count" not in metrics
    assert metrics == {"answer_count": 2}


def test_unix_timestamps_are_timezone_aware_utc() -> None:
    item = QuestionResource.model_validate(QUESTION_SO_A)
    question = normalize_question(item, site="stackoverflow", collected_at=COLLECTED)
    assert question.published_at == datetime.fromtimestamp(1175714200, tz=timezone.utc)
    assert question.source_metadata["last_activity_date"].endswith("+00:00")


def test_missing_link_is_not_invented() -> None:
    payload = {**QUESTION_SO_A, "link": ""}
    question = normalize_question(
        QuestionResource.model_validate(payload),
        site="stackoverflow",
        collected_at=COLLECTED,
    )
    assert question.url is None


def test_title_is_preserved() -> None:
    payload = {**QUESTION_SO_A, "title": "How do I groupby in pandas?"}
    question = normalize_question(
        QuestionResource.model_validate(payload),
        site="stackoverflow",
        collected_at=COLLECTED,
    )
    assert question.title == "How do I groupby in pandas?"


def test_naive_collected_at_is_rejected() -> None:
    item = QuestionResource.model_validate(QUESTION_SO_A)
    with pytest.raises(ValueError, match="timezone-aware"):
        normalize_question(item, site="stackoverflow", collected_at=datetime(2026, 8, 20))
