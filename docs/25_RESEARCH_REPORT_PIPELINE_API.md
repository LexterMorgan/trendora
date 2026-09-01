# 25 — Research Report Pipeline + API (M23A)

## Status

**M23A (this document + implementation):** composes existing M15–M22 seams into one truthful structured report and exposes it via `POST /api/v1/research/report`. No new intelligence, no fourth AI call, no frontend.

Backend: **750 unit tests passing** (+33 new). No DB, connector, M5, or frontend changes; no dependency added.

## 1. Orchestration order

```text
ResearchApplicationService → completed ResearchRun → analyze_references →
aggregate_patterns → EvidencePack → GroundedInterpretationService →
InterpretationResult → StrategicContext → GroundedStrategyService →
StrategicResult → IdeationContext → GroundedIdeationService →
IdeationResult → ResearchReport
```

`ResearchReportService` calls each stage exactly once and never duplicates M15–M22 logic.

## 2. Report contract

`ResearchReport(status, research_run, evidence_pack, interpretation_result, strategic_result, ideation_result)` — frozen+slots. No IDs, timestamps, scores, rankings, summaries, confidence, persistence metadata, or extra claim types.

`ResearchReportStatus`: `completed` | `no_evidence`. Distinct from `ResearchRun.status`.

## 3. Completed vs no_evidence

- **NO_EVIDENCE**: run COMPLETED, retrieval executed, `references == ()`, all four downstream fields None. No AI service runs. HTTP 200 (not an error).
- **COMPLETED**: run COMPLETED, references nonempty, every reference has a nonblank original URL, all four downstream fields present, EvidencePack reference IDs exactly match the run references (no missing/extra/reordered/duplicate), the URL fact of every analyzed reference matches its `ResearchReference.url`, interpretations revalidate against the pack, strategy revalidates through `StrategicContext`, ideation revalidates through `IdeationContext`, and model provenance stays independent on each AI result.

`validate_research_report` returns the unchanged report or raises a research-domain error.

## 4. Successful empty AI output vs unexecuted AI

Executed AI stages may return empty tuples; they remain non-null stage results with trusted provenance. This is distinct from `NO_EVIDENCE` (no evidence) and from provider failure (never converted to empty output).

## 5. Report service

`ResearchReportService(research, interpretation, strategy, ideation)` — one method with the same inputs as `ResearchApplicationService.execute`. Blocked run → `ResearchNoCoverageError` (no downstream calls). Zero references → validated `NO_EVIDENCE`. Nonempty → full pipeline. Provider/grounding failures propagate; nothing is skipped, repaired, retried, or partially completed.

## 6. Endpoint

`POST /api/v1/research/report` — reuses the existing `ResearchRequest` body via `ResearchReportRequest` (same fields, `extra="forbid"` so client-controlled provider/model/prompt/score fields are rejected). Thin adapter over `ResearchReportService`.

## 7. Response

```json
{"status":"completed","research":{},"evidence":{},"interpretation":{},"strategy":{},"ideation":{}}
```

- `no_evidence`: research populated, downstream sections `null`.
- `completed`: all sections populated even when inner lists are empty.

Sections expose: reference IDs, facts, observations, pattern aggregates with provenance IDs, interpretations + citations + provenance, gaps (supporting interpretation indexes + citations), opportunities (gap indexes + citations), ideas (title/angle/opportunity indexes + citations), briefs (idea index/objective/format/hook/outline + citations). Citations reuse the exact M20 JSON contract via `citation_to_json`. Separate trusted model provenance per AI stage.

No resolved claims, synthetic labels, flattened provenance, performance fields, or duplicated URLs inside citations.

## 8. Runtime construction

One dependency builds: provider config from `build_ai_provider_config` (settings `TRENDORA_AI_PROVIDER/MODEL/ENDPOINT_URL/API_KEY`), one `YouTubeClient` when `YOUTUBE_API_KEY` set, one shared `httpx.Client` for the three AI adapters. Owned clients close exactly once. Missing AI config fails fast (503) before retrieval; never represented as `NO_EVIDENCE`.

## 9. Error semantics

Preserved: all M15 errors (e.g. `research_no_coverage` 422). Added:

| Error | HTTP | Code |
| --- | --- | --- |
| `ResearchAIProviderNotConfiguredError` | 503 | `ai_provider_not_configured` |
| `ResearchAIProviderError` | 502 | `ai_provider_error` |
| `ResearchAIResponseError` | 502 | `ai_response_invalid` |
| `ResearchInterpretationError` (grounding) | 502 | `ai_response_invalid` |

Fixed public messages; never leak keys, endpoint URLs, headers, provider bodies, reprs, traces, prompts, or evidence text.

## 10. Truth boundaries

Preserved across the whole report: requested ≠ available ≠ executed source; missing metric ≠ zero; market ≠ nationality; description ≠ transcript/media; source rank ≠ Trendora ranking; rare pattern ≠ gap; structural grounding ≠ entailment; gap ≠ opportunity ≠ idea ≠ brief; index links ≠ citations; no causality/uplift/expected performance/engagement/velocity/score/ranking.

## 11. Latency / production notes

- **Synchronous**: the report endpoint performs one research call + three AI provider calls serially. Documented latency limitation.
- **In-memory, non-production**: no persistence, no auth, live provider unverified; intended as a backend integration surface, not production.

## 12. M23B readiness

M23B can consume the report response and resolve the entire chain (brief → idea → opportunity → gap → interpretation → citation → reference → URL) without inventing data.

## 13. Files

- `src/trendora/research/reporting.py` — ResearchReportStatus, ResearchReport, validate_research_report, ResearchReportService, build_research_report_service
- `src/trendora/api/research_report_models.py` — request/response models + serializers
- `src/trendora/api/app.py` — dependency + `POST /api/v1/research/report`
- `src/trendora/api/errors.py` — AI error mappings
- `src/trendora/research/__init__.py`, `src/trendora/api/__init__.py` — exports
- `tests/unit/test_research_reporting.py` (18), `tests/unit/test_research_report_api.py` (15)
