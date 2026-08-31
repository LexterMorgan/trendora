# 14 — Product & Architecture Re-baseline (M12)

## Status

**M12:** Documentation/architecture milestone. No application code, schema, migration, connector, API, dependency, or test changes were made.

**Context:** M1–M11B established an evidence-first Python analytics platform with a forecasting product slice (M8–M11B). The product direction has now evolved: forecasting remains a valid capability but is no longer the center of the product. This document re-baselines the architecture and roadmap toward an **evidence-backed content intelligence and research platform**.

**Document discipline:** each section distinguishes
- `CURRENT:` a fact true in the repository today,
- `DECISION:` a direction chosen by this re-baseline,
- `PROPOSAL:` a design to consider, not yet built,
- `OPEN:` a question the repository cannot yet resolve.

The repository remains the source of truth for everything labeled CURRENT.

---

## 1. Executive Decision

- **What Trendora was originally becoming:** a SEA education/technology intelligence platform whose first visible product surface was a **forecasting dashboard** (M6 baselines → M7 diagnostics → M8/M9 product contract → M10 GitHub forecast product → M11 FastAPI adapter).
- **Why the direction has evolved:** the product owner redefined the core job. The user does not primarily want to read forecast charts; they want help deciding **what to post and why, backed by inspectable evidence**. Forecasting answers one narrow question (“what is likely next for this metric”) and does not carry the discovery → evidence → opportunity workflow.
- **What remains valid from M1–M11B:**
  - The principle **“Python owns the truth. AI owns the explanation.”** ([00](00_PROJECT_OVERVIEW.md), [01](01_ARCHITECTURE.md)).
  - The **source-agnostic normalized schema** (`sources`, `markets`, `topics`, `retention_policies`, `publishers`, `content_items`, `content_item_topics`, `metric_snapshots`) ([02](02_DATABASE_SCHEMA.md)).
  - The **single M5 metric-analytics read path** — all downstream metric analytics continue through it; no second metric-SQL path ([05](05_ANALYTICS_SPEC.md)).
  - The **connectors** as legitimate, policy-respecting ingestion (YouTube primary; HN/SE/GitHub supporting signals) ([03](03_DATA_SOURCES.md), [04](04_INGESTION_PIPELINE.md)).
  - The **thin layered architecture** (M5 → M6/M7 → M10 product → M11 API adapter) as the pattern for every future feature surface.
  - **M6–M11 forecasting** as a reusable predictive signal, not deleted.
- **What becomes secondary:** forecasting as the primary product surface and the dedicated forecast-dashboard framing.
- **What the new V1 product is:** a deliberately narrow, **YouTube-first** research workflow — *topic + market + recent date range* → legitimate content discovery → inspectable references/evidence → recurring patterns → opportunities → (later) ideas and content briefs. Every recommendation must trace backward to evidence.
- **What Trendora explicitly is NOT:** an enterprise social-management suite, an omnichannel public firehose, a scraper, an LLM-chat product where the model is the source of truth, or a forecasting dashboard as the main interface.

---

## 2. North-Star User Workflow

`CURRENT:` the repository has no research concept yet. The workflow below is the target.

`DECISION:` the primary end-to-end flow is:

```text
research request
    ↓
structured ResearchQuery
    ↓
source capability resolution
    ↓
content/reference retrieval        (YouTube-first; capability-aware)
    ↓
evidence normalization             (into existing content_items + references)
    ↓
research result
    ↓
pattern analysis                  (recurring structure/topics/claims)
    ↓
opportunity discovery             (content gaps)
    ↓
evidence-backed ideas
    ↓
content brief
    ↓
report / workspace
```

Terminology maps onto existing repository concepts where possible:

| Workflow step | Repository anchor |
| --- | --- |
| Sources / platforms | `sources` registry ([02](02_DATABASE_SCHEMA.md)) |
| Markets, topics | `markets`, `topics`, `content_item_topics` |
| Content | `content_items` (videos/stories/questions/repositories) |
| Measured observations | `metric_snapshots` via M5 |
| Evidence for recommendations | future research references (Section 10) |

`OPEN:` exact object names for `research_runs`, references, patterns, opportunities, ideas, briefs — see Section 20.

---

## 3. V1 Persona / Job To Be Done

`DECISION:` the primary V1 user is a **social media specialist, content strategist, or small marketing/content team** operating in SEA markets (ID, TH, MY, SG, VN, PH — the seeded `markets`).

Core job to be done:

> “Help me decide what content to create using real, inspectable evidence rather than generic AI advice.”

The user is not a data scientist, does not want raw snapshots, and does not want unsourced recommendations. They want: a question in, a curated set of references, the patterns those references actually show, and opportunities with visible evidence.

`DECISION:` V1 does **not** target enterprise social management, campaign ad buying, publishing, or multi-team workspaces.

---

## 4. V1 Scope

`DECISION:` the first useful vertical slice is:

```text
topic + market + recent date range
    ↓
legitimate YouTube-first content research
    ↓
reference results (content_items + URLs + collected metadata)
    ↓
evidence-backed patterns
    ↓
opportunities
    ↓
ideas / briefs later
```

| Bucket | Includes |
| --- | --- |
| **V1** | ResearchQuery contract; capability resolution; YouTube-first retrieval into `content_items`; evidence/reference collection; deterministic pattern extraction (e.g., topic/claim/format frequencies over returned references); opportunity flags with evidence back-references; provenance invariants (Section 14). |
| **Next** | Ideas and briefs (AI-assisted, labeled); other sources; workspace UI. |
| **Later** | Alerts/recurring research; competitor/watchlist tracking; richer media analysis where policy permits. |
| **Explicitly out of scope (forever unless re-decided)** | Scraping; TikTok/Instagram/Facebook public firehose; pretending capabilities exist; LLM-as-truth; forecasting as the primary surface. |

`RATIONALE:` YouTube is the only source with a documented legitimate broad public-discovery path already ingested ([03](03_DATA_SOURCES.md)); starting anywhere else would force unsupported capability claims.

---

## 5. Existing Architecture Reuse

| M1–M11 component | Reuse in the new product |
| --- | --- |
| `sources`, `markets`, `topics` | Remain the canonical registries; capability model attaches to `sources` (Section 9). |
| `publishers`, `content_items` | Become **central**: `content_items` are the substrate every evidence/reference anchors to; `publishers` support watchlist/creator filters. |
| `metric_snapshots` + M5 | Remain the **only** metric-analytics path. Reach/engagement signals (views, scores, stars) continue to flow through M5. |
| M6 / M6C / M7 (forecasting/diagnostics) | Optional **predictive signal** inside research (Section 17). No rewrite, no deletion. |
| M10 product layer | The thin `product → service → repository` pattern is the template for future research/evidence services. |
| M11 FastAPI adapter | The pattern for exposing future read models. The existing forecast endpoint stays as a signal endpoint. |
| Connectors (YouTube/HN/SE/GitHub) | Keep. YouTube is the V1 research source; HN/SE/GitHub remain supporting topic/technology signals, not pretended social networks. |
| `retention_policies` | Keep and reuse for research-collected content (Section 21). |

`DECISION:` **do not rewrite** M1–M11 code. It is the foundation; the new product layers on top.

---

## 6. Content-Centric Read Model

`CURRENT:` M5 (`AnalyticsRepository` / `AnalyticsService`) is observation-oriented: it answers “what snapshots exist for (source, metric, subject, window)” ([05](05_ANALYTICS_SPEC.md)). It is not oriented around content discovery (topic → content_items → references).

`PROPOSAL:` add a separate **content research read/service layer** above `content_items` (not yet built). Responsibilities:
- resolve a `ResearchQuery` to content items (topic, market, `published_at` range, publisher/creator, content type, URL);
- expose references (content + collected metadata + original URL);
- never re-aggregate `metric_snapshots` — if a research result needs measured metrics, it must get them through M5 (existing `AggregateSummary` / `MetricSeries`), preserving the single metric path.

Boundaries:
- `M5` = metric analytics. `ContentResearch` = content discovery/reference/evidence. They cooperate; they do not merge.
- A content research layer must **not** create an uncontrolled second metric-SQL path. If it needs numbers, it calls M5.

`DECISION:` keep the generic normalized `content_items` abstraction. **Do not create** platform-specific tables (`youtube_videos`, `instagram_posts`, `tiktok_posts`) — there is no repository evidence this is required, and it would fragment the evidence substrate.

---

## 7. ResearchQuery Contract

`PROPOSAL:` the conceptual V1 request contract.

| Field | Class | Notes |
| --- | --- | --- |
| `topic` / query text | **required** | free text; topics registry may be applied later |
| `market` | required for V1 | one of seeded SEA `markets` |
| `platforms` / sources | required | V1: `youtube` only; the contract allows more later |
| `date_from`, `date_to` | required | research window; V1 = recent range |
| creator / watchlist filters | optional | constrained by `publishers` watchlist capability |
| `content_type` | optional | e.g., `video` |
| `result_limit` | optional | bound on references returned |
| sort / ranking preference | optional | e.g., relevance, recency; ranking methodology OPEN |
| `analysis_basis` | derived | from source capability (Section 12) |

