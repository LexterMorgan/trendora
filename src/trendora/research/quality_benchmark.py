"""Offline quality/cost benchmark for recorded or mocked synthesis outputs.

The evaluator in ``evaluation.py`` answers structural questions about one
report. This module adds the workflow around it: a versioned dataset, named
configurations, recorded-output replay, human-review annotations, explicit
missing-data accounting, and a two-configuration comparison.

It never calls a provider, database, or network. A recorded output is data, not
proof of live model quality or latency.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import re
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from trendora.api.research_report_models import ResearchReportResponse
from trendora.research.ai_input import (
    MAX_DESCRIPTION_CHARS,
    MAX_INPUT_REFERENCES,
    MAX_TITLE_CHARS,
    build_interpretation_input,
)
from trendora.research.ai_provider import (
    RESPONSE_REASON_BOUNDS_CHARS,
    RESPONSE_REASON_BOUNDS_COUNT,
    RESPONSE_REASON_CITATION,
    RESPONSE_REASON_OUTPUT_LENGTH,
    evidence_pack_to_payload,
    parse_research_synthesis,
)
from trendora.research.evaluation import (
    JUDGMENTS,
    SNAPSHOT_FIELDS,
    UNREVIEWED,
    EvaluationError,
    apply_annotations,
    build_diagnostics,
    build_worksheet,
    canonical_sha256,
    count_judgments,
    report_fingerprint,
)
from trendora.research.evidence import (
    AnalysisBasis,
    ContentObservation,
    EvidenceFact,
    EvidenceField,
    ObservationType,
    ReferenceAnalysis,
    ReferenceId,
)
from trendora.research.exceptions import (
    ResearchAIResponseError,
    ResearchInterpretationError,
)
from trendora.research.interpretation import (
    EvidencePack,
    InterpretationResult,
    ModelProvenance,
    validate_research_synthesis,
)
from trendora.research.models import ResearchQuery
from trendora.research.patterns import PatternAggregate
from trendora.research.strategy import citation_to_json

BENCHMARK_SCHEMA_VERSION = 1
SPLITS = ("development", "held_out")
MODES = ("recorded_output", "mocked_transport")
USAGE_FIELDS = (
    "prompt_tokens",
    "completion_tokens",
    "reasoning_tokens",
    "cached_tokens",
    "total_tokens",
)
_SUPPORTED_COMPACTION = {
    "max_title_chars": MAX_TITLE_CHARS,
    "max_description_chars": MAX_DESCRIPTION_CHARS,
    "max_references": MAX_INPUT_REFERENCES,
}
_SAFE_FAILURE_CODES = frozenset(
    {
        "provider_timeout",
        "provider_error",
        "provider_refusal",
        "no_coverage",
        "output_truncated",
        "output_over_bound",
        "output_empty",
        "output_invalid",
        "output_failed_schema",
        "output_unresolved_citation",
        "output_no_text_support",
        "output_rejected",
    }
)
_SHA256 = re.compile(r"^[a-f0-9]{64}$")


class BenchmarkError(EvaluationError):
    """A dataset, run, or comparison cannot be evaluated honestly."""


def load_json_object(path: str | Path, label: str) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkError(f"{label} could not be read as JSON") from exc
    if not isinstance(data, dict):
        raise BenchmarkError(f"{label} must contain a JSON object")
    return data


# --- Dataset ---------------------------------------------------------------


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkError(f"{label} must be a non-blank string")
    return value


def _require_sha256(value: Any, label: str) -> str:
    text = _require_text(value, label)
    if not _SHA256.fullmatch(text):
        raise BenchmarkError(f"{label} must be a lowercase SHA-256 hex digest")
    return text


def validate_dataset(dataset: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(dataset, Mapping):
        raise BenchmarkError("dataset must be a JSON object")
    if dataset.get("schema_version") != BENCHMARK_SCHEMA_VERSION:
        raise BenchmarkError("unsupported benchmark dataset schema_version")
    dataset_id = _require_text(dataset.get("dataset_id"), "dataset_id")
    dataset_version = _require_text(dataset.get("dataset_version"), "dataset_version")
    raw_cases = dataset.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise BenchmarkError("dataset.cases must be a non-empty list")

    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw_case in enumerate(raw_cases):
        case = _mapping(raw_case, f"cases[{index}]")
        case_id = _require_text(case.get("id"), f"cases[{index}].id")
        if case_id in seen:
            raise BenchmarkError(f"duplicate case id {case_id}")
        seen.add(case_id)
        split = case.get("split")
        if split not in SPLITS:
            raise BenchmarkError(f"case {case_id} has unknown split")
        for field in ("topic", "question", "expected_behavior", "review_rubric", "rationale"):
            _require_text(case.get(field), f"case {case_id}.{field}")
        categories = case.get("failure_categories")
        if not isinstance(categories, list) or not categories or not all(
            isinstance(item, str) and item for item in categories
        ):
            raise BenchmarkError(f"case {case_id}.failure_categories must be non-empty strings")
        if case.get("label_status") != "provisional_author":
            raise BenchmarkError(f"case {case_id} must mark labels provisional_author")
        report = _mapping(case.get("report"), f"case {case_id}.report")
        if set(report) != set(SNAPSHOT_FIELDS):
            raise BenchmarkError(f"case {case_id} report must contain exactly the six snapshot fields")
        try:
            ResearchReportResponse.model_validate(report)
        except ValidationError as exc:
            raise BenchmarkError(f"case {case_id} has an invalid source snapshot") from exc
        if report.get("interpretation") is not None:
            raise BenchmarkError(f"case {case_id} must supply evidence, not a recorded interpretation")
        cases.append(dict(case))

    splits = _mapping(dataset.get("splits"), "dataset.splits")
    partition: dict[str, list[str]] = {}
    for split in SPLITS:
        ids = splits.get(split)
        if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
            raise BenchmarkError(f"dataset.splits.{split} must be a list of case ids")
        if len(set(ids)) != len(ids):
            raise BenchmarkError(f"dataset.splits.{split} contains duplicates")
        if set(ids) != {case["id"] for case in cases if case["split"] == split}:
            raise BenchmarkError(f"dataset.splits.{split} does not match case split fields")
        partition[split] = list(ids)
    if set(partition["development"]) & set(partition["held_out"]):
        raise BenchmarkError("development and held_out splits must be disjoint")
    if set(partition["development"]) | set(partition["held_out"]) != seen:
        raise BenchmarkError("splits must cover every case")

    return {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "description": dataset.get("description"),
        "label_status": dataset.get("label_status"),
        "cases": cases,
        "splits": partition,
        "limitations": dataset.get("limitations", []),
    }


def load_dataset(path: str | Path) -> dict[str, Any]:
    return validate_dataset(load_json_object(path, "dataset"))


def dataset_fingerprint(dataset: Mapping[str, Any]) -> str:
    return canonical_sha256(dataset)


def source_snapshot(case: Mapping[str, Any]) -> dict[str, Any]:
    report = _mapping(case["report"], f"case {case['id']}.report")
    return {
        "research": copy.deepcopy(report["research"]),
        "evidence": copy.deepcopy(report["evidence"]),
    }


def source_snapshot_sha256(case: Mapping[str, Any]) -> str:
    return canonical_sha256(source_snapshot(case))


def _basis_for_field(field: EvidenceField) -> AnalysisBasis:
    if field is EvidenceField.TITLE:
        return AnalysisBasis.TITLE
    if field is EvidenceField.DESCRIPTION:
        return AnalysisBasis.DESCRIPTION
    if field in {
        EvidenceField.VIEW_COUNT,
        EvidenceField.LIKE_COUNT,
        EvidenceField.COMMENT_COUNT,
        EvidenceField.REACTION_COUNT,
        EvidenceField.SHARE_COUNT,
    }:
        return AnalysisBasis.RAW_METRICS
    return AnalysisBasis.SOURCE_METADATA


def _reference_id(raw: Any, label: str) -> ReferenceId:
    value = _mapping(raw, label)
    return ReferenceId(
        source_code=_require_text(value.get("source_code"), f"{label}.source_code"),
        content_external_id=_require_text(
            value.get("content_external_id"), f"{label}.content_external_id"
        ),
    )


def _research_query(report: Mapping[str, Any]) -> ResearchQuery:
    raw = _mapping(_mapping(report["research"], "research")["query"], "research.query")
    try:
        return ResearchQuery(
            topic=_require_text(raw.get("topic"), "research.query.topic"),
            date_from=date.fromisoformat(_require_text(raw.get("date_from"), "research.query.date_from")),
            date_to=date.fromisoformat(_require_text(raw.get("date_to"), "research.query.date_to")),
            markets=tuple(raw.get("markets") or ()),
            source_codes=tuple(raw.get("sources") or ()),
            result_limit=raw.get("result_limit"),
            facebook_page_id=raw.get("facebook_page_id"),
            market=raw.get("market"),
        )
    except (TypeError, ValueError) as exc:
        raise BenchmarkError("saved research query is invalid") from exc


def evidence_pack_for_case(case: Mapping[str, Any]) -> EvidencePack:
    """Build the saved evidence pack without changing the source snapshot."""
    report = _mapping(case["report"], f"case {case['id']}.report")
    evidence = _mapping(report["evidence"], f"case {case['id']}.evidence")
    analyses = []
    for index, raw_analysis in enumerate(evidence.get("analyses", [])):
        analysis = _mapping(raw_analysis, f"evidence.analyses[{index}]")
        identity = _reference_id(analysis.get("reference_id"), f"evidence.analyses[{index}].reference_id")
        facts = []
        bases: set[AnalysisBasis] = set()
        for raw_fact in analysis.get("facts", []):
            fact = _mapping(raw_fact, "fact")
            try:
                field = EvidenceField(fact.get("field"))
            except ValueError as exc:
                raise BenchmarkError("evidence fact uses an unknown field") from exc
            facts.append(EvidenceFact(identity, field, fact.get("value")))
            bases.add(_basis_for_field(field))
        observations = []
        for raw_observation in analysis.get("observations", []):
            observation = _mapping(raw_observation, "observation")
            try:
                observation_type = ObservationType(observation.get("observation_type"))
                observation_basis = AnalysisBasis(observation.get("analysis_basis"))
                evidence_fields = tuple(
                    EvidenceField(field) for field in observation.get("evidence_fields", [])
                )
            except ValueError as exc:
                raise BenchmarkError("evidence observation uses an unknown value") from exc
            observations.append(
                ContentObservation(
                    identity,
                    observation_type,
                    observation.get("value"),
                    evidence_fields,
                    observation_basis,
                )
            )
            bases.add(observation_basis)
        analyses.append(
            ReferenceAnalysis(
                identity,
                tuple(sorted(bases, key=lambda item: item.value)),
                tuple(facts),
                tuple(observations),
            )
        )
    patterns = []
    for raw_pattern in evidence.get("patterns", []):
        pattern = _mapping(raw_pattern, "pattern")
        try:
            observation_type = ObservationType(pattern.get("observation_type"))
        except ValueError as exc:
            raise BenchmarkError("evidence pattern uses an unknown observation type") from exc
        patterns.append(
            PatternAggregate(
                observation_type,
                pattern.get("analyzed_count"),
                pattern.get("matching_count"),
                pattern.get("non_matching_count"),
                pattern.get("ratio"),
                tuple(
                    _reference_id(item, "pattern.reference")
                    for item in pattern.get("matching_reference_ids", [])
                ),
                tuple(
                    _reference_id(item, "pattern.reference")
                    for item in pattern.get("non_matching_reference_ids", [])
                ),
            )
        )
    try:
        return EvidencePack(
            tuple(analyses), tuple(patterns), research_query=_research_query(report)
        )
    except Exception as exc:
        raise BenchmarkError("saved evidence cannot form an evidence pack") from exc


def compacted_evidence(case: Mapping[str, Any]) -> dict[str, Any]:
    """Apply the production compaction used for a model request."""
    compacted = build_interpretation_input(evidence_pack_for_case(case))
    return evidence_pack_to_payload(compacted)


def compacted_evidence_sha256(case: Mapping[str, Any]) -> str:
    return canonical_sha256(compacted_evidence(case))


def model_input_sha256(case: Mapping[str, Any], configuration: Mapping[str, Any]) -> str:
    """Hash the exact compacted evidence, question, prompt, and compaction identity."""
    projection = {
        "case_id": case["id"],
        "question": case["question"],
        "compacted_evidence_sha256": compacted_evidence_sha256(case),
        "prompt_sha256": configuration["prompt_sha256"],
        "compaction": configuration["compaction"],
    }
    return canonical_sha256(projection)


def prepared_identities(
    case: Mapping[str, Any], configuration: Mapping[str, Any]
) -> dict[str, str]:
    """Identities a recording must carry from its preparation time."""
    return {
        "source_snapshot_sha256": source_snapshot_sha256(case),
        "compacted_evidence_sha256": compacted_evidence_sha256(case),
        "model_input_sha256": model_input_sha256(case, configuration),
        "prompt_sha256": configuration["prompt_sha256"],
        "configuration_sha256": configuration_fingerprint(configuration),
    }


# --- Configuration and run inputs ------------------------------------------


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise BenchmarkError(f"{label} must be a JSON object")
    return value


def _positive_number(value: Any, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise BenchmarkError(f"{label} must be a finite positive number")
    return float(value)


def _validate_generation_parameters(value: Any) -> dict[str, Any]:
    params = dict(_mapping(value, "configuration.generation_parameters"))
    allowed = {"temperature", "top_p", "max_output_tokens", "seed"}
    unknown = set(params) - allowed
    if unknown:
        raise BenchmarkError(
            "configuration.generation_parameters contains unsupported fields: "
            + ", ".join(sorted(unknown))
        )
    if "temperature" in params:
        temp = params["temperature"]
        if isinstance(temp, bool) or not isinstance(temp, (int, float)) or not math.isfinite(temp) or not 0 <= temp <= 2:
            raise BenchmarkError("configuration.generation_parameters.temperature must be between 0 and 2")
    if "top_p" in params:
        top_p = params["top_p"]
        if isinstance(top_p, bool) or not isinstance(top_p, (int, float)) or not math.isfinite(top_p) or not 0 < top_p <= 1:
            raise BenchmarkError("configuration.generation_parameters.top_p must be in (0, 1]")
    if "max_output_tokens" in params:
        limit = params["max_output_tokens"]
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise BenchmarkError("configuration.generation_parameters.max_output_tokens must be a positive integer")
    if "seed" in params and params["seed"] is not None:
        seed = params["seed"]
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise BenchmarkError("configuration.generation_parameters.seed must be an integer or null")
    return params


def _validate_retry_policy(value: Any) -> dict[str, Any]:
    retry = dict(_mapping(value, "configuration.retry_policy"))
    allowed = {"max_attempts", "retry_on"}
    unknown = set(retry) - allowed
    if unknown:
        raise BenchmarkError(
            "configuration.retry_policy contains unsupported fields: "
            + ", ".join(sorted(unknown))
        )
    attempts = retry.get("max_attempts")
    if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 1:
        raise BenchmarkError("configuration.retry_policy.max_attempts must be >= 1")
    retry_on = retry.get("retry_on", [])
    if not isinstance(retry_on, list) or not all(
        isinstance(item, str) and re.fullmatch(r"[a-z_]{1,64}", item) for item in retry_on
    ):
        raise BenchmarkError("configuration.retry_policy.retry_on must be safe reason strings")
    return {"max_attempts": attempts, "retry_on": list(retry_on)}


def validate_configuration(value: Any) -> dict[str, Any]:
    config = dict(_mapping(value, "configuration"))
    allowed = {
        "id", "provider", "model", "prompt_version", "prompt_sha256",
        "generation_parameters", "compaction", "retry_policy", "deadline_seconds",
    }
    unknown = set(config) - allowed
    if unknown:
        raise BenchmarkError(
            "configuration contains unsupported fields: " + ", ".join(sorted(unknown))
        )
    _require_text(config.get("id"), "configuration.id")
    _require_text(config.get("provider"), "configuration.provider")
    _require_text(config.get("model"), "configuration.model")
    _require_text(config.get("prompt_version"), "configuration.prompt_version")
    _require_sha256(config.get("prompt_sha256"), "configuration.prompt_sha256")
    config["generation_parameters"] = _validate_generation_parameters(
        config.get("generation_parameters")
    )
    compaction = dict(_mapping(config.get("compaction"), "configuration.compaction"))
    if set(compaction) != set(_SUPPORTED_COMPACTION):
        raise BenchmarkError(
            "configuration.compaction must contain exactly "
            + ", ".join(sorted(_SUPPORTED_COMPACTION))
        )
    for key, expected in _SUPPORTED_COMPACTION.items():
        value = compaction.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value != expected:
            raise BenchmarkError(
                "configuration.compaction supports only production limits "
                f"({key}={expected})"
            )
    config["compaction"] = compaction
    config["retry_policy"] = _validate_retry_policy(config.get("retry_policy"))
    _positive_number(config.get("deadline_seconds"), "configuration.deadline_seconds")
    return config


def configuration_fingerprint(config: Mapping[str, Any]) -> str:
    return canonical_sha256(config)


def configuration_differences(
    left: Mapping[str, Any], right: Mapping[str, Any]
) -> list[str]:
    keys = (set(left) | set(right)) - {"id"}
    return sorted(
        key for key in keys if canonical_sha256(left.get(key)) != canonical_sha256(right.get(key))
    )


def validate_run(run: Mapping[str, Any], dataset: Mapping[str, Any]) -> dict[str, Any]:
    run = dict(_mapping(run, "run"))
    if run.get("schema_version") != BENCHMARK_SCHEMA_VERSION:
        raise BenchmarkError("unsupported run schema_version")
    mode = run.get("mode")
    if mode not in MODES:
        raise BenchmarkError(
            "run.mode must be recorded_output or mocked_transport; "
            "live execution is not implemented by this offline workflow"
        )
    if run.get("dataset_id") != dataset["dataset_id"]:
        raise BenchmarkError("run dataset_id does not match dataset")
    if run.get("dataset_version") != dataset["dataset_version"]:
        raise BenchmarkError("run dataset_version does not match dataset")
    if run.get("dataset_sha256") != dataset_fingerprint(dataset):
        raise BenchmarkError("run dataset hash is missing or does not match dataset")
    if run.get("split") not in SPLITS:
        raise BenchmarkError("run.split must be development or held_out")
    case_ids = run.get("case_ids")
    if not isinstance(case_ids, list) or not case_ids or not all(
        isinstance(item, str) for item in case_ids
    ):
        raise BenchmarkError("run.case_ids must be a non-empty list of case ids")
    if len(set(case_ids)) != len(case_ids):
        raise BenchmarkError("run.case_ids contains duplicates")
    allowed_ids = set(dataset["splits"][run["split"]])
    if not set(case_ids) <= allowed_ids:
        raise BenchmarkError("run.case_ids contains a case outside the selected split")
    outputs = run.get("outputs")
    if not isinstance(outputs, Mapping):
        raise BenchmarkError("run.outputs must be a JSON object keyed by case id")
    if set(outputs) - set(case_ids):
        raise BenchmarkError("run.outputs contains a case not selected by run.case_ids")
    config = validate_configuration(run.get("configuration"))
    run["configuration"] = config
    if "run_elapsed_ms" in run:
        _elapsed(run["run_elapsed_ms"], "run.run_elapsed_ms")
    run["case_ids"] = sorted(case_ids)
    run["outputs"] = dict(outputs)
    return run


def load_run(path: str | Path) -> dict[str, Any]:
    return load_json_object(path, "run")


# --- Attempts, usage, and cost ---------------------------------------------


def _elapsed(value: Any, label: str) -> int | None:
    if value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value > 2**53 - 1
    ):
        raise BenchmarkError(f"{label} must be a non-negative safe integer or null")
    return value


def _token(value: Any, label: str) -> int | None:
    if value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value > 2**53 - 1
    ):
        raise BenchmarkError(f"{label} must be a non-negative safe integer or null")
    return value


def parse_usage(value: Any) -> dict[str, Any]:
    """Parse token fields independently; invalid fields stay unknown."""
    errors: list[str] = []
    parsed: dict[str, Any] = {"present": value is not None, "errors": errors}
    if value is None:
        parsed.update({field: None for field in USAGE_FIELDS})
        return parsed
    if not isinstance(value, Mapping):
        parsed.update({field: None for field in USAGE_FIELDS})
        errors.append("usage_invalid")
        return parsed
    for field in USAGE_FIELDS:
        try:
            parsed[field] = _token(value.get(field), f"attempt.usage.{field}")
        except BenchmarkError:
            parsed[field] = None
            errors.append(f"usage_{field}_invalid")
    return parsed


def _usage_errors(usage: Mapping[str, Any]) -> list[str]:
    raw = usage.get("errors")
    return [item for item in raw if isinstance(item, str)] if isinstance(raw, list) else []


def parse_cost(value: Any) -> tuple[dict[str, Any] | None, list[str]]:
    """Parse one cost object; malformed cost stays unknown with a safe code."""
    if value is None:
        return None, []
    if not isinstance(value, Mapping):
        return None, ["cost_invalid"]
    kind = value.get("kind")
    if kind not in ("actual", "estimated"):
        return None, ["cost_kind_invalid"]
    amount = value.get("amount")
    if (
        isinstance(amount, bool)
        or not isinstance(amount, (int, float))
        or not math.isfinite(amount)
        or amount < 0
    ):
        return None, ["cost_amount_invalid"]
    currency = value.get("currency")
    if not isinstance(currency, str) or not currency.strip():
        return None, ["cost_currency_invalid"]
    pricing = None
    if kind == "estimated":
        raw_pricing = value.get("pricing")
        if not isinstance(raw_pricing, Mapping):
            return None, ["cost_pricing_invalid"]
        source = raw_pricing.get("source")
        unit = raw_pricing.get("unit")
        pricing_date = raw_pricing.get("date")
        if not all(isinstance(item, str) and item.strip() for item in (source, unit, pricing_date)):
            return None, ["cost_pricing_invalid"]
        try:
            date.fromisoformat(pricing_date)
        except ValueError:
            return None, ["cost_pricing_date_invalid"]
        pricing = {"source": source, "unit": unit, "date": pricing_date}
    return {"kind": kind, "amount": amount, "currency": currency, "pricing": pricing}, []


def parse_attempts(value: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse attempts in order, preserving valid independent accounting fields."""
    if value is None:
        return [], ["attempts_missing"]
    if not isinstance(value, list):
        return [], ["attempts_invalid"]
    attempts: list[dict[str, Any]] = []
    for index, raw_attempt in enumerate(value):
        errors: list[str] = []
        if not isinstance(raw_attempt, Mapping):
            attempts.append(
                {
                    "attempt": index + 1,
                    "status": "unknown",
                    "elapsed_ms": None,
                    "usage": parse_usage(None),
                    "cost": None,
                    "accounting_errors": ["attempt_invalid"],
                }
            )
            continue
        status = raw_attempt.get("status")
        if not isinstance(status, str) or not re.fullmatch(r"[a-z_]{1,32}", status):
            status = "unknown"
            errors.append("status_invalid")
        try:
            elapsed = _elapsed(raw_attempt.get("elapsed_ms"), f"attempts[{index}].elapsed_ms")
        except BenchmarkError:
            elapsed = None
            errors.append("elapsed_ms_invalid")
        usage = parse_usage(raw_attempt.get("usage"))
        errors.extend(_usage_errors(usage))
        cost, cost_errors = parse_cost(raw_attempt.get("cost"))
        errors.extend(cost_errors)
        attempts.append(
            {
                "attempt": index + 1,
                "status": status,
                "elapsed_ms": elapsed,
                "usage": usage,
                "cost": cost,
                "accounting_errors": errors,
            }
        )
    return attempts, []


