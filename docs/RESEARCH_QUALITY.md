# Research quality evaluation

Status: offline structural evaluator for exported research reports. It produces
a human worksheet and structural diagnostics; it does not score quality.

Code: [evaluation.py](../src/trendora/research/evaluation.py). Fixtures:
[cases.json](../tests/fixtures/research_quality/cases.json) and
[annotations.json](../tests/fixtures/research_quality/annotations.json). Tests:
[test_research_evaluation.py](../tests/unit/test_research_evaluation.py).

## Commands

```bash
# Print the evaluation document.
.venv/bin/trendora-research-evaluate report.json

# Apply human judgments and write a file.
.venv/bin/trendora-research-evaluate report.json \
  --annotations annotations.json \
  --output evaluation.json

# Without the console script installed:
.venv/bin/python -m trendora.research.evaluation report.json

# Focused tests.
.venv/bin/python -m pytest tests/unit/test_research_evaluation.py -q
```

The evaluator uses only the Python standard library. It does not use the
network, fetch sources, call a model, read a clock, or write random data.

## Input

The report path must contain one JSON object: either the six-field snapshot
(`status`, `research`, `evidence`, `interpretation`, `strategy`, `ideation`) or
the full API response that also carries `persistence` and `run_details`. Extra
keys are ignored. The input object is never mutated.

`report_fingerprint` is the lowercase SHA-256 hex of the canonical JSON of the
six snapshot fields only. Canonical JSON is UTF-8, sorted keys, compact
separators, and integral floats normalized to integers. This is the same rule
as `trendora.api.report_snapshot`.

## Output

The CLI writes one JSON document with these keys:

| Key | Meaning |
| --- | --- |
| `report_fingerprint` | SHA-256 of the six-field snapshot. |
| `diagnostics` | Structural facts for every interpretation finding. |
| `worksheet` | One row per finding, ready for human judgment. |
| `annotations_applied` | Annotations matched to current finding ids. |
| `stale_annotations` | Annotation ids that do not exist in this worksheet. |
| `counts` | `supported`, `partially_supported`, `unsupported`, `unreviewed`, plus `total`. |

### Diagnostics

`diagnostics` has `interpretation_origin`, `model_provenance`, and `findings`.
`interpretation_origin` is:

- `extractive` when provider is `source_evidence` and model is `extractive-v1`;
- `ai` for any other interpretation provenance;
- `absent` when the report has no interpretation stage.

Each finding records `index`, `statement`, `origin`, `citations`, `references`,
`has_text_support`, and `publication_collection_dates_distinct`.

Each citation resolves against the evidence map (`evidence.analyses` and
`evidence.patterns`) and records:

| Field | Meaning |
| --- | --- |
| `identity` | Canonical citation shape: kind, reference identity, fact field, observation type, or pattern type. |
| `resolved` | The exact evidence-map target exists. |
| `reference_found` | The identity exists in `research.references`. |
| `analysis_found` | An evidence analysis exists for the reference. |
| `fact_found` / `observation_found` / `pattern_found` | The kind-specific evidence entry exists. |
| `value` | Exact evidence-map value, or `null` when unresolved. Patterns resolve to the aggregate object. |
| `value_status` | `missing`, `null`, `blank`, `non_text`, or `text`. |
| `cited_text` | Exact string value when the value is a string; otherwise `null`. |
| `unresolved_reason` | `reference_not_found`, `analysis_not_found`, `fact_absent`, `observation_absent`, `pattern_absent`, `malformed_citation`, or `unsupported_citation_kind`. |

`non_text` means the resolved value is not a string: a number, boolean, list,
or pattern aggregate. `blank` means a whitespace-only string. `null` is an
explicit JSON null. `missing` means there was no resolved value.

`cited_text` is the exact cited value; the evaluator does not compare the
statement to it. A title citation and a different description are both exposed
in `references`, so a reviewer can see which field was cited and what the other
field said. `title` and `description` in `references` are exact values.

Each reference entry records `reference_found` (in research), `analysis_found`
(in evidence), exact `title` and `description`, raw `published_at` and
`collected_at`, their calendar dates, and
`publication_collection_dates_distinct`. The last value is `true` when both
dates parse and differ, `false` when both parse and match, and `null` when a
date is absent or unparseable. At finding level, the value is `true` if any
cited reference has distinct dates, `false` if all comparable references match,
and `null` if none are comparable. Date distinctness is a structural fact; it
does not say whether the statement used the wrong date.

