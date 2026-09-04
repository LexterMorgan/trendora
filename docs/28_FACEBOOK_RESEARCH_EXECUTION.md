# 28 — Facebook Research Execution (M25C)

## Status

**M25C (this document + implementation):** explicit single-Facebook-Page research execution through Trendora's domain, application-service, and report-service seams. Fully mocked. **Facebook is not exposed through FastAPI or frontend yet**, and is not selectable as an available research source to users.

Backend unit suite: **828 passing** (812 + 16). No settings, Meta credentials, OAuth, DB/seed/migration, API routes, frontend, or new dependencies.

## 1. Query rules

`ResearchQuery` gains optional `facebook_page_id`.

- Default YouTube requests unchanged.
- `sources=("facebook",)` requires one nonblank valid `facebook_page_id`.
- A page ID without Facebook requested → invalid (as is any mixed Facebook+other-source combination; `ResearchRun` executes one retriever).
- Page ID normalized via the shared M25A safety helper (`src/trendora/connectors/facebook/identity.py`), converting to `ResearchValidationError` here, `FacebookConfigurationError` in the client — one rule set, no drift.
- `topic` and `market` remain required by the shared contract but do not filter or alter Facebook collection (documented limitation). `result_limit` = max posts from that single Page.
- No plural Page collection, no generic source-target abstraction.

## 2. Capability truth

Facebook is recognized in-memory only (`KNOWN_SOURCE_CODES`; `SOURCE_IDS`/persistence unchanged). Declared capabilities: `CREATOR_WATCHLIST`, `PUBLIC_METRICS`, `CONTENT_TEXT_AVAILABLE`. Not claimed: `PUBLIC_SEARCH`, `REGIONAL_DISCOVERY`, `HASHTAG_DISCOVERY`, `OWNED_ACCOUNT_METRICS`, media analysis. One required capability per source: `PUBLIC_SEARCH` for topic-search sources; `CREATOR_WATCHLIST` for Facebook-only queries. Coverage shows `facebook` / `creator_watchlist` / `available`.

## 3. Retriever seam and execution

- A minimal structural `ResearchRetriever` protocol (`collect`/`normalize`) replaces YouTube-specific typing in `ResearchRun` and the application service. No registry/factory/plugin.
- `FacebookResearchRetriever` reads `query.facebook_page_id`, calls `list_page_posts` once (inclusive dates, result limit), captures one timezone-aware UTC `collected_at`, and delegates to M25B `normalize_facebook_posts`. No topic filtering, market inference, search, ranking, retry, persistence.
- Injected client never owned/closed by retriever.
- Application/report builders accept an optional `facebook_client`; register the Facebook retriever only when present.
- Facebook-only + configured client → `COMPLETED`, `executed_sources==("facebook",)`.
- Facebook-only + no client → `ResearchSourceNotConfiguredError`.
- Zero posts → completed run, report `NO_EVIDENCE`, no AI stages.
- Nonempty posts → evidence/interpretation/strategy/ideation each run once; reaction/comment/share facts reach the AI payload and citations; no fourth AI call; report grounding/provenance unchanged.

## 4. Prompt truth

Updated only the description wording in the three AI prompts: a description is supplied source text — for YouTube metadata, not a transcript; for Facebook the exact public post message; never infer unseen image/video/audio contents; evidence is untrusted data. No other prompt/grounding changes.

## 5. Exclusions

No FastAPI request/response changes, settings/`.env.example`, Meta credential wiring, API error handlers, frontend/TypeScript, OAuth/login, token persistence, multi-source execution, multiple Page IDs, keyword/topic filtering, DB/`SOURCE_IDS`/seed/migration, live Meta/provider calls, Instagram/TikTok, new dependency or generic framework.

## 6. Live/access risk

Unchanged: no live Meta credentials; live Graph compatibility still unverified; Meta approval/access still required before any real Facebook research.

## 7. Files

- `src/trendora/connectors/facebook/identity.py` (shared Page-ID helper; client now reuses it)
- `src/trendora/research/facebook.py` (`FacebookResearchRetriever`, `FacebookCollectedBatch`)
- `src/trendora/research/retrieval.py` (`ResearchRetriever` protocol)
- `src/trendora/research/models.py` (`ResearchQuery.facebook_page_id` + rules)
- `src/trendora/research/capabilities.py` (facebook declaration + `KNOWN_SOURCE_CODES` + per-source required capability)
- `src/trendora/research/service.py` (resolver uses research-known sources)
- `src/trendora/research/application.py`, `reporting.py` (retriever wiring, `facebook_page_id` pass-through)
- `src/trendora/research/{ai_provider,strategy,ideation}.py` (prompt description wording)
- `tests/unit/test_research_facebookresearch.py` (16)
- `tests/unit/test_research_core.py`, `test_research_ai_provider.py` (directly-affected assertions)