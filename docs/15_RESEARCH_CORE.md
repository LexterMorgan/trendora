# 15 — Research Core (M13)

## Status

**M13 (this document + implementation):** the first implementation milestone under Trendora's evidence-backed content intelligence direction. It establishes the smallest trustworthy domain contracts for research: a typed `ResearchQuery`, a platform capability vocabulary with static source declarations, deterministic capability/coverage resolution, and a synchronous in-memory `ResearchRun` lifecycle.

**What M13 does NOT do:** no external content retrieval, no database persistence, no schema, no connectors, no API routes, no LLM, no evidence/pattern/opportunity/idea/brief models.

**Implementations:** `src/trendora/research/` (models, capabilities, service, exceptions) with 38 focused unit tests. Full suite: **392 passing** (354 baseline + 38).

---

## 1. Purpose

M13 answers deterministically:

1. What did the user request? (`ResearchQuery`)
2. Which source capabilities are required for that request?
3. What does each source declare it can actually support? (`SourceCapabilities`)
4. Which requested sources are available / unavailable / conditional?
5. Why is a requested capability unavailable? (`CoverageReason`)
6. What is the current state of the research run? (`ResearchRunStatus`)
7. Can an unsupported source capability accidentally be represented as successful?

The answer to #7 is **NO**, enforced by code and tests (Section 9).

---

## 2. ResearchQuery contract

Frozen, validated-at-construction dataclass (`src/trendora/research/models.py`):

| Field | Class | Semantics |
| --- | --- | --- |
| `topic` | required | trimmed free text; must not be blank |
| `market` | required | normalized to uppercase; must be a canonical SEA market (`ID`, `TH`, `MY`, `SG`, `VN`, `PH`) |
| `date_from` / `date_to` | required | Python `date` objects; `date_from <= date_to` |
| `source_codes` | optional (default `("youtube",)`) | lowercased, trimmed, deduplicated order-preserving; must be non-empty |
| `result_limit` | optional (default `50`) | `1 <= limit <= 100` |

Normalization and validation run in `__post_init__`, so an invalid query cannot be constructed. `validate_research_query()` is exported for explicit reuse.

**Deliberate exclusions:** no sentiment, demographics, campaign objectives, personas, embeddings, ranking weights, LLM prompts, model selection, content generation, or team/workspace fields. V1 research is intentionally narrow.

**Date semantics:** a research window is a calendar-day range (`date`, not `datetime`). "Last 30 days" natural language is **not** interpreted here; M13 receives resolved structured dates. Platform retrieval (M14) converts the day range to timestamps at its boundary.

**Markets:** validated against the in-memory canonical set derived from `reference.MARKET_IDS` — the same deterministic seed module that populates the `markets` table. M13 therefore reuses the canonical market taxonomy; it does not maintain a second one. M13 stays DB-free; authoritative DB validation, if ever needed, would live in a later layer without changing `ResearchQuery`.

**Default sources:** omitting `source_codes` defaults to `("youtube",)` — the V1 YouTube-first direction. This is explicit and tested, not an implicit "all sources" behavior.

---

## 3. Platform capability vocabulary

`PlatformCapability` (StrEnum) — what a platform CAN support. Capability is distinct from credentials, authorization state, temporary API errors, policy constraints, and whether a query requested it.

- `public_search`
- `creator_watchlist`
- `content_lookup`
- `hashtag_discovery`
- `public_metrics`
- `owned_account_metrics`
- `regional_discovery`
- `content_text_available`
- `media_analysis_available`

Only the minimum vocabulary needed for the research architecture and upcoming YouTube-first retrieval is included. Nothing more is invented.

---

## 4. Source capability declarations

`SourceCapabilities` (frozen dataclass):

| Field | Meaning |
| --- | --- |
| `source_code` | canonical source code (reuses `reference.SOURCE_IDS`; no pseudo-sources like `youtube2`) |
| `supported` | capabilities available today without authorization |
| `conditional` | capabilities available only under a condition (e.g. channel-owner OAuth); must not overlap `supported` |
| `retention_note` | policy/retention marker (e.g. YouTube 30-day rule) |

**Authorization is capability-specific, not source-wide.** There is intentionally **no** `requires_authorization` boolean on a source. A future mixed-access source (public discovery without user authorization, owned-account metrics only with authorization) is represented by putting the authorized capability in `conditional` while public capabilities stay in `supported`. Authorization is the meaning of `conditional`; coverage reports it per capability as `conditional / authorization_required`.

Declarations are **static and in-memory** (`default_declarations()` in `capabilities.py`):

- `youtube`: `public_search`, `creator_watchlist`, `content_lookup`, `regional_discovery`, `public_metrics`, `content_text_available`; conditional `owned_account_metrics`; YouTube retention note.
- `hacker_news`: `content_lookup`, `creator_watchlist`, `public_metrics`, `content_text_available` (no `public_search` — the HN API has no search endpoint).
- `stack_exchange`: `public_search`, `content_lookup`, `public_metrics`, `content_text_available`.
- `github`: `content_lookup`, `creator_watchlist`, `public_metrics` (no `public_search`).
- `wikimedia` / `gdelt`: **no declaration** — known sources with no research capability claim; any research capability requested against them resolves to `capability_not_supported`.

A future connector can register its own declaration without modifying `ResearchQuery`. No DB table, no API probes, no secrets, no network calls.

---

## 5. Coverage resolution

`ResearchCapabilityResolver` (in `service.py`) resolves a `ResearchQuery` against declarations:

| Condition | Status | Reason |
| --- | --- | --- |
| source code not in the canonical registry | `unavailable` | `source_unknown` |
| canonical source with no declaration | `unavailable` | `capability_not_supported` |
| capability in `supported` | `available` | — |
| capability in `conditional` | `conditional` | `authorization_required` |
| capability in neither set | `unavailable` | `capability_not_supported` |

`SourceCoverage` records `source_code`, `capability`, `status`, `reason` (machine-readable). Ordering follows the query's deduplicated source order (deterministic).

The required capability for V1 queries is `public_search` (`required_capabilities(query)` — a small explicit mapping, the extension point for future query shapes).

### Completeness

`CoverageCompleteness` (docs/14 section 20), coverage truth not a quality score:

- `complete` — every requested (source, capability) pair is available.
- `partial` — at least one available and at least one unavailable/conditional.
- `none` — no requested pair is available.

### Core invariant

> TRENDORA MUST NEVER REPORT A SOURCE AS AVAILABLE/SEARCHED FOR A CAPABILITY THE SOURCE DECLARATION DOES NOT SUPPORT.

Enforced by construction (AVAILABLE is only emitted when the capability is in `supported`) and proven by tests (Section 9).

---

## 6. ResearchRun lifecycle

`ResearchRun` is a synchronous in-memory domain object. M13 performs **no collection**; `resolve_capabilities()` only resolves coverage and then reports whether the run is eligible to be executed later.

```text
requested
   ↓ resolve_capabilities
resolving_capabilities
   ↓ resolution result
ready | blocked
```

- `ready` — at least one requested source can satisfy the required capability; the run is **eligible for future collection**.
- `blocked` — no requested source can satisfy the required capability (coverage completeness is `none`).

**READY is not completed.** M13 has no collection/completion states; capability resolution success is not research execution completion. M14 may later extend the lifecycle from `ready` into states such as collecting/normalizing/completed.

Explicit transitions only (`_TRANSITIONS` map); an invalid transition (e.g. resolving twice after resolution) raises `ResearchStateError`. No timestamps, no UUIDs, no persistence, no queue, no background work — none of it serves an M13 purpose.

**Execution status and coverage completeness are separate concepts** (docs/14 section 8):

| Example | Run status | Coverage completeness |
| --- | --- | --- |
| YouTube available only | `ready` | `complete` |
| YouTube available + Instagram unavailable | `ready` | `partial` |
| Instagram + TikTok unavailable | `blocked` | `none` |

One unavailable source never makes a run `blocked`; only zero available sources do. A run is never reported `completed` by capability resolution.

---

## 7. Examples

Request `AI education`, Singapore, last 30 days, sources YouTube + Instagram + TikTok:

```text
ResearchQuery(topic="AI education", market="SG", date_from=..., date_to=...,
              source_codes=("youtube", "instagram", "tiktok"))

youtube      public_search  available
instagram    public_search  unavailable  reason=source_unknown
tiktok       public_search  unavailable  reason=source_unknown
completeness: partial
run status:   ready   (eligible for collection via YouTube)
```

Request `AI education`, Singapore, sources YouTube only:

```text
youtube      public_search  available
completeness: complete
run status:   ready
```

Request `AI education`, Singapore, sources Instagram + TikTok only:

```text
instagram    public_search  unavailable  reason=source_unknown
tiktok       public_search  unavailable  reason=source_unknown
completeness: none
run status:   blocked
```

---

## 8. Invariants proven by tests

- A source can never be reported available for a capability absent from its declaration.
- The resolver cannot silently substitute another capability (e.g. HN `content_lookup` cannot satisfy `public_search`).
- Unknown sources (`instagram`, `tiktok`, `facebook`, typos) can never become available.
- Known-but-undeclared sources (`wikimedia`, `gdelt`) resolve to `capability_not_supported`, never available.
- Partial coverage is never mislabeled complete; all-unavailable is never partial or complete.
- Capability resolution cannot claim that content was retrieved (the coverage result carries no collection artifact; the run can only reach `ready`, never `completed`).
- A single unavailable source does not block the run; only zero available sources do (`blocked`).
- Authorization is capability-specific: a capability in `conditional` resolves to `conditional / authorization_required` without affecting the source's other capabilities.

---

## 9. Non-goals

- No retrieval, no connectors, no network calls.
- No DB schema, no migrations, no persistence (no `research_runs`/capabilities/evidence tables).
- No API routes; the M11 forecast API is unchanged.
- No LLM, agents, prompts, embeddings, vector stores, RAG.
- No evidence/pattern/opportunity/idea/brief models — those follow real retrieval in/after M14.
- No new dependencies (stdlib + existing project packages only).

---

## 10. Readiness for M14

M14 (YouTube-first research retrieval) can now:
- construct a validated `ResearchQuery`,
- resolve YouTube `public_search` coverage truthfully,
- detect and represent unavailable/conditional sources without faking omnichannel parity,
- run the synchronous lifecycle.

Retrieval will fail at M14's boundary if a source is not `available`; capability truth is already enforced.

---

## 11. Files

- `src/trendora/research/__init__.py`
- `src/trendora/research/models.py` — enums, `ResearchQuery`, `SourceCapabilities`, coverage types, `ResearchRun`
- `src/trendora/research/capabilities.py` — vocabulary usage, static declarations, `required_capabilities`
- `src/trendora/research/service.py` — `ResearchCapabilityResolver`
- `src/trendora/research/exceptions.py`
- `tests/unit/test_research_core.py`
