# Research quality evaluation

Status: offline structural evaluator and recorded-output benchmark. The
evaluator produces structural diagnostics and a human worksheet; it does not
score quality. The benchmark compares two explicitly identified configurations
using supplied outputs. Neither mode calls a model or the network.

Code: [evaluation.py](../src/trendora/research/evaluation.py) for one report;
[quality_benchmark.py](../src/trendora/research/quality_benchmark.py) for the
versioned dataset, run replay, comparison, accounting, and Markdown report.
Fixtures: [cases.json](../tests/fixtures/research_quality/cases.json),
[benchmark_v1.json](../tests/fixtures/research_quality/benchmark_v1.json), and
[runs/](../tests/fixtures/research_quality/runs/). Tests:
[test_research_evaluation.py](../tests/unit/test_research_evaluation.py) and
[test_quality_benchmark.py](../tests/unit/test_quality_benchmark.py).

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

# Evaluate one recorded benchmark run.
.venv/bin/python -m trendora.research.quality_benchmark evaluate \
  --dataset tests/fixtures/research_quality/benchmark_v1.json \
  --run tests/fixtures/research_quality/runs/baseline.json \
  --split development \
  --output /tmp/trendora-benchmark-baseline

# Compare two recorded runs.
.venv/bin/python -m trendora.research.quality_benchmark compare \
  --dataset tests/fixtures/research_quality/benchmark_v1.json \
  --baseline tests/fixtures/research_quality/runs/baseline.json \
  --candidate tests/fixtures/research_quality/runs/candidate.json \
  --split development \
  --output /tmp/trendora-benchmark-comparison

# Focused tests.
.venv/bin/python -m pytest tests/unit/test_research_evaluation.py tests/unit/test_quality_benchmark.py -q
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
- The 24-case benchmark is a small smoke benchmark, not statistically
  representative evidence. Its author-written expectations are provisional.

# Quality and cost benchmark

The benchmark wraps the evaluator with a versioned dataset, two named
configurations, recorded outputs, explicit accounting, and a comparison report.
It is an engineering workflow, not a model-ranking system.

## Dataset v1

`tests/fixtures/research_quality/benchmark_v1.json` contains 24 clearly
fictional cases. Each case has a stable ID, a `development` or `held_out` split,
a fixed six-field source snapshot with no recorded interpretation, a question,
failure categories, and author-written provisional expectations/rubric/
rationale. The split is 16 development and 8 held-out. The held-out split is
small and deterministic; it is not a statistical holdout.

Expected behavior, rubric, and rationale are review metadata. They never enter
the prepared evidence or model-input hash. The input projection contains the
case ID, question, exact compacted-evidence hash, prompt hash, and effective
compaction identity.

The dataset reuses five existing structural cases and adds compact cases for
negation, changed numbers/units/percentages/eligibility, unsupported
specificity and trends/popularity, promotion, date uncertainty, contradictory
and syndicated sources, blank/missing/unresolved evidence, observations and
patterns, mixed sources, multilingual text, and paraphrase.

## Run file

A run file is JSON with:

- `schema_version: 1`;
- `run_id`, `mode` (`recorded_output` or `mocked_transport` only);
- `dataset_id`, `dataset_version`, and required `dataset_sha256`;
- `split` and `case_ids`;
- `configuration` containing exactly: `id`, `provider`, `model`,
  `prompt_version`, `prompt_sha256`, `generation_parameters`, `compaction`,
  `retry_policy`, `deadline_seconds`;
- optional `run_elapsed_ms`;
- `outputs`, keyed by selected case ID. Every present output carries a required
  `prepared` identity block:
  `source_snapshot_sha256`, `compacted_evidence_sha256`,
  `model_input_sha256`, `prompt_sha256`, and `configuration_sha256`.

A case output is one of:

```json
{"kind":"synthesis","interpretations":[...],"model_provenance":{"provider":"...","model":"..."},
 "attempts":[{"status":"ok","elapsed_ms":123,"usage":{"prompt_tokens":10,"completion_tokens":5}}]}
{"kind":"synthesis","content":"{\"interpretations\": [...]}","model_provenance":{"provider":"...","model":"..."}}
{"kind":"fallback","attempts":[]}
{"kind":"failure","failure_code":"provider_timeout","attempts":[{"status":"timeout","elapsed_ms":30000}]}
```

