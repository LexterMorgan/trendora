# 32 — Multi-Market Research (M26C / M26D)

## Status

**M26C (backend) + M26D (frontend), this document:** the research/report contract accepts an ordered list of SEA markets as the canonical query field, and the workspace form lets users select one or more markets. Everything is fully mocked in tests; no live Meta verification, no persistence, no new dependencies.

## 1. Canonical market query

- `ResearchQuery.markets` is the canonical ordered, normalized, deduplicated market tuple. Markets are upper-cased, blank entries rejected, unsupported codes rejected, duplicates dropped (first occurrence wins), request order preserved.
- Legacy singular `market` is accepted for single-market requests and becomes a one-element `markets`. Exactly one of `market` / `markets` must be supplied — neither or both raises `ResearchValidationError` before any network call.
- At least one market is required. Every market must exist in `MARKET_CODES` (ID/TH/MY/SG/VN/PH).

## 2. Retrieval targets and limit allocation

- YouTube produces **one retrieval target per selected market**, in market order; each target's `regionCode` is that market.
- Facebook produces **exactly one retrieval target** regardless of market count. The selected markets are report context only and never filter which Page posts are collected.
- The global `result_limit` is split deterministically across targets with `divmod`: even base share per target, earlier targets take any remainder. `result_limit` must be ≥ the target count (fail-closed with a validation error before any network call).
- Every planned source must have a configured retriever before any collection; one missing retriever fails the whole request with `research_source_not_configured` and zero retrieval calls. Any target failure fails the run and propagates the original error — never a silent partial result.

## 3. Merge and identity

- Per-target cap at its allocated limit, merged in target order, deduplicated by `(source_code, content_external_id)`.
- First occurrence owns all source facts (metadata, metrics, URL, timestamps). Metrics are never summed, averaged, or combined.
- Duplicate YouTube videos union `market_contexts` in selected-market order.
- `source_rank` is reassigned per source after deduplication using first-seen merged order (source order only — not relevance/performance ranking).
- Legacy `market_context` stays truthful: the sole context when exactly one exists, otherwise `None`. `market_contexts` is always the full canonical list.
- `executed_sources` records unique source codes in first-attempt order (YouTube once, even with several market targets). All-empty targets complete with zero references.

## 4. Evidence

- `EvidenceField.MARKET_CONTEXTS` replaces the singular internal market-context fact; `FactValue` includes `list[str]`.
- Evidence sent to the AI uses the plural `market_contexts` value. The AI provider and strategy prompts forbid inferring creator/publisher nationality, content origin, audience location, or language from market contexts — they prove regional YouTube availability/viewability only.
- Facebook references keep empty `market_contexts` (topic/market do not filter Page-post collection); their `market_basis` stays `None`. YouTube `market_basis` stays `youtube_region_availability`.

## 5. API

- Request accepts `market` (legacy) or `markets` (canonical); exactly one is required. Both/neither/blank/unsupported markets are rejected as `422 invalid_research_request`.
- Response always returns `query.markets` plus nullable legacy `query.market` (sole market or `null`) and per-reference `market_contexts` alongside legacy `market_context`.

## 6. Frontend

- The workspace form replaces the single-select Market dropdown with a checkbox group (styled like the existing source selector). All six SEA markets are selectable; submission order follows the fixed `MARKETS` list order, not click order.
- At least one market is required and enforced locally with a clear error message. Default selection is `["SG"]`.
- Requests are sent with the canonical `markets` array; the singular `market` field is no longer submitted by the UI. Facebook mode is otherwise unchanged (Page ID required; topic/markets organize the report but do not filter posts).

## 7. Limitations

- Facebook remains mocked-only; no live Meta verification. No persistence, database, or concurrency changes. No local/regional/global market classification, no geographic inference, no ranking/scoring.

## 8. Files

- `src/trendora/research/models.py` (canonical `markets`, `market_contexts`, `_merge_targets`, `_reassign_source_ranks`, `_sync_legacy_market_context`)
- `src/trendora/research/application.py` (`_resolve_markets`, per-market/per-source target plan, `_allocate_target_limits`, `_target_query`)
- `src/trendora/research/youtube.py` (per-market `regionCode`, plural `market_contexts`)
- `src/trendora/research/evidence.py` (`EvidenceField.MARKET_CONTEXTS`, `FactValue` list)
- `src/trendora/research/ai_provider.py`, `strategy.py` (prompt rules)
- `src/trendora/api/research_models.py` (request/response plural fields)
- `web/components/ResearchForm.tsx`, `TurnView.tsx`, `web/lib/trendora-api.ts` (multi-select form, markets submission, turn summary)
- `tests/unit/test_research_multimarket.py` (32 tests)
