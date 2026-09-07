# 31 — Combined Multi-Source Execution (M26B)

## Status

**M26B (this document + implementation):** one combined research/report run can execute YouTube plus one explicit Facebook Page through the existing M13–M23 seams. No multi-market, frontend, persistence, or new-dependency changes; everything is fully mocked in tests.

## 1. Query validation

`sources=["youtube","facebook"]` is now valid in any normalized order (duplicates deduplicated, first occurrence wins). Facebook requested anywhere requires a valid `facebook_page_id`; a Page ID without the Facebook source remains invalid; YouTube-only and Facebook-only behavior is unchanged. `result_limit` is a global maximum across executed sources.

## 2. Capability truth

Capability resolution is per source, never a cross-product: topic-search sources (YouTube, Stack Exchange, …) require `public_search`; Facebook requires `creator_watchlist`. Coverage contains one truthful entry per requested source with unchanged complete/partial/none semantics.

## 3. Runtime execution

- The plan is every requested source whose capability resolved AVAILABLE, in normalized request order.
- Before any network call, every planned source must have a configured retriever; one missing retriever fails the whole request with the sanitized `research_source_not_configured` (503) and zero retrieval calls — never a silent partial result.
- The global `result_limit` is split deterministically with `divmod`: even base share per source, earlier requested sources take any remainder, single-source requests keep the full limit. A limit below the executable source count raises a validation error. Shares always sum to exactly the global limit.
- Each retriever receives its own validated per-source query: only its own source code, its allocated limit, `facebook_page_id` only for Facebook.
- Every planned retriever is called exactly once. References merge in request order, preserving each source's internal order and source-local `source_rank`; the merged total never exceeds the global limit.
- `executed_sources` records sources actually attempted, in attempt order, including the failing source. Any failure marks the run FAILED and propagates the original exception. All-empty results still complete with zero references.

## 4. Report pipeline

A combined nonempty run produces one evidence pack and exactly one interpretation, strategy, and ideation stage (subject only to the existing single malformed-response retry). Citation identity remains `(source_code, content_external_id)`. All grounding and report validation is unchanged. Facebook topic/market remain non-filtering: they organize the report but do not filter which Page posts are collected.

## 5. Behavior change vs. M25D

Requesting a statically-available source that has no configured runtime retriever (e.g. `["stack_exchange","youtube"]`) now fails closed with 503 `research_source_not_configured` instead of silently executing only the configured source. Coverage truth is unchanged; execution no longer silently skips requested available sources.

## 6. Files

- `src/trendora/research/models.py` (validation, `allocate_result_limits`, `ResearchRun.execute_sources`)
- `src/trendora/research/capabilities.py` (`required_capability_for_source`)
- `src/trendora/research/service.py` (per-source resolution)
- `src/trendora/research/application.py` (plan, pre-check, allocation, per-source queries)
- `tests/unit/test_research_combined.py` (20 tests), API combined tests in `tests/unit/test_research_api.py`, updated V1 skip-semantics tests