When `content` is supplied instead of parsed interpretations, the real provider
DTO parser is exercised. Raw content and decoded interpretations converge on
the same production parser, research-synthesis bounds (six findings, 500
characters each), citation validation against the compacted pack, provenance
check, non-empty check, and title/description text-presence boundary. Invalid
provider JSON, empty output, over-bound output, unresolved or missing-field
citations, pattern/observation-only findings, and blank text become failed
cases; they do not become synthesized success or invented fallback. Rejected
diagnostics are retained where the interpretations parsed. The report is
validated as an API response snapshot before diagnostics; unresolved citations
are exposed, not repaired.

The `prepared` identities are established when the recording is prepared and
verified before evaluation. A missing or mismatched dataset hash, source
snapshot, compacted evidence, prompt, or configuration rejects the run; older
recordings without these fields must be re-prepared, not upgraded by inference.
This workflow applies the production compaction function; only its current limits
(24 references, 200 title characters, 600 description characters) are
supported. Other compaction settings are rejected rather than represented by
metadata alone. The run records the evaluator application revision and marks
generation provenance unverified unless a recording supplies separate
generation-code identity.

Missing outputs and malformed/truncated/over-bound synthesis outputs stay in the
case denominator. `finish_reason: "length"` maps to `output_truncated`.

Observed model identity is taken from the recorded output provenance and is
labelled as recorded, not proof of the live route. Requested provider/model is
the configuration identity, not evidence that the route used it.

## Comparison and artifacts

`evaluate` writes `run.json` and `worksheet.json`. `compare` writes
`comparison.json`, `worksheet.json`, and `comparison.md`. The comparison records
dataset hash/version/split/case-set and per-case source-snapshot, compacted
evidence, prompt, and model-input hashes. Differing dataset hashes, versions,
splits, case sets, or source snapshots are blocking. Differing compacted
evidence is visible and not treated as like-for-like. Prompt-only differences
leave evidence unchanged; model-only differences leave evidence and prompt
unchanged. Multiple configuration differences are flagged and the comparison
does not claim a controlled single-variable improvement. Identical
configurations are compared but flagged.

Artifacts must stay outside source control unless they are intentionally small,
sanitized fixtures. The shipped example runs cover six development cases; they
demonstrate the machinery, not the full 16-case development split. Raw provider
responses, prompts, authorization headers, and reasoning text are never written
by this workflow; only known answer/evidence fields and safe diagnostics are
retained.

## Metadata policy and limits

Nested configuration is allowlisted: generation parameters (`temperature`,
`top_p`, `max_output_tokens`, `seed`), production compaction limits, and retry
policy (`max_attempts`, `retry_on`). Unknown nested fields are rejected with a
field-name-only error, not echoed values. Model provenance is reconstructed with
only provider and model. Attempts retain only status, elapsed time, allowlisted
usage fields, and cost/pricing fields; extra headers, envelopes, and reasoning
are dropped. Failure codes must be from a fixed safe set, otherwise they become
`provider_error`.

Attempt accounting is parsed independently. A malformed usage field, cost,
attempt time, case time, or non-object attempt leaves that value unknown with a
fixed diagnostic; it does not erase valid fields, earlier attempts, attempt
order, or operational acceptance. Missing and invalid values remain unknown,
never zero. Aggregate totals retain known subtotals and expose
`invalid_attempts`, `invalid_case_elapsed`, `accounting_complete`, and related
counts. Configuration numeric fields remain strict and reject non-finite or
boolean values.

This is structured metadata control, not a universal secret scrubber. Answer
text, source text, and human annotations can contain sensitive data; sanitize
real recordings before use.

## Metrics

All rates carry explicit denominators:

- accepted synthesis / fallback / failed cases over selected cases;
- accepted and rejected-diagnostic finding counts separately; structural and
  review denominators include findings from accepted outputs plus parseable
  findings retained as rejected diagnostics;
- resolved citations over total citations (same combined denominator);
- findings with cited text present over total findings (same combined
  denominator);
