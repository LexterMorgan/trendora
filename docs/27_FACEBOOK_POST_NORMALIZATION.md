# 27 — Facebook Post Normalization & Grounded Evidence (M25B)

## Status

**M25B (this document + implementation):** normalizes public Facebook Page posts into Trendora's research-reference and grounded-evidence model. Backend foundation only — **Facebook remains isolated and is not exposed through `/api/v1/research` or `/api/v1/research/report`.**

Backend unit suite: **812 passing** (795 + 17 new). No settings, token configuration, OAuth, database changes, API routes, report wiring, capability declarations, frontend, or dependencies.

## 1. Normalizer

`normalize_facebook_posts(posts, *, collected_at) -> tuple[ResearchReference, ...]` — pure mapping of `FacebookPostResource` objects.

| ResearchReference field | Facebook mapping |
| --- | --- |
| `source_code` | `"facebook"` |
| `content_external_id` | `post.id` |
| `url` | `permalink_url` (must be nonblank HTTP(S)) |
| `title` | `None` — never invented from the message |
| `description` | `post.message`, preserved exactly |
| `published_at` | parsed from `created_time` (UTC/offset; missing → `None`) |
| `source_rank` | stable 1-based input order |
| `market_context` / `market_basis` | `None` |
| `channel_external_id` / `channel_title` | `None` (no Facebook Page→channel forcing) |

No country, audience, language, performance, or relevance inference.

## 2. Metrics

`ResearchMetrics` extended with `reaction_count` and `share_count` (existing fields unchanged). Facebook mapping: `reaction_count` ← reactions summary, `comment_count` ← comments summary, `share_count` ← shares, `view_count=None`, `like_count=None`. Zero stays `0`, missing stays `None`; **reactions are never likes**; no derived metric.

## 3. Grounded evidence

`EvidenceField` extended with `REACTION_COUNT` and `SHARE_COUNT`; `extract_evidence` emits them for every reference; both map to `AnalysisBasis.RAW_METRICS` in citation-basis resolution. Evidence serialization and citation parsing are the existing generic enum-driven paths — no new claim types or AI stages.

## 4. Validation (fail closed)

- `collected_at` must be timezone-aware.
- Blank post IDs rejected; duplicate post IDs rejected (no duplicate evidence identities).
- Nonblank HTTP(S) permalink required (provenance chain needs an original URL).
- Missing `created_time` → `published_at=None`; malformed or timezone-naive `created_time` → `FacebookResponseError` (never silently rewritten; stdlib parsing only).
- No tokens, response bodies, or raw upstream messages in errors/logs.

## 5. Exclusions

No settings/env, Meta token config or OAuth, FastAPI routes, report wiring, capability declaration claiming Facebook availability, `SOURCE_IDS`/DB/migration changes, frontend, Page-ID request contract, keyword search, scraping, retries, generic frameworks, new dependencies, Instagram/TikTok. The M25A HTTP client is unchanged.

## 6. Live compatibility

Unchanged from M25A: no live Meta credentials; live Graph compatibility remains unverified. This normalizer operates on the mocked DTO contract.

## 7. Files

- `src/trendora/connectors/facebook/normalizer.py`
- `src/trendora/connectors/facebook/__init__.py` (exports)
- `src/trendora/research/models.py` (`ResearchMetrics` + reaction/share)
- `src/trendora/research/evidence.py` (`EvidenceField` + extraction)
- `src/trendora/research/interpretation.py` (basis map)
- `tests/unit/test_facebook_normalizer.py` (15 tests)
- `tests/unit/test_research_youtube.py` (metric-field-set assertion updated)