# 33 — Reader, exports, history filters, and run diagnostics

This document records the reader and history contracts added after the M23A
report pipeline. It describes what the UI and API do today. Where this document
disagrees with the code, the code wins.

## 1. Reading a report

- A citation resolves against the returned evidence map. For text facts
  (`title`, `description`), the citation drawer shows the exact cited value or
  an explicit unavailable reason (missing fact, null, blank, non-text). It never
  substitutes the reference's own description for the cited field.
- Returned values render as escaped text. Structural grounding identifies the
  evidence a claim cites; it does not prove the claim is true.
- The source library filters intersect title text, platform derived from the
  URL hostname, and whether a valid publication day exists. Platform matching
  uses the same exact hostname boundaries as the reference card, so a spoofed
  host such as `reddit.com.evil.example` is not Reddit.
- Filters and expansion are view state only. Source identities, order, citation
  targets, and the returned report object are unchanged.
- The source list reports the returned total and the matching count. A no-match
  state says no source matches and offers a reset; it never claims the report
  has no sources.

### Ask and comparison

- "Ask this report" answers cite source identities from the saved report, not
  exact title/description fields. The trace drawer labels them source-level and
  does not claim the cited source supports the answer semantically.
- Ask is bounded by a 180-second Next.js proxy deadline plus the provider
  deadline. Cancelling or navigating away ends this browser's wait; it does not
  guarantee the router or upstream provider stopped its work. A late response
  cannot replace a newer request or survive an account change.
- Report comparison fetches the nearest older report once per saved report id.
  It reports added and removed finding statements after whitespace and case
  normalization. Those are wording differences, not real-world change.
- With no earlier report, comparison says so and shows no counts. An expired
  prior report cannot be compared; the route returns an error and the UI offers
  an explicit GET retry rather than skipping the prior report.

## 2. Exports and print

- **Full Markdown copy** uses returned data only. It includes findings with
  their citations and cited evidence, source identities and safe links, scope,
  coverage gaps, publication-date uncertainty, synthesis/excerpt labeling,
  content tools when present, and run diagnostics when present. Source text is
  escaped so HTML-looking returned text stays literal. Only `http(s)` source
  URLs become links.
- **JSON download** remains the exact returned report, unchanged.
- **Print / Save as PDF** uses the browser's native print dialog. The print
  action opens every disclosure before printing and restores the reader's
  previous disclosure state afterwards, including when printing fails. Print
  CSS hides application chrome, interactive controls, and save state, and shows
  every source even when screen filters or the six-source expansion hid it.
  There is no separate print-only copy of report content visible on screen.
- Clipboard failures render a visible message instead of a silent no-op.

## 3. Saved-report filters

`GET /api/v1/research/reports` accepts optional, bounded parameters:

| Parameter | Meaning |
| --- | --- |
| `q` | Literal, case-insensitive topic substring. Trimmed; maximum 200 characters including surrounding whitespace. `%`, `_`, and `\` are matched literally. |
| `status` | Persisted outcome at save time. Must be a known status. |
| `date_from`, `date_to` | Inclusive overlap with the report's *requested* window, not its save date. Either bound may be omitted. |

Filters run before count, ordering, and pagination, across creators in the same
workspace. A non-admin's rolling 30-day visibility window still applies first.
Ordering stays `created_at` descending with `id` descending as the tiebreak.

Validation: unknown status, invalid calendar date, or `date_from > date_to`
returns 422 before any query. `q` longer than 200 characters also returns 422.

Two status concepts stay separate:

- The **stored outcome** is what `status` filters. Retention can overwrite it
  with `source_data_expired`, after which the original outcome is no longer
  available.
- The **effective read status** is computed when the summary is returned. A
  stored `completed` report whose source data aged out is returned as
  `source_data_expired`.

The history UI labels the control "Saved outcome" and states this limitation.
It applies only on explicit Apply, resets pagination to the first page when
filters change, aborts superseded loads, ignores stale responses, and
distinguishes empty history from no matches, loading, and errors.

## 4. Run diagnostics

`POST /api/v1/research/report` may include top-level `run_details`:

```json
{
  "elapsed_ms": 1234,
  "stage_durations_ms": {"collection": 500, "interpretation": 600, "persistence": 134},
  "ai_requests": [{
    "stage": "interpretation",
    "request_bytes": 2048,
    "elapsed_ms": 590,
    "prompt_tokens": 100,
    "completion_tokens": 0,
    "total_tokens": 100
  }],
  "retry_count": 0,
  "finding_mode": "ai_interpretation"
}
```

- `elapsed_ms` and stage durations are monotonic measurements for that request.
- `request_bytes` is the UTF-8 size of the serialized provider request. It is
  not a token count and not billing.
- Token counts are included only when the provider returned an integer in the
  JavaScript-safe range. Missing, negative, boolean, fractional, or oversized
  values stay `null`. A real zero stays zero.
- Prompt text, source bodies, credentials, endpoints, and raw provider errors
  are never collected.

`run_details` is envelope metadata. It is **not** part of the six-field
immutable snapshot (`status`, `research`, `evidence`, `interpretation`,
`strategy`, `ideation`), is not fingerprinted, and is not persisted. Saved and
legacy reports show that diagnostics were not recorded; they do not display
invented zeroes. Persisting telemetry would require a separate schema decision
and migration. The on-demand content endpoint returns fresh `run_details` for
its own operation; the derived saved snapshot still omits them.

The UI keeps three clocks distinct: browser wait (submit to response), backend
run duration, and per-attempt AI request time. While the synchronous request is
in flight it shows only the measured browser elapsed time; it does not simulate
stages or percentage completion. Local cancellation stops the browser request;
it does not guarantee the router or upstream provider stopped its work.

## 5. Research-quality evaluation

`docs/RESEARCH_QUALITY.md` documents the offline evaluation CLI, its benchmark,
and the human-review worksheet. Its retained `has_text_support` field means only
that a resolved title or description fact carries nonblank text. It is not an
entailment check, a factual-support judgment, or a quality score. Structural
diagnostics never become a semantic pass, and absent review stays `unreviewed`.

## 6. Verification

Backend:

```sh
.venv/bin/python -m pytest tests/unit/test_report_history_scope.py tests/unit/test_report_history_search.py tests/unit/test_research_run_details.py -q
```

Frontend, from `web/`:

```sh
npm test
npm run lint
npm run typecheck
npm run test:browser:contract
npm run test:browser   # isolated fixture build; requires the installed driver/browser paths
```
