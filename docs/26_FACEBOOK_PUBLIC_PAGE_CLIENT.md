# 26 — Facebook Public Page Client (M25A)

## Status

**M25A (this document + implementation):** a small, concrete, isolated Graph API client (`FacebookPublicClient`) that retrieves public posts and visible engagement from an explicitly supplied Facebook Page ID. **No live credentials exist; everything is verified through mocked HTTP only.**

Backend unit suite: **795 passing** (752 pre-M25A baseline + 43 Facebook tests). No dependencies added; no backend pipeline wiring; no API/frontend changes.

## 1. Purpose

Prepare public Facebook research without requiring Trendora users to log in. The Trendora backend will eventually authenticate with its own, reviewed Meta app credentials; no assumption is made about those credentials existing today.

## 2. Scope and truth

- Retrieves posts **only from an explicitly supplied public Page ID**. No global Facebook keyword search, no discovery, no scraping.
- Public metrics are exactly what the requested fields return: reactions summary, comments summary, share count, and other explicitly requested fields (`id`, `message`, `created_time`, `permalink_url`, `from{id,name}`).
- **Reach, impressions, clicks, saves, demographics, and private insights are unavailable.**
- **Total reactions is reactions, never likes.** No engagement rates, scores, averages, or inferred metrics are computed.
- No market, audience location, Page location, relevance, or performance inference.

## 3. Client contract

`FacebookPublicClient(access_token, graph_version, *, http_client=None)`

- Explicit nonblank access token; Graph version validated as `v<major>.<minor>` (no guessed default).
- Environment variables are never read by the client.
- Optional shared `httpx.Client` is reused and **never closed** by the client; only internally owned clients are closed.

`list_page_posts(page_id, *, date_from, date_to, limit) -> tuple[FacebookPostResource, ...]`

- Inclusive `date_from`/`date_to`; the exclusive end boundary is `date_to + 1 day` passed as `until` to Graph.
- Rejects blank Page IDs, reversed dates, and limits outside `1..100`.
- Requests only the required fields; authenticates via `Authorization: Bearer …` (token never in query strings, logs, or errors).
- Paginates using returned `paging.cursors.after`; **never follows `paging.next` URLs**.
- Stops at requested limit; deduplicates post IDs deterministically (first occurrence wins); preserves source order.
- No retries.

## 4. Strict schemas

Pydantic DTOs with `extra="forbid"` for requested fields. Optional metrics default to `None`; source zero stays `0`; counts are non-negative integers. Malformed items fail closed (`FacebookResponseError`).

## 5. Errors

`FacebookConfigurationError`, `FacebookHttpError`, `FacebookApiError` (status/reason), `FacebookResponseError`. Errors and logs never include access tokens or raw response bodies.

## 6. Explicit exclusions

No OAuth/Facebook Login, user accounts, token persistence/refresh, database tables/migrations, environment settings, FastAPI routes, research/report pipeline integration, capability registration claiming Facebook availability, frontend changes, scraping, browser automation, keyword search, connected/owned Page insights, Instagram/TikTok, or generic provider frameworks. No new dependencies.

## 7. Access / approval truth

- The backend still requires a Meta app access token and the relevant Meta approval/access for the planned public mode.
- **Live Meta compatibility remains unverified** until credentials and approval exist; this client is isolated and not yet wired into `/api/v1/research` or report generation.

## 8. Files

- `src/trendora/connectors/facebook/__init__.py`
- `src/trendora/connectors/facebook/client.py`
- `src/trendora/connectors/facebook/schemas.py`
- `src/trendora/connectors/facebook/exceptions.py`
- `tests/unit/test_facebook_client.py` (32 tests)