# --- Case evaluation --------------------------------------------------------


def _model_provenance(value: Any) -> dict[str, str]:
    provenance = _mapping(value, "output.model_provenance")
    return {
        "provider": _require_text(provenance.get("provider"), "output.model_provenance.provider"),
        "model": _require_text(provenance.get("model"), "output.model_provenance.model"),
    }


def _interpretations_json(interpretations: Sequence[Any]) -> list[dict[str, Any]]:
    return [
        {
            "statement": item.statement,
            "citations": [citation_to_json(citation) for citation in item.citations],
        }
        for item in interpretations
    ]


def _case_report(
    case: Mapping[str, Any],
    provenance: Mapping[str, str],
    interpretations: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    report = {
        field: copy.deepcopy(case["report"][field]) for field in SNAPSHOT_FIELDS
    }
    report["interpretation"] = {
        "model_provenance": dict(provenance),
        "interpretations": list(interpretations),
    }
    try:
        normalized = ResearchReportResponse.model_validate(report)
    except ValidationError as exc:
        raise BenchmarkError("output failed response-schema validation") from exc
    return normalized.model_dump(mode="json")


def _extractive(provenance: Mapping[str, str]) -> bool:
    return provenance.get("provider") == "source_evidence" and provenance.get("model") == "extractive-v1"


def _verify_prepared(
    case: Mapping[str, Any],
    configuration: Mapping[str, Any],
    output: Any,
) -> None:
    value = _mapping(output, "output")
    prepared = _mapping(value.get("prepared"), "output.prepared")
    expected = prepared_identities(case, configuration)
    for field, expected_value in expected.items():
        if prepared.get(field) != expected_value:
            raise BenchmarkError(
                f"recording prepared identity does not match current {field}"
            )


def _parse_failure_code(exc: ResearchAIResponseError) -> str:
    reason = getattr(exc, "reason_code", None)
    if reason in (RESPONSE_REASON_BOUNDS_CHARS, RESPONSE_REASON_BOUNDS_COUNT):
        return "output_over_bound"
    if reason == RESPONSE_REASON_OUTPUT_LENGTH:
        return "output_truncated"
    if reason == RESPONSE_REASON_CITATION:
        return "output_unresolved_citation"
    return "output_invalid"


def _parse_output_interpretations(value: Mapping[str, Any]) -> tuple[Any, ...]:
    if "content" in value:
        content = value.get("content")
        if not isinstance(content, str):
            raise BenchmarkError("output.content must be a string")
        return parse_research_synthesis(content=content)
    interpretations = value.get("interpretations")
    if not isinstance(interpretations, list):
        raise BenchmarkError(
            "synthesis output must contain an interpretations list or raw content"
        )
    return parse_research_synthesis(decoded={"interpretations": interpretations})


def _diagnostics_for(
    report: Mapping[str, Any], *, accepted_synthesis: bool
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    diagnostics = build_diagnostics(report)
    fingerprint = report_fingerprint(report)
    worksheet = build_worksheet(report, fingerprint=fingerprint, diagnostics=diagnostics)
    finding_rows = {finding["index"]: finding for finding in diagnostics["findings"]}
    enriched = []
    for row in worksheet:
        finding = finding_rows.get(row["finding_index"], {})
        enriched.append(
            {
                **row,
                "case_id": report.get("_case_id"),
                "accepted_synthesis": accepted_synthesis,
                "cited_evidence": [
                    {
                        "identity": citation["identity"],
                        "resolved": citation["resolved"],
                        "value": citation.get("value"),
                        "value_status": citation.get("value_status"),
                        "cited_text": citation.get("cited_text"),
                        "unresolved_reason": citation.get("unresolved_reason"),
                    }
                    for citation in finding.get("citations", [])
                ],
                "reference_context": finding.get("references", []),
            }
        )
    return diagnostics, enriched


def _evaluate_case(
    case: Mapping[str, Any], output: Any, configuration: Mapping[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    base = {
        "case_id": case["id"],
        "source_snapshot_sha256": source_snapshot_sha256(case),
        "compacted_evidence_sha256": compacted_evidence_sha256(case),
        "model_input_sha256": model_input_sha256(case, configuration),
        "accounting_errors": [],
    }
    if output is None:
        return {
            **base,
            "status": "failed",
            "failure_reason": "output_missing",
            "attempts": [],
            "case_elapsed_ms": None,
        }, []
    _verify_prepared(case, configuration, output)
    value = _mapping(output, "output")
    attempts, accounting_errors = parse_attempts(value.get("attempts"))
    try:
        case_elapsed = _elapsed(value.get("case_elapsed_ms"), "output.case_elapsed_ms")
    except BenchmarkError:
        case_elapsed = None
        accounting_errors.append("case_elapsed_ms_invalid")
    base["accounting_errors"] = accounting_errors
    kind = value.get("kind")
    if kind not in ("synthesis", "fallback", "failure"):
        return {
            **base,
            "status": "failed",
            "failure_reason": "output_invalid",
            "attempts": attempts,
            "case_elapsed_ms": case_elapsed,
        }, []
    if kind == "failure":
        failure_code = value.get("failure_code")
        if failure_code not in _SAFE_FAILURE_CODES:
            failure_code = "provider_error"
        return {
            **base,
            "status": "failed",
            "failure_reason": failure_code,
            "attempts": attempts,
            "case_elapsed_ms": case_elapsed,
        }, []
    if kind == "fallback":
        return {
            **base,
            "status": "fallback",
            "failure_reason": None,
            "attempts": attempts,
            "case_elapsed_ms": case_elapsed,
        }, []
    if value.get("finish_reason") == "length":
        return {
            **base,
            "status": "failed",
            "failure_reason": "output_truncated",
            "attempts": attempts,
            "case_elapsed_ms": case_elapsed,
        }, []
    try:
        provenance = _model_provenance(value.get("model_provenance"))
        interpretations = _parse_output_interpretations(value)
    except ResearchAIResponseError as exc:
        return {
            **base,
            "status": "failed",
            "failure_reason": _parse_failure_code(exc),
            "attempts": attempts,
            "case_elapsed_ms": case_elapsed,
        }, []
    except BenchmarkError:
        return {
            **base,
            "status": "failed",
            "failure_reason": "output_invalid",
            "attempts": attempts,
            "case_elapsed_ms": case_elapsed,
        }, []
    if _extractive(provenance):
        return {
            **base,
            "status": "fallback",
            "failure_reason": "extractive_fallback",
            "attempts": attempts,
            "case_elapsed_ms": case_elapsed,
        }, []
    if not interpretations:
        return {
            **base,
            "status": "failed",
            "failure_reason": "output_empty",
            "attempts": attempts,
            "case_elapsed_ms": case_elapsed,
        }, []
    interpretations_json = _interpretations_json(interpretations)
    try:
        report = _case_report(case, provenance, interpretations_json)
    except BenchmarkError:
        return {
            **base,
            "status": "failed",
            "failure_reason": "output_failed_schema",
            "attempts": attempts,
            "case_elapsed_ms": case_elapsed,
        }, []
    report_for_evidence = copy.deepcopy(report)
    report_for_evidence["_case_id"] = case["id"]
    accepted = True
    rejection_reason = None
    compacted = build_interpretation_input(evidence_pack_for_case(case))
    result = InterpretationResult(
        model_provenance=ModelProvenance(provenance["provider"], provenance["model"]),
        interpretations=tuple(interpretations),
    )
    try:
        validate_research_synthesis(compacted, result)
    except ResearchInterpretationError:
        accepted = False
        rejection_reason = "output_rejected"
    diagnostics, worksheet = _diagnostics_for(
        report_for_evidence, accepted_synthesis=accepted
    )
    outcome = {
        **base,
        "status": "accepted_synthesis" if accepted else "failed",
        "failure_reason": rejection_reason,
        "attempts": attempts,
        "case_elapsed_ms": case_elapsed,
        "report_fingerprint": report_fingerprint(report),
        "model_provenance": provenance,
        "diagnostics": diagnostics,
        "findings_total": len(worksheet),
    }
    return outcome, worksheet




# --- Metrics ---------------------------------------------------------------


def _aggregate_attempts(outcomes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    attempts = [
        attempt
        for outcome in outcomes
        for attempt in outcome.get("attempts", [])
        if isinstance(attempt, Mapping)
    ]
    status_counts: dict[str, int] = {}
    for attempt in attempts:
        status = attempt.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    usage_sums = {field: 0 for field in USAGE_FIELDS}
    usage_known = {field: 0 for field in USAGE_FIELDS}
    inconsistent = 0
    attempts_with_usage = 0
    for attempt in attempts:
        usage = attempt.get("usage", {})
        if usage.get("present"):
            attempts_with_usage += 1
        for field in USAGE_FIELDS:
            if usage.get(field) is not None:
                usage_sums[field] += usage[field]
                usage_known[field] += 1
        prompt, completion, total = (
            usage.get("prompt_tokens"),
            usage.get("completion_tokens"),
            usage.get("total_tokens"),
        )
        if None not in (prompt, completion, total) and total != prompt + completion:
            inconsistent += 1
    elapsed_known = [attempt["elapsed_ms"] for attempt in attempts if attempt.get("elapsed_ms") is not None]
    case_elapsed_known = [
        outcome["case_elapsed_ms"]
        for outcome in outcomes
        if outcome.get("case_elapsed_ms") is not None
    ]
    invalid_attempts = sum(bool(attempt.get("accounting_errors")) for attempt in attempts)
    invalid_elapsed_attempts = sum(
        "elapsed_ms_invalid" in attempt.get("accounting_errors", []) for attempt in attempts
    )
    invalid_cost_attempts = sum(
        any(str(code).startswith("cost_") for code in attempt.get("accounting_errors", []))
        for attempt in attempts
    )
    attempts_with_valid_usage = sum(
        attempt.get("usage", {}).get("present") is True
        and not _usage_errors(attempt.get("usage", {}))
        for attempt in attempts
    )
    case_accounting_errors = sum(len(outcome.get("accounting_errors", [])) for outcome in outcomes)
    invalid_case_elapsed = sum(
        "case_elapsed_ms_invalid" in outcome.get("accounting_errors", [])
        for outcome in outcomes
    )
    core_token_missing = any(
        usage_known[field] < len(attempts)
        for field in ("prompt_tokens", "completion_tokens", "total_tokens")
    )
    usage = {
        "attempts": len(attempts),
        "attempts_with_usage": attempts_with_usage,
        "attempts_without_usage": len(attempts) - attempts_with_usage,
        "known": {
            field: usage_sums[field] if usage_known[field] else None
            for field in USAGE_FIELDS
        },
        "known_counts": usage_known,
        "reasoning_not_added_to_completion": True,
        "inconsistent_total_attempts": inconsistent,
    }
    timing = {
        "attempt_count": len(attempts),
        "attempt_elapsed_ms_known": sum(elapsed_known) if elapsed_known else None,
        "attempt_elapsed_ms_known_count": len(elapsed_known),
        "attempt_elapsed_ms_unknown_count": len(attempts) - len(elapsed_known),
        "case_elapsed_ms_known": sum(case_elapsed_known) if case_elapsed_known else None,
        "case_elapsed_ms_known_count": len(case_elapsed_known),
        "case_elapsed_ms_unknown_count": len(outcomes) - len(case_elapsed_known),
    }
    actual: dict[str, float] = {}
    estimated: dict[str, float] = {}
    pricing: set[tuple[str, str, str, str]] = set()
    cost_known = 0
    cost_unknown = 0
    for attempt in attempts:
        cost = attempt.get("cost")
        if cost is None:
            cost_unknown += 1
            continue
        cost_known += 1
        bucket = actual if cost["kind"] == "actual" else estimated
        bucket[cost["currency"]] = bucket.get(cost["currency"], 0) + cost["amount"]
        if cost["kind"] == "estimated" and cost["pricing"] is not None:
            item = cost["pricing"]
            pricing.add((cost["currency"], item["source"], item["unit"], item["date"]))
    costs = {
        "attempts_with_cost": cost_known,
        "attempts_without_cost": cost_unknown,
        "actual": actual,
        "estimated": estimated,
        "estimated_pricing": [
            {"currency": currency, "source": source, "unit": unit, "date": pricing_date}
            for currency, source, unit, pricing_date in sorted(pricing)
        ],
    }
    accounting = {
        "invalid_attempts": invalid_attempts,
        "attempts_with_valid_usage": attempts_with_valid_usage,
        "invalid_elapsed_attempts": invalid_elapsed_attempts,
        "invalid_cost_attempts": invalid_cost_attempts,
        "case_accounting_errors": case_accounting_errors,
        "invalid_case_elapsed": invalid_case_elapsed,
        "token_fields_incomplete": core_token_missing,
        "accounting_complete": bool(
            attempts
            and not invalid_attempts
            and not case_accounting_errors
            and attempts_with_usage == len(attempts)
            and cost_known == len(attempts)
            and len(elapsed_known) == len(attempts)
            and len(case_elapsed_known) == len(outcomes)
            and not core_token_missing
        ),
    }
    return {
        "statuses": status_counts,
        "usage": usage,
        "timing": timing,
        "cost": costs,
        "accounting": accounting,
    }


def _metrics(
    outcomes: Sequence[Mapping[str, Any]],
    worksheets: Sequence[Mapping[str, Any]],
    *,
    case_count: int,
    annotations_applied: Sequence[Mapping[str, Any]],
    stale_annotations: Sequence[str],
) -> dict[str, Any]:
    accepted = [item for item in outcomes if item["status"] == "accepted_synthesis"]
    fallback = [item for item in outcomes if item["status"] == "fallback"]
    failed = [item for item in outcomes if item["status"] == "failed"]
    findings = [
        finding
        for outcome in outcomes
        for finding in outcome.get("diagnostics", {}).get("findings", [])
    ]
    accepted_findings = [
        finding
        for outcome in accepted
        for finding in outcome.get("diagnostics", {}).get("findings", [])
    ]
    rejected_findings = len(findings) - len(accepted_findings)
    citations = [
        citation
        for finding in findings
        for citation in finding.get("citations", [])
        if isinstance(citation, Mapping)
    ]
    resolved = sum(1 for citation in citations if citation.get("resolved") is True)
    text_present = sum(1 for finding in findings if finding.get("has_text_support") is True)
    judgments = count_judgments(worksheets)
    reviewed = judgments["total"] - judgments[UNREVIEWED]
    attempt_aggregate = _aggregate_attempts(outcomes)
    return {
        "cases": {
            "total": case_count,
            "accepted_synthesis": len(accepted),
            "fallback": len(fallback),
            "failed": len(failed),
            "accepted_synthesis_rate": len(accepted) / case_count if case_count else None,
            "fallback_rate": len(fallback) / case_count if case_count else None,
            "failed_rate": len(failed) / case_count if case_count else None,
        },
        "findings": {
            "total": len(findings),
            "accepted": len(accepted_findings),
            "rejected_diagnostics": rejected_findings,
            "citations": len(citations),
            "resolved_citations": resolved,
            "citation_resolution_rate": resolved / len(citations) if citations else None,
            "with_cited_text_present": text_present,
            "cited_text_presence_rate": text_present / len(findings) if findings else None,
        },
        "review": {
            "total_findings": judgments["total"],
            "reviewed": reviewed,
            "unreviewed": judgments[UNREVIEWED],
            "review_coverage_rate": reviewed / judgments["total"] if judgments["total"] else None,
            "supported": judgments["supported"],
            "partially_supported": judgments["partially_supported"],
            "unsupported": judgments["unsupported"],
            "annotations_applied": len(annotations_applied),
            "stale_annotations": len(stale_annotations),
        },
        "attempts": {
            **attempt_aggregate["statuses"],
            **attempt_aggregate["usage"],
            **attempt_aggregate["timing"],
            **attempt_aggregate["cost"],
            **attempt_aggregate["accounting"],
        },
        "failed_cases": [
            {"case_id": item["case_id"], "reason": item.get("failure_reason")}
            for item in failed
        ],
        "fallback_cases": [{"case_id": item["case_id"]} for item in fallback],
    }


def _application_state() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[3]
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=5,
        )
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True, timeout=5,
        )
        if revision.returncode != 0 or status.returncode != 0:
            raise OSError("git unavailable")
        return {
            "revision": revision.stdout.strip() or None,
            "dirty": bool(status.stdout.strip()),
            "source": "git",
        }
    except (OSError, subprocess.SubprocessError):
        return {"revision": None, "dirty": None, "source": "unknown"}


def evaluate_run(
    dataset: Mapping[str, Any],
    run: Mapping[str, Any],
    split: str,
    *,
    annotations: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    dataset = validate_dataset(dataset)
    if split not in SPLITS:
        raise BenchmarkError("split must be development or held_out")
    run = validate_run(run, dataset)
    if run["split"] != split:
        raise BenchmarkError("run.split does not match the selected split")
    started = time.monotonic()
    cases_by_id = {case["id"]: case for case in dataset["cases"]}
    outcomes: list[dict[str, Any]] = []
    worksheet: list[dict[str, Any]] = []
    for case_id in run["case_ids"]:
        outcome, rows = _evaluate_case(
            cases_by_id[case_id], run["outputs"].get(case_id), run["configuration"]
        )
        outcomes.append(outcome)
        worksheet.extend(rows)
    applied_rows, applied, stale = apply_annotations(worksheet, annotations or {})
    metrics = _metrics(
        outcomes,
        applied_rows,
        case_count=len(outcomes),
        annotations_applied=applied,
        stale_annotations=stale,
    )
    observed = sorted(
        {
            output.get("model_provenance", {}).get("model")
            for output in run["outputs"].values()
            if isinstance(output, Mapping)
            and isinstance(output.get("model_provenance"), Mapping)
            and isinstance(output["model_provenance"].get("model"), str)
        }
    )
    fingerprint = dataset_fingerprint(dataset)
    return {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "kind": "run",
        "mode": run["mode"],
        "dataset": {
            "id": dataset["dataset_id"],
            "version": dataset["dataset_version"],
            "sha256": fingerprint,
            "split": split,
            "case_count": len(outcomes),
            "case_ids": list(run["case_ids"]),
        },
        "application": _application_state(),
        "generation_provenance": {
            "status": "unverified",
            "reason": "recorded outputs do not include the code or prompt revision that generated them",
        },
        "configuration": run["configuration"],
        "configuration_sha256": configuration_fingerprint(run["configuration"]),
        "requested": {
            "provider": run["configuration"]["provider"],
            "model": run["configuration"]["model"],
        },
        "observed_models": [
            {"model": model, "basis": "recorded output; not proof of the live route"}
            for model in observed
        ],
        "cases": outcomes,
        "worksheet": applied_rows,
        "annotations": {"applied": applied, "stale": stale},
        "metrics": metrics,
        "timing": {
            "recorded_run_elapsed_ms": run.get("run_elapsed_ms"),
            "benchmark_processing_elapsed_ms": round((time.monotonic() - started) * 1000),
            "basis": "recorded replay; benchmark processing time is not model latency",
        },
        "limitations": [
            "Recorded outputs are not live model results.",
            "Structural diagnostics do not establish factual support.",
            "Human judgments apply only to the reviewed findings and their bound output.",
        ],
    }


# --- Comparison -------------------------------------------------------------


def compare_runs(
    dataset: Mapping[str, Any],
    baseline_run: Mapping[str, Any],
    candidate_run: Mapping[str, Any],
    split: str,
    *,
    baseline_annotations: Mapping[str, Any] | None = None,
    candidate_annotations: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    baseline = evaluate_run(dataset, baseline_run, split, annotations=baseline_annotations)
    candidate = evaluate_run(dataset, candidate_run, split, annotations=candidate_annotations)
    blocking: list[str] = []
    warnings: list[str] = []
    if baseline["dataset"]["sha256"] != candidate["dataset"]["sha256"]:
        blocking.append("dataset hash differs")
    if baseline["dataset"]["split"] != candidate["dataset"]["split"]:
        blocking.append("split differs")
    if baseline["dataset"]["case_ids"] != candidate["dataset"]["case_ids"]:
        blocking.append("case sets differ")
    if baseline["mode"] != candidate["mode"]:
        warnings.append("execution modes differ")
    baseline_by_id = {item["case_id"]: item for item in baseline["cases"]}
    candidate_by_id = {item["case_id"]: item for item in candidate["cases"]}
    source_changes = [
        case_id
        for case_id in baseline["dataset"]["case_ids"]
        if case_id in candidate_by_id
        and baseline_by_id[case_id]["source_snapshot_sha256"]
        != candidate_by_id[case_id]["source_snapshot_sha256"]
    ]
    if source_changes:
        blocking.append("source snapshots differ")
    compacted_changes = [
        case_id
        for case_id in baseline["dataset"]["case_ids"]
        if case_id in candidate_by_id
        and baseline_by_id[case_id].get("compacted_evidence_sha256")
        != candidate_by_id[case_id].get("compacted_evidence_sha256")
    ]
    input_hash_changes = [
        case_id
        for case_id in baseline["dataset"]["case_ids"]
        if case_id in candidate_by_id
        and baseline_by_id[case_id]["model_input_sha256"]
        != candidate_by_id[case_id]["model_input_sha256"]
    ]
    if compacted_changes:
        warnings.append(
            "compacted evidence differs for "
            + str(len(compacted_changes))
            + " case(s); evidence was not held fixed"
        )
    if input_hash_changes and not compacted_changes:
        warnings.append(
            "prompt or configuration input identity differs for "
            + str(len(input_hash_changes))
            + " case(s); this is not a model-only comparison"
        )
    config_differences = configuration_differences(
        baseline["configuration"], candidate["configuration"]
    )
    if not config_differences:
        warnings.append("configurations are identical; differences show run variation only")
    elif len(config_differences) > 1:
        warnings.append(
            "multiple configuration fields differ: " + ", ".join(config_differences)
        )
    comparable = not blocking
    if not comparable:
        conclusion = "Runs are not comparable: " + "; ".join(blocking) + ". No quality conclusion."
    elif len(config_differences) > 1:
        conclusion = (
            "Multiple configuration fields differ, so this is not a controlled "
            "single-variable comparison. No quality improvement is claimed."
        )
    elif baseline["metrics"]["review"]["reviewed"] == 0 and candidate["metrics"]["review"]["reviewed"] == 0:
        conclusion = (
            "No human-reviewed findings in either run. Operational and structural differences "
            "are recorded, but no live quality improvement is established."
        )
    else:
        conclusion = (
            "Human review covers "
            f"{baseline['metrics']['review']['reviewed']}/{baseline['metrics']['review']['total_findings']} "
            "baseline findings and "
            f"{candidate['metrics']['review']['reviewed']}/{candidate['metrics']['review']['total_findings']} "
            "candidate findings. These are recorded-output observations, not a live model result."
        )
    return {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "kind": "comparison",
        "dataset": baseline["dataset"],
        "application": baseline["application"],
        "runs": {"baseline": baseline, "candidate": candidate},
        "comparison": {
            "comparable": comparable,
            "blocking_reasons": blocking,
            "warnings": warnings,
            "configuration_differences": config_differences,
            "source_snapshots_match": not source_changes,
            "compacted_evidence_hashes_match": not compacted_changes,
            "prompt_hashes_match": (
                baseline["configuration"]["prompt_sha256"]
                == candidate["configuration"]["prompt_sha256"]
            ),
            "input_hashes_match": not input_hash_changes,
            "changed_input_cases": input_hash_changes,
            "conclusion": conclusion,
        },
        "limitations": [
            "Offline recorded/mocked outputs are not evidence of live quality, latency, or cost.",
            "The 24-case synthetic benchmark is not statistically representative.",
            "Structural citation checks are not semantic or factual verification.",
            "Human review remains unreviewed until a person annotates the worksheet.",
        ],
    }


# --- Artifacts --------------------------------------------------------------


def _pct(value: float | None) -> str:
    return "unknown" if value is None else f"{value * 100:.1f}%"


def _money(value: Mapping[str, float]) -> str:
    return ", ".join(f"{currency} {amount:g}" for currency, amount in sorted(value.items())) or "unknown"


def _run_table(metric: str, baseline: Any, candidate: Any) -> str:
    return f"| {metric} | {baseline} | {candidate} |"


def _token_cell(run: Mapping[str, Any], field: str) -> str:
    attempts = run["metrics"]["attempts"]
    value = attempts["known"][field]
    if value is None:
        return "unknown (0 known attempts)"
    return f"{value} ({attempts['known_counts'][field]} attempts)"


def _time_cell(run: Mapping[str, Any]) -> str:
    attempts = run["metrics"]["attempts"]
    value = attempts["attempt_elapsed_ms_known"]
    if value is None:
        return "unknown (0 timed attempts)"
    return f"{value} ms over {attempts['attempt_elapsed_ms_known_count']} attempts"


def _case_time_cell(run: Mapping[str, Any]) -> str:
    attempts = run["metrics"]["attempts"]
    value = attempts["case_elapsed_ms_known"]
    if value is None:
        return "unknown (0 timed cases)"
    return f"{value} ms over {attempts['case_elapsed_ms_known_count']} cases"


def _ms_cell(value: Any) -> str:
    return "unknown" if value is None else f"{value} ms"


def _observed_cell(run: Mapping[str, Any]) -> str:
    models = [item["model"] for item in run["observed_models"]]
    return ", ".join(models) + " (recorded)" if models else "unknown"


def _pricing_cell(run: Mapping[str, Any]) -> str:
    items = run["metrics"]["attempts"]["estimated_pricing"]
    if not items:
        return "none supplied"
    return "; ".join(
        f"{item['currency']} {item['source']} {item['unit']} ({item['date']})"
        for item in items
    )


def render_markdown(document: Mapping[str, Any]) -> str:
    comparison = document["comparison"]
    runs = document["runs"]
    baseline = runs["baseline"]
    candidate = runs["candidate"]
    lines = [
        "# Trendora quality and cost comparison",
        "",
        f"Dataset: `{document['dataset']['id']}` version `{document['dataset']['version']}` "
        f"(`{document['dataset']['sha256']}`), split `{document['dataset']['split']}`, "
        f"{document['dataset']['case_count']} cases.",
        f"Evaluator revision: `{document['application']['revision'] or 'unknown'}` "
        f"(dirty: {document['application']['dirty']}).",
        "Generation provenance: **unverified** (the evaluator revision is not the recording-generation revision).",
        "",
        f"Comparison: **{'comparable' if comparison['comparable'] else 'NOT COMPARABLE'}**.",
        "",
        "## Comparability",
        "",
        f"- Dataset hash: `{document['dataset']['sha256']}`",
        f"- Split and case set: `{document['dataset']['split']}`; both runs use {document['dataset']['case_count']} cases.",
        f"- Source snapshots match: {'yes' if comparison['source_snapshots_match'] else 'no'}.",
        f"- Compacted evidence hashes match: {'yes' if comparison['compacted_evidence_hashes_match'] else 'no'}.",
        f"- Prompt hashes match: {'yes' if comparison['prompt_hashes_match'] else 'no'}.",
        f"- Model-input hashes match: {'yes' if comparison['input_hashes_match'] else 'no'}.",
        "- Source-snapshot differences are blocking; a differing compacted input is visible, not treated as like-for-like.",
        "",
        "## Configurations",
        "",
        "| Field | Baseline | Candidate |",
        "| --- | --- | --- |",
        _run_table("Configuration id", baseline["configuration"]["id"], candidate["configuration"]["id"]),
        _run_table("Requested provider", baseline["requested"]["provider"], candidate["requested"]["provider"]),
        _run_table("Requested model", baseline["requested"]["model"], candidate["requested"]["model"]),
        _run_table("Observed model (recorded)", _observed_cell(baseline), _observed_cell(candidate)),
        _run_table("Prompt version", baseline["configuration"]["prompt_version"], candidate["configuration"]["prompt_version"]),
        _run_table("Prompt SHA-256", baseline["configuration"]["prompt_sha256"][:12] + "…", candidate["configuration"]["prompt_sha256"][:12] + "…"),
        _run_table("Configuration SHA-256", baseline["configuration_sha256"][:12] + "…", candidate["configuration_sha256"][:12] + "…"),
        "",
        "Controlled differences: " + (", ".join(comparison["configuration_differences"]) or "none") + ".",
        "",
    ]
    if comparison["warnings"]:
        lines.extend(["Warnings:", *[f"- {item}" for item in comparison["warnings"]], ""])
    if comparison["blocking_reasons"]:
        lines.extend(["Blocking comparability issues:", *[f"- {item}" for item in comparison["blocking_reasons"]], ""])
    lines.extend([
        "## Operational outcomes",
        "",
        "| Metric | Baseline | Candidate |",
        "| --- | ---: | ---: |",
        _run_table("Accepted synthesis", f"{baseline['metrics']['cases']['accepted_synthesis']}/{baseline['metrics']['cases']['total']} ({_pct(baseline['metrics']['cases']['accepted_synthesis_rate'])})", f"{candidate['metrics']['cases']['accepted_synthesis']}/{candidate['metrics']['cases']['total']} ({_pct(candidate['metrics']['cases']['accepted_synthesis_rate'])})"),
        _run_table("Fallback", f"{baseline['metrics']['cases']['fallback']}/{baseline['metrics']['cases']['total']}", f"{candidate['metrics']['cases']['fallback']}/{candidate['metrics']['cases']['total']}"),
        _run_table("Failed", f"{baseline['metrics']['cases']['failed']}/{baseline['metrics']['cases']['total']}", f"{candidate['metrics']['cases']['failed']}/{candidate['metrics']['cases']['total']}"),
        "",
        "## Structural metrics",
        "",
        "| Metric | Baseline | Candidate |",
        "| --- | ---: | ---: |",
        _run_table("Findings (accepted + rejected diagnostics)", f"{baseline['metrics']['findings']['total']} ({baseline['metrics']['findings']['accepted']} accepted / {baseline['metrics']['findings']['rejected_diagnostics']} rejected)", f"{candidate['metrics']['findings']['total']} ({candidate['metrics']['findings']['accepted']} accepted / {candidate['metrics']['findings']['rejected_diagnostics']} rejected)"),
        _run_table("Citations resolved", f"{baseline['metrics']['findings']['resolved_citations']}/{baseline['metrics']['findings']['citations']} ({_pct(baseline['metrics']['findings']['citation_resolution_rate'])})", f"{candidate['metrics']['findings']['resolved_citations']}/{candidate['metrics']['findings']['citations']} ({_pct(candidate['metrics']['findings']['citation_resolution_rate'])})"),
        _run_table("Findings with cited text present", f"{baseline['metrics']['findings']['with_cited_text_present']}/{baseline['metrics']['findings']['total']}", f"{candidate['metrics']['findings']['with_cited_text_present']}/{candidate['metrics']['findings']['total']}"),
        _run_table("Findings reviewed (diagnostic worksheet)", f"{baseline['metrics']['review']['reviewed']}/{baseline['metrics']['review']['total_findings']}", f"{candidate['metrics']['review']['reviewed']}/{candidate['metrics']['review']['total_findings']}"),
        _run_table("Supported / partial / unsupported", f"{baseline['metrics']['review']['supported']} / {baseline['metrics']['review']['partially_supported']} / {baseline['metrics']['review']['unsupported']}", f"{candidate['metrics']['review']['supported']} / {candidate['metrics']['review']['partially_supported']} / {candidate['metrics']['review']['unsupported']}"),
        _run_table("Unreviewed", baseline["metrics"]["review"]["unreviewed"], candidate["metrics"]["review"]["unreviewed"]),
        "",
        "## Latency, usage, and cost",
        "",
        "Timing basis: recorded replay. Recorded timings are supplied values, not measured live model latency.",
        "",
        "| Metric | Baseline | Candidate |",
        "| --- | ---: | ---: |",
        _run_table("Provider attempts", baseline["metrics"]["attempts"]["attempts"], candidate["metrics"]["attempts"]["attempts"]),
        _run_table("Accounting complete", "yes" if baseline["metrics"]["attempts"]["accounting_complete"] else "no", "yes" if candidate["metrics"]["attempts"]["accounting_complete"] else "no"),
        _run_table("Invalid accounting attempts", baseline["metrics"]["attempts"]["invalid_attempts"], candidate["metrics"]["attempts"]["invalid_attempts"]),
        _run_table("Invalid case elapsed values", baseline["metrics"]["attempts"]["invalid_case_elapsed"], candidate["metrics"]["attempts"]["invalid_case_elapsed"]),
        _run_table("Case accounting errors", baseline["metrics"]["attempts"]["case_accounting_errors"], candidate["metrics"]["attempts"]["case_accounting_errors"]),
        _run_table("Attempts with usage", baseline["metrics"]["attempts"]["attempts_with_usage"], candidate["metrics"]["attempts"]["attempts_with_usage"]),
        _run_table("Attempts without usage", baseline["metrics"]["attempts"]["attempts_without_usage"], candidate["metrics"]["attempts"]["attempts_without_usage"]),
        _run_table("Attempts with cost", baseline["metrics"]["attempts"]["attempts_with_cost"], candidate["metrics"]["attempts"]["attempts_with_cost"]),
        _run_table("Attempts without cost", baseline["metrics"]["attempts"]["attempts_without_cost"], candidate["metrics"]["attempts"]["attempts_without_cost"]),
        _run_table("Prompt tokens known", _token_cell(baseline, "prompt_tokens"), _token_cell(candidate, "prompt_tokens")),
        _run_table("Completion tokens known", _token_cell(baseline, "completion_tokens"), _token_cell(candidate, "completion_tokens")),
        _run_table("Reasoning tokens known (not added)", _token_cell(baseline, "reasoning_tokens"), _token_cell(candidate, "reasoning_tokens")),
        _run_table("Cached tokens known", _token_cell(baseline, "cached_tokens"), _token_cell(candidate, "cached_tokens")),
        _run_table("Total tokens known", _token_cell(baseline, "total_tokens"), _token_cell(candidate, "total_tokens")),
        _run_table("Attempt time known", _time_cell(baseline), _time_cell(candidate)),
        _run_table("Case time known", _case_time_cell(baseline), _case_time_cell(candidate)),
        _run_table("Recorded run time", _ms_cell(baseline["timing"]["recorded_run_elapsed_ms"]), _ms_cell(candidate["timing"]["recorded_run_elapsed_ms"])),
        _run_table("Benchmark processing time", _ms_cell(baseline["timing"]["benchmark_processing_elapsed_ms"]), _ms_cell(candidate["timing"]["benchmark_processing_elapsed_ms"])),
        _run_table("Actual charge", _money(baseline["metrics"]["attempts"]["actual"]), _money(candidate["metrics"]["attempts"]["actual"])),
        _run_table("Estimated charge", _money(baseline["metrics"]["attempts"]["estimated"]), _money(candidate["metrics"]["attempts"]["estimated"])),
        _run_table("Estimated pricing", _pricing_cell(baseline), _pricing_cell(candidate)),
        "",
        "Unknown usage and cost remain unknown; zero is shown only when returned as zero. Costs are not inferred from tokens. Recorded replay timing is not model latency; benchmark processing time measures this offline evaluation.",
        "",
        "## Failure and fallback cases",
        "",
    ])
    rows = [
        f"- Baseline failed: {item['case_id']} — {item['reason']}" for item in baseline["metrics"]["failed_cases"]
    ] + [
        f"- Candidate failed: {item['case_id']} — {item['reason']}" for item in candidate["metrics"]["failed_cases"]
    ] + [
        f"- Baseline fallback: {item['case_id']}" for item in baseline["metrics"]["fallback_cases"]
    ] + [
        f"- Candidate fallback: {item['case_id']}" for item in candidate["metrics"]["fallback_cases"]
    ]
    lines.extend(rows or ["No failed or fallback cases in the selected set."])
    lines.extend([
        "",
        "## Conclusion",
        "",
        comparison["conclusion"],
        "",
        "## Limitations",
        "",
        *[f"- {item}" for item in document["limitations"]],
        "",
    ])
    return "\n".join(lines)


def write_run_artifacts(document: Mapping[str, Any], output_directory: str | Path) -> list[Path]:
    directory = Path(output_directory)
    directory.mkdir(parents=True, exist_ok=True)
    run_path = directory / "run.json"
    worksheet_path = directory / "worksheet.json"
    run_path.write_text(json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    worksheet_path.write_text(json.dumps(document["worksheet"], indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return [run_path, worksheet_path]


def write_comparison_artifacts(document: Mapping[str, Any], output_directory: str | Path) -> list[Path]:
    directory = Path(output_directory)
    directory.mkdir(parents=True, exist_ok=True)
    comparison_path = directory / "comparison.json"
    worksheet_path = directory / "worksheet.json"
    markdown_path = directory / "comparison.md"
    comparison_path.write_text(json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    worksheet_path.write_text(json.dumps({"baseline": document["runs"]["baseline"]["worksheet"], "candidate": document["runs"]["candidate"]["worksheet"]}, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(document), encoding="utf-8")
    return [comparison_path, worksheet_path, markdown_path]


# --- CLI --------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="trendora-quality-benchmark",
        description="Offline recorded-output quality benchmark. No provider or network calls.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    evaluate_parser = subparsers.add_parser("evaluate", help="evaluate one recorded run")
    evaluate_parser.add_argument("--dataset", type=Path, required=True)
    evaluate_parser.add_argument("--run", type=Path, required=True)
    evaluate_parser.add_argument("--split", choices=SPLITS, required=True)
    evaluate_parser.add_argument("--annotations", type=Path)
    evaluate_parser.add_argument("--output", type=Path, required=True)
    compare_parser = subparsers.add_parser("compare", help="compare two recorded runs")
    compare_parser.add_argument("--dataset", type=Path, required=True)
    compare_parser.add_argument("--baseline", type=Path, required=True)
    compare_parser.add_argument("--candidate", type=Path, required=True)
    compare_parser.add_argument("--split", choices=SPLITS, required=True)
    compare_parser.add_argument("--baseline-annotations", type=Path)
    compare_parser.add_argument("--candidate-annotations", type=Path)
    compare_parser.add_argument("--annotations", type=Path, help="apply to both runs when specific files are omitted")
    compare_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        dataset = load_dataset(args.dataset)
        if args.command == "evaluate":
            annotations = load_json_object(args.annotations, "annotations") if args.annotations else {}
            document = evaluate_run(dataset, load_run(args.run), args.split, annotations=annotations)
            paths = write_run_artifacts(document, args.output)
        else:
            shared = load_json_object(args.annotations, "annotations") if args.annotations else {}
            baseline_annotations = (
                load_json_object(args.baseline_annotations, "baseline annotations")
                if args.baseline_annotations else shared
            )
            candidate_annotations = (
                load_json_object(args.candidate_annotations, "candidate annotations")
                if args.candidate_annotations else shared
            )
            document = compare_runs(
                dataset,
                load_run(args.baseline),
                load_run(args.candidate),
                args.split,
                baseline_annotations=baseline_annotations,
                candidate_annotations=candidate_annotations,
            )
            paths = write_comparison_artifacts(document, args.output)
    except (BenchmarkError, EvaluationError, OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"trendora-quality-benchmark: {exc}\n")
        return 2
    for path in paths:
        sys.stdout.write(f"wrote {path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
