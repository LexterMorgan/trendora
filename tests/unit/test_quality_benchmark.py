"""Offline quality/cost benchmark: dataset, comparison, accounting, review."""

from __future__ import annotations

import copy
import json
import socket
from pathlib import Path
from unittest import mock

import pytest

from trendora.research.evaluation import UNREVIEWED
from trendora.research.quality_benchmark import (
    BenchmarkError,
    compare_runs,
    configuration_differences,
    configuration_fingerprint,
    compacted_evidence,
    dataset_fingerprint,
    evaluate_run,
    load_dataset,
    load_run,
    model_input_sha256,
    prepared_identities,
    render_markdown,
    source_snapshot_sha256,
    validate_dataset,
    write_comparison_artifacts,
    write_run_artifacts,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "research_quality"
DATASET = load_dataset(FIXTURES / "benchmark_v1.json")
BASELINE = load_run(FIXTURES / "runs" / "baseline.json")
CANDIDATE = load_run(FIXTURES / "runs" / "candidate.json")


def _config(run=BASELINE):
    return run["configuration"]


def _copy(value):
    return copy.deepcopy(value)


def _prepared(run, case_id, output):
    case = next(item for item in DATASET["cases"] if item["id"] == case_id)
    output["prepared"] = prepared_identities(case, run["configuration"])
    return output


def test_dataset_split_is_stable_disjoint_and_complete():
    assert DATASET["dataset_id"] == "trendora-quality-benchmark"
    assert DATASET["dataset_version"] == "1.0.0"
    dev = DATASET["splits"]["development"]
    held = DATASET["splits"]["held_out"]
    assert len(DATASET["cases"]) == 24
    assert len(dev) == 16 and len(held) == 8
    assert set(dev).isdisjoint(held)
    assert set(dev) | set(held) == {case["id"] for case in DATASET["cases"]}
    assert len({case["id"] for case in DATASET["cases"]}) == 24
    assert all(case["label_status"] == "provisional_author" for case in DATASET["cases"])
    assert dataset_fingerprint(DATASET) == dataset_fingerprint(load_dataset(FIXTURES / "benchmark_v1.json"))


def test_expected_labels_never_change_model_input_hash():
    case = next(item for item in DATASET["cases"] if item["id"] == "q-008-negation")
    original = model_input_sha256(case, _config())
    altered = _copy(case)
    altered["expected_behavior"] = "Totally different private answer."
    altered["review_rubric"] = "Different private rubric."
    altered["rationale"] = "Different private rationale."
    assert model_input_sha256(altered, _config()) == original
    altered["report"]["evidence"]["analyses"][0]["facts"][3]["value"] = "Changed evidence."
    assert model_input_sha256(altered, _config()) != original


def test_configuration_and_input_hashes_track_relevant_content():
    base = _config()
    model_only = _copy(base)
    model_only["model"] = "fictional-synth-b"
    prompt_only = _copy(base)
    prompt_only["prompt_sha256"] = "f" * 64
    case = DATASET["cases"][0]
    assert configuration_fingerprint(base) != configuration_fingerprint(model_only)
    assert model_input_sha256(case, base) == model_input_sha256(case, model_only)
    assert model_input_sha256(case, base) != model_input_sha256(case, prompt_only)


def test_evaluate_run_keeps_source_snapshot_and_counts_failures_and_fallback():
    before = copy.deepcopy(next(case for case in DATASET["cases"] if case["id"] == "q-001-exact-description")["report"])
    result = evaluate_run(DATASET, BASELINE, "development")
    case = next(item for item in DATASET["cases"] if item["id"] == "q-001-exact-description")
    assert case["report"] == before
    assert result["dataset"]["case_count"] == 6
    assert result["metrics"]["cases"] == {
        "total": 6,
        "accepted_synthesis": 4,
        "fallback": 1,
        "failed": 1,
        "accepted_synthesis_rate": 4 / 6,
        "fallback_rate": 1 / 6,
        "failed_rate": 1 / 6,
    }
    assert result["metrics"]["failed_cases"][0]["case_id"] == "q-015-undated-web"
    assert [item["case_id"] for item in result["metrics"]["fallback_cases"]] == ["q-022-mixed-sources"]
    assert result["metrics"]["review"]["reviewed"] == 0
    assert result["metrics"]["review"]["unreviewed"] == 4
    assert result["observed_models"][0]["model"] == "fictional-synth-a"
    assert result["observed_models"][0]["basis"].startswith("recorded output")
    assert set(result["application"]) == {"revision", "dirty", "source"}


def test_wrong_field_and_negation_numbers_stay_structural_and_unreviewed():
    result = evaluate_run(DATASET, BASELINE, "development")
    title_row = next(row for row in result["worksheet"] if row["case_id"] == "q-002-title-detail-in-description")
    assert title_row["judgment"] == UNREVIEWED
    assert title_row["cited_evidence"][0]["identity"]["field"] == "title"
    assert title_row["cited_evidence"][0]["value"] == "Solar microgrids reach rural schools"
    assert any("results expected next year" in (item.get("description") or "") for item in title_row["reference_context"])
    assert title_row["reference_context"][0]["title"] == title_row["cited_evidence"][0]["value"]
    for case_id in ("q-008-negation", "q-009-changed-number"):
        row = next(row for row in result["worksheet"] if row["case_id"] == case_id)
        assert row["judgment"] == UNREVIEWED
        assert row["cited_evidence"][0]["value_status"] == "text"


def test_comparison_records_controlled_model_difference_and_matching_inputs():
    comparison = compare_runs(DATASET, BASELINE, CANDIDATE, "development")
    assert comparison["comparison"]["comparable"] is True
    assert comparison["comparison"]["configuration_differences"] == ["model"]
    assert comparison["comparison"]["input_hashes_match"] is True
    assert comparison["runs"]["baseline"]["metrics"]["cases"]["accepted_synthesis"] == 4
    assert comparison["runs"]["candidate"]["metrics"]["cases"]["accepted_synthesis"] == 5
    assert "No human-reviewed findings" in comparison["comparison"]["conclusion"]
    markdown = render_markdown(comparison)
    assert "not measured live model latency" in markdown
    assert "No human-reviewed findings" in markdown
    assert "provider_timeout" in markdown


def test_identical_configurations_compare_with_warning():
    comparison = compare_runs(DATASET, BASELINE, BASELINE, "development")
    assert comparison["comparison"]["comparable"] is True
    assert "identical" in comparison["comparison"]["warnings"][0]
    assert "No human-reviewed findings" in comparison["comparison"]["conclusion"]


def test_mismatched_dataset_and_case_sets_are_blocked():
    with pytest.raises(BenchmarkError, match="dataset_version"):
        evaluate_run(DATASET, {**CANDIDATE, "dataset_version": "9.9.9"}, "development")
    shorter = {**_copy(CANDIDATE), "case_ids": CANDIDATE["case_ids"][:-1], "outputs": {
        key: value for key, value in CANDIDATE["outputs"].items() if key in CANDIDATE["case_ids"][:-1]
    }}
    comparison = compare_runs(DATASET, BASELINE, shorter, "development")
    assert comparison["comparison"]["comparable"] is False
    assert any("case sets differ" in item for item in comparison["comparison"]["blocking_reasons"])


def test_split_mismatch_is_rejected():
    run = _copy(CANDIDATE)
    run["split"] = "held_out"
    with pytest.raises(BenchmarkError):
        evaluate_run(DATASET, run, "development")


def test_live_mode_and_secret_configuration_fail_closed():
    with pytest.raises(BenchmarkError, match="live"):
        evaluate_run(DATASET, {**BASELINE, "mode": "live"}, "development")
    with pytest.raises(BenchmarkError, match="unsupported fields"):
        evaluate_run(
            DATASET,
            {**BASELINE, "configuration": {**BASELINE["configuration"], "api_key": "SECRET"}},
            "development",
        )


def test_malformed_and_missing_outputs_remain_in_denominators():
    broken = _copy(BASELINE)
    broken["outputs"]["q-001-exact-description"] = _prepared(
        broken, "q-001-exact-description", {
            "kind": "synthesis", "model_provenance": {"provider": "x", "model": "y"},
            "interpretations": "not a list",
            "attempts": [{"status": "ok", "elapsed_ms": 5, "usage": None}],
        }
    )
    del broken["outputs"]["q-002-title-detail-in-description"]
    result = evaluate_run(DATASET, broken, "development")
    failed = {item["case_id"]: item["reason"] for item in result["metrics"]["failed_cases"]}
    assert failed["q-001-exact-description"] == "output_invalid"
    assert failed["q-002-title-detail-in-description"] == "output_missing"
    assert result["metrics"]["cases"]["failed"] == 3
    assert result["metrics"]["attempts"]["attempts"] == 4
    assert result["metrics"]["cases"]["total"] == 6


def test_usage_zero_reasoning_and_inconsistent_totals_are_honest():
    run = _copy(BASELINE)
    run["case_ids"] = ["q-001-exact-description"]
    run["outputs"] = {"q-001-exact-description": _prepared(run, "q-001-exact-description", {
        "kind": "synthesis",
        "model_provenance": {"provider": "fictional-router", "model": "fictional-synth-a"},
        "interpretations": [{"statement": "Three provinces piloted solar microgrids for rural schools.", "citations": [{"kind": "fact", "reference": {"source_code": "youtube", "content_external_id": "solar-vid-001"}, "field": "description"}]}],
        "attempts": [
            {"status": "ok", "elapsed_ms": 10, "usage": {"prompt_tokens": 0, "completion_tokens": 0, "reasoning_tokens": 5, "cached_tokens": 0, "total_tokens": 0}, "cost": {"kind": "actual", "amount": 0, "currency": "USD"}},
            {"status": "timeout", "elapsed_ms": 20, "usage": {"prompt_tokens": 10, "completion_tokens": 5, "reasoning_tokens": 3, "total_tokens": 12}},
        ],
        "case_elapsed_ms": 30,
    })}
    result = evaluate_run(DATASET, run, "development")
    attempts = result["metrics"]["attempts"]
    assert attempts["attempts"] == 2
    assert attempts["attempts_with_usage"] == 2
    assert attempts["known"]["prompt_tokens"] == 10
    assert attempts["known"]["completion_tokens"] == 5
    assert attempts["known"]["reasoning_tokens"] == 8
    assert attempts["known"]["cached_tokens"] == 0
    assert attempts["inconsistent_total_attempts"] == 1
    assert attempts["actual"] == {"USD": 0}
    assert attempts["attempt_elapsed_ms_known"] == 30


def test_missing_usage_and_cost_stay_unknown():
    run = _copy(BASELINE)
    run["case_ids"] = ["q-001-exact-description"]
    run["outputs"] = {"q-001-exact-description": _prepared(run, "q-001-exact-description", {
        "kind": "fallback", "attempts": [{"status": "ok", "elapsed_ms": None, "usage": None}],
    })}
    result = evaluate_run(DATASET, run, "development")
    attempts = result["metrics"]["attempts"]
    assert attempts["known"]["prompt_tokens"] is None
    assert attempts["actual"] == {}
    assert attempts["estimated"] == {}
    assert attempts["attempts_without_cost"] == 1


def test_annotations_bind_to_output_and_do_not_leak_across_runs():
    baseline = evaluate_run(DATASET, BASELINE, "development")
    finding = baseline["worksheet"][0]
    annotations = {finding["finding_id"]: {"judgment": "supported", "note": "reviewed once", "categories": ["wrong_field"]}}
    reviewed = evaluate_run(DATASET, BASELINE, "development", annotations=annotations)
    assert reviewed["metrics"]["review"]["reviewed"] == 1
    assert reviewed["metrics"]["review"]["supported"] == 1
    assert reviewed["worksheet"][0]["categories"] == ["wrong_field"]
    candidate = evaluate_run(DATASET, CANDIDATE, "development", annotations=annotations)
    assert candidate["metrics"]["review"]["reviewed"] == 0
    assert candidate["metrics"]["review"]["stale_annotations"] == 1


def test_offline_evaluation_opens_no_socket(tmp_path):
    with mock.patch.object(socket, "socket", side_effect=AssertionError("network attempted")):
        result = evaluate_run(DATASET, BASELINE, "development")
    assert result["mode"] == "recorded_output"
    paths = write_comparison_artifacts(compare_runs(DATASET, BASELINE, CANDIDATE, "development"), tmp_path)
    assert {path.name for path in paths} == {"comparison.json", "worksheet.json", "comparison.md"}
    assert "not measured live model latency" in (tmp_path / "comparison.md").read_text()


def test_artifacts_exclude_secret_and_raw_reasoning_text(tmp_path):
    run = _copy(BASELINE)
    run["outputs"]["q-001-exact-description"]["reasoning"] = "SECRET_RAW_REASONING"
    document = compare_runs(DATASET, run, CANDIDATE, "development")
    paths = write_comparison_artifacts(document, tmp_path)
    combined = "\n".join(path.read_text() for path in paths)
    assert "SECRET_RAW_REASONING" not in combined
    assert "fictional-key" not in combined


def test_truncated_and_over_bound_outputs_are_failed_not_trimmed():
    truncated = _copy(BASELINE)
    truncated["outputs"]["q-001-exact-description"] = _prepared(truncated, "q-001-exact-description", {
        "kind": "synthesis",
        "finish_reason": "length",
        "model_provenance": {"provider": "fictional-router", "model": "fictional-synth-a"},
        "interpretations": [{"statement": "cut off", "citations": []}],
        "attempts": [],
    })
    over_bound = _copy(BASELINE)
    over_bound["outputs"]["q-001-exact-description"] = _prepared(over_bound, "q-001-exact-description", {
        "kind": "synthesis",
        "model_provenance": {"provider": "fictional-router", "model": "fictional-synth-a"},
        "interpretations": [{"statement": "x" * 501, "citations": [{"kind": "fact", "reference": {"source_code": "youtube", "content_external_id": "solar-vid-001"}, "field": "description"}]}],
        "attempts": [],
    })
    truncated_result = evaluate_run(DATASET, truncated, "development")
    over_bound_result = evaluate_run(DATASET, over_bound, "development")
    assert next(item for item in truncated_result["metrics"]["failed_cases"] if item["case_id"] == "q-001-exact-description")["reason"] == "output_truncated"
    assert next(item for item in over_bound_result["metrics"]["failed_cases"] if item["case_id"] == "q-001-exact-description")["reason"] == "output_over_bound"


def test_paraphrase_and_multilingual_text_remain_unreviewed():
    run = _copy(BASELINE)
    run["split"] = "held_out"
    run["case_ids"] = ["q-023-multilingual", "q-024-valid-paraphrase"]
    run["outputs"] = {
        "q-023-multilingual": _prepared(run, "q-023-multilingual", {
            "kind": "synthesis",
            "model_provenance": {"provider": "fictional-router", "model": "fictional-synth-a"},
            "interpretations": [{"statement": "该试点在三个地区改善了阅读教学。", "citations": [{"kind": "fact", "reference": {"source_code": "youtube", "content_external_id": "cn-vid"}, "field": "description"}]}],
            "attempts": [{"status": "ok", "elapsed_ms": 10, "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}],
            "case_elapsed_ms": 10,
        }),
        "q-024-valid-paraphrase": _prepared(run, "q-024-valid-paraphrase", {
            "kind": "synthesis",
            "model_provenance": {"provider": "fictional-router", "model": "fictional-synth-a"},
            "interpretations": [{"statement": "Learners strengthened literacy after a ten-week course.", "citations": [{"kind": "fact", "reference": {"source_code": "youtube", "content_external_id": "para-vid"}, "field": "description"}]}],
            "attempts": [{"status": "ok", "elapsed_ms": 10, "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}],
            "case_elapsed_ms": 10,
        }),
    }
    result = evaluate_run(DATASET, run, "held_out")
    assert result["metrics"]["cases"]["accepted_synthesis"] == 2
    assert all(row["judgment"] == UNREVIEWED for row in result["worksheet"])
    assert all(item["has_text_support"] is True for item in result["cases"][0]["diagnostics"]["findings"] + result["cases"][1]["diagnostics"]["findings"])


def test_source_snapshot_hash_changes_only_with_source_material():
    case = DATASET["cases"][0]
    original = source_snapshot_sha256(case)
    altered = _copy(case)
    altered["expected_behavior"] = "Changed label only."
    assert source_snapshot_sha256(altered) == original
    altered["report"]["evidence"]["analyses"][0]["facts"][3]["value"] = "Changed source description."
    assert source_snapshot_sha256(altered) != original


def test_run_dataset_hash_mismatch_is_rejected():
    with pytest.raises(BenchmarkError, match="dataset hash"):
        evaluate_run(DATASET, {**BASELINE, "dataset_sha256": "0" * 64}, "development")


def test_compare_cli_writes_machine_and_markdown_artifacts(tmp_path, capsys):
    from trendora.research.quality_benchmark import main

    code = main([
        "compare",
        "--dataset", str(FIXTURES / "benchmark_v1.json"),
        "--baseline", str(FIXTURES / "runs" / "baseline.json"),
        "--candidate", str(FIXTURES / "runs" / "candidate.json"),
        "--split", "development",
        "--output", str(tmp_path / "out"),
    ])
    assert code == 0
    output = tmp_path / "out"
    assert {path.name for path in output.iterdir()} == {"comparison.json", "worksheet.json", "comparison.md"}
    machine = json.loads((output / "comparison.json").read_text())
    assert machine["kind"] == "comparison"
    assert "comparable" in machine["comparison"]
    assert "wrote" in capsys.readouterr().out


def test_estimated_cost_requires_and_reports_pricing_provenance(tmp_path):
    run = _copy(BASELINE)
    run["case_ids"] = ["q-001-exact-description"]
    run["outputs"] = {"q-001-exact-description": _prepared(run, "q-001-exact-description", {
        "kind": "synthesis",
        "model_provenance": {"provider": "fictional-router", "model": "fictional-synth-a"},
        "interpretations": [{"statement": "Three provinces piloted solar microgrids for rural schools.", "citations": [{"kind": "fact", "reference": {"source_code": "youtube", "content_external_id": "solar-vid-001"}, "field": "description"}]}],
        "attempts": [{"status": "ok", "elapsed_ms": 10, "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}, "cost": {"kind": "estimated", "amount": 0.002, "currency": "USD", "pricing": {"source": "fictional price sheet", "unit": "per 1K tokens", "date": "2026-10-01"}}}],
        "case_elapsed_ms": 10,
    })}
    result = evaluate_run(DATASET, run, "development")
    assert result["metrics"]["attempts"]["estimated"] == {"USD": 0.002}
    assert result["metrics"]["attempts"]["estimated_pricing"] == [
        {"currency": "USD", "source": "fictional price sheet", "unit": "per 1K tokens", "date": "2026-10-01"}
    ]
    document = compare_runs(DATASET, run, run, "development")
    markdown = render_markdown(document)
    assert "fictional price sheet" in markdown
    assert "per 1K tokens" in markdown
    assert "2026-10-01" in markdown
    invalid = _copy(run)
    invalid["outputs"]["q-001-exact-description"]["attempts"][0]["cost"]["pricing"] = {}
    invalid_result = evaluate_run(DATASET, invalid, "development")
    assert invalid_result["cases"][0]["status"] == "accepted_synthesis"
    assert invalid_result["metrics"]["attempts"]["invalid_cost_attempts"] == 1
    assert invalid_result["metrics"]["attempts"]["estimated"] == {}


def test_unresolved_citation_exposes_unavailable_value_not_a_guess():
    run = _copy(BASELINE)
    run["split"] = "held_out"
    run["case_ids"] = ["q-006-missing-evidence"]
    run["outputs"] = {"q-006-missing-evidence": _prepared(run, "q-006-missing-evidence", {
        "kind": "synthesis",
        "model_provenance": {"provider": "fictional-router", "model": "fictional-synth-a"},
        "interpretations": [{"statement": "A claim with no available evidence.", "citations": [{"kind": "fact", "reference": {"source_code": "youtube", "content_external_id": "not-in-snapshot"}, "field": "description"}]}],
        "attempts": [{"status": "ok", "elapsed_ms": 10, "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}],
        "case_elapsed_ms": 10,
    })}
    result = evaluate_run(DATASET, run, "held_out")
    ev = result["worksheet"][0]["cited_evidence"][0]
    assert ev["value"] is None
    assert ev["resolved"] is False
    assert ev["unresolved_reason"] == "reference_not_found"
    assert result["worksheet"][0]["judgment"] == UNREVIEWED
    assert result["metrics"]["findings"]["resolved_citations"] == 0


def test_raw_provider_content_uses_the_real_parser_and_rejects_malformed_json():
    base = _copy(BASELINE)
    base["case_ids"] = ["q-001-exact-description"]
    valid = _copy(base["outputs"]["q-001-exact-description"])
    valid.pop("interpretations")
    valid["content"] = json.dumps({"interpretations": [{
        "statement": "Three provinces piloted solar microgrids for rural schools.",
        "citations": [{"kind": "fact", "reference": {"source_code": "youtube", "content_external_id": "solar-vid-001"}, "field": "description"}],
    }]})
    base["outputs"] = {"q-001-exact-description": valid}
    accepted = evaluate_run(DATASET, base, "development")
    assert accepted["cases"][0]["status"] == "accepted_synthesis"
    invalid = _copy(base)
    invalid["outputs"]["q-001-exact-description"]["content"] = "not provider JSON"
    failed = evaluate_run(DATASET, invalid, "development")
    assert failed["cases"][0]["status"] == "failed"
    assert failed["cases"][0]["failure_reason"] == "output_invalid"


def test_evaluate_cli_writes_run_and_worksheet(tmp_path):
    from trendora.research.quality_benchmark import main

    code = main([
        "evaluate",
        "--dataset", str(FIXTURES / "benchmark_v1.json"),
        "--run", str(FIXTURES / "runs" / "baseline.json"),
        "--split", "development",
        "--output", str(tmp_path / "run"),
    ])
    assert code == 0
    assert {path.name for path in (tmp_path / "run").iterdir()} == {"run.json", "worksheet.json"}


def test_unsupported_compaction_settings_are_rejected_not_pretended():
    candidate = _copy(BASELINE)
    candidate["configuration"]["compaction"]["max_description_chars"] = 300
    with pytest.raises(BenchmarkError, match="production limits"):
        evaluate_run(DATASET, candidate, "development")


def _case(case_id):
    return next(item for item in DATASET["cases"] if item["id"] == case_id)


def _one_case_run(case_id, output, config=None):
    run = _copy(BASELINE)
    run["case_ids"] = [case_id]
    run["split"] = _case(case_id)["split"]
    run["configuration"] = _copy(config or BASELINE["configuration"])
    output = _copy(output)
    output["prepared"] = prepared_identities(_case(case_id), run["configuration"])
    run["outputs"] = {case_id: output}
    return run


def _q1_interpretation(statement="Three provinces piloted solar microgrids for rural schools.", field="description"):
    return {
        "statement": statement,
        "citations": [{"kind": "fact", "reference": {"source_code": "youtube", "content_external_id": "solar-vid-001"}, "field": field}],
    }


def _synthesis_output(interpretations, **extra):
    return {
        "kind": "synthesis",
        "model_provenance": {"provider": "fictional-router", "model": "fictional-synth-a"},
        "interpretations": interpretations,
        "attempts": [],
        **extra,
    }


@pytest.mark.parametrize("count", [0, 7])
def test_empty_and_too_many_findings_are_not_accepted(count):
    output = _synthesis_output([_q1_interpretation()] * count)
    result = evaluate_run(DATASET, _one_case_run("q-001-exact-description", output), "development")
    assert result["cases"][0]["status"] == "failed"
    assert result["cases"][0]["failure_reason"] == ("output_empty" if count == 0 else "output_over_bound")
    assert result["metrics"]["cases"]["fallback"] == 0


def test_501_character_finding_is_not_accepted_but_500_is():
    over = _synthesis_output([_q1_interpretation("x" * 501)])
    at_limit = _synthesis_output([_q1_interpretation("x" * 500)])
    over_result = evaluate_run(DATASET, _one_case_run("q-001-exact-description", over), "development")
    at_limit_result = evaluate_run(DATASET, _one_case_run("q-001-exact-description", at_limit), "development")
    assert over_result["cases"][0]["failure_reason"] == "output_over_bound"
    assert at_limit_result["cases"][0]["status"] == "accepted_synthesis"


def test_six_findings_at_the_boundary_are_accepted():
    output = _synthesis_output([_q1_interpretation(f"Finding {index} " + "x" * 480) for index in range(6)])
    result = evaluate_run(DATASET, _one_case_run("q-001-exact-description", output), "development")
    assert result["cases"][0]["status"] == "accepted_synthesis"
    assert result["cases"][0]["findings_total"] == 6


def test_unresolved_citation_is_rejected_but_keeps_diagnostics():
    output = _synthesis_output([{
        "statement": "A claim with no available evidence.",
        "citations": [{"kind": "fact", "reference": {"source_code": "youtube", "content_external_id": "absent"}, "field": "description"}],
    }])
    result = evaluate_run(DATASET, _one_case_run("q-001-exact-description", output), "development")
    assert result["cases"][0]["status"] == "failed"
    assert result["cases"][0]["failure_reason"] == "output_rejected"
    assert result["cases"][0]["findings_total"] == 1
    assert result["worksheet"][0]["accepted_synthesis"] is False
    assert result["worksheet"][0]["cited_evidence"][0]["unresolved_reason"] == "reference_not_found"
    assert result["worksheet"][0]["judgment"] == UNREVIEWED


def test_missing_cited_field_and_textless_evidence_are_rejected():
    missing_field = _synthesis_output([_q1_interpretation(field="market_basis")])
    blank_case = _case("q-018-blank-description")
    blank_output = {
        "kind": "synthesis",
        "model_provenance": {"provider": "fictional-router", "model": "fictional-synth-a"},
        "interpretations": [{
            "statement": "The evidence says something.",
            "citations": [{"kind": "fact", "reference": {"source_code": "youtube", "content_external_id": "blank-vid"}, "field": "description"}],
        }],
        "attempts": [],
    }
    for run, case_id in (
        (_one_case_run("q-001-exact-description", missing_field), "q-001-exact-description"),
        (_one_case_run("q-018-blank-description", blank_output), "q-018-blank-description"),
    ):
        result = evaluate_run(DATASET, run, _case(case_id)["split"])
        assert result["cases"][0]["status"] == "failed"
        assert result["cases"][0]["failure_reason"] == "output_rejected"


def test_observation_and_pattern_only_findings_are_rejected():
    observation = {
        "kind": "synthesis",
        "model_provenance": {"provider": "fictional-router", "model": "fictional-synth-a"},
        "interpretations": [{
            "statement": "The description exists.",
            "citations": [{"kind": "observation", "reference": {"source_code": "youtube", "content_external_id": "obs-only"}, "observation_type": "description_present"}],
        }],
        "attempts": [],
    }
    pattern = {
        "kind": "synthesis",
        "model_provenance": {"provider": "fictional-router", "model": "fictional-synth-a"},
        "interpretations": [{
            "statement": "The pattern holds.",
            "citations": [{"kind": "pattern", "observation_type": "description_present"}],
        }],
        "attempts": [],
    }
    obs_result = evaluate_run(DATASET, _one_case_run("q-020-observation-only", observation), "held_out")
    pattern_result = evaluate_run(DATASET, _one_case_run("q-021-pattern-only", pattern), "held_out")
    for result in (obs_result, pattern_result):
        assert result["cases"][0]["status"] == "failed"
        assert result["cases"][0]["failure_reason"] == "output_rejected"
        assert result["cases"][0]["findings_total"] == 1


def test_length_stopped_valid_json_is_rejected_without_trimming():
    output = _synthesis_output([_q1_interpretation()], finish_reason="length")
    result = evaluate_run(DATASET, _one_case_run("q-001-exact-description", output), "development")
    assert result["cases"][0]["status"] == "failed"
    assert result["cases"][0]["failure_reason"] == "output_truncated"
    assert result["worksheet"] == []


def test_raw_content_and_decoded_output_use_the_same_acceptance_path():
    decoded = _one_case_run("q-001-exact-description", _synthesis_output([_q1_interpretation()]))
    raw = _one_case_run("q-001-exact-description", {
        "kind": "synthesis",
        "model_provenance": {"provider": "fictional-router", "model": "fictional-synth-a"},
        "content": json.dumps({"interpretations": [_q1_interpretation()]}),
        "attempts": [],
    })
    decoded_result = evaluate_run(DATASET, decoded, "development")
    raw_result = evaluate_run(DATASET, raw, "development")
    assert decoded_result["cases"][0]["status"] == raw_result["cases"][0]["status"] == "accepted_synthesis"
    assert decoded_result["cases"][0]["findings_total"] == raw_result["cases"][0]["findings_total"] == 1


def test_citation_to_evidence_excluded_by_compaction_is_rejected_with_diagnostics():
    dataset = _copy(DATASET)
    case = next(item for item in dataset["cases"] if item["id"] == "q-001-exact-description")
    base_ref = _copy(case["report"]["research"]["references"][0])
    base_analysis = _copy(case["report"]["evidence"]["analyses"][0])
    for index in range(24):
        ref = _copy(base_ref)
        ref["content_external_id"] = f"compact-{index:02d}"
        ref["url"] = f"https://example.test/compact-{index:02d}"
        case["report"]["research"]["references"].append(ref)
        analysis = _copy(base_analysis)
        analysis["reference_id"] = {"source_code": "youtube", "content_external_id": f"compact-{index:02d}"}
        for fact in analysis["facts"]:
            if fact["field"] == "url":
                fact["value"] = ref["url"]
        case["report"]["evidence"]["analyses"].append(analysis)
    dataset = validate_dataset(dataset)
    excluded_id = "compact-23"  # 25 refs total; the 24-reference cap drops the last
    output = _synthesis_output([{
        "statement": "A compacted-away source supports this.",
        "citations": [{"kind": "fact", "reference": {"source_code": "youtube", "content_external_id": excluded_id}, "field": "description"}],
    }])
    run = _copy(BASELINE)
    run["dataset_sha256"] = dataset_fingerprint(dataset)
    run["case_ids"] = ["q-001-exact-description"]
    output["prepared"] = prepared_identities(case, run["configuration"])
    run["outputs"] = {"q-001-exact-description": output}
    result = evaluate_run(dataset, run, "development")
    assert result["cases"][0]["status"] == "failed"
    assert result["cases"][0]["failure_reason"] == "output_rejected"
    assert result["cases"][0]["findings_total"] == 1
    assert result["worksheet"][0]["cited_evidence"][0]["resolved"] is True


def test_prepared_identity_is_required_and_bound_to_source_and_inputs():
    run = _one_case_run("q-001-exact-description", _synthesis_output([_q1_interpretation()]))
    missing = _copy(run)
    missing["outputs"]["q-001-exact-description"].pop("prepared")
    with pytest.raises(BenchmarkError, match="prepared"):
        evaluate_run(DATASET, missing, "development")

    changed = _copy(DATASET)
    case = next(item for item in changed["cases"] if item["id"] == "q-001-exact-description")
    case["report"]["evidence"]["analyses"][0]["facts"][3]["value"] = "Changed after recording."
    changed = validate_dataset(changed)
    rerun = _copy(run)
    rerun["dataset_sha256"] = dataset_fingerprint(changed)
    with pytest.raises(BenchmarkError, match="prepared identity"):
        evaluate_run(changed, rerun, "development")


def test_labels_and_annotations_never_enter_prepared_evidence():
    case = _case("q-001-exact-description")
    payload = json.dumps(compacted_evidence(case), ensure_ascii=False)
    assert case["expected_behavior"] not in payload
    assert case["review_rubric"] not in payload
    assert case["rationale"] not in payload
    assert "expected_behavior" not in payload
    assert "review_rubric" not in payload


def test_model_only_comparison_holds_evidence_and_prompt_fixed():
    comparison = compare_runs(DATASET, BASELINE, CANDIDATE, "development")
    checks = comparison["comparison"]
    assert checks["source_snapshots_match"] is True
    assert checks["compacted_evidence_hashes_match"] is True
    assert checks["prompt_hashes_match"] is True
    assert checks["input_hashes_match"] is True
    assert checks["configuration_differences"] == ["model"]


def test_prompt_only_comparison_changes_prompt_not_evidence():
    candidate = _copy(BASELINE)
    candidate["configuration"]["prompt_version"] = "synthesis-v2"
    candidate["configuration"]["prompt_sha256"] = "e" * 64
    for cid, output in candidate["outputs"].items():
        output["prepared"] = prepared_identities(_case(cid), candidate["configuration"])
    comparison = compare_runs(DATASET, BASELINE, candidate, "development")
    checks = comparison["comparison"]
    assert checks["comparable"] is True
    assert checks["source_snapshots_match"] is True
    assert checks["compacted_evidence_hashes_match"] is True
    assert checks["prompt_hashes_match"] is False
    assert checks["input_hashes_match"] is False
    assert checks["configuration_differences"] == ["prompt_sha256", "prompt_version"]
    assert any("not a model-only comparison" in item for item in checks["warnings"])


def test_unrelated_configuration_changes_do_not_claim_controlled_improvement():
    candidate = _copy(BASELINE)
    candidate["configuration"]["model"] = "another-model"
    candidate["configuration"]["generation_parameters"]["temperature"] = 0.7
    for cid, output in candidate["outputs"].items():
        output["prepared"] = prepared_identities(_case(cid), candidate["configuration"])
    comparison = compare_runs(DATASET, BASELINE, candidate, "development")
    assert set(comparison["comparison"]["configuration_differences"]) == {
        "generation_parameters", "model"
    }
    assert any("multiple configuration fields" in item for item in comparison["comparison"]["warnings"])
    assert "not a controlled single-variable comparison" in comparison["comparison"]["conclusion"]


def test_nested_secret_metadata_is_rejected_without_echo():
    for container, key in (
        ("generation_parameters", "api_key"),
        ("retry_policy", "authorization"),
        ("compaction", "api_key"),
    ):
        run = _one_case_run("q-001-exact-description", _synthesis_output([_q1_interpretation()]))
        run["configuration"][container][key] = "FICTIONAL_SECRET_MARKER"
        with pytest.raises(BenchmarkError) as caught:
            evaluate_run(DATASET, run, "development")
        assert "FICTIONAL_SECRET_MARKER" not in str(caught.value)


def test_provenance_attempt_and_envelope_extras_do_not_survive(tmp_path):
    run = _one_case_run("q-001-exact-description", _synthesis_output([_q1_interpretation()]))
    output = run["outputs"]["q-001-exact-description"]
    output["model_provenance"]["reasoning"] = "FICTIONAL_REASONING_MARKER"
    output["model_provenance"]["headers"] = {"authorization": "FICTIONAL_SECRET_MARKER"}
    output["reasoning"] = "FICTIONAL_REASONING_MARKER"
    output["response"] = {"raw": "FICTIONAL_REASONING_MARKER"}
    output["attempts"] = [{
        "status": "ok",
        "elapsed_ms": 10,
        "reasoning": "FICTIONAL_REASONING_MARKER",
        "headers": {"authorization": "FICTIONAL_SECRET_MARKER"},
    }]
    result = evaluate_run(DATASET, run, "development")
    paths = write_run_artifacts(result, tmp_path / "run")
    paths += write_comparison_artifacts(compare_runs(DATASET, run, run, "development"), tmp_path / "comparison")
    combined = json.dumps(result) + "\n" + "\n".join(path.read_text() for path in paths)
    assert "FICTIONAL_SECRET_MARKER" not in combined
    assert "FICTIONAL_REASONING_MARKER" not in combined
    assert result["cases"][0]["model_provenance"] == {
        "provider": "fictional-router", "model": "fictional-synth-a"
    }


def test_arbitrary_failure_code_is_replaced_with_fixed_safe_code():
    run = _one_case_run("q-001-exact-description", {
        "kind": "failure",
        "failure_code": "FICTIONAL_SECRET_MARKER",
        "attempts": [],
    })
    result = evaluate_run(DATASET, run, "development")
    assert result["cases"][0]["failure_reason"] == "provider_error"
    assert "FICTIONAL_SECRET_MARKER" not in json.dumps(result)


def test_malformed_numeric_accounting_is_unknown_not_a_case_failure():
    invalid_usage = _one_case_run("q-001-exact-description", _synthesis_output([_q1_interpretation()]))
    invalid_usage["outputs"]["q-001-exact-description"]["attempts"] = [
        {"status": "ok", "elapsed_ms": 1, "usage": {"prompt_tokens": float("nan")}},
    ]
    result = evaluate_run(DATASET, invalid_usage, "development")
    assert result["cases"][0]["status"] == "accepted_synthesis"
    assert result["metrics"]["attempts"]["attempts"] == 1
    assert result["metrics"]["attempts"]["known"]["prompt_tokens"] is None
    assert result["metrics"]["attempts"]["invalid_attempts"] == 1

    invalid_cost = _one_case_run("q-001-exact-description", _synthesis_output([_q1_interpretation()]))
    invalid_cost["outputs"]["q-001-exact-description"]["attempts"] = [
        {"status": "ok", "elapsed_ms": 1, "cost": {"kind": "actual", "amount": float("inf"), "currency": "USD"}},
    ]
    cost_result = evaluate_run(DATASET, invalid_cost, "development")
    assert cost_result["cases"][0]["status"] == "accepted_synthesis"
    assert cost_result["metrics"]["attempts"]["invalid_cost_attempts"] == 1
    assert cost_result["metrics"]["attempts"]["actual"] == {}

    invalid_deadline = _one_case_run("q-001-exact-description", _synthesis_output([_q1_interpretation()]))
    invalid_deadline["configuration"]["deadline_seconds"] = float("inf")
    with pytest.raises(BenchmarkError, match="finite"):
        evaluate_run(DATASET, invalid_deadline, "development")

    invalid_run_time = _one_case_run("q-001-exact-description", _synthesis_output([_q1_interpretation()]))
    invalid_run_time["run_elapsed_ms"] = True
    with pytest.raises(BenchmarkError):
        evaluate_run(DATASET, invalid_run_time, "development")

    invalid_temperature = _one_case_run("q-001-exact-description", _synthesis_output([_q1_interpretation()]))
    invalid_temperature["configuration"]["generation_parameters"]["temperature"] = float("nan")
    with pytest.raises(BenchmarkError, match="temperature"):
        evaluate_run(DATASET, invalid_temperature, "development")


def test_cli_error_does_not_echo_secret(tmp_path, capsys):
    from trendora.research.quality_benchmark import main

    run = _one_case_run("q-001-exact-description", _synthesis_output([_q1_interpretation()]))
    run["configuration"]["retry_policy"]["authorization"] = "FICTIONAL_SECRET_MARKER"
    run_path = tmp_path / "bad-run.json"
    run_path.write_text(json.dumps(run))
    code = main([
        "evaluate",
        "--dataset", str(FIXTURES / "benchmark_v1.json"),
        "--run", str(run_path),
        "--split", "development",
        "--output", str(tmp_path / "out"),
    ])
    assert code == 2
    stderr = capsys.readouterr().err
    assert "FICTIONAL_SECRET_MARKER" not in stderr
    assert "unsupported fields" in stderr


def test_supported_metadata_is_retained_and_unknown_is_separate():
    run = _one_case_run("q-001-exact-description", _synthesis_output([_q1_interpretation()]))
    run["configuration"]["generation_parameters"]["seed"] = 7
    run["outputs"]["q-001-exact-description"]["prepared"] = prepared_identities(
        _case("q-001-exact-description"), run["configuration"]
    )
    result = evaluate_run(DATASET, run, "development")
    assert result["configuration"]["generation_parameters"]["seed"] == 7
    assert result["configuration"]["provider"] == "fictional-router"
    assert result["cases"][0]["status"] == "accepted_synthesis"


def test_annotation_does_not_follow_reordered_findings():
    first = _q1_interpretation("First finding.")
    second = _q1_interpretation("Second finding.")
    forward_run = _one_case_run("q-001-exact-description", _synthesis_output([first, second]))
    forward = evaluate_run(DATASET, forward_run, "development")
    annotation = {forward["worksheet"][0]["finding_id"]: {"judgment": "supported", "note": "first only"}}
    reversed_run = _copy(forward_run)
    reversed_run["outputs"]["q-001-exact-description"]["interpretations"] = [second, first]
    reversed_run["outputs"]["q-001-exact-description"]["prepared"] = prepared_identities(
        _case("q-001-exact-description"), reversed_run["configuration"]
    )
    reviewed = evaluate_run(DATASET, reversed_run, "development", annotations=annotation)
    assert reviewed["metrics"]["review"]["reviewed"] == 0
    assert reviewed["metrics"]["review"]["stale_annotations"] == 1


def test_compaction_actually_truncates_and_does_not_mutate_source():
    case = _copy(_case("q-001-exact-description"))
    original = "word " * 200
    case["report"]["evidence"]["analyses"][0]["facts"][3]["value"] = original
    before = _copy(case)
    payload = compacted_evidence(case)
    assert payload["research_context"]["topic"] == "solar microgrids in rural schools"
    description = next(
        fact["value"]
        for analysis in payload["references"]
        for fact in analysis["facts"]
        if fact["field"] == "description"
    )
    assert len(description) <= 601
    assert description.endswith("…")
    assert case == before


def test_changed_statement_invalidates_old_annotation():
    first_run = _one_case_run("q-001-exact-description", _synthesis_output([_q1_interpretation("First statement.")]))
    first = evaluate_run(DATASET, first_run, "development")
    annotation = {first["worksheet"][0]["finding_id"]: {"judgment": "supported", "note": "old"}}
    second_run = _copy(first_run)
    second_run["outputs"]["q-001-exact-description"]["interpretations"] = [_q1_interpretation("Changed statement.")]
    second = evaluate_run(DATASET, second_run, "development", annotations=annotation)
    assert second["metrics"]["review"]["reviewed"] == 0
    assert second["metrics"]["review"]["stale_annotations"] == 1


def _attempt(status="ok", elapsed=10, usage=None, cost=None):
    return {"status": status, "elapsed_ms": elapsed, "usage": usage, "cost": cost}


def test_malformed_usage_preserves_earlier_attempt_accounting():
    run = _one_case_run("q-001-exact-description", _synthesis_output([_q1_interpretation()]))
    run["outputs"]["q-001-exact-description"]["attempts"] = [
        _attempt(usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}, cost={"kind": "actual", "amount": 0.01, "currency": "USD"}),
        _attempt(usage={"prompt_tokens": "bad", "completion_tokens": 7}),
    ]
    result = evaluate_run(DATASET, run, "development")
    attempts = result["metrics"]["attempts"]
    assert result["cases"][0]["status"] == "accepted_synthesis"
    assert attempts["attempts"] == 2
    assert attempts["known"]["prompt_tokens"] == 10
    assert attempts["known"]["completion_tokens"] == 12
    assert attempts["known"]["total_tokens"] == 15
    assert attempts["actual"] == {"USD": 0.01}
    assert attempts["attempt_elapsed_ms_known"] == 20
    assert attempts["invalid_attempts"] == 1
    assert attempts["accounting_complete"] is False
    assert result["cases"][0]["accounting_errors"] == []
    assert result["cases"][0]["attempts"][1]["accounting_errors"] == ["usage_prompt_tokens_invalid"]
    assert "bad" not in json.dumps(result)


def test_invalid_cost_keeps_valid_usage_and_other_costs():
    run = _one_case_run("q-001-exact-description", _synthesis_output([_q1_interpretation()]))
    run["outputs"]["q-001-exact-description"]["attempts"] = [
        _attempt(usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}, cost={"kind": "actual", "amount": 0.02, "currency": "USD"}),
        _attempt(usage={"prompt_tokens": 4, "completion_tokens": 5, "total_tokens": 9}, cost={"kind": "actual", "amount": float("inf"), "currency": "USD"}),
    ]
    result = evaluate_run(DATASET, run, "development")
    attempts = result["metrics"]["attempts"]
    assert result["cases"][0]["status"] == "accepted_synthesis"
    assert attempts["known"]["prompt_tokens"] == 5
    assert attempts["known"]["completion_tokens"] == 7
    assert attempts["attempts_with_cost"] == 1
    assert attempts["attempts_without_cost"] == 1
    assert attempts["invalid_cost_attempts"] == 1
    assert attempts["actual"] == {"USD": 0.02}


def test_invalid_case_elapsed_does_not_erase_attempts():
    run = _one_case_run("q-001-exact-description", _synthesis_output([_q1_interpretation()]))
    run["outputs"]["q-001-exact-description"]["attempts"] = [
        _attempt(elapsed=10), _attempt(elapsed=20)
    ]
    run["outputs"]["q-001-exact-description"]["case_elapsed_ms"] = "not-a-number"
    result = evaluate_run(DATASET, run, "development")
    attempts = result["metrics"]["attempts"]
    assert result["cases"][0]["status"] == "accepted_synthesis"
    assert result["cases"][0]["case_elapsed_ms"] is None
    assert attempts["attempts"] == 2
    assert attempts["attempt_elapsed_ms_known"] == 30
    assert attempts["invalid_case_elapsed"] == 1
    assert attempts["case_elapsed_ms_known"] is None


def test_known_zero_and_unknown_remain_distinct_after_malformed_attempt():
    run = _one_case_run("q-001-exact-description", _synthesis_output([_q1_interpretation()]))
    run["outputs"]["q-001-exact-description"]["attempts"] = [
        _attempt(elapsed=0, usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}, cost={"kind": "actual", "amount": 0, "currency": "USD"}),
        _attempt(elapsed=5),
    ]
    result = evaluate_run(DATASET, run, "development")
    attempts = result["metrics"]["attempts"]
    assert attempts["known"]["prompt_tokens"] == 0
    assert attempts["known"]["completion_tokens"] == 0
    assert attempts["known"]["total_tokens"] == 0
    assert attempts["known_counts"]["prompt_tokens"] == 1
    assert attempts["known"]["reasoning_tokens"] is None
    assert attempts["attempts_without_usage"] == 1
    assert attempts["actual"] == {"USD": 0}
    assert attempts["accounting_complete"] is False


def test_artifacts_preserve_known_subtotals_and_expose_incomplete_accounting(tmp_path):
    run = _one_case_run("q-001-exact-description", _synthesis_output([_q1_interpretation()]))
    run["outputs"]["q-001-exact-description"]["attempts"] = [
        _attempt(usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}, cost={"kind": "actual", "amount": 0.01, "currency": "USD"}),
        _attempt(usage={"prompt_tokens": "bad", "completion_tokens": 7}),
    ]
    result = evaluate_run(DATASET, run, "development")
    run_paths = write_run_artifacts(result, tmp_path / "run")
    comparison_paths = write_comparison_artifacts(compare_runs(DATASET, run, run, "development"), tmp_path / "comparison")
    combined = "\n".join(path.read_text() for path in run_paths + comparison_paths)
    assert '"prompt_tokens": 10' in combined
    assert '"invalid_attempts": 1' in combined
    assert '"accounting_complete": false' in combined
    assert "Accounting complete | no" in (tmp_path / "comparison" / "comparison.md").read_text()
    assert "bad" not in combined


def test_non_object_attempt_preserves_position_and_other_attempts():
    run = _one_case_run("q-001-exact-description", _synthesis_output([_q1_interpretation()]))
    run["outputs"]["q-001-exact-description"]["attempts"] = [
        _attempt(usage={"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}),
        "malformed-attempt",
        _attempt(usage={"prompt_tokens": 4, "completion_tokens": 5, "total_tokens": 9}),
    ]
    result = evaluate_run(DATASET, run, "development")
    attempts = result["cases"][0]["attempts"]
    assert [item["attempt"] for item in attempts] == [1, 2, 3]
    assert attempts[1]["status"] == "unknown"
    assert attempts[1]["accounting_errors"] == ["attempt_invalid"]
    metrics = result["metrics"]["attempts"]
    assert metrics["attempts"] == 3
    assert metrics["known"]["prompt_tokens"] == 6
    assert metrics["invalid_attempts"] == 1
