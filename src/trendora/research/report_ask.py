"""Answer one question about a saved report, grounded in that report only.

The snapshot is already the immutable record of what was collected and
interpreted. Nothing here re-runs retrieval, scoring, or interpretation: the
prompt context is derived from the stored report, and every citation the model
returns must resolve to a reference that report already holds. An answer that
cites nothing, or cites a reference outside the report, is refused rather than
shown with a caveat.
"""

from __future__ import annotations

from typing import Any

MAX_QUESTION_CHARS = 500
MAX_REFERENCES = 60
MAX_STATEMENT_CHARS = 400
MAX_DESCRIPTION_CHARS = 280


class UngroundedAnswerError(Exception):
    """The model answered without a citation the report can resolve."""


def _reference_id(value: Any) -> tuple[str, str] | None:
    """Read one reference identity from either contract shape.

    Snapshots carry references as ``{source_code, content_external_id}`` at the
    top level; citations nest the same pair under ``reference``. Both are
    accepted here, nothing else.
    """
    if not isinstance(value, dict):
        return None
    pair = value.get("reference") if isinstance(value.get("reference"), dict) else value
    source_code = pair.get("source_code")
    content_external_id = pair.get("content_external_id")
    if not isinstance(source_code, str) or not isinstance(content_external_id, str):
        return None
    if not source_code or not content_external_id:
        return None
    return source_code, content_external_id


def allowed_reference_ids(snapshot: dict[str, Any]) -> set[tuple[str, str]]:
    """Every reference identity the saved report can legitimately cite."""
    allowed: set[tuple[str, str]] = set()
    research = snapshot.get("research") or {}
    for reference in research.get("references") or []:
        key = _reference_id(reference)
        if key is not None:
            allowed.add(key)
    for item in (snapshot.get("interpretation") or {}).get("interpretations") or []:
        for citation in item.get("citations") or []:
            key = _reference_id(citation)
            if key is not None:
                allowed.add(key)
    return allowed


def build_ask_context(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Bounded, deterministic context: findings first, then their sources."""
    research = snapshot.get("research") or {}
    query = research.get("query") or {}
    findings: list[dict[str, Any]] = []
    for item in (snapshot.get("interpretation") or {}).get("interpretations") or []:
        statement = item.get("statement")
        if not isinstance(statement, str) or not statement.strip():
            continue
        citations = [
            {"source_code": key[0], "content_external_id": key[1]}
            for key in (
                _reference_id(citation) for citation in item.get("citations") or []
            )
            if key is not None
        ]
        findings.append(
            {"statement": statement[:MAX_STATEMENT_CHARS], "citations": citations}
        )

    sources: list[dict[str, Any]] = []
    for reference in research.get("references") or []:
        key = _reference_id(reference)
        if key is None:
            continue
        description = reference.get("description")
        sources.append(
            {
                "source_code": key[0],
                "content_external_id": key[1],
                "title": reference.get("title"),
                "published_at": reference.get("published_at"),
                "description": (
                    description[:MAX_DESCRIPTION_CHARS]
                    if isinstance(description, str)
                    else None
                ),
            }
        )
        if len(sources) >= MAX_REFERENCES:
            break

    return {
        "topic": query.get("topic"),
        "date_from": query.get("date_from"),
        "date_to": query.get("date_to"),
        "status": snapshot.get("status"),
        "findings": findings,
        "sources": sources,
    }


def validate_answer(
    citations: list[dict[str, str]], allowed: set[tuple[str, str]]
) -> None:
    """Refuse an answer that cites nothing, or cites outside the report."""
    if not citations:
        raise UngroundedAnswerError("The answer cited no source in this report.")
    unknown = [
        citation
        for citation in citations
        if (citation["source_code"], citation["content_external_id"]) not in allowed
    ]
    if unknown:
        raise UngroundedAnswerError(
            "The answer cited a source that is not part of this report."
        )
