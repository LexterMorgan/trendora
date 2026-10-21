"""Grounded-answer rules: nothing outside the saved report may be cited."""

from __future__ import annotations

import pytest

from trendora.research.report_ask import (
    UngroundedAnswerError,
    allowed_reference_ids,
    build_ask_context,
    validate_answer,
)

SNAPSHOT = {
    "status": "completed",
    "research": {
        "query": {"topic": "battery recycling", "date_from": "2026-01-01", "date_to": "2026-02-01"},
        "references": [
            {
                "source_code": "youtube",
                "content_external_id": "vid-1",
                "title": "Recycling plant tour",
                "description": "A tour of a plant.",
                "published_at": "2026-01-10T00:00:00Z",
            },
            {
                "source_code": "web",
                "content_external_id": "doc-9",
                "title": "Policy update",
                "description": None,
                "published_at": None,
            },
        ],
    },
    "interpretation": {
        "interpretations": [
            {
                "statement": "Two facilities opened.",
                "citations": [
                    {
                        "kind": "fact",
                        "reference": {"source_code": "youtube", "content_external_id": "vid-1"},
                        "field": "title",
                    }
                ],
            }
        ]
    },
}


def test_allowed_ids_cover_sources_and_citations() -> None:
    assert allowed_reference_ids(SNAPSHOT) == {("youtube", "vid-1"), ("web", "doc-9")}


def test_answer_must_cite_something() -> None:
    with pytest.raises(UngroundedAnswerError):
        validate_answer([], allowed_reference_ids(SNAPSHOT))


def test_answer_may_not_cite_outside_the_report() -> None:
    with pytest.raises(UngroundedAnswerError):
        validate_answer(
            [{"source_code": "web", "content_external_id": "not-in-report"}],
            allowed_reference_ids(SNAPSHOT),
        )


def test_answer_inside_the_report_is_accepted() -> None:
    validate_answer(
        [{"source_code": "web", "content_external_id": "doc-9"}],
        allowed_reference_ids(SNAPSHOT),
    )


def test_context_is_built_from_the_snapshot_only() -> None:
    context = build_ask_context(SNAPSHOT)
    assert context["topic"] == "battery recycling"
    assert len(context["findings"]) == 1
    assert {source["content_external_id"] for source in context["sources"]} == {"vid-1", "doc-9"}
