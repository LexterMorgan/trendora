"""Offline, structural evaluation of an exported research report.

The evaluator answers structural questions only: does each citation resolve to
an evidence-map value, what exact value does it resolve to, is source text
present, and are publication and collection dates distinct? It does not decide
whether a finding is true, supported, significant, or well written. Those are
human judgments recorded in an annotation file.

No network, model, clock, or randomness is used. The input report is never
mutated.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

SNAPSHOT_FIELDS: tuple[str, ...] = (
    "status",
    "research",
    "evidence",
    "interpretation",
    "strategy",
    "ideation",
)

JUDGMENTS: tuple[str, ...] = ("supported", "partially_supported", "unsupported")
UNREVIEWED = "unreviewed"
_TEXT_FIELDS = frozenset({"title", "description"})


class EvaluationError(ValueError):
    """Raised when an input cannot be evaluated."""


# --- Canonical JSON and fingerprints ---------------------------------------


def _canonicalize(value: Any) -> Any:
    """Match the report snapshot's canonical number and container rules."""
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise EvaluationError("value contains a non-finite number")
        return int(value) if value.is_integer() else value
    if isinstance(value, Mapping):
        return {str(key): _canonicalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _canonicalize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_sha256(value: Any) -> str:
    """SHA-256 of the canonical JSON form used by the evaluator."""
    return _sha256(_canonical_json(value))


def report_fingerprint(report: Mapping[str, Any]) -> str:
    """SHA-256 of the canonical six-field snapshot; extra keys are ignored."""
    if not isinstance(report, Mapping):
        raise EvaluationError("report must be a JSON object")
    projected = {field: report.get(field) for field in SNAPSHOT_FIELDS}
    return _sha256(_canonical_json(projected))


def finding_id_for(
    fingerprint: str,
    finding_index: int,
    statement: str,
    citation_identities: Sequence[Mapping[str, Any]],
    cited_evidence_values: Sequence[Any],
) -> str:
    """Stable id for one worksheet row.

    The hash input is exactly the canonical JSON of: report fingerprint,
    finding index, statement, canonical citation identities, and the resolved
    evidence values (``null`` when unresolved).
    """
    payload = {
        "report_fingerprint": fingerprint,
        "finding_index": finding_index,
        "statement": statement,
        "citation_identities": list(citation_identities),
        "cited_evidence_values": list(cited_evidence_values),
    }
    return _sha256(_canonical_json(payload))


# --- Input inspection -------------------------------------------------------


def _as_mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _model_provenance(interpretation: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if interpretation is None:
        return None
    provenance = _as_mapping(interpretation.get("model_provenance"))
    if provenance is None:
        return None
    provider = provenance.get("provider")
    model = provenance.get("model")
    provider = provider if isinstance(provider, str) else None
    model = model if isinstance(model, str) else None
    if provider is None and model is None:
        return None
    return {"provider": provider, "model": model}


def _interpretation_origin(interpretation: Mapping[str, Any] | None) -> str:
    provenance = _model_provenance(interpretation)
    if (
        provenance is not None
        and provenance["provider"] == "source_evidence"
        and provenance["model"] == "extractive-v1"
    ):
        return "extractive"
    return "ai" if interpretation is not None else "absent"


def _evidence_index(
    report: Mapping[str, Any],
) -> tuple[
    dict[tuple[str, str], dict[str, Any]],
    dict[str, Mapping[str, Any]],
]:
    analyses: dict[tuple[str, str], dict[str, Any]] = {}
    patterns: dict[str, Mapping[str, Any]] = {}
    evidence = _as_mapping(report.get("evidence"))
    if evidence is None:
        return analyses, patterns

    raw_analyses = evidence.get("analyses")
    if isinstance(raw_analyses, list):
        for raw_analysis in raw_analyses:
            analysis = _as_mapping(raw_analysis)
            if analysis is None:
                continue
            reference = _as_mapping(analysis.get("reference_id"))
            if reference is None:
                continue
            source_code = reference.get("source_code")
            external_id = reference.get("content_external_id")
            if not isinstance(source_code, str) or not isinstance(external_id, str):
                continue
            facts: dict[str, Any] = {}
            raw_facts = analysis.get("facts")
            if isinstance(raw_facts, list):
                for raw_fact in raw_facts:
                    fact = _as_mapping(raw_fact)
                    if fact is None:
                        continue
                    field = fact.get("field")
                    if isinstance(field, str):
                        facts[field] = fact.get("value")
            observations: dict[str, Any] = {}
            raw_observations = analysis.get("observations")
            if isinstance(raw_observations, list):
                for raw_observation in raw_observations:
                    observation = _as_mapping(raw_observation)
                    if observation is None:
                        continue
                    observation_type = observation.get("observation_type")
                    if isinstance(observation_type, str):
                        observations[observation_type] = observation.get("value")
            analyses[(source_code, external_id)] = {
                "facts": facts,
                "observations": observations,
            }

    raw_patterns = evidence.get("patterns")
    if isinstance(raw_patterns, list):
        for raw_pattern in raw_patterns:
            pattern = _as_mapping(raw_pattern)
            if pattern is None:
                continue
            observation_type = pattern.get("observation_type")
            if isinstance(observation_type, str):
                patterns[observation_type] = pattern
    return analyses, patterns


def _reference_index(report: Mapping[str, Any]) -> dict[tuple[str, str], Mapping[str, Any]]:
    references: dict[tuple[str, str], Mapping[str, Any]] = {}
    research = _as_mapping(report.get("research"))
    raw_references = research.get("references") if research is not None else None
    if isinstance(raw_references, list):
        for raw_reference in raw_references:
            reference = _as_mapping(raw_reference)
            if reference is None:
                continue
            source_code = reference.get("source_code")
            external_id = reference.get("content_external_id")
            if isinstance(source_code, str) and isinstance(external_id, str):
                references[(source_code, external_id)] = reference
    return references


# --- Citation diagnostics ---------------------------------------------------


def _citation_identity(citation: Any) -> dict[str, Any]:
    citation = _as_mapping(citation)
    kind = citation.get("kind") if citation is not None else None
    kind = kind if isinstance(kind, str) else None

    if kind == "pattern":
        observation_type = citation.get("observation_type")
        return {
            "kind": "pattern",
            "observation_type": observation_type
            if isinstance(observation_type, str)
            else None,
        }
    if kind in ("fact", "observation"):
        reference = _as_mapping(citation.get("reference"))
        source_code = reference.get("source_code") if reference is not None else None
        external_id = (
            reference.get("content_external_id") if reference is not None else None
        )
        identity: dict[str, Any] = {
            "kind": kind,
            "reference": {
                "source_code": source_code if isinstance(source_code, str) else None,
                "content_external_id": external_id
                if isinstance(external_id, str)
                else None,
            },
        }
        key = "field" if kind == "fact" else "observation_type"
        value = citation.get(key)
        identity[key] = value if isinstance(value, str) else None
        return identity
    return {"kind": kind}


def _reference_key(identity: Mapping[str, Any]) -> tuple[str | None, str | None]:
    reference = _as_mapping(identity.get("reference"))
    if reference is None:
        return None, None
    source_code = reference.get("source_code")
    external_id = reference.get("content_external_id")
    return (
        source_code if isinstance(source_code, str) else None,
        external_id if isinstance(external_id, str) else None,
    )


def _value_status(value: Any, resolved: bool) -> str:
    if not resolved:
        return "missing"
    if value is None:
        return "null"
    if isinstance(value, str):
        return "blank" if not value.strip() else "text"
    return "non_text"


def _date_component(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        return datetime.fromisoformat(normalized).date().isoformat()
    except ValueError:
        pass
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return None


def _diagnose_citation(
    citation: Any,
    analyses: Mapping[tuple[str, str], Mapping[str, Any]],
    patterns: Mapping[str, Mapping[str, Any]],
    references: Mapping[tuple[str, str], Mapping[str, Any]],
) -> dict[str, Any]:
    identity = _citation_identity(citation)
    kind = identity.get("kind")
    diagnostic: dict[str, Any] = {
        "identity": identity,
        "resolved": False,
        "reference_found": None,
        "analysis_found": None,
        "value": None,
        "value_status": "missing",
        "cited_text": None,
        "unresolved_reason": None,
    }

    if kind == "pattern":
        observation_type = identity.get("observation_type")
        if observation_type is None:
            diagnostic["unresolved_reason"] = "malformed_citation"
            return diagnostic
        pattern = patterns.get(observation_type)
        diagnostic["pattern_found"] = pattern is not None
        if pattern is None:
            diagnostic["unresolved_reason"] = "pattern_absent"
            return diagnostic
        diagnostic["resolved"] = True
        diagnostic["value"] = pattern
        diagnostic["value_status"] = _value_status(pattern, True)
        return diagnostic

    if kind not in ("fact", "observation"):
        diagnostic["reference_found"] = False
        diagnostic["analysis_found"] = False
        diagnostic["unresolved_reason"] = "unsupported_citation_kind"
        return diagnostic

    key = _reference_key(identity)
    valid_reference = key[0] is not None and key[1] is not None
    analysis = analyses.get(key) if valid_reference else None
    diagnostic["reference_found"] = key in references
    diagnostic["analysis_found"] = analysis is not None
    diagnostic[kind + "_found"] = False

    if not valid_reference:
        diagnostic["unresolved_reason"] = "malformed_citation"
        return diagnostic
    if analysis is None:
        diagnostic["unresolved_reason"] = (
            "reference_not_found"
            if not diagnostic["reference_found"]
            else "analysis_not_found"
        )
        return diagnostic

    if kind == "fact":
        field = identity.get("field")
        if field is None:
            diagnostic["unresolved_reason"] = "malformed_citation"
            return diagnostic
        if field not in analysis["facts"]:
            diagnostic["unresolved_reason"] = "fact_absent"
            return diagnostic
        value = analysis["facts"][field]
    else:
        observation_type = identity.get("observation_type")
        if observation_type is None:
            diagnostic["unresolved_reason"] = "malformed_citation"
            return diagnostic
        if observation_type not in analysis["observations"]:
            diagnostic["unresolved_reason"] = "observation_absent"
            return diagnostic
        value = analysis["observations"][observation_type]

    diagnostic["resolved"] = True
    diagnostic[kind + "_found"] = True
    diagnostic["value"] = value
    diagnostic["value_status"] = _value_status(value, True)
    if isinstance(value, str):
        diagnostic["cited_text"] = value
    return diagnostic


def _diagnose_references(
    citation_diagnostics: Sequence[Mapping[str, Any]],
    analyses: Mapping[tuple[str, str], Mapping[str, Any]],
    references: Mapping[tuple[str, str], Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str | None, str | None]] = set()
    for diagnostic in citation_diagnostics:
        identity = _as_mapping(diagnostic.get("identity"))
        if identity is None or identity.get("kind") not in ("fact", "observation"):
            continue
        key = _reference_key(identity)
        if key in seen:
            continue
        seen.add(key)
        analysis = analyses.get(key)
        reference = references.get(key)
        facts = analysis["facts"] if analysis is not None else {}
        title = facts["title"] if "title" in facts else (
            reference.get("title") if reference is not None else None
        )
        description = (
            facts["description"]
            if "description" in facts
            else (reference.get("description") if reference is not None else None)
        )
        published_at = (
            facts["published_at"]
            if "published_at" in facts
            else (reference.get("published_at") if reference is not None else None)
        )
        collected_at = (
            facts["collected_at"]
            if "collected_at" in facts
            else (reference.get("collected_at") if reference is not None else None)
        )
        published_date = _date_component(published_at)
        collection_date = _date_component(collected_at)
        distinct = (
            published_date != collection_date
            if published_date is not None and collection_date is not None
            else None
        )
        rows.append(
            {
                "source_code": key[0],
                "content_external_id": key[1],
                "reference_found": reference is not None,
                "analysis_found": analysis is not None,
                "title": title,
                "description": description,
                "published_at": published_at,
                "collected_at": collected_at,
                "published_date": published_date,
                "collection_date": collection_date,
                "publication_collection_dates_distinct": distinct,
            }
        )
    return rows


def _has_text_support(
    citation_diagnostics: Sequence[Mapping[str, Any]],
) -> bool:
    """Whether exact cited text exists, not whether it supports the claim."""
    for diagnostic in citation_diagnostics:
        identity = _as_mapping(diagnostic.get("identity"))
        if identity is None or identity.get("kind") != "fact":
            continue
        if identity.get("field") not in _TEXT_FIELDS:
            continue
        if not diagnostic.get("resolved"):
            continue
        value = diagnostic.get("value")
        if not isinstance(value, str) or not value.strip():
            continue
        return True
    return False


def _diagnose_findings(
    report: Mapping[str, Any],
) -> tuple[str, dict[str, Any] | None, list[dict[str, Any]]]:
    interpretation = _as_mapping(report.get("interpretation"))
    origin = _interpretation_origin(interpretation)
    provenance = _model_provenance(interpretation)
    raw_interpretations = (
        interpretation.get("interpretations") if interpretation is not None else None
    )
    items = raw_interpretations if isinstance(raw_interpretations, list) else []

    analyses, patterns = _evidence_index(report)
    references = _reference_index(report)
    findings: list[dict[str, Any]] = []
    for index, raw_item in enumerate(items):
        item = _as_mapping(raw_item)
        statement = item.get("statement") if item is not None else None
        statement = statement if isinstance(statement, str) else ""
        raw_citations = item.get("citations") if item is not None else None
        citations = raw_citations if isinstance(raw_citations, list) else []
        citation_diagnostics = [
            _diagnose_citation(citation, analyses, patterns, references)
            for citation in citations
        ]
        reference_diagnostics = _diagnose_references(
            citation_diagnostics, analyses, references
        )
        comparable_dates = [
            row["publication_collection_dates_distinct"]
            for row in reference_diagnostics
            if row["publication_collection_dates_distinct"] is not None
        ]
        findings.append(
            {
                "index": index,
                "statement": statement,
                "origin": origin,
                "citations": citation_diagnostics,
                "references": reference_diagnostics,
                "has_text_support": _has_text_support(citation_diagnostics),
                "publication_collection_dates_distinct": (
                    any(comparable_dates) if comparable_dates else None
                ),
            }
        )
    return origin, provenance, findings


def build_diagnostics(report: Mapping[str, Any]) -> dict[str, Any]:
    """Structural diagnostics for every interpretation finding."""
    origin, provenance, findings = _diagnose_findings(report)
    return {
        "interpretation_origin": origin,
        "model_provenance": provenance,
        "findings": findings,
    }


# --- Worksheet and annotations ---------------------------------------------


def build_worksheet(
    report: Mapping[str, Any],
    *,
    fingerprint: str | None = None,
    diagnostics: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """One stable row per finding. Unannotated rows start ``unreviewed``."""
    if fingerprint is None:
        fingerprint = report_fingerprint(report)
    if diagnostics is None:
        diagnostics = build_diagnostics(report)
    raw_findings = diagnostics.get("findings")
    findings = raw_findings if isinstance(raw_findings, list) else []

    rows: list[dict[str, Any]] = []
    for fallback_index, raw_finding in enumerate(findings):
        finding = _as_mapping(raw_finding)
        if finding is None:
            continue
        raw_citations = finding.get("citations")
        citation_list = raw_citations if isinstance(raw_citations, list) else []
        citation_diagnostics = [
            citation for citation in citation_list if isinstance(citation, Mapping)
        ]
        identities = [citation["identity"] for citation in citation_diagnostics]
        values = [citation.get("value") for citation in citation_diagnostics]
        index = finding.get("index")
        index = index if isinstance(index, int) else fallback_index
        statement = finding.get("statement")
        statement = statement if isinstance(statement, str) else ""
        rows.append(
            {
                "finding_id": finding_id_for(
                    fingerprint, index, statement, identities, values
                ),
                "finding_index": index,
                "statement": statement,
                "citation_identities": identities,
                "cited_evidence_values": values,
                "judgment": UNREVIEWED,
                "note": "",
            }
        )
    return rows


def _normalize_annotation(
    finding_id: str, annotation: Any
) -> tuple[str, str, list[str]]:
    if not isinstance(annotation, Mapping):
        raise EvaluationError(f"annotation for {finding_id} must be a JSON object")
    judgment = annotation.get("judgment")
    if judgment not in JUDGMENTS:
        raise EvaluationError(
            f"annotation for {finding_id} has invalid judgment; "
            f"use one of {', '.join(JUDGMENTS)}"
        )
    note = annotation.get("note", "")
    if not isinstance(note, str):
        raise EvaluationError(f"annotation note for {finding_id} must be a string")
    categories = annotation.get("categories", [])
    if not isinstance(categories, list) or not all(
        isinstance(category, str) and category for category in categories
    ):
        raise EvaluationError(
            f"annotation categories for {finding_id} must be non-empty strings"
        )
    return judgment, note, list(categories)


def apply_annotations(
    rows: Sequence[Mapping[str, Any]],
    annotations: Mapping[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Apply known annotations; return rows, applied entries, and stale ids.

    Annotation ids absent from the current worksheet are stale: they are
    listed but never applied. Malformed stale payloads are not inspected.
    """
    if annotations is None:
        annotations = {}
    if not isinstance(annotations, Mapping):
        raise EvaluationError("annotations must be a JSON object keyed by finding_id")
    for finding_id in annotations:
        if not isinstance(finding_id, str):
            raise EvaluationError("annotation keys must be finding ids")

    applied_rows: list[dict[str, Any]] = [dict(row) for row in rows]
    known_ids = {row.get("finding_id") for row in applied_rows}
    applied: list[dict[str, Any]] = []
    for row in applied_rows:
        finding_id = row.get("finding_id")
        if finding_id not in annotations:
            continue
        judgment, note, categories = _normalize_annotation(
            finding_id, annotations[finding_id]
        )
        row["judgment"] = judgment
        row["note"] = note
        row["categories"] = categories
        applied.append(
            {
                "finding_id": finding_id,
                "finding_index": row.get("finding_index"),
                "judgment": judgment,
                "note": note,
                "categories": categories,
            }
        )
    stale = sorted(
        finding_id
        for finding_id in annotations
        if finding_id not in known_ids
    )
    return applied_rows, applied, stale


def count_judgments(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Four separate states plus a total; unreviewed is never support."""
    counts = {judgment: 0 for judgment in (*JUDGMENTS, UNREVIEWED)}
    for row in rows:
        judgment = row.get("judgment", UNREVIEWED)
        if judgment not in counts:
            raise EvaluationError(f"unknown judgment {judgment!r}")
        counts[judgment] += 1
    counts["total"] = len(rows)
    return counts


# --- Public evaluation and CLI ---------------------------------------------


def evaluate_report(
    report: Mapping[str, Any],
    annotations: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate one report and return the document the CLI writes."""
    fingerprint = report_fingerprint(report)
    diagnostics = build_diagnostics(report)
    worksheet = build_worksheet(
        report, fingerprint=fingerprint, diagnostics=diagnostics
    )
    applied_rows, applied, stale = apply_annotations(worksheet, annotations)
    return {
        "report_fingerprint": fingerprint,
        "diagnostics": diagnostics,
        "worksheet": applied_rows,
        "annotations_applied": applied,
        "stale_annotations": stale,
        "counts": count_judgments(applied_rows),
    }


def load_annotations(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise EvaluationError("annotation file must contain a JSON object")
    return data


def evaluate_corpus(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate structural diagnostics across named cases.

    Structural only: a resolved citation means the cited value exists in that
    report's evidence map. It does not mean the finding is true, and a low rate
    is a defect in the report, not a judgment about the model.
    """
    rows: list[dict[str, Any]] = []
    total_findings = total_citations = total_resolved = total_supported = 0
    for case in cases:
        if not isinstance(case, Mapping):
            raise EvaluationError("corpus case must be an object")
        name = case.get("name")
        report = case.get("report")
        if not isinstance(name, str) or not isinstance(report, Mapping):
            raise EvaluationError("corpus case needs a name and a report")
        diagnostics = build_diagnostics(report)
        raw_findings = diagnostics.get("findings")
        findings = [
            finding
            for finding in (raw_findings if isinstance(raw_findings, list) else [])
            if isinstance(finding, Mapping)
        ]
        citations = [
            citation
            for finding in findings
            for citation in (
                finding.get("citations")
                if isinstance(finding.get("citations"), list)
                else []
            )
            if isinstance(citation, Mapping)
        ]
        resolved = sum(1 for citation in citations if citation.get("resolved") is True)
        supported = sum(1 for finding in findings if finding.get("has_text_support") is True)
        total_findings += len(findings)
        total_citations += len(citations)
        total_resolved += resolved
        total_supported += supported
        rows.append(
            {
                "name": name,
                "findings": len(findings),
                "citations": len(citations),
                "resolved_citations": resolved,
                "findings_with_text_support": supported,
                "origin": diagnostics.get("interpretation_origin"),
            }
        )
    return {
        "cases": rows,
        "totals": {
            "cases": len(rows),
            "findings": total_findings,
            "citations": total_citations,
            "resolved_citations": total_resolved,
            "findings_with_text_support": total_supported,
        },
        "rates": {
            "citation_resolution": (
                total_resolved / total_citations if total_citations else None
            ),
            "text_support": (
                total_supported / total_findings if total_findings else None
            ),
        },
        "definition": (
            "Structural only: a resolved citation means the cited value exists "
            "in the report's evidence map."
        ),
    }


def load_corpus(path: str | Path) -> list[Mapping[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
        raise EvaluationError('corpus file must contain {"cases": [...]}')
    return data["cases"]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="trendora-research-evaluate",
        description=(
            "Offline structural evaluation of an exported Trendora research "
            "report. Does not fetch sources or judge semantics."
        ),
    )
    parser.add_argument("report", type=Path, nargs="?", help="exported report JSON file")
    parser.add_argument(
        "--corpus",
        type=Path,
        help='corpus JSON file containing {"cases": [...]}; aggregates structure only',
    )
    parser.add_argument(
        "--annotations",
        type=Path,
        help="human annotation JSON object keyed by finding_id",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="write the evaluation document here instead of stdout",
    )
    args = parser.parse_args(argv)
    if args.report is None and args.corpus is None:
        parser.error("provide a report file or --corpus")
    if args.corpus is not None and args.annotations is not None:
        parser.error("--annotations applies to a single report")

    try:
        if args.corpus is not None:
            document = evaluate_corpus(load_corpus(args.corpus))
        else:
            report = json.loads(args.report.read_text(encoding="utf-8"))
            if not isinstance(report, dict):
                raise EvaluationError("report file must contain a JSON object")
            annotations = load_annotations(args.annotations) if args.annotations else {}
            document = evaluate_report(report, annotations)
        serialized = (
            json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        )
        if args.output is None:
            sys.stdout.write(serialized)
        else:
            args.output.write_text(serialized, encoding="utf-8")
    except (EvaluationError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
