# 17 — Research API (M15)

## Status

**M15 (this document + implementation):** exposes the existing M13/M14 research workflow through one synchronous FastAPI boundary. No new intelligence is added — the API is a thin adapter over the research application service.

Full suite: **450 passing** (425 baseline + 25 new).

---

## 1. Purpose

Let a client run a structured research request and receive the resulting `ResearchRun` state: the executed query, capability coverage, execution status, and normalized in-memory references. It answers "what content is out there for this topic/market/window" — it does **not** answer "which video is best", "what patterns exist", or "what should we create".

---

## 2. Application service

`ResearchApplicationService` (`src/trendora/research/application.py`) is the single synchronous orchestration entry point:

```text
inputs
  → construct/validate ResearchQuery
  → resolve capability coverage
  → create ResearchRun (READY | BLOCKED)
  → execute the registered runtime retriever for the first available source
  → return ResearchRun
```

It is explicit and small — no command bus, workflow engine, event bus, plugin framework, or DI container. The HTTP adapter never owns orchestration or retrieval.

`build_research_application_service(youtube_client=...)` registers the runtime retrievers that actually exist. Static capability truth is separate from runtime availability: YouTube stays `available` in the capability model even when no API key is configured; a request that needs it then raises `ResearchSourceNotConfiguredError`.

---

## 3. Endpoint

```text
POST /api/v1/research
```

Synchronous. No research history, GET-by-id, DELETE, PATCH, PUT, saved research, or source-specific routes.

---

## 4. Request schema

```json
{
  "topic": "AI education",
  "market": "SG",
  "date_from": "2026-08-01",
  "date_to": "2026-08-31",
  "sources": ["youtube"],
  "result_limit": 20
}
```

| Field | Type | Notes |
| --- | --- | --- |
| `topic` | string | required; blank rejected by `ResearchQuery` |
| `market` | string | required; canonical SEA market (ID/TH/MY/SG/VN/PH) |
| `date_from` / `date_to` | date | required; `date_from <= date_to` |
| `sources` | list[str] | defaults `["youtube"]`; maps to `ResearchQuery.source_codes`; lowercased/deduplicated |
| `result_limit` | int | defaults 50; `1..100` |

**Validation ownership:** the HTTP request model only types the structure. Semantic validation (blank topic, market validity, date range, source normalization, result_limit bounds) lives exclusively in `ResearchQuery` and is not duplicated in Pydantic. Structural malformation (missing field, bad type) is `invalid_request`; semantic rejection is `invalid_research_request`.

No language, sentiment, audience, creator country, engagement thresholds, ranking mode, campaign objective, or AI/model fields.

---

## 5. Response schema

```json
{
  "query": {
    "topic": "AI education",
    "market": "SG",
    "date_from": "2026-08-01",
    "date_to": "2026-08-31",
    "sources": ["youtube"],
    "result_limit": 20
  },
  "coverage": {
    "completeness": "complete",
    "sources": [
      {"source_code": "youtube", "capability": "public_search", "status": "available", "reason": null}
    ]
  },
  "executed_sources": ["youtube"],
  "status": "completed",
  "references": [...]
}
```

**Three distinct contracts, never collapsed:**

- `query.sources` — what the client requested.
- `coverage` — static platform capability truth (available/unavailable/conditional, complete/partial/none).
- `executed_sources` — which source(s) Trendora actually attempted at runtime (`"youtube"` today; empty before execution).

Static capability availability does not mean execution: a source may support `public_search` while Trendora has no configured runtime retriever (e.g. `stack_exchange`). The application service executes the first requested source that is both statically available **and** has a runtime retriever; it never fails just because an earlier requested source is statically available but not executable when a later one is genuinely executable. If no requested available source has a runtime retriever, the run is not falsely completed — the client gets `503 research_source_not_configured`.

Coverage is never overloaded to mean execution: `coverage available != source actually searched`, and `references empty != source not executed`.

---

## 6. Reference serialization

Each reference exposes official source facts only:

- `source_code`, `content_external_id`, `url`, `title`, `description`
- `published_at`, `channel_external_id`, `channel_title`
- `market_context`, `market_basis`
- `source_rank`
- `metrics`: `{view_count, like_count, comment_count}` (each `int | null`)
- `collected_at`

Enums serialize as stable strings (`"youtube_region_availability"`, `"available"`, `"completed"`). Datetimes are timezone-aware ISO 8601. No dataclass internals, ORM objects, or raw YouTube payloads are exposed.

