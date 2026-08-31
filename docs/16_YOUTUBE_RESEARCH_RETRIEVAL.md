# 16 — YouTube-First Research Retrieval (M14)

## Status

**M14 (this document + implementation):** the first milestone where Trendora executes a real evidence-source research request. It extends the M13 `ResearchRun` lifecycle from `ready` into actual retrieval execution and produces normalized in-memory research references.

**Flow implemented:**

```text
validated ResearchQuery
  → capability resolution (M13)
  → YouTube public discovery (search.list, type=video)
  → YouTube metadata/statistics enrichment (videos.list)
  → normalized in-memory research references
  → truthful ResearchRun execution result
```

**What M14 does NOT do:** no AI analysis, no content opportunities, no ranking scores, no database persistence, no frontend, no research API routes, no derived metrics. Nothing is written to PostgreSQL; retrieved references follow YouTube's standard non-authorized public-data policy (in-memory only; the repository has no approved analytics storage amendment).

**Implementations:** `src/trendora/research/youtube.py` (retriever), `src/trendora/research/models.py` (lifecycle extension + `ResearchReference`), `src/trendora/connectors/youtube/client.py` (search.list), `src/trendora/connectors/youtube/schemas.py` (search resources). Full suite: **413 passing** (393 baseline + 20 new).

---

## 1. Discovery (search.list)

`YouTubeClient.search_videos(...)` adds `search.list` with:

- `type=video`
- `q` from `ResearchQuery.topic`
- `regionCode` from `ResearchQuery.market`
- `publishedAfter` / `publishedBefore` from the query date window
- `order=relevance` (no invented ranking; `viewCount` ordering is not used)
- `maxResults <= 50`, deterministic pagination, deduplication by video id

**Pagination semantics** (driven by `result_limit <= 100`):

- `1..50` → at most one search page
- `51..100` → at most two search pages
- stop early when `nextPageToken` is absent
- never return more than `result_limit`
- preserve source result ordering

**Quota note (documented, not enforced):** per official YouTube documentation (June 2026), `search.list` sits in its own granular Search Queries bucket at **1 unit/call, 100 calls/day**. The client does not hard-code quota; it is an observed API constraint for M14 operations planning. `videos.list` costs 1 unit in the main bucket.

---

## 2. Enrichment (videos.list)

Enrichment reuses the existing `YouTubeClient.list_videos` path (`part=snippet,contentDetails,statistics`), which is the tested, chunked, validated method used by M2A/M2B.

**Documented enrichment choice:** YouTube's newer `videos.batchGetStats` (June 2026, own granular bucket, 1 unit/call) exists and could be a future quota optimization. M14 keeps enrichment on the established `videos.list` path because (a) it already returns every field a reference needs (title, channel, publish time, view/like/comment counts) and (b) it avoids introducing an untested endpoint shape. This is an engineering decision, not a claim that `batchGetStats` does not exist.

---

## 3. Date window semantics

`ResearchQuery.date_from` / `date_to` are calendar `date` objects (M13). The retriever converts them to YouTube's RFC 3339 `publishedAfter`/`publishedBefore` as **UTC midnight**, treating the window as inclusive-start / exclusive-end:

```text
publishedAfter  = date_from       T00:00:00Z   (inclusive)
publishedBefore = date_to + 1 day T00:00:00Z   (exclusive)
```

Example: `date_from=2026-08-01`, `date_to=2026-08-30` → `publishedAfter=2026-08-01T00:00:00Z`, `publishedBefore=2026-08-31T00:00:00Z`.

---

## 4. Normalized research reference

`ResearchReference` (frozen dataclass in `research/models.py`):

| Field | Meaning |
| --- | --- |
| `source_code` | `"youtube"` |
| `content_external_id` | YouTube video id |
| `url` | `https://www.youtube.com/watch?v={id}` (original URL for provenance) |
| `title` | video title (enriched, falling back to search snippet) |
| `description` | source-provided description (video snippet, falling back to search snippet). **This is YouTube source metadata, not a transcript, caption, video-content analysis, or spoken content.** |
| `published_at` | parsed UTC publish time |
| `channel_external_id` | YouTube channel id |
| `channel_title` | publisher/channel display name (from the search snippet) |
| `market_context` | requested market code (e.g. `"SG"`) |
| `market_basis` | `MarketBasis.YOUTUBE_REGION_AVAILABILITY` |
| `source_rank` | 1-based position in the deduplicated source search order (source order only) |
| `metrics` | immutable `ResearchMetrics` with exactly three official fields: `view_count`, `like_count`, `comment_count`; each is `None` when the source did not provide it (never zero for missing) |
| `collected_at` | timezone-aware retrieval time |

**No derived metrics.** Engagement rate, views-per-day, velocity, popularity/trend/Trendora scores, sentiment, and any cross-metric normalization are never computed. `ResearchMetrics` is a frozen, slots-typed value object: its three fields are the only metrics carried, and they cannot be mutated after a `ResearchReference` is constructed.