`DECISION:` a natural-language request may later be parsed into this contract by an LLM, but **the LLM never retrieves content or metrics**. The parsed contract is executed by deterministic code.

---

## 8. ResearchRun Lifecycle

`PROPOSAL:` a research run is the unit of work. States justified by the future workflow:

```text
requested → validating → resolving_capabilities → collecting → normalizing
→ analyzing → completed
```

plus terminal degradation states: `partially_completed` (some sources succeeded, some failed/degraded) and `failed`.

Clarifications:
- **V1 synchronous:** a single-source (YouTube) run can complete synchronously inside a request; no queue needed yet.
- **Future asynchronous/background:** only when multi-source runs or long media analysis justify it (Section 19).
- **Per-source success/failure:** each source reports its own outcome (Section 9), so one unavailable source degrades the run rather than failing it wholesale.

`OPEN:` persistence of runs (Section 20, item B).

---

## 9. Platform Capability Model

`PROPOSAL:` a capability registry attached to `sources`, so the product never claims capabilities it does not have. A research run reports per source, e.g.:

```text
YouTube         searched (public_search)
Instagram       watchlist-only / not configured
TikTok          unavailable for organic public discovery
Facebook        not configured
Google Trends   not configured
```

Capability vocabulary:

| Capability | Meaning |
| --- | --- |
| `public_search` | legitimate public content search available |
| `creator_watchlist` | track a fixed set of creators/channels |
| `content_lookup` | fetch a known content item by id/URL |
| `hashtag_discovery` | hashtag/tag-based discovery |
| `public_metrics` | read public engagement/statistics |
| `owned_account_metrics` | metrics only for accounts the user authorizes |
| `regional_discovery` | region/market-scoped discovery |
| `content_text_available` | title/description/caption text available |
| `media_analysis_available` | media (video/image) accessible for analysis |
| `retention_constraints` | source policy restricts storage (e.g., YouTube 30-day) |
| `authorization_required` | access gated by OAuth/permissions/app review |

Per-source record fields: capability set, access status (`available` / `degraded` / `unavailable` / `not_configured`), authorization requirement, coverage note, policy/retention note, failure/degradation behavior.

`DECISION:` capability resolution runs **before** retrieval and is deterministic. No unsupported promise is ever emitted.

---

## 10. Evidence Contract

`PROPOSAL:` a conceptual evidence/reference item. Do not commit a DB schema yet (Section 20).

An evidence item must be able to answer:

| Question | Field concept |
| --- | --- |
| Which source produced this? | `source_code` |
| Which content item does this refer to? | `content_item_id` |
| What original URL supports it? | `content_item.url` (existing column) |
| When was it collected? | `collected_at` / snapshot timestamps |
| What observation/data supports the conclusion? | reference to `metric_snapshots` via M5, or stored source metadata/text |
| What analysis basis was available? | `analysis_basis` (Section 12) |
| Which ResearchRun produced it? | `research_run_id` |
| What claim(s) rely on it? | reverse link from claims (Section 11, Section 14) |

`DECISION:` evidence is the backbone of the provenance invariant (Section 14). Everything downstream points back to it.

---

## 11. Claim / Assertion Types

`DECISION:` four structured claim categories, with required evidence:

| Claim type | Meaning | Required evidence |
| --- | --- | --- |
| `FACT` | directly supported by source data | direct reference to a `content_item`/`metric_snapshot`/source field |
| `OBSERVATION` | deterministically derived, or a documented structural observation | the deterministic code path that produced it (or explicit “structural observation” note) |
| `AI_INTERPRETATION` | model interpretation of structured evidence | cited evidence item(s) + model/provider + `analysis_basis`; **clearly labeled** as interpretation |
| `RECOMMENDATION` | suggested action | trace to ≥1 opportunity/observation/evidence item |

`DECISION:` unsupported AI inference is **never** labeled `FACT`. `FACT` requires direct source evidence. This is the mechanism that stops the LLM from silently converting interpretation into measured fact.

---

## 12. Analysis Basis / Media Boundary

`PROPOSAL:` every analysis records what the system actually had access to:

- `metadata` (title, description, published_at, duration)
- `source-provided_text` (e.g., YouTube title/description; HN text; SE body where stored)
- `authorized_captions_transcript`
- `user_supplied_text`
- `user_supplied_media`
- `platform_permitted_media`

`DECISION:` the system **must not claim** visual-pacing, spoken-hook, scene, or body-language analysis unless the recorded `analysis_basis` includes the appropriate media/text access. Capability `media_analysis_available` gates this.

---

## 13. Content Intelligence Pipeline

`PROPOSAL:` conceptual transformations:

```text
ContentItem → Evidence → Analysis → Pattern → Opportunity
```

Stage nature:

| Stage | Nature |
| --- | --- |
| ContentItem → Evidence | **deterministic** (collection + normalization) |
| Evidence → Analysis | **deterministic + heuristic** (structure, topic/claim extraction on available text) |
| Analysis → Pattern | **deterministic aggregation** over analyzed items; **AI-assisted** only for interpretation of the aggregated evidence, labeled as such |
| Pattern → Opportunity | **heuristic scoring** + evidence back-links; AI may suggest candidates, never fabricate |

`DECISION:` no vague “AI agent” architecture. Each stage names its method class (deterministic/heuristic/AI-assisted) and its provenance output.

---

## 14. Opportunity → Idea → Brief Provenance

`DECISION:` the following lineage is a **core product invariant**:

```text
Brief → Idea → Opportunity → Pattern → Evidence → ContentItem → original URL
```

Every downstream object must be able to point backward to the object(s) that produced it. At minimum each object carries the id of its upstream source object(s); the chain ends at a real `content_item.url`.

`RATIONALE:` this is the mechanism that makes “every meaningful recommendation traceable to evidence” true by construction, not by promise.

---

## 15. AI Boundary

`CURRENT:` [07_AI_ORCHESTRATION.md](07_AI_ORCHESTRATION.md) already constrains the AI layer (structured inputs only; no unrestricted SQL; $0 no-op default).

`DECISION:` the LLM **may** later:
- parse natural language into a `ResearchQuery`,
- summarize structured evidence,
- classify content structure (from the recorded `analysis_basis`),
- suggest pattern interpretations (labeled `AI_INTERPRETATION`),
- identify candidate gaps/opportunities (labeled),
- generate ideas,
- draft briefs.

The LLM **must not**:
- invent metrics, source URLs, creators, or platform coverage,
- fabricate capability availability,
- bypass official access restrictions,
- silently modify numeric evidence,
- present unsupported inference as fact (`FACT`),
- write to canonical source facts without validation.

`DECISION:` provider-agnostic design: a replaceable `AIProvider` interface (no-op default) consuming **structured contracts** — consistent with [01](01_ARCHITECTURE.md) and [07](07_AI_ORCHESTRATION.md). No provider is chosen in M12.

---

## 16. AI Evaluation Strategy

`PROPOSAL:` future automated checks (not implemented in M12):

- output schema validity,
- every cited evidence reference exists,
- every cited URL maps to a known `content_item`,
- `FACT` claims contain direct source evidence,
- `AI_INTERPRETATION` / `RECOMMENDATION` labels preserved,
- unsupported-claim detection (a claim with no evidence back-link),
- provider/model recorded,
- `analysis_basis` recorded,
- deterministic fallback behavior when the AI provider is a no-op or fails.

`DECISION:` these become acceptance criteria for any AI-assisted milestone, reusing the existing test philosophy in [10_TESTING_EVALUATION.md](10_TESTING_EVALUATION.md).

---

## 17. Forecasting's New Role

`DECISION:` forecasting (M6–M11) is repositioned as **one optional predictive signal** within Trendora intelligence, not the primary surface.

| Stage | What exists | Role |
| --- | --- | --- |
| Descriptive | M5 analytics (current levels, aggregates) | What is happening |
| Diagnostic | M7 diagnostics, M5 deltas/cadence | Why it looks this way (evidence) |
| Predictive | M6/M6C naive-vs-challenger; M10 product; M11 API | Optional: what is likely next for a tracked metric |
| Decision | future research/opportunity layer | What to do, backed by evidence |

`DECISION:` keep the forecast product and API. A research run may attach a forecast signal to a tracked subject (e.g., repository star growth) where it is genuinely useful, clearly labeled `origin=trendora_forecast`. Forecasting does not block, and is not required by, the V1 research slice.

---

## 18. UI Product Direction

`DECISION:` eventual primary surfaces:

