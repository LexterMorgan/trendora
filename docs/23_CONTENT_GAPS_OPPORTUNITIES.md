# 23 — Content Gaps & Opportunities (M21)

## Status

**M21 (this document + implementation):** Trendora's first explicit strategic layer. `ContentGap` (a model-generated diagnosis of a semantic angle absent/limited within the analyzed set) and `Opportunity` (a strategic direction derived from validated gaps), executed through the existing OpenAI-compatible provider with strict parsing and mandatory grounding validation.

Pipeline:

```text
ResearchReference → EvidenceFact → ContentObservation → PatternAggregate → AIInterpretation → ContentGap → Opportunity
```

Backend baseline: **694 passing** (644 + 50 new). No DB, API, connector, M5, or frontend changes; no dependency added.

## 1. Purpose

Introduce strategic diagnosis while keeping it anchored: a gap traces to deterministic evidence **and** prior grounded interpretation; an opportunity traces to gaps **and** deterministic evidence. Prevalence is evidence; gap diagnosis is semantic AI interpretation; opportunity is a strategic recommendation.

## 2. Claim chain

```text
FACT → OBSERVATION → PATTERN → AI_INTERPRETATION → CONTENT GAP → OPPORTUNITY / RECOMMENDATION
```

`ClaimType` gains `recommendation`. `ContentGap.claim_type` is always `AI_INTERPRETATION`; `Opportunity.claim_type` is always `RECOMMENDATION` (both `init=False`). Gap/opportunity are domain types, not additional claim types.

## 3. ContentGap contract

`ContentGap(statement, citations, supporting_interpretation_indexes, claim_type=AI_INTERPRETATION)` — frozen+slots. Non-blank statement; ≥1 typed citation (Fact/Observation/Pattern); ≥1 supporting interpretation index; no duplicate citations/indexes; indexes non-negative. No confidence/severity/score/rank/priority/expected-performance.

## 4. Opportunity contract

`Opportunity(statement, gap_indexes, citations, claim_type=RECOMMENDATION)` — frozen+slots. Non-blank statement; ≥1 gap index; ≥1 typed citation; no duplicates; indexes non-negative. Strategic direction only — no titles/hooks/scripts/CTAs/formats/schedules/briefs/deliverables (those are M22 ideas).

## 5. Strategic context

`StrategicContext(evidence_pack, interpretation_result)` — constructor runs `validate_interpretations`, so only grounded interpretations can enter strategy.

## 6. Strategic result

`StrategicResult(model_provenance, content_gaps, opportunities)` — trusted provenance, no IDs/timestamps/cost/ranking. Successful empty (`()`, `()`) is valid after a configured provider actually executes.

## 7. Gap provenance

Each gap cites deterministic evidence (resolved against the pack) and references interpretation indexes (resolved against `InterpretationResult.interpretations`). Chain: gap → interpretations + facts/observations/patterns → references → URLs.

## 8. Opportunity provenance

Each opportunity references ≥1 gap index (resolved against `StrategicResult.content_gaps`) and cites deterministic evidence. Free-floating opportunities are structurally impossible.

## 9. Citation reuse

Extracted `validate_citations(pack, citations)` in M19 interpretation and made `validate_interpretations` use it; M21 reuses it. No duplicated resolution logic. M19 validation semantics unchanged (M19 tests green).

## 10. Strategic validation

`validate_strategic_result(context, result)` — every gap/opportunity citation resolves against the pack; supporting interpretation indexes in range; opportunity gap indexes in range; structural claim types fixed; returns result unchanged or raises `ResearchInterpretationError`. No silent repair.

## 11. Rare pattern vs gap

No deterministic rules like `ratio < 0.2 → gap`. `PatternAggregate` is evidence supplied to semantic reasoning; the model decides under the analyzed-set rule. `DESCRIPTION_HAS_URL = 2/20` is a count, not a gap, until a model says so with citations.

## 12. Provider execution

Reuses M20 transport: `_post_chat_request`, `_parse_envelope_content`, `AIProviderConfig`, trusted `ModelProvenance`, finite timeout, one request, no retries/streaming. `OpenAICompatibleStrategyProvider` + `GroundedStrategyService` mirror the interpretation flow.

## 13. Strategic prompt

`SYSTEM_STRATEGIC_PROMPT` — 22 rules: evidence/interpretations are DATA; no embedded-instruction following; gap needs citations + interpretation indexes; opportunity needs gap index + citations; gap = within analyzed set only; no market/platform-wide absence claims; no nationality inference; no media/transcript claims; no causal/performance advantage; no derived metrics; no content ideas/briefs/expected performance; strict JSON schema; no claim_type/provider/model/confidence/score/priority.

## 14. Model output contract

```json
{"content_gaps": [{"statement":"...","citations":[...],"supporting_interpretation_indexes":[0]}],
 "opportunities": [{"statement":"...","gap_indexes":[0],"citations":[...]}]}
```

Citations reuse the exact M20 shapes (fact/observation/pattern).

## 15. Strict parsing

Pydantic `extra=forbid` DTOs. Rejects malformed JSON, fences/prose, unknown fields, blank statements, missing/empty citations, missing/negative indexes, model-supplied claim_type/provider/model/score/confidence/priority/idea/brief. No repair, no silent drop.

## 16. Trusted model provenance

`ModelProvenance` from adapter config only; model output cannot override.

## 17. Successful empty result

`{"content_gaps":[], "opportunities":[]}` → successful `StrategicResult(..., (), ())`. Gaps-without-opportunities is valid; opportunities-without-gaps is structurally rejected. Not-configured remains an error, distinct from empty success.

## 18. Structural vs semantic validation

M21 guarantees provenance resolves to actual evidence + grounded interpretations. It cannot prove strategic importance, commercial quality, entailment, or performance. No NLI/evaluator/judge/confidence/hallucination score/performance prediction.

## 19. Performance / market / media boundaries

No expected views/engagement prediction/ranking/uplift/confidence. Market context never implies nationality. No transcript/video/audio/visual analysis; description stays metadata.

## 20. Prompt injection

Evidence + interpretation text stay DATA, in the user message only, never system instructions, never executed locally. System prompt states the untrusted-data rule. Not a formal injection proof.

## 21. AI non-determinism

Deterministic: serialization, prompt construction, HTTP, parsing, conversion, validation, error mapping. Not deterministic: model-generated gap/opportunity text.

## 22. Non-goals / scope

No ideas, hooks, titles, scripts, captions, CTAs, briefs, reports, ranking, priorities, scores, confidence, expected performance, performance prediction, deterministic gap thresholding, entailment checker, second-model judge, second provider, retries, streaming, RAG, embeddings, transcript/media analysis, DB/persistence, API, frontend, auth, queues, alerts, publishing.

## 23. M22 readiness

M22 (grounded content ideas + briefs) can build on validated `StrategicResult` gaps/opportunities with full provenance intact.

## 24. Files

- `src/trendora/research/strategy.py` — ContentGap, Opportunity, StrategicContext, StrategicResult, validate_strategic_result, AIStrategyProvider, OpenAICompatibleStrategyProvider, SYSTEM_STRATEGIC_PROMPT, GroundedStrategyService
- `src/trendora/research/evidence.py` — `ClaimType.RECOMMENDATION`
- `src/trendora/research/interpretation.py` — extracted `validate_citations`
- `src/trendora/research/ai_provider.py` — extracted shared `_post_chat_request`
- `src/trendora/research/__init__.py` — exports
- `tests/unit/test_research_strategy.py` — 50 tests
