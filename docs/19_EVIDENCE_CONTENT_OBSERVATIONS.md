# 19 — Evidence & Deterministic Content Observations (M17)

## Status

**M17 (this document + implementation):** Trendora's first content-intelligence foundation — a deterministic per-reference evidence/observation layer over M14 `ResearchReference`. No AI, no cross-reference patterns, no gaps, no opportunities, no recommendations.

**Flow added:**

```text
ResearchReference
  → immutable source Evidence Facts (FACT)
  → deterministic per-reference Content Observations (OBSERVATION)
```

Backend baseline: **484 passing** (455 + 29 new). No DB, API, connector, M5, or frontend changes.

**Core invariant:** Trendora must never claim to have analyzed information it did not actually possess.

---

## 1. Purpose

Before higher-level reasoning, Trendora needs an explicit evidence contract: what does the system actually know from a retrieved reference, which fields were available for analysis, and which deterministic statements are safe. M17 makes the boundaries structurally difficult to violate later.

Allowed:

```text
FACT:          view_count = 182433
OBSERVATION:   title_has_numeral = true
```

Not allowed in M17:

```text
"listicle-style hook"        (interpretation)
"the hook is strong"         (opening not analyzed)
"performed well because…"    (causal interpretation)
```

---

## 2. Package boundary

Implemented in `src/trendora/research/evidence.py` — inside the existing research package, because it operates directly on `ResearchReference` and avoids a new package tree. `research/__init__.py` re-exports the public contracts. If M18 pattern aggregation grows, it can move to a dedicated package then.

---

## 3. Claim types

`ClaimType` (StrEnum): `fact`, `observation`. Only these two exist. `ai_interpretation` / `recommendation` are deliberately absent (later milestones).

---

## 4. Reference identity / provenance

`ReferenceId` — immutable `(source_code, content_external_id)`. Every fact and observation carries it; the original URL stays on the reference/analysis. No DB/UUID/random IDs.

---

## 5. Evidence field vocabulary

`EvidenceField` (StrEnum):

`url`, `collected_at`, `title`, `description`, `published_at`, `channel_title`, `market_context`, `market_basis`, `source_rank`, `view_count`, `like_count`, `comment_count`.

Identity fields (`source_code`, `content_external_id`) live on `ReferenceId`, not here. `collected_at` is **temporal provenance**: the timezone-aware time Trendora retrieved the source data, preserved exactly from `ResearchReference.collected_at` (no generated analysis timestamp). No `transcript`, `spoken_hook`, `visual_hook`, `scene`, `sentiment`, `creator_country`, or `audience_demographic` — M14 does not provide them.

---

## 6. Analysis basis

`AnalysisBasis` (StrEnum):

- `title` — source-provided YouTube title text
- `description` — source-provided YouTube description metadata
- `source_metadata` — channel, published time, source rank, market context/basis, URL
- `raw_metrics` — view_count / like_count / comment_count

No `transcript`/`audio`/`video`/`image`/`caption`. Basis records what Trendora actually possessed.

---

## 7. Evidence fact

`EvidenceFact` — immutable `(reference, field, value, claim_type=FACT)`. Value union: `str | int | datetime | None`. Integer metrics stay integers; missing stays `None`; zero stays zero. No dict-based evidence bag. `claim_type` is **structural** (`init=False`): an `EvidenceFact` cannot be constructed as anything but FACT.

---

## 8. Content observation

`ContentObservation` — immutable `(reference, observation_type, value, evidence_fields, analysis_basis, claim_type=OBSERVATION)`. Value: `bool | int`. No free-form rationale, no confidence scores, no generated explanations. `claim_type` is **structural** (`init=False`): a `ContentObservation` cannot be constructed as anything but OBSERVATION.

`ReferenceAnalysis` — immutable per-reference result: `reference`, `analysis_basis` (bases actually used), `facts`, `observations`.

---

## 9. Observation vocabulary and exact detection rules

All deterministic, stdlib only (no NLP/LLM):

