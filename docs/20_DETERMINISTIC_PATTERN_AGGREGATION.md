# 20 — Deterministic Pattern Aggregation (M18)

## Status

**M18 (this document + implementation):** aggregates the per-reference M17 observations into deterministic, immutable `PatternAggregate` objects. No AI, no semantic understanding, no content gaps, no opportunities, no performance comparison, no recommendations.

**Flow:**

```text
ResearchReference → M17 analyze_reference → ReferenceAnalysis → M18 aggregate_patterns → PatternAggregate[]
```

Backend baseline: **508 passing** (489 + 19 new). No DB, API, connector, M5, or frontend changes.

---

## 1. Purpose

Answer deterministic prevalence questions like "how many analyzed references have a numeral in the title?" — never "do numbered titles perform better?" or "what content gap exists?".

---

## 2. Package boundary

`src/trendora/research/patterns.py` — a small module in the research package, consuming M17's `ReferenceAnalysis`. No large intelligence tree.

---

## 3. Input contract

Consumes `Sequence[ReferenceAnalysis]` (M17 output). Consumes `ContentObservation` values directly; never reconstructs observations from raw `ResearchReference` text (M17 owns detection semantics).

---

## 4. Pattern aggregate contract

`PatternAggregate` (frozen + slots):

```text
observation_type: ObservationType
analyzed_count: int
matching_count: int
non_matching_count: int
ratio: float            # matching / analyzed, in [0.0, 1.0]
matching_reference_ids: tuple[ReferenceId, ...]
non_matching_reference_ids: tuple[ReferenceId, ...]
```

No random IDs, no timestamps, no formatted "60%" strings, no free-form pattern text, no `name` with interpretation.

---

## 5. Supported observations

Boolean observations only: `TITLE_HAS_NUMERAL`, `TITLE_HAS_QUESTION_MARK`, `DESCRIPTION_PRESENT`, `DESCRIPTION_HAS_URL` (`BOOLEAN_OBSERVATION_TYPES`).

## 6. Numeric observations — deferred

`TITLE_CHARACTER_COUNT` / `DESCRIPTION_CHARACTER_COUNT` are not aggregated. Numeric-distribution aggregation (min/max/mean) would add statistical surface without a product need; deferred until a later milestone explicitly requires it.

---

## 7. Boolean aggregation semantics

Counts per observation type: `matching` (true), `non_matching` (false), `analyzed` (matching + non_matching), `ratio = matching / analyzed`. No coercion: a non-boolean value raises `ResearchAggregationError`. The denominator is never hidden.

---

## 8. Denominator semantics

`analyzed_count` = references that actually contain that observation. A missing observation is not counted and is not false. This matters when observations are absent from some analyses (future multi-source).

## 9. Missing observations

Absent observation type in an analysis → skipped for that analysis (not false, not counted). If no reference has a given observation type, no aggregate is emitted for it. Proven by tests.

---

## 10. Duplicates

- Duplicate `ReferenceId` in the input → `ResearchAggregationError` (rejected, not deduplicated — deduplication could hide upstream mistakes).
- Duplicate `ObservationType` within one analysis → `ResearchAggregationError`.
- M17 structurally emits exactly one observation per type per reference; the guard is defensive.

---

## 11. Provenance

Aggregates carry `matching_reference_ids` / `non_matching_reference_ids` in input order, so every count is traceable to exact references. No rereading of `ResearchReference` needed.

## 12. Ordering

Aggregates emitted in `ObservationType` enum declaration order (only types present in input). Reference IDs preserve input order. No prevalence-based or performance-based sorting (that would create an implicit ranking).

---

## 13. Ratio

Internal representation is `float` in `[0.0, 1.0]` derived from integer counts. It is descriptive prevalence among analyzed references only — never success rate, effectiveness, confidence, or recommendation strength. Empty input → empty tuple (no zero-denominator aggregates are fabricated).

---

## 14. Performance boundary

No join of observations with `view_count`/`like_count`/`comment_count`. No engagement, velocity, correlation, uplift, benchmark, or scores. No derived YouTube metrics.

## 15. Content-gap boundary

No gaps, opportunities, whitespace, saturation, underserved/underused claims. `DESCRIPTION_HAS_URL = 1/20` is just a count; "most creators do not include links" is a deferred strategic concept.

---

## 16. Immutability

All M18 value objects `@dataclass(frozen=True, slots=True)`; reference-id collections are tuples. Mutation raises (tested).

## 17. Determinism

No time, random IDs, network, DB, or global state. Identical input → identical output (tested).

---

## 18. Non-goals

No AI/LLM/semantics, no topic classification, no title-structure interpretation (listicle/hook/curiosity-gap), no gaps, no opportunities, no recommendations, no performance/engagement/ranking, no API exposure, no frontend, no DB/persistence/schema, no new dependencies.

## 19. M19 readiness

M19 (grounded semantic / AI interpretation) can consume `ReferenceAnalysis[]` + `PatternAggregate[]` and must keep deterministic evidence distinct from AI interpretation — M18 emits no interpretation to confuse.

---

## 20. Files

- `src/trendora/research/patterns.py` — `PatternAggregate`, `BOOLEAN_OBSERVATION_TYPES`, `aggregate_patterns`
- `src/trendora/research/exceptions.py` — `ResearchAggregationError`
- `src/trendora/research/__init__.py` — exports
- `tests/unit/test_research_patterns.py` — 19 tests
