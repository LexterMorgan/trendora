# 24 — Grounded Content Ideas & Briefs (M22)

## Status

**M22 (this document + implementation):** grounded content ideation above validated M21 gaps/opportunities. `ContentIdea` (title + angle derived from opportunities) and `ContentBrief` (elaboration of one idea), executed through the existing OpenAI-compatible provider with strict parsing and mandatory grounding validation.

Chain preserved structurally:

```text
ContentBrief → ContentIdea → Opportunity → ContentGap → AIInterpretation → deterministic citation → ResearchReference → original URL
```

Backend: 717 unit tests passing (M19–M21 regression green; +47 new). No DB, API, connector, M5, or frontend changes; no dependency added.

## 1. Purpose

Produce concrete but still strategic content directions (titles, angles, hooks, formats, objectives, outlines) that stay traceable to evidence, interpretations, gaps, and opportunities. Ideas/briefs never claim performance, absence, nationality, or media analysis.

## 2. ContentIdea contract

`ContentIdea(title, angle, opportunity_indexes, citations, claim_type=RECOMMENDATION init=False)` — frozen+slots. Nonblank title/angle; ≥1 opportunity index; ≥1 typed citation; no duplicate indexes/citations; indexes nonnegative. No scores/confidence/priority/ranking/expected-performance/IDs/timestamps.

## 3. ContentBrief contract

`ContentBrief(idea_index, objective, format, hook, outline, citations, claim_type=RECOMMENDATION init=False)` — frozen+slots. Nonnegative idea index; nonblank objective/format/hook; outline with ≥1 nonblank item; ≥1 citation; no duplicate citations.

## 4. IdeationContext

`IdeationContext(strategic_context, strategic_result)` — constructor runs `validate_strategic_result`, so only M21-validated strategy can enter.

## 5. IdeationResult

`IdeationResult(model_provenance, content_ideas, content_briefs)` — trusted provenance from provider config only.

## 6. Grounding validation

`validate_ideation_result(context, result)`:
- every idea citation resolves against the evidence pack
- every idea opportunity index resolves against `strategic_result.opportunities`
- every brief citation resolves against the evidence pack
- every brief idea index resolves against `result.content_ideas`
- fixed `RECOMMENDATION` claim types
- returns unchanged or raises `ResearchInterpretationError`; never repairs/drops

Successful empty ideas+briefs valid after real provider execution. Ideas without briefs valid. Briefs without valid ideas impossible.

## 7. Provider execution

Reuses M20/M21 transport: `AIProviderConfig`, `_post_chat_request`, `_parse_envelope_content`, `ProviderCitation`, `_to_domain_citation`, `evidence_pack_to_payload`, `ModelProvenance`. One request, finite timeout, no retries/streaming/second provider. M21's `citation_to_json` serializer promoted to a public name (smallest edit) and reused.

Components: `AIIdeationProvider` protocol, `OpenAICompatibleIdeationProvider`, `GroundedIdeationService`, `SYSTEM_IDEATION_PROMPT`, `build_grounded_ideation_request`.

## 8. Provider input

User message (untrusted data) carries: evidence pack, grounded interpretations, validated gaps, validated opportunities. System prompt contains rules only; never evidence/strategy text.

## 9. Model output contract

```json
{"content_ideas":[{"title":"...","angle":"...","opportunity_indexes":[0],"citations":[...]}],
 "content_briefs":[{"idea_index":0,"objective":"...","format":"...","hook":"...","outline":["..."],"citations":[...]}]}
```

Citations reuse exact M20 shapes.

## 10. Strict parsing

Pydantic `extra=forbid`. Rejects malformed JSON/fences/prose, unknown fields, blank strings, empty indexes/outline/citations, negative/out-of-range indexes, duplicates, model-supplied claim_type/provider/model/confidence/score/priority/rank/expected-performance/IDs/timestamps, invalid citation kinds/enums. No repair/drop.

## 11. Truth boundaries

Ideas/briefs may create titles/angles/hooks/formats/objectives/outlines. They must not claim market/platform-wide absence, causality/performance advantage, expected views/engagement/uplift/ranking/confidence, nationality from market context, transcript/media analysis, or derived metrics absent from evidence. Description stays source metadata.

## 12. Prompt injection

Evidence + strategy text stay DATA in the user message; never system; never executed locally; untrusted-data rule stated. Not a formal immunity proof.

## 13. AI non-determinism

Deterministic: serialization, prompt construction, HTTP, parsing, conversion, validation, error mapping. Not deterministic: model-generated idea/brief text.

## 14. Non-goals / scope

No API endpoint, frontend, database, persistence, migration, report, publishing, scheduling, ranking, scoring, RAG, embeddings, judge model, entitlement checker, dependency, connector, or forecast changes.

## 15. M23 readiness

M23 (reporting / product integration) can consume validated `IdeationResult` with full provenance intact.

## 16. Files

- `src/trendora/research/ideation.py` — ContentIdea, ContentBrief, IdeationContext, IdeationResult, validate_ideation_result, provider, prompt, service
- `src/trendora/research/strategy.py` — `citation_to_json` promoted public
- `src/trendora/research/__init__.py` — exports
- `tests/unit/test_research_ideation.py` — 47 tests
