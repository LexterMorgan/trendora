# 21 — Grounded AI Interpretation Contract (M19)

## Status

**M19 (this document + implementation):** the boundary between Trendora's deterministic evidence system and future LLM-generated interpretation. M19 calls no LLM, integrates no provider, and generates no interpretation. It defines what evidence an AI may receive, what it may return, how citations work, how they are validated, and how provider/model provenance is represented.

Backend baseline: **541 passing** (508 + 33 new). No DB, API, connector, M5, or frontend changes.

---

## 1. Purpose

Make future interpretation labeled, inspectable, grounded, provenance-aware, provider-traceable, and structurally validated — without M19 itself reasoning. M19 validates *"does this interpretation cite evidence that actually exists?"* It does not prove *"does the statement logically follow from the evidence?"* (semantic entailment is a later concern).

## 2. Trust hierarchy

```text
FACT → OBSERVATION → PATTERN → AI_INTERPRETATION
```

Each layer is derived from the previous. M19 adds AI_INTERPRETATION only. No RECOMMENDATION/OPPORTUNITY/GAP/IDEA/BRIEF yet.

---

## 3. Package boundary

`src/trendora/research/interpretation.py` — a small module in the research package, consuming M17 (`ReferenceAnalysis`, citations over `EvidenceFact`/`ContentObservation`) and M18 (`PatternAggregate`). No new package tree; provider transport belongs to M20.

---

## 4. Claim types

`ClaimType` now has `fact`, `observation`, `ai_interpretation`. Existing structural invariants preserved: `EvidenceFact.claim_type` = FACT, `ContentObservation.claim_type` = OBSERVATION, `AIInterpretation.claim_type` = AI_INTERPRETATION — all `field(init=False)`; wrong claim-type construction is a `TypeError`.

---

## 5. Evidence pack

`EvidencePack` (frozen + slots): `analyses: tuple[ReferenceAnalysis, ...]`, `patterns: tuple[PatternAggregate, ...]`. Reuses M17/M18 outputs directly — no source-truth duplication, no raw connector/API/ORM/secret material.

### Pack validation

- non-empty (empty pack rejected — interpretation without evidence is meaningless)
- duplicate `ReferenceId` rejected
- duplicate `PatternAggregate` observation type rejected
- every pattern provenance id must exist inside the pack
- ordering preserved as given (no view/like/ratio-based ranking)
- inputs not mutated; no generated time; no random IDs

---

## 6. Citation types

All frozen + slots:

- `FactCitation(reference: ReferenceId, field: EvidenceField)`
- `ObservationCitation(reference: ReferenceId, observation_type: ObservationType)`
- `PatternCitation(observation_type: ObservationType)`

No generic `citations: list[str]`, no random citation IDs.

### Resolution semantics

- **Fact**: resolves iff that exact reference's facts contain that `EvidenceField` (a `None`-valued fact still exists — M17 emits all facts).
- **Observation**: resolves iff that exact reference contains that exact `ContentObservation` type.
- **Pattern**: resolves iff the pack contains a `PatternAggregate` for that `ObservationType`.

Unknown reference, absent field, absent observation, or absent pattern → `ResearchInterpretationError`.

---

## 7. AI interpretation

`AIInterpretation` (frozen + slots): `statement: str`, `citations: tuple[Citation, ...]`, `claim_type=AI_INTERPRETATION` (structural). Construction enforces: non-blank statement, ≥1 citation, no duplicate citations. No recommendation/confidence/probability/action/score fields.

## 8. Model provenance

`ModelProvenance(provider: str, model: str)` — explicit non-blank strings, no vendor enum, no API keys/pricing/tokens/temperature. Provider-neutral.

## 9. Interpretation result

`InterpretationResult(model_provenance, interpretations: tuple[AIInterpretation, ...])` — frozen. No result IDs, timestamps, token counts, or cost.

---

## 10. Grounding validation

`validate_interpretations(pack, result)` deterministically resolves every citation against the pack and returns the result unchanged, or raises `ResearchInterpretationError`. It rejects unknown references, unresolved fact/observation/pattern citations, empty citation sets, wrong claim types, blank statements, and duplicate citations. No silent dropping, rewriting, or repairing.

## 11. Analysis-basis derivation

`interpretation_analysis_basis(pack, citation)` derives basis from cited evidence (no caller-declared basis):

- FactCitation: `EvidenceField` → basis map (TITLE→TITLE, DESCRIPTION→DESCRIPTION, view/like/comment→RAW_METRICS, URL/COLLECTED_AT/PUBLISHED_AT/CHANNEL_TITLE/MARKET_CONTEXT/MARKET_BASIS/SOURCE_RANK→SOURCE_METADATA).
- ObservationCitation: reads the actual observation's `analysis_basis` from the pack.
- PatternCitation: derives from the underlying M17 observation-type semantics.

No VIDEO/AUDIO/TRANSCRIPT/IMAGE basis can be produced.

---

## 12. Structural grounding vs semantic support

M19 guarantees every accepted interpretation cites evidence that actually exists in the pack. It does **not** guarantee the statement is semantically entailed. Example: evidence `6/10 titles have numerals` + statement "numbered titles always cause higher engagement" may be structurally grounded but semantically unsupported; M19 cannot prove this. Entailment checking, unsupported-claim detection, human review, provider comparison are later milestones.

## 13. Market boundary

`market_context`/`market_basis` remain facts. `SG` + `youtube_region_availability` never implies creator/publisher/origin country; no such structured fields exist.

## 14. Media / description boundary

The pack contains title/description metadata, source metadata, raw metrics, and their deterministic observations/patterns — no transcript, frames, audio, scenes, or visual content. Description stays YouTube-provided metadata, never structurally labeled transcript/spoken/full-video content.

---

## 15. Immutability / determinism

All M19 objects frozen+slots with tuple collections. No time, randomness, network, DB, or global state; identical pack + result → identical validation outcome.

---

## 16. Non-goals

No live LLM calls, provider SDKs/interfaces, prompts, structured-output APIs, retries, token/cost accounting, semantic entailment, recommendations, opportunities, gaps, ideas, briefs, sentiment, embeddings, vector DB, RAG, media analysis, performance interpretation, derived metrics, DB persistence/schema, API routes, frontend, auth, async.

## 17. M20 readiness

M20 (provider adapter + execution) can consume `EvidencePack` (serialize later), produce structured model output → `AIInterpretation[]` → `validate_interpretations` → `InterpretationResult`, without redesigning identity, citations, claim type, provenance, or grounding. M19 deliberately does not define provider transport.

---

## 18. Files

- `src/trendora/research/interpretation.py` — EvidencePack, citations, AIInterpretation, ModelProvenance, InterpretationResult, validate_interpretations, interpretation_analysis_basis
- `src/trendora/research/evidence.py` — `ClaimType.AI_INTERPRETATION`
- `src/trendora/research/exceptions.py` — `ResearchInterpretationError`
- `src/trendora/research/__init__.py` — exports
- `tests/unit/test_research_interpretation.py` — 33 tests