`has_text_support` is `true` only when at least one resolved fact citation
points to a nonblank `title` or `description` string. It is a structural
presence check, not a support judgment.

### Worksheet

Each row contains `finding_id`, `finding_index`, `statement`,
`citation_identities`, `cited_evidence_values`, `judgment`, and `note`.
Unannotated rows start as `unreviewed`.

`finding_id` is the lowercase SHA-256 hex of the canonical JSON object:

```json
{
  "report_fingerprint": "<sha256>",
  "finding_index": 0,
  "statement": "<statement>",
  "citation_identities": [],
  "cited_evidence_values": []
}
```

`cited_evidence_values` keeps the same order as `citation_identities`; an
unresolved citation contributes `null`. Changing the report, finding order,
statement, citation identity, or cited evidence value changes the id. Applying
a judgment or editing a note does not.

### Annotations

An annotation file is one JSON object keyed by `finding_id`:

```json
{
  "<finding_id>": {
    "judgment": "supported",
    "note": "The description states this directly."
  }
}
```

Judgment must be `supported`, `partially_supported`, or `unsupported`. `note`
is a string and defaults to empty when omitted. Only ids present in the current
worksheet are applied.

Ids that are not in the worksheet are listed in `stale_annotations` and are
never applied. A stale entry is not validated or counted, so an old annotation
file cannot silently inflate `supported`. A malformed annotation for a current
finding is an input error.

`counts` keeps the four states separate. `unreviewed` is never counted as
`supported`; there is no combined "positive" bucket. `total` is the number of
worksheet rows.

## Human-review workflow

1. Export one report JSON from the application.
2. Run the evaluator without annotations, or with the empty template.
3. Read each worksheet row against its exact citations. Check the cited field,
   the exact source text, the description when the title was cited, and both
   dates when recency is part of the statement.
4. Assign one of the three judgments and write a short note. Use
   `tests/fixtures/research_quality/annotations.json` as the empty format
   template; it is deliberately empty because finding ids depend on the report.
5. Rerun with `--annotations`. Unannotated findings remain `unreviewed`; stale
   ids are reported and ignored.
6. Keep the report, annotation file, and evaluation output together for audit.

Suggested human meanings:

- `supported`: every specific claim in the statement is entailed by the cited
  text.
- `partially_supported`: some claims are entailed, but a specific detail,
  qualification, attribution, or date is not.
- `unsupported`: the cited text does not entail the statement's specific claim.

These definitions apply to the reviewer's reading. The evaluator never assigns
them.

## What it does not establish

- It does not prove semantic entailment, factual correctness, significance, or
  recency.
- It does not infer an event date, validate a launch date, or treat publication
  date as event date.
- It does not judge promotional wording, sponsorship, endorsement, authority,
  expertise, or source independence.
- It does not detect duplicates, missing qualifications, or model quality.
- A resolved citation proves only that the cited evidence-map entry exists. It
  does not authenticate the source, verify the source's own claim, or show the
  citation supports the statement.
- `has_text_support` proves only that a cited title or description has text.
- There is no aggregate quality score, ranking, threshold, or pass/fail gate.
- There is no LLM-as-judge and no model-generated annotation. Judgments come
  only from the annotation file.
- No network access, source fetch, transcription, OCR, or media analysis is
  performed.

## Limits

- Only interpretation findings are evaluated. Strategy gaps, opportunities,
  ideas, and briefs are not findings in this worksheet.
- Duplicate evidence-map entries are resolved deterministically by using the
  last entry seen; the evaluator does not report the ambiguity.
- Malformed citations stay unresolved with an explicit reason. The evaluator
  does not repair report structure.
- Dates use the calendar-date component as serialized; time-zone offsets are
  not normalized.
- Finding ids change when evidence values change, so a changed report makes old
  annotations stale. That is intended: re-review instead of carrying judgments
  across different evidence.
- The benchmark cases are small fictional reports for regression tests, not a
  quality benchmark or a statistically meaningful sample.
