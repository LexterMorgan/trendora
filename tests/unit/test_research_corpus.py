"""Corpus-level structural evaluation over the research-quality fixtures.

These assertions are a regression gate, not a quality score. They pin what the
evaluator currently reports so a change in behaviour is visible in review.
"""

from __future__ import annotations

from pathlib import Path

from trendora.research.evaluation import (
    build_diagnostics,
    evaluate_corpus,
    load_corpus,
)

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "research_quality" / "cases.json"

# What the evaluator reports today for the one finding in each case.
EXPECTED_TEXT_SUPPORT = {
    "exact_description_citation": True,
    "title_description_mismatch": False,  # cites title, words only appear in description
    "unsupported_specific_claim": False,
    "publication_event_date_confusion": False,
    "promotional_attribution": False,
    "missing_evidence": False,
    "extractive_fallback": True,
}


def test_corpus_totals_are_stable() -> None:
    summary = evaluate_corpus(load_corpus(CORPUS))
    assert summary["totals"] == {
        "cases": 7,
        "findings": 7,
        "citations": 8,
        "resolved_citations": 7,
        "findings_with_text_support": 2,
    }
    assert summary["rates"]["citation_resolution"] == 0.875
    assert summary["rates"]["text_support"] == 2 / 7


def test_each_case_reports_the_same_support_flag() -> None:
    cases = load_corpus(CORPUS)
    for case in cases:
        diagnostics = build_diagnostics(case["report"])
        findings = diagnostics["findings"]
        assert len(findings) == 1, case["name"]
        assert findings[0]["has_text_support"] is EXPECTED_TEXT_SUPPORT[case["name"]]

    assert {case["name"] for case in cases} == set(EXPECTED_TEXT_SUPPORT)


def test_unresolved_citation_is_counted() -> None:
    summary = evaluate_corpus(load_corpus(CORPUS))
    missing = next(row for row in summary["cases"] if row["name"] == "missing_evidence")
    assert missing["resolved_citations"] == 0
    assert missing["citations"] == 1


def test_empty_corpus_has_no_rates() -> None:
    summary = evaluate_corpus([])
    assert summary["totals"]["cases"] == 0
    assert summary["rates"]["citation_resolution"] is None
    assert summary["rates"]["text_support"] is None