- **Research** (start a run: question/topic → results)
- **References** (evidence/backing content with URLs)
- **Opportunities** (gaps + evidence)
- **Ideas**
- **Briefs**
- **Reports**
- **Signals / Forecasts** (the M6–M11 capability as a secondary signal surface)

The main interface should **begin with the research/action workflow**, not a wall of charts ([08_DASHBOARD_SPEC.md](08_DASHBOARD_SPEC.md) is superseded in priority, not deleted).

`DECISION:` the old dedicated Streamlit forecast dashboard is **deferred / retained only as an internal or dev tool**. It is **not** the primary product surface. No dashboard decision here changes the “Streamlit, not React” constraint ([08](08_DASHBOARD_SPEC.md)) — that constraint concerns framework choice for the future workspace UI, which is still OPEN (Section 23).

---

## 19. Deployment Direction

`PROPOSAL:` long-term split (nothing implemented in M12):

| Layer | Direction |
| --- | --- |
| Web frontend/application surface | Vercel (frontend) |
| Python API/core | FastAPI (already exists as the adapter pattern) |
| Canonical persisted data | Supabase/PostgreSQL (current) |
| Background worker/queue | **only when** research jobs justify it (multi-source or long media analysis); do not choose infrastructure prematurely |
| AI provider | replaceable external dependency (no-op default) |

`DECISION:` V1 research runs are synchronous. No queue/worker/Celery/Redis in V1.

---

## 20. Data Model Impact

`CURRENT:` schema is generic and source-agnostic: `sources`, `markets`, `topics`, `retention_policies`, `publishers`, `content_items`, `content_item_topics`, `metric_snapshots` ([02](02_DATABASE_SCHEMA.md), `src/trendora/models/`). No research/evidence/pattern/idea/brief tables exist.

### A. Current entities sufficient for:
- source registry + capabilities (extend `sources` metadata or a new capability table later),
- market/topic taxonomy,
- publishers and content items (the evidence substrate),
- append-only measured observations (M5),
- retention hooks.

### B. Conceptual entities eventually needed (names provisional — final names must fit the schema):
- `research_runs` (lifecycle, Section 8),
- research references / evidence (Section 10),
- `content_analysis` (per-item analysis with `analysis_basis`),
- `patterns`,
- `opportunities`,
- `ideas`,
- `briefs`.

### C. Additions that must **not** be created yet:
- any of the above tables,
- platform-specific tables (`youtube_videos`, etc.),
- forecast/analysis/persistence tables beyond what M6–M11 already decided (none exist).

`DECISION:` M12 creates **no** tables. The exact table names, keys, and lineage columns are a later schema milestone decision informed by Section 14 invariants.

---

## 21. Policy / Retention Boundaries

`CURRENT:` documented in [03_DATA_SOURCES.md](03_DATA_SOURCES.md), [04](04_INGESTION_PIPELINE.md), [05](05_ANALYTICS_SPEC.md):
- YouTube non-authorized statistics/metadata carry `retention_policies` (30-day default; amendment path for longer storage from 2026-06-01). `retain_until` exists on publishers, content_items, and metric_snapshots.
- Prohibited scraping; no fake stand-ins for official metrics; derived metrics on YouTube data require policy review.
- Capability-dependent access (Instagram professional/authorized, TikTok research restrictions, Facebook permissions).

`DECISION:` research-collected content inherits these boundaries. The capability model (Section 9) exposes retention/c authorization constraints per source. Source facts are distinguished from derived and AI output (Sections 10–11).

`OPEN:` any current policy detail that changed since [03](03_DATA_SOURCES.md) was researched (2026-08-18) requires re-verification against live official documentation before a source milestone.

---

## 22. Revised Roadmap

`DECISION:` the old “forecast dashboard next” assumption is replaced by research-aligned vertical slices. Milestones are sized as vertical slices; each must state goal, deliverable, dependencies, out-of-scope, readiness criterion.