---

## 7. Coverage semantics

- `completeness`: `complete` / `partial` / `none`
- per-source `status`: `available` / `unavailable` / `conditional`
- `reason` when present: `source_unknown`, `capability_not_supported`, `authorization_required`

Coverage is capability truth — it does **not** mean a source was actually searched.

---

## 8. Execution status

`completed` / `blocked` (and intermediate domain states) reflect actual run execution. A `completed` run means the executed source(s) were retrieved and normalized; `blocked` means no requested source had usable coverage. Execution provenance (`executed_sources`) carries which source(s) were actually attempted and is observable even when a successful search returns zero references.

---

## 9. Market semantics

`market_context` = requested market; `market_basis` = `youtube_region_availability`. YouTube `regionCode` is regional availability/viewability, **not** creator/publisher/content origin country and not language. No `creator_country`, `publisher_country`, `origin_country`, or `language` field is exposed.

---

## 10. Errors

Envelope: `{"error": {"code": ..., "message": ...}}`.

| Condition | HTTP | Code |
| --- | --- | --- |
| Structurally malformed body/params | 422 | `invalid_request` |
| Domain rejection (blank topic, invalid market, bad date range, bad result_limit, empty sources) | 422 | `invalid_research_request` |
| No requested source has usable coverage (run blocked) | 422 | `research_no_coverage` |
| Source available but no runtime retriever configured (e.g. missing `YOUTUBE_API_KEY`) | 503 | `research_source_not_configured` |
| Upstream YouTube failure | 502 | `research_upstream_error` |
| Unexpected | 500 | `internal_error` |

No Python class names, stack traces, object reprs, or secrets are exposed.

---

## 11. Zero results

`HTTP 200`, `status: "completed"`, `references: []`, and `executed_sources: ["youtube"]` — so a successful zero-match search remains observably executed. Zero search matches and upstream failure are different: upstream failure is `502 research_upstream_error`, never an empty 200.

---

## 12. Partial coverage

`POST /api/v1/research` with `sources: ["youtube", "instagram"]`:
- `HTTP 200`, `status: "completed"` (YouTube retrieval succeeded)
- `coverage.completeness: "partial"`; Instagram `status: "unavailable"`, `reason: "source_unknown"`
- references contain only YouTube; Instagram is never claimed searched and never gets a fake reference

The request is not failed merely because some requested sources are unsupported.

---

## 13. Runtime configuration

Missing `YOUTUBE_API_KEY` is **not** `capability_not_supported` (static capability truth is unchanged). It is a runtime/service availability error: `503 research_source_not_configured`.

---

## 14. Upstream failure

A YouTube API failure becomes `502 research_upstream_error` — never `200` with empty references. No API key or traceback leaks.

---

## 15. In-memory nature / no persistence

Everything is in memory. No research_runs table, no persisted references/metrics, no publisher/content_item/snapshot writes, no migrations, no SQL reads or writes for research. M5 and the existing forecast DB path are untouched.

---

## 16. API boundary

- Application service: constructs query, resolves coverage, creates/advances the run, selects registered retrievers, executes, returns the run.
- FastAPI adapter: deserializes request, calls the service, serializes the domain result, maps known exceptions to HTTP.
- The adapter does not call YouTube, build URLs, paginate search, parse payloads, calculate metrics, rank, query SQL, or persist.

---

## 17. Non-goals

No persistence, saved references, research history, AI/LLM, patterns, gaps, opportunities, ideas, briefs, reports, embeddings, vector DB, transcripts, media download, scraping, other platforms, auth, users/workspaces, async jobs, queues, WebSockets, caching, alerts, frontend, deployment, publishing, scheduling, or derived metrics.

---

## 18. Readiness for M16

M16 (research workspace UI) can consume `POST /api/v1/research` directly: submit a query, receive query/coverage/status/references, and render references without any new backend intelligence.

---

## 19. Files

- `src/trendora/research/application.py` — `ResearchApplicationService`, `build_research_application_service`
- `src/trendora/research/exceptions.py` — `ResearchNoCoverageError`, `ResearchSourceNotConfiguredError`
- `src/trendora/api/research_models.py` — `ResearchRequest` + explicit response models
- `src/trendora/api/app.py` — `POST /api/v1/research` + dependency
- `src/trendora/api/errors.py` — research/upstream error handlers
- `tests/unit/test_research_api.py`