| Observation | Rule |
| --- | --- |
| `TITLE_CHARACTER_COUNT` | `len(title)`; `None` title → 0 |
| `TITLE_HAS_NUMERAL` | any title char where `char.isdigit()` (Python digit detection, covers Unicode digits) |
| `TITLE_HAS_QUESTION_MARK` | contains `"?"` or full-width `"？"` |
| `DESCRIPTION_PRESENT` | description exists and is non-blank after trim |
| `DESCRIPTION_CHARACTER_COUNT` | `len(description)` when present, else 0 |
| `DESCRIPTION_HAS_URL` | regex `https?://` (case-insensitive); bare `www.` is **not** detected |

Character counts are used (not whitespace word counts) because languages like Thai do not tokenize like English.

---

## 10. FACT vs OBSERVATION boundary

- `extract_evidence(reference)` → `tuple[EvidenceFact, ...]` — values directly present in the reference, deterministic fixed order.
- `analyze_reference(reference)` → `ReferenceAnalysis` — facts + derived structural observations.
- `analyze_references(references)` → `tuple[ReferenceAnalysis, ...]` — independent per-reference analysis; **no aggregation**.

Facts are source values; observations are deterministic functions of specific facts; neither is AI interpretation.

---

## 11. Provenance

Every observation cites ≥1 `EvidenceField` and exactly one `AnalysisBasis`. Title observations cite `(TITLE,)` / basis `title`; description observations cite `(DESCRIPTION,)` / basis `description`. No observation can reference another content item (identity is per-reference). Observations without evidence fields are structurally impossible.

---

## 12. Market boundary

`market_context` / `market_basis` are preserved as source facts. `SG` + `youtube_region_availability` still means regional availability/viewability, never creator/publisher/origin country, and never language. No country-origin or language inference exists in the vocabulary.

---

## 13. Description / media boundary

M17 inspects the description only for deterministic structure (present, length, explicit URL). It is source metadata, not transcript, spoken content, content body, summary, or scene description. No transcript/video/audio/image claim is structurally possible.

---

## 14. Metrics boundary

Raw `view_count` / `like_count` / `comment_count` are facts only. No engagement rate, views/day, velocity, percentile, benchmark, score, normalized metric, or Trendora Score. No `HIGH_VIEW_COUNT` / `LOW_ENGAGEMENT` / `VIRAL` observations.

---

## 15. Source rank boundary

`source_rank` is preserved as a fact. Meaning: YouTube search position after deterministic deduplication. Not a Trendora rank, performance, relevance, or confidence signal; no observation interprets it.

---

## 16. Immutability

All M17 value objects use `@dataclass(frozen=True, slots=True)`; collections are tuples. Proven by tests.

### Temporal provenance

A fact such as `view_count = 100000` remains traceable to when Trendora retrieved it: `extract_evidence` emits `EvidenceFact(field=COLLECTED_AT, value=<reference.collected_at>)` at a fixed position in the deterministic order, preserving the original timezone-aware timestamp exactly. No current-time call and no generated analysis timestamp exists in M17 analysis.

### Claim-type invariants

`EvidenceFact.claim_type` is always FACT and `ContentObservation.claim_type` is always OBSERVATION — enforced structurally with `field(init=False)`, so incorrect construction (`EvidenceFact(claim_type=OBSERVATION)`, `ContentObservation(claim_type=FACT)`) is a `TypeError`. No inheritance or generic claim hierarchy.

## 17. Determinism

No time, random IDs, model output, network, DB, or global state. Same reference → identical analysis (tested).

---

## 18. Non-goals

No AI/interpretation/recommendation, LLM, pattern aggregation, prevalence, trend detection, gaps, opportunities, ideas, briefs, reports, sentiment, topic classification, semantic similarity, embeddings, vector DB, transcript/media retrieval/download, video/audio/image analysis, extra sources, research API changes, frontend changes, database/persistence/schema, auth, async, derived performance metrics, Trendora Score.

---

## 19. Why patterns are deferred to M18

M17 emits per-reference observations only (e.g. `title_has_numeral = true` three times). Counting how many references share an observation, or saying numbered titles "are common" or "perform better", is cross-reference aggregation — that is M18.

---

## 20. Readiness for M18

M18 can count `TITLE_HAS_NUMERAL = true` across `ReferenceAnalysis[]` without rereading raw YouTube data or inventing semantics.

---

## 21. Files

- `src/trendora/research/evidence.py` — types + `extract_evidence` / `analyze_reference` / `analyze_references`
- `src/trendora/research/__init__.py` — exports
- `tests/unit/test_research_evidence.py` — 29 tests