| Milestone | Goal | Concrete deliverable | Depends on | Out of scope | Readiness |
| --- | --- | --- | --- | --- | --- |
| **M13 Research Core** | capability + query contracts | ResearchQuery contract, capability registry, research-run lifecycle scaffolding (docs + minimal code) | M12 | retrieval, UI, AI, schema | contracts exercised by unit tests |
| **M14 YouTube-first vertical slice** | first real research | ResearchRun that resolves capabilities, retrieves YouTube content into `content_items`, returns references | M13 | other sources, media analysis | end-to-end run with seeded YouTube data |
| **M15 Research workspace UI** | usable surface | Research UI (query → results → references) | M14 | patterns/opportunities UI | user can run a research query and inspect references |
| **M16 Content intelligence** | analysis + patterns | deterministic per-item analysis + pattern aggregation over references | M14 | AI interpretation | patterns have evidence back-links |
| **M17 Opportunities** | gaps | opportunity candidates with evidence back-links + heuristic ranking | M16 | idea generation | opportunities traceable to evidence |
| **M18 AI grounded interpretation** | labeled AI | `AI_INTERPRETATION` over structured evidence with provider/basis recorded | M16 | unlabeled generation | Section 16 checks pass |
| **M19 Ideas** | idea generation | evidence-backed ideas (AI-labeled) | M17, M18 | publishing | ideas trace to opportunities |
| **M20 Briefs** | deliverable | content brief with provenance chain | M19 | distribution | brief → … → URL chain intact |
| **M21 Reports** | summary output | report/workspace export | M20 | — | — |
| **M22 Additional sources/signals** | broaden | second legitimate source per capability model | M14 | — | capabilities truthful |
| **M23 Competitor/watchlists** | tracking | creator/repo watchlists + tracked signals (can use M10 forecast) | M22 | — | — |
| **M24 Alerts / recurring research** | automation | recurring runs + alerts | M22/M23 | — | — |

`OPEN:` exact milestone ordering beyond M15 is provisional and will be re-derived from build progress. Milestone numbers here are proposals, not commitments.

---

## 23. Open Decisions

| Decision | Impact | Class |
| --- | --- | --- |
| Exact Instagram API access available to Trendora | scope of a future Instagram source | **BLOCKING LATER** |
| TikTok legitimate commercial/public research path | TikTok capability claim | **BLOCKING LATER** |
| Google Trends API access | complementary market-interest signal | **BLOCKING LATER** |
| Final UI framework (Streamlit vs web frontend on Vercel) | M15 surface | **BLOCKING LATER** |
| Async job infrastructure (worker/queue) | multi-source/long runs | **BLOCKING LATER** |
| Authentication provider | any non-local deployment (already OPEN in [09](09_API_SPEC.md)) | **BLOCKING LATER** |
| Team/workspace model | reports/workspace | **BLOCKING LATER** |
| AI provider | M18 interpretation | **BLOCKING LATER** |
| Persistence model for AI output | briefs/ideas storage | **BLOCKING LATER** |
| Ranking methodology for research results | sort/ranking in ResearchQuery | **NON-BLOCKING** for M13/M14 |
| Policy approval for derived metrics on YouTube data | signals over YouTube fields (already OPEN from M8/M9) | **BLOCKING LATER** |
| Exact research/evidence/pattern/opportunity/idea/brief table design | schema milestone | **NON-BLOCKING** for M13 |

Nothing here is **BLOCKING NOW** for M13 (Research Core is contracts + minimal code, no external access required).

---

## 24. Next Implementation Slice

`DECISION:` the next implementation milestone is **M13 — Research Core**.

- **Goal:** establish the capability and query contracts so every later research slice has a truthful foundation.
- **Concrete deliverable:** `ResearchQuery` contract; platform capability vocabulary + per-source resolution (truthful `available/degraded/unavailable/not_configured`); research-run lifecycle scaffolding (synchronous, single source); unit tests proving capabilities cannot be overclaimed.
- **Dependencies:** M12 (this document). No new connectors, no UI, no AI, no schema, no new dependencies.
- **Out of scope:** retrieval against live sources, media analysis, patterns/opportunities, UI, AI, persistence tables.
- **Readiness criterion:** a ResearchQuery for a YouTube topic resolves capabilities truthfully and produces a valid (empty or seeded) run result, with tests proving unsupported capability claims are impossible.

`RATIONALE:` M13 is the smallest slice that makes M14 (YouTube-first retrieval) safe, because retrieval must not run before capability truth is encoded. It reuses the established thin-service pattern (M10/M11) and requires no external access or policy sign-off.

`OPEN:` if the product owner prefers a working first retrieval over contracts first, M14 could be pulled ahead of M13 — but that risks building retrieval before capability truth exists; M13-first is recommended.

---

## Non-goals (unchanged by re-baseline)

M12 creates no migrations, schema, connectors, API routes, frontend, Streamlit/Next.js/React, deployment, queues/workers, LLM integration, embeddings, vector DB, ideation, reports, auth, caching, scheduling, publishing, scraping, or advanced forecasting. No dependencies were added. No test changed.
