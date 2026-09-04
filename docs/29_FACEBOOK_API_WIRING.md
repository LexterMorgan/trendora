# 29 — Facebook API Wiring (M25D)

## Status

**M25D (this document + implementation):** the isolated Facebook research path (M25A–M25C) is now wired into the FastAPI read model. When both `META_ACCESS_TOKEN` and `META_GRAPH_API_VERSION` are configured, `POST /api/v1/research` and `POST /api/v1/research/report` can run a single-Facebook-Page research/report flow; otherwise an explicit Facebook request fails with 503 `research_source_not_configured`, never a silent empty success. Fully mocked; no frontend, OAuth, DB, or live Meta calls.

Backend unit suite: **851 passing** (845 + 6). No dependencies added. `web/AGENTS.md` and `web/CLAUDE.md` are untouched.

## 1. Settings wiring

`Settings` gains optional `meta_access_token` (`META_ACCESS_TOKEN`) and `meta_graph_api_version` (`META_GRAPH_API_VERSION`), both defaulting to `None` and sharing the existing blank-to-`None` validator: blank/missing env values keep the Facebook source unconfigured (503), and the token never enters logs, errors, or URLs.

- `.env.example` documents both variables as optional-until-enabled.
- Both variables are required together to create the client; partial/missing settings keep the source unconfigured.

## 2. Dependency lifecycle

Both research dependencies in `src/trendora/api/app.py` own their clients and close them **exactly once**, including when a later client construction or service build fails:

- `get_research_application_service` owns YouTube + Facebook clients.
- `get_research_report_service` owns YouTube + Facebook clients plus one shared `httpx.Client` for the three AI adapters.

Implementation uses a stdlib `contextlib.ExitStack` with a `close()` callback registered immediately after each client is created. If any later construction (`FacebookPublicClient`, `httpx.Client`) or `build_research_*_service` raises, the stack closes every already-created client once. On normal teardown, leaving the `with ExitStack()` block performs the same teardown and closes each registered client exactly once — no double close, no leak. Injected clients are never owned by the service layer (`FacebookResearchRetriever` never closes its client).

## 3. Error mapping

`src/trendora/api/errors.py` maps the connector taxonomy onto the existing envelope:

| Exception | Status | Code |
| --- | --- | --- |
| `ResearchSourceNotConfiguredError` (no facebook retriever) | 503 | `research_source_not_configured` |
| `FacebookConfigurationError` | 503 | `research_source_not_configured` |
| `FacebookConnectorError` subclasses (HTTP/api/response failures) | 502 | `research_upstream_error` |

Messages are fixed public strings ("The requested source is not configured." / "The upstream source failed."); tokens and upstream details never reach the client.

## 4. Request/response contract

`ResearchRequest` and `ResearchReportRequest` gain optional `facebook_page_id`. Rules (enforced in `ResearchQuery`, unchanged from M25C): nonblank safe Page ID required when `sources=["facebook"]`; mixed Facebook+other sources and page IDs with non-Facebook sources are invalid (422 `invalid_research_request`).

`ResearchMetricsResponse` now always serializes all five nullable metric fields: `view_count`, `like_count`, `comment_count`, `reaction_count`, `share_count`. YouTube runs keep `reaction_count`/`share_count` as `None`; Facebook runs keep `view_count`/`like_count` as `None`; nulls are nulls, source zeros remain `0`.

`ResearchQueryResponse` carries `facebook_page_id` back so request provenance round-trips.

## 5. Exclusions

No frontend, OAuth/Facebook Login, token persistence/refresh, database tables/migrations, seed data, live Meta/provider calls, multi-source Facebook execution, multiple Page IDs, keyword/topic filtering, new dependency, or changes to `web/AGENTS.md` / `web/CLAUDE.md`.

## 6. Live/access risk

Unchanged: no live Meta credentials; live Graph compatibility remains unverified; Meta approval/access is still required before any real Facebook research. The 503-not-503-silence rule guarantees an explicit page request never looks like a completed empty search when unconfigured.

## 7. Files

- `src/trendora/config.py`, `.env.example` (`META_ACCESS_TOKEN`, `META_GRAPH_API_VERSION`)
- `src/trendora/api/app.py` (client construction + `ExitStack`-owned lifecycle in both research dependencies)
- `src/trendora/api/errors.py` (Facebook 503/502 handlers)
- `src/trendora/api/research_models.py` (`facebook_page_id`, five nullable metric fields, response round-trip)
- `tests/unit/test_research_api.py` (12 Facebook app tests + existing-assertion updates)
- `tests/unit/test_research_report_api.py` (3 Facebook report tests + 5 lifecycle tests)
- `tests/unit/test_config.py` (3 Meta settings tests)