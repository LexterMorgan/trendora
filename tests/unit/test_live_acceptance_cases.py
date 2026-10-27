"""Sanitized live-acceptance cases remain explicit semantic judgments."""

import json
from pathlib import Path

FIXTURE = Path(__file__).parents[1] / "fixtures/research_quality/live_acceptance_2026-10-27_skincare.json"


def _load():
    return json.loads(FIXTURE.read_text())


def test_live_acceptance_fixture_keeps_exact_cited_fields_and_pending_human_review():
    document = _load()
    assert document["source"]["sanitized"] is True
    assert document["source"]["report_id"] == "ebffbd2a-5f3b-4077-890e-b0e08c87b73f"
    assert len(document["cases"]) == 2
    assert all(case["human_confirmation"] == "pending" for case in document["cases"])


def test_finding_5_is_unsupported_by_its_citation_but_details_exist_elsewhere():
    case = _load()["cases"][0]
    cited = case["cited_evidence"]
    elsewhere = case["details_in_pack_elsewhere"]
    assert case["support_judgment"] == "unsupported_by_cited_evidence"
    assert case["citation_mapping"] == "wrong_reference"
    assert "BPOM" not in (cited["title"] + " " + cited["description"])
    assert "HB Khanza" not in (cited["title"] + " " + cited["description"])
    assert "BPOM" in elsewhere["title"]
    assert "HB Khanza" in elsewhere["title"]
    assert "merkuri" in elsewhere["description"]
    assert cited["content_external_id"] != elsewhere["content_external_id"]


def test_finding_3_keeps_the_personalized_qualifier_as_unsupported():
    case = _load()["cases"][1]
    cited = case["cited_evidence"]
    assert case["support_judgment"] == "partially_supported"
    assert case["citation_mapping"] == "correct_reference"
    assert "personalized" not in (cited["title"] + " " + cited["description"]).lower()
    assert "solusi" in cited["description"].lower()
