"""Offline tests for structural research-quality evaluation. No network."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from trendora.research.evaluation import (
    EvaluationError,
    SNAPSHOT_FIELDS,
    apply_annotations,
    build_diagnostics,
    build_worksheet,
    count_judgments,
    evaluate_report,
    finding_id_for,
    main,
    report_fingerprint,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "research_quality"
CASES = json.loads((FIXTURES / "cases.json").read_text(encoding="utf-8"))["cases"]
CASES_BY_NAME = {case["name"]: case["report"] for case in CASES}


def _case(name: str) -> dict[str, Any]:
    return copy.deepcopy(CASES_BY_NAME[name])


def _finding(name: str) -> dict[str, Any]:
    return evaluate_report(_case(name))["diagnostics"]["findings"][0]


def _reference(**overrides: Any) -> dict[str, Any]:
    reference: dict[str, Any] = {
        "source_code": "youtube",
        "content_external_id": "video-1",
        "url": "https://example.test/watch?v=video-1",
        "title": "Title text",
        "description": "Description text",
        "published_at": "2026-03-01T00:00:00Z",
        "channel_external_id": None,
        "channel_title": "Channel name",
        "market_contexts": [],
        "market_context": None,
        "market_basis": None,
        "source_rank": 1,
        "metrics": {
            "view_count": 1200,
            "like_count": 90,
            "comment_count": 11,
            "reaction_count": None,
            "share_count": None,
        },
        "collected_at": "2026-03-05T09:30:00Z",
    }
    reference.update(overrides)
    return reference


def _facts(
    reference: dict[str, Any],
    *,
    omit: tuple[str, ...] = (),
    **overrides: Any,
) -> list[dict[str, Any]]:
    values = {
        "url": reference["url"],
        "collected_at": reference["collected_at"],
        "title": reference["title"],
        "description": reference["description"],
        "published_at": reference["published_at"],
        "channel_title": reference["channel_title"],
        "view_count": reference["metrics"]["view_count"],
    }
    values.update(overrides)
    for field in omit:
        values.pop(field, None)
    return [{"field": field, "value": value} for field, value in values.items()]


def _fact_citation(field: str, external_id: str = "video-1") -> dict[str, Any]:
    return {
        "kind": "fact",
        "reference": {
            "source_code": "youtube",
            "content_external_id": external_id,
        },
        "field": field,
    }


def _observation_citation(observation_type: str = "description_present") -> dict[str, Any]:
    return {
        "kind": "observation",
        "reference": {
            "source_code": "youtube",
            "content_external_id": "video-1",
        },
        "observation_type": observation_type,
    }


def _pattern_citation(observation_type: str = "description_present") -> dict[str, Any]:
    return {"kind": "pattern", "observation_type": observation_type}


def _report(
    *,
    findings: list[dict[str, Any]] | None = None,
    citations: list[dict[str, Any]] | None = None,
    statement: str = "A finding.",
    reference: dict[str, Any] | None = None,
    facts: list[dict[str, Any]] | None = None,
    observations: list[dict[str, Any]] | None = None,
    patterns: list[dict[str, Any]] | None = None,
    provenance: dict[str, str] | None = None,
) -> dict[str, Any]:
    reference = reference or _reference()
    if findings is None:
        findings = [{"statement": statement, "citations": citations or []}]
    if facts is None:
        facts = _facts(reference)
    identity = {
        "source_code": reference["source_code"],
        "content_external_id": reference["content_external_id"],
    }
    return {
        "status": "research_completed",
        "research": {"references": [reference]},
        "evidence": {
            "analyses": [
                {
                    "reference_id": identity,
                    "facts": facts,
                    "observations": observations or [],
                }
            ],
            "patterns": patterns or [],
        },
        "interpretation": {
            "model_provenance": provenance
            or {"provider": "openai-compatible", "model": "fictional-model-1"},
            "interpretations": findings,
        },
        "strategy": None,
        "ideation": None,
    }


# --- Benchmark cases --------------------------------------------------------


def test_benchmark_cases_are_present() -> None:
    assert set(CASES_BY_NAME) == {
        "exact_description_citation",
        "title_description_mismatch",
        "unsupported_specific_claim",
        "publication_event_date_confusion",
        "promotional_attribution",
        "missing_evidence",
        "extractive_fallback",
    }
    assert json.loads((FIXTURES / "annotations.json").read_text(encoding="utf-8")) == {}


def test_exact_field_citation_resolves_to_exact_description() -> None:
    finding = _finding("exact_description_citation")
    citation = finding["citations"][0]

    assert citation["identity"] == {
        "kind": "fact",
        "reference": {
            "source_code": "youtube",
            "content_external_id": "solar-vid-001",
        },
        "field": "description",
    }
    assert citation["resolved"] is True
    assert citation["reference_found"] is True
    assert citation["analysis_found"] is True
    assert citation["fact_found"] is True
    assert citation["value_status"] == "text"
    assert citation["cited_text"] == (
        "Three provinces pilot solar microgrids for rural schools, "
        "with results expected next year."
    )
    assert finding["has_text_support"] is True
    assert finding["origin"] == "ai"


def test_title_citation_exposes_the_distinct_description_text() -> None:
    finding = _finding("title_description_mismatch")
    citation = finding["citations"][0]
    reference = finding["references"][0]

    assert citation["identity"]["field"] == "title"
    assert citation["cited_text"] == "Solar microgrids reach rural schools"
    assert reference["title"] == citation["cited_text"]
    assert reference["description"] == (
        "Three provinces pilot solar microgrids for rural schools, "
        "with results expected next year."
    )
    assert "results expected next year" not in citation["cited_text"]
    assert "results expected next year" in reference["description"]
    assert finding["statement"] == "The pilot reported results expected next year."


def test_observation_and_pattern_only_claim_has_no_source_text_support() -> None:
    finding = _finding("unsupported_specific_claim")
    observation, pattern = finding["citations"]

    assert [item["identity"]["kind"] for item in finding["citations"]] == [
        "observation",
        "pattern",
    ]
    assert observation["resolved"] is True
    assert observation["observation_found"] is True
    assert observation["value"] is True
    assert observation["value_status"] == "non_text"
    assert pattern["resolved"] is True
    assert pattern["pattern_found"] is True
    assert pattern["value"]["analyzed_count"] == 1
    assert pattern["value"]["matching_count"] == 1
    assert pattern["value_status"] == "non_text"
    assert finding["has_text_support"] is False


def test_publication_and_collection_dates_are_distinct_facts() -> None:
    finding = _finding("publication_event_date_confusion")
    citation = finding["citations"][0]
    reference = finding["references"][0]

    assert citation["identity"]["field"] == "published_at"
    assert citation["resolved"] is True
    assert citation["cited_text"] == "2026-03-01T00:00:00Z"
    assert reference["published_date"] == "2026-03-01"
    assert reference["collection_date"] == "2026-03-05"
    assert reference["publication_collection_dates_distinct"] is True
    assert finding["publication_collection_dates_distinct"] is True


def test_promotional_attribution_is_not_source_text_support() -> None:
    finding = _finding("promotional_attribution")
    citation = finding["citations"][0]
    reference = finding["references"][0]

    assert citation["identity"]["field"] == "channel_title"
    assert citation["resolved"] is True
    assert citation["value_status"] == "text"
    assert citation["cited_text"] == "Northstar Learning"
    assert "accreditation" not in reference["title"]
    assert "accreditation" not in reference["description"]
    assert finding["has_text_support"] is False


def test_missing_reference_is_unresolved_not_guessed() -> None:
    finding = _finding("missing_evidence")
    citation = finding["citations"][0]

    assert citation["identity"]["reference"]["content_external_id"] == (
        "solar-vid-missing"
    )
    assert citation["resolved"] is False
    assert citation["reference_found"] is False
    assert citation["analysis_found"] is False
    assert citation["fact_found"] is False
    assert citation["value"] is None
    assert citation["value_status"] == "missing"
    assert citation["cited_text"] is None
    assert citation["unresolved_reason"] == "reference_not_found"
    assert finding["has_text_support"] is False


def test_extractive_fallback_is_labelled_and_exact() -> None:
    document = evaluate_report(_case("extractive_fallback"))
    finding = document["diagnostics"]["findings"][0]
    citation = finding["citations"][0]

    assert document["diagnostics"]["interpretation_origin"] == "extractive"
    assert document["diagnostics"]["model_provenance"] == {
        "provider": "source_evidence",
        "model": "extractive-v1",
    }
    assert finding["origin"] == "extractive"
    assert citation["resolved"] is True
    assert citation["identity"]["field"] == "description"
    assert citation["cited_text"] == finding["statement"]
    assert finding["has_text_support"] is True


# --- Canonical fingerprint and finding id -----------------------------------


def test_fingerprint_matches_app_snapshot_rule_and_ignores_extras() -> None:
    from trendora.api.report_snapshot import snapshot_fingerprint

    report = _case("exact_description_citation")
    projected = {field: report.get(field) for field in SNAPSHOT_FIELDS}

    assert report_fingerprint(report) == report_fingerprint(projected)
    assert report_fingerprint(report) == snapshot_fingerprint(report)
    assert len(report_fingerprint(report)) == 64


def test_worksheet_id_is_recomputable_from_its_components() -> None:
    document = evaluate_report(_case("exact_description_citation"))
    row = document["worksheet"][0]

    expected = finding_id_for(
        document["report_fingerprint"],
        row["finding_index"],
        row["statement"],
        row["citation_identities"],
        row["cited_evidence_values"],
    )
    assert row["finding_id"] == expected
    assert len(row["finding_id"]) == 64
    assert int(row["finding_id"], 16) >= 0


# --- Value states -----------------------------------------------------------


def test_null_fact_value_is_resolved_but_not_text_support() -> None:
    reference = _reference(title=None)
    report = _report(reference=reference, citations=[_fact_citation("title")])
    finding = build_diagnostics(report)["findings"][0]
    citation = finding["citations"][0]

    assert citation["resolved"] is True
    assert citation["fact_found"] is True
    assert citation["value"] is None
    assert citation["value_status"] == "null"
    assert citation["cited_text"] is None
    assert finding["has_text_support"] is False


def test_blank_fact_value_is_resolved_but_not_text_support() -> None:
    reference = _reference(title="   ")
    report = _report(reference=reference, citations=[_fact_citation("title")])
    finding = build_diagnostics(report)["findings"][0]
    citation = finding["citations"][0]

    assert citation["resolved"] is True
    assert citation["fact_found"] is True
    assert citation["value"] == "   "
    assert citation["value_status"] == "blank"
    assert citation["cited_text"] == "   "
    assert finding["has_text_support"] is False


def test_non_text_fact_value_is_reported_as_non_text() -> None:
    report = _report(citations=[_fact_citation("view_count")])
    finding = build_diagnostics(report)["findings"][0]
    citation = finding["citations"][0]

    assert citation["resolved"] is True
    assert citation["fact_found"] is True
    assert citation["value"] == 1200
    assert citation["value_status"] == "non_text"
    assert citation["cited_text"] is None
    assert finding["has_text_support"] is False


def test_absent_fact_field_is_unresolved_but_reference_is_found() -> None:
    report = _report(
        citations=[_fact_citation("title")],
        facts=_facts(_reference(), omit=("title",)),
    )
    finding = build_diagnostics(report)["findings"][0]
    citation = finding["citations"][0]

    assert citation["resolved"] is False
    assert citation["reference_found"] is True
    assert citation["analysis_found"] is True
    assert citation["fact_found"] is False
    assert citation["value"] is None
    assert citation["value_status"] == "missing"
    assert citation["unresolved_reason"] == "fact_absent"


def test_missing_analysis_is_distinct_from_missing_reference() -> None:
    report = _report(citations=[_fact_citation("title")])
    report["evidence"]["analyses"] = []
    finding = build_diagnostics(report)["findings"][0]
    citation = finding["citations"][0]

    assert citation["reference_found"] is True
    assert citation["analysis_found"] is False
    assert citation["fact_found"] is False
    assert citation["unresolved_reason"] == "analysis_not_found"


def test_absent_observation_and_pattern_are_unresolved() -> None:
    observation_report = _report(citations=[_observation_citation()])
    observation = build_diagnostics(observation_report)["findings"][0]["citations"][0]
    assert observation["observation_found"] is False
    assert observation["resolved"] is False
    assert observation["unresolved_reason"] == "observation_absent"

    pattern_report = _report(citations=[_pattern_citation()])
    pattern = build_diagnostics(pattern_report)["findings"][0]["citations"][0]
    assert pattern["pattern_found"] is False
    assert pattern["resolved"] is False
    assert pattern["unresolved_reason"] == "pattern_absent"


# --- Human judgments --------------------------------------------------------


def _four_finding_report() -> dict[str, Any]:
    findings = [
        {
            "statement": f"Finding {index}.",
            "citations": [_fact_citation("description")],
        }
        for index in range(4)
    ]
    return _report(findings=findings)


def test_all_four_judgment_states_stay_separate() -> None:
    report = _four_finding_report()
    rows = build_worksheet(report)
    annotations = {
        rows[0]["finding_id"]: {"judgment": "supported", "note": "direct excerpt"},
        rows[1]["finding_id"]: {
            "judgment": "partially_supported",
            "note": "one detail missing",
        },
        rows[2]["finding_id"]: {
            "judgment": "unsupported",
            "note": "not in cited text",
        },
    }

    applied_rows, applied, stale = apply_annotations(rows, annotations)
    counts = count_judgments(applied_rows)

    assert stale == []
    assert len(applied) == 3
    assert applied[0]["note"] == "direct excerpt"
    assert counts == {
        "supported": 1,
        "partially_supported": 1,
        "unsupported": 1,
        "unreviewed": 1,
        "total": 4,
    }
    assert counts["unreviewed"] == 1
    assert counts["supported"] == 1
    assert applied_rows[3]["judgment"] == "unreviewed"


def test_unreviewed_is_never_counted_as_supported() -> None:
    report = _four_finding_report()
    document = evaluate_report(report)
    assert document["counts"] == {
        "supported": 0,
        "partially_supported": 0,
        "unsupported": 0,
        "unreviewed": 4,
        "total": 4,
    }


def test_stale_annotation_is_listed_and_never_applied() -> None:
    report = _report(citations=[_fact_citation("description")])
    rows = build_worksheet(report)
    valid_id = rows[0]["finding_id"]
    stale_id = "f" * 64
    annotations = {
        valid_id: {"judgment": "supported", "note": "applied"},
        stale_id: {"judgment": "unsupported", "note": "stale"},
    }

    applied_rows, applied, stale = apply_annotations(rows, annotations)
    counts = count_judgments(applied_rows)

    assert stale == [stale_id]
    assert [entry["finding_id"] for entry in applied] == [valid_id]
    assert applied_rows[0]["judgment"] == "supported"
    assert counts["supported"] == 1
    assert counts["unsupported"] == 0

    document = evaluate_report(report, annotations)
    assert document["stale_annotations"] == [stale_id]
    assert document["counts"]["supported"] == 1
    assert document["counts"]["unsupported"] == 0


def test_malformed_stale_annotation_does_not_raise() -> None:
    report = _report(citations=[_fact_citation("description")])
    rows = build_worksheet(report)

    applied_rows, applied, stale = apply_annotations(
        rows, {"deadbeef": "not-an-annotation-object"}
    )

    assert applied == []
    assert stale == ["deadbeef"]
    assert applied_rows[0]["judgment"] == "unreviewed"


def test_invalid_annotation_for_a_real_finding_raises() -> None:
    report = _report(citations=[_fact_citation("description")])
    rows = build_worksheet(report)

    with pytest.raises(EvaluationError, match="judgment"):
        apply_annotations(
            rows,
            {rows[0]["finding_id"]: {"judgment": "maybe", "note": ""}},
        )
    with pytest.raises(EvaluationError, match="note"):
        apply_annotations(
            rows,
            {rows[0]["finding_id"]: {"judgment": "supported", "note": 3}},
        )


# --- Determinism and input safety ------------------------------------------


def test_evaluation_is_deterministic() -> None:
    report = _case("unsupported_specific_claim")
    annotations = {
        build_worksheet(report)[0]["finding_id"]: {
            "judgment": "partially_supported",
            "note": "structure only",
        }
    }

    first = evaluate_report(report, annotations)
    second = evaluate_report(report, annotations)

    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_input_report_is_not_mutated() -> None:
    report = _case("exact_description_citation")
    before = copy.deepcopy(report)

    evaluate_report(report)
    evaluate_report(report, {})

    assert report == before


# --- CLI -------------------------------------------------------------------


def _write_report(tmp_path: Path) -> Path:
    path = tmp_path / "report.json"
    path.write_text(json.dumps(_case("exact_description_citation")), encoding="utf-8")
    return path


def test_cli_writes_valid_json_to_output_path(tmp_path: Path) -> None:
    report_path = _write_report(tmp_path)
    output_path = tmp_path / "evaluation.json"

    assert main([str(report_path), "--output", str(output_path)]) == 0

    document = json.loads(output_path.read_text(encoding="utf-8"))
    assert set(document) == {
        "report_fingerprint",
        "diagnostics",
        "worksheet",
        "annotations_applied",
        "stale_annotations",
        "counts",
    }
    assert document["counts"]["unreviewed"] == 1
    assert document["report_fingerprint"] == report_fingerprint(
        _case("exact_description_citation")
    )


def test_cli_applies_annotation_file(tmp_path: Path) -> None:
    report = _case("exact_description_citation")
    report_path = _write_report(tmp_path)
    row = build_worksheet(report)[0]
    annotations_path = tmp_path / "annotations.json"
    annotations_path.write_text(
        json.dumps(
            {
                row["finding_id"]: {
                    "judgment": "supported",
                    "note": "checked against the description",
                }
            }
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "evaluation.json"

    assert (
        main(
            [
                str(report_path),
                "--annotations",
                str(annotations_path),
                "--output",
                str(output_path),
            ]
        )
        == 0
    )

    document = json.loads(output_path.read_text(encoding="utf-8"))
    assert document["counts"]["supported"] == 1
    assert document["counts"]["unreviewed"] == 0
    assert document["annotations_applied"][0]["note"] == (
        "checked against the description"
    )


def test_cli_defaults_to_stdout(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    report_path = _write_report(tmp_path)

    assert main([str(report_path)]) == 0

    document = json.loads(capsys.readouterr().out)
    assert document["counts"]["total"] == 1
    assert document["stale_annotations"] == []


def test_console_script_is_declared() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert (
        'trendora-research-evaluate = "trendora.research.evaluation:main"'
        in pyproject
    )