- reviewed findings over total worksheet findings, including rejected
  diagnostic rows; each row carries `accepted_synthesis`;
- supported, partially_supported, unsupported among reviewed findings;
- unreviewed separately, never counted as supported;
- provider attempts, attempt statuses, attempts with usage, known token sums and
  known-attempt counts (unknown stays unknown), invalid accounting counts, and
  whether accounting is complete;
- recorded attempt/case timing and separately measured benchmark-processing
  time; recorded replay timing is not model latency;
- actual and estimated charges by currency, with attempts-with-cost and
  attempts-without-cost counts.

Usage fields accepted: prompt, completion, reasoning, cached, and total tokens.
Missing values stay unknown. Reasoning tokens are reported separately and never
added to completion tokens. A known total that disagrees with prompt+completion
is flagged, not corrected. Estimated cost requires caller-supplied pricing
source, unit, date, and currency; the comparison reports that pricing provenance
and never builds in a price table. Actual provider charge, estimate, and unknown
remain separate.

## Human review

`worksheet.json` contains one row per parseable synthesis finding, including
findings from rejected outputs, with case ID, finding ID, statement, canonical
citation identities, exact cited values, value status, reference context (title,
description, dates), `accepted_synthesis`, and the bound judgment. A title
citation with a detail that appears only in the description shows both values;
it does not silently become an exact-field support judgment. Rejected rows are
diagnostic evidence, not accepted synthesis.

Annotations are keyed by finding ID. A changed statement, citation, evidence
value, or report makes old annotations stale. Stale ids are reported and never
applied. All judgments start `unreviewed`; agents may add proposed notes but must
not impersonate owner review.

To review:

1. Run `evaluate` or `compare` without annotations.
2. Open `worksheet.json` beside the cited source values.
3. Assign one judgment and a short rationale; keep a JSON map keyed by
   `finding_id`. Optional `categories` may list issue types such as
   `wrong_field`, `altered_number`, `missing_qualification`, `misleading_date`,
   or `unattributed_promotion`.
4. Rerun with `--annotations`, `--baseline-annotations`, or
   `--candidate-annotations`.
5. Keep the dataset, run files, worksheet, and comparison together.

## Engineering case study template

Use this when a real, authorized comparison exists:

- **Problem:** what failure motivated the change.
- **Baseline:** configuration, dataset split, case IDs, prompt/input hashes.
- **Controlled change:** the single intended difference.
- **Results:** operational, structural, review coverage, latency/usage/cost.
- **Failure analysis:** representative failed/fallback cases and reviewed
  unsupported findings.
- **Limitations:** sample size, mock/replay status, missing metrics, and what the
  evidence cannot establish.

Leave numbers blank or explicitly fictional until measured. A recorded-output
example demonstrates the machinery only.

## Future live experiment

No live runner is implemented by this offline workflow. A future live run must
be explicitly opt-in and fail closed unless the operator supplies both exact
configurations, selected case IDs/split, maximum app-level attempts,
per-request timeout, and a bounded call limit. It must not default to the whole
dataset, silently substitute models, or retry without limit. Router-internal
retries, upstream cancellation, and final billing may remain outside
Trendora's control; a local call limit is not a guaranteed monetary ceiling.

The smallest proposed live experiment is the 8-case held-out split, two
explicit configurations, and one application-level attempt per case:
16 maximum provider calls total, a 30-second per-request timeout, no retries.
It must not be run without owner authorization and a bounded pricing/call
approval; it is not part of this milestone.

## Benchmark limits

- 24 synthetic cases are a smoke benchmark, not production evidence.
- Author expectations are provisional and unreviewed.
- Structural diagnostics do not establish factual or semantic support.
- Recorded outputs do not establish live quality, latency, or cost.
- Human review coverage is reported explicitly; absence of review is not a pass.
- The recorded `application` revision is the evaluator run revision, not proof
  of the code or prompt revision that generated the recording. Generation-code
  provenance remains unverified unless separately recorded.
- Structured metadata allowlists prevent known accidental leaks from nested
  configuration, provenance, attempt, and failure fields. They cannot prove
  arbitrary answer text, source text, or human annotations are non-sensitive;
  sanitize real recordings before use.