### Market semantics

`ResearchQuery.market` maps to YouTube `regionCode` at discovery time. The reference preserves the market truth explicitly and separately:

- `market_context` — the requested market code (e.g. `"SG"`, `"TH"`).
- `market_basis` — what that context means for this source: `"youtube_region_availability"`.

**Critical invariant:** YouTube `regionCode` reflects regional availability/viewability of content. It is **not** creator nationality, publisher nationality, or content country-of-origin evidence, and it is **not** a language signal. No `creator_country`, `publisher_country`, `origin_country`, or `language` field is ever inferred or produced.

### Source rank

`source_rank` is the first unique returned video = rank 1; deduplication does not create gaps; pagination preserves global source order; enrichment never reorders references. It is **source order only** — not a Trendora relevance score, performance score, confidence, or opportunity score, and no new ranking is calculated.

---

## 5. ResearchRun lifecycle extension

M14 extends the M13 lifecycle by adding real execution states:

```text
requested
  → resolving_capabilities
  → ready | blocked
  (ready)
  → collecting       (retrieval/discovery + enrichment)
  → normalizing      (reference construction)
  → completed | failed
```

- `collecting` / `normalizing` / `completed` / `failed` are new in M14.
- `ready` still means *eligible for execution*, never completed.
- `blocked` cannot execute (transition guard raises `ResearchStateError`).
- On retrieval failure the run is marked `failed` and the original error (e.g. `YouTubeApiError`) is re-raised — errors are never swallowed.

`ResearchRun.execute(retriever)` drives `collect()` then `normalize()`; references are exposed via `run.references`. Execution status and coverage completeness remain separate concepts: a partial-coverage query still completes execution over the available source, with coverage truth preserved separately.

---

## 6. Truthful execution result

**`ResearchRun` is the M14 top-level execution result.** It already exposes, directly:

- `query` — the `ResearchQuery` that was executed
- `coverage` — the M13 capability/coverage result (`complete`/`partial`/`none`, per-source statuses)
- `status` — execution status (`blocked` / `failed` / `completed`, plus intermediate `ready`/`collecting`/`normalizing`)
- `references` — the normalized in-memory references (empty tuple if no results; `None` before execution)

A completed run therefore lets the caller determine the query, the coverage truth, whether it was blocked/failed/completed, and the retrieved references. **No separate `ResearchResult` model is created** — `ResearchRun` already satisfies the contract.

Nothing in the result claims retrieval for a source that was not available, and no content is persisted.

---

## 7. Invariants proven by tests

- `search.list` builds the documented params (q, regionCode, type=video, order=relevance, date window, maxResults) with no chart/order invention.
- Pagination never exceeds `result_limit`, stops without `nextPageToken`, dedupes video ids, and skips non-video results.
- References carry only official metrics (`ResearchMetrics`: view_count, like_count, comment_count); no derived metric can appear; a missing statistic is `None`, and `ResearchMetrics` cannot be mutated after construction.
- A video missing enrichment still yields a truthful reference from search metadata (all metrics `None`), never a fabricated stat.
- Description and channel display name are preserved from source snippets; the description boundary (metadata, not transcript/caption/analysis) is documented.
- `market_context` equals the requested market and `market_basis` is `youtube_region_availability`; no creator/publisher/origin country and no language is inferred.
- `source_rank` is 1-based, consecutive across deduplication, continuous across pagination, and unaffected by enrichment order; it is never a computed score.
- Date window is inclusive-start / exclusive-end.
- `ready` is not `completed`; a run must pass through collection and normalization to complete.
- Execution failure marks the run `failed` and re-raises; a `blocked` run cannot execute.
- No DB writes, no persistence, no schema change.

---

## 8. Non-goals

- No persistence of content/publisher/snapshot/research rows (in-memory only; YouTube 30-day non-authorized policy applies).
- No derived metrics, scores, or ranking.
- No AI, opportunities, ideas, briefs, or evidence model.
- No research API routes; the M11 forecast API is unchanged.
- No connector behavior changes to existing ingestion paths (search.list is additive).
- No new dependencies.

---

## 9. Readiness for M15

M15 can consume `ResearchRun.references` for the research workspace surface or extend retrieval to other sources through the same capability-gated run lifecycle. Persistence (with explicit retention) remains a later decision.

---

## 10. Files

- `src/trendora/connectors/youtube/schemas.py` — `SearchResource` / id / snippet
- `src/trendora/connectors/youtube/client.py` — `search_videos`
- `src/trendora/research/models.py` — `ResearchReference`, extended `ResearchRunStatus`, `ResearchRun.execute`
- `src/trendora/research/youtube.py` — `YouTubeResearchRetriever`
- `src/trendora/research/__init__.py` — exports
- `tests/fixtures/youtube_responses.py` — search fixtures
- `tests/unit/test_youtube_client.py` — search client tests
- `tests/unit/test_research_youtube.py` — retriever + run execution tests
