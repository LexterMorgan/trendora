# Trendora — project preparation

This file started as the Phase 0 audit (2026-08-18). The historical sections below are kept. Where they conflict with Milestone 1, the status in this section wins.

## Current status (Milestone 21 — 2026-09-01)

Milestone 2A–4 ingestion, Milestone 5 (analytics), Milestone 6A (in-memory naive / MA / SES), Milestone 6C (in-memory naive-vs-challenger MAE comparison), Milestone 7 (in-memory series diagnostics), Milestone 8 (product contract), Milestone 10 (V1 GitHub forecast product), Milestone 11B (FastAPI adapter), Milestone 13 (research core), Milestone 14 (YouTube-first research retrieval), Milestone 15 (research API boundary), Milestone 16 (research workspace UI), Milestone 17 (evidence facts + observations), Milestone 18 (deterministic pattern aggregation), Milestone 19 (grounded AI-interpretation contract), Milestone 20 (AI provider adapter + grounded execution), and Milestone 21 (content gaps & opportunities) are implemented. Milestone 6B remains the evaluation/model-selection write-up in [docs/06_ML_FORECASTING.md](docs/06_ML_FORECASTING.md). Milestone 9 decides the V1 forecasting product requirements in [docs/12_FORECASTING_PRODUCT_REQUIREMENTS.md](docs/12_FORECASTING_PRODUCT_REQUIREMENTS.md). Milestone 11A/M11B define and implement the forecast API contract ([docs/13](docs/13_FORECASTING_API_CONTRACT.md), `src/trendora/api/`). Milestone 12 re-baselines the product direction in [docs/14_PRODUCT_ARCHITECTURE_REBASELINE.md](docs/14_PRODUCT_ARCHITECTURE_REBASELINE.md).

Milestone 21 adds `src/trendora/research/strategy.py`: `ContentGap` (claim_type AI_INTERPRETATION, cites deterministic evidence + supporting interpretation indexes), `Opportunity` (claim_type RECOMMENDATION, gap_indexes + citations), `StrategicContext`, `StrategicResult`, `validate_strategic_result`, `OpenAICompatibleStrategyProvider`, and `GroundedStrategyService`. Reuses M20 transport/config/provenance; `ClaimType` gains `recommendation`. No deterministic prevalence→gap rules. Backend full suite: **694 passing** (644 + 50 new). No forecast tables, Streamlit, or ML libraries.

- Git remote: `https://github.com/LexterMorgan/trendora.git` (branch `main`; no commits required by this milestone).
- Python: `.venv` with CPython 3.12.14. Runtime packages: SQLAlchemy, psycopg, Alembic, pydantic-settings, httpx, FastAPI (added M11B). Dev: pytest. Streamlit, pandas, and ML libraries are still not installed. M6A baselines use the standard library.
- V1 development database: existing Supabase PostgreSQL project `https://ymzloduyggkcmapmiics.supabase.co` (database `postgres`). Local PostgreSQL remains a portable target for the same SQLAlchemy models; it is not required for V1.
- Application tables live in `public` and were created by Alembic revision `0001_initial_schema`. Milestones 5–7 reuse that schema; no analytics, forecast, or diagnostic tables were added. Details: [docs/02_DATABASE_SCHEMA.md](docs/02_DATABASE_SCHEMA.md).
- Required env var: `DATABASE_URL`. Copy `.env.example` to `.env` locally. Never commit `.env` or `.cursor/mcp.json`.
- Supabase MCP is available in this development environment and was used to verify the applied schema. Prefer `read_only=true` for day-to-day inspection. Do not treat MCP as a production component.

Stale Phase 0 claims to ignore: “no remote”, “no application code”, “do not install SQLAlchemy”, “no Supabase project”, “development database is local PostgreSQL only”, “recommended next step is still Phase 0”.

Recommended next milestone: only if requested. Do not assume WebSub, Atom, other sources, or a scheduler.

Research date: 2026-08-18.

## 1. Workspace state

- Path: `/Users/lex/Projects/trendora`
- The folder was empty except for a newly initialized Git repository.
- Created a minimal Python package layout (`src/trendora`, `tests`, `pyproject.toml`) and documentation under `docs/`.
- No application code, connectors, models, or dashboard were implemented.

## 2. Git state

- Git was already initialized.
- Branch: `main`
- No commits existed at the start of Phase 0.
- Remote at Phase 0 start: none. Later: `https://github.com/LexterMorgan/trendora.git` (see Current status above).

## 3. Python environment state

- System interpreter: `/usr/bin/python3` → CPython 3.9.6 from Apple Command Line Tools. **This version is past end-of-life and must not be used for Trendora.**
- Homebrew Python was not installed (a system-wide `brew install python@3.12` was not performed).
- Project-local [uv](https://docs.astral.sh/uv/) 0.12.5 was placed in `.tools/uv` (gitignored) and used to create `.venv` with **CPython 3.12.14**.
- Phase 0 venv extras were only `pip`, `setuptools`, `wheel`. Milestone 1 added SQLAlchemy, psycopg, Alembic, pydantic-settings, and pytest. FastAPI, Streamlit, pandas, and ML libraries are still not installed.
- Target recorded in `.python-version` and `requires-python = ">=3.12"` in `pyproject.toml`.
- Activate with: `source .venv/bin/activate`

## 4. MCPs already available

In this Cursor workspace, only **cursor-app-control** was connected. That server controls Cursor itself (workspace root, projects, opening resources). It is not a GitHub, Postgres, or documentation MCP.

Cursor already provides first-party filesystem/codebase tools and web fetch/search. A separate filesystem MCP is **not** recommended.

## 5. MCPs recommended (development only)

MCPs are development/research tools. They are **not** part of the production application. The production app will use Python API clients.

| Category | Recommendation | Why | When to enable |
| --- | --- | --- | --- |
| GitHub | Official GitHub MCP (`github/github-mcp-server`) | Repo, issues, PRs, commits | After a GitHub remote exists and a PAT can be created |
| Postgres (local) | [crystaldba/postgres-mcp](https://github.com/crystaldba/postgres-mcp) (`postgres-mcp` on PyPI) | Inspect schema, run read-mostly SQL, explain plans | After local PostgreSQL and a Trendora database exist |
| Supabase | Official hosted MCP `https://mcp.supabase.com/mcp` | Cloud schema, docs search, read-only SQL | After a free Supabase project exists; use `read_only=true` |
| Library docs | Context7 remote MCP | Current FastAPI / SQLAlchemy / Streamlit docs | Optional now; does not replace official platform API research |
| Filesystem | **Do not add** | Cursor already has workspace file tools | — |
| Per-platform social MCPs | **Do not add** | Production uses Python connectors, not MCPs | — |

The archived npm package `@modelcontextprotocol/server-github` is deprecated (April 2025). Do not use it.

The original `@modelcontextprotocol/server-postgres` reference server is archived. Prefer `postgres-mcp` (read-restricted) for local Postgres, and official Supabase MCP for hosted Postgres.

## 6. MCPs successfully configured

None live. Credentials and a running database are required. Exact JSON is in `.cursor/mcp.json.example`.

Do not copy that file to `.cursor/mcp.json` until tokens exist. `.cursor/mcp.json` is gitignored so secrets are not committed.

## 7. MCPs requiring manual setup

### GitHub MCP (official)

Purpose: inspect repositories, commits, branches, issues, and pull requests.

Verified useful: yes, once Trendora has a GitHub remote. Not useful before that.

Cannot be completed automatically: official Cursor guide currently requires a GitHub Personal Access Token. Docker is not installed on this machine, so the local Docker server is also blocked.

Cursor config (project or `~/.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "github": {
      "url": "https://api.githubcopilot.com/mcp/",
      "headers": {
        "Authorization": "Bearer YOUR_GITHUB_PAT"
      }
    }
  }
}
```

Create a fine-grained PAT with the minimum repo scopes needed. After saving, restart Cursor and confirm a green status under Settings → Tools & MCP.

Official sources:

- https://github.com/github/github-mcp-server
- https://github.com/github/github-mcp-server/blob/main/docs/installation-guides/install-cursor.md

### Supabase MCP (official)

Purpose: inspect hosted schema, run SQL, search Supabase docs.

Verified useful: yes for production/staging Supabase. Not useful until a project exists.

Cursor config:

```json
{
  "mcpServers": {
    "supabase": {
      "url": "https://mcp.supabase.com/mcp?read_only=true"
    }
  }
}
```

Cursor should prompt a browser OAuth login. Scope later with `project_ref=` once the project ref is known.

Official source: https://supabase.com/docs/guides/ai-tools/mcp

Security: do not point this MCP at production data. Prefer a development project and `read_only=true`.

Local Supabase CLI also exposes `http://localhost:54321/mcp`. That path is unused until the CLI is adopted. Trendora’s stated development database is local PostgreSQL, not necessarily local Supabase.

### Local PostgreSQL MCP (`postgres-mcp`)

Purpose: inspect the development database that SQLAlchemy/Alembic will manage.

Verified useful: yes after Postgres is running. PostgreSQL 18 binaries are present via Homebrew (`psql` on PATH) but `pg_isready` reported nothing listening on port 5432.

Do not enable write-unrestricted mode against any database that matters. Use `--access-mode=restricted` or a dedicated read-only role.

Docker is not installed, so the Docker image path is unavailable. Python/`uv` path from the upstream README:

```json
{
  "mcpServers": {
    "postgres": {
      "command": "uv",
      "args": ["run", "postgres-mcp", "--access-mode=restricted"],
      "env": {
        "DATABASE_URI": "postgresql://trendora:trendora@localhost:5432/trendora"
      }
    }
  }
}
```

Official source: https://github.com/crystaldba/postgres-mcp

### Context7 (library documentation)

Purpose: fetch current Python library docs during later implementation.

Verified useful: yes for FastAPI, SQLAlchemy, Alembic, Streamlit, Plotly. Not a substitute for YouTube/Meta/TikTok official API docs (those were researched with first-party developer sites).

Remote config without a key (lower rate limits):

```json
{
  "mcpServers": {
    "context7": {
      "url": "https://mcp.context7.com/mcp"
    }
  }
}
```

Optional: `npx ctx7 setup --cursor` for OAuth/API key. A free key is documented for higher limits.

Official source: https://context7.com/docs/clients/cursor

## 8. Data sources

Full research: [docs/03_DATA_SOURCES.md](docs/03_DATA_SOURCES.md).

## 9. Recommended MVP data sources

Smallest realistic V1 set under a $0 / legitimate-access constraint:

1. **YouTube Data API v3** — only source among major social platforms with a documented free public-read path that can cover SEA regions and education/tech categories.
2. **YouTube Atom / WebSub topic URL** — official new-video notifications for a curated channel watchlist (no statistics).
3. **Hacker News official Firebase API** — free, no auth, global tech signal (not SEA-specific).
4. **Stack Exchange API** — free public Q&A for programming/data-science topics (not SEA-specific).
5. **GitHub REST API** — free authenticated public read for tech-education repository activity (not social media).
6. **Wikimedia Action API** — free encyclopedic context, not social metrics.
7. **GDELT 2.0 raw files over HTTP** — free news/event context. Avoid assuming BigQuery is $0.

Instagram Business Discovery is the only Meta path that can observe *other* professional accounts, and only after a professional account, tokens, and likely App Review. It is **not** in the V1 set.

Facebook, TikTok market-wide data, X/Twitter reads, and LinkedIn are **not** V1.

## 10. Important API limitations

- YouTube default quota: 10,000 units/day for most methods, plus a separate **100 `search.list` calls/day** and **100 `videos.insert` calls/day**. Search cannot be the discovery engine.
- YouTube does **not** return historical view/like/comment time series. `videos.list` statistics are current snapshots. Any trend line is something Trendora would have to collect itself.
- YouTube Developer Policies: **non-authorized statistics must not be stored more than 30 days** unless the analytics/derived-metrics amendment is approved via the quota extension / compliance audit path (from 1 June 2026). Default V1 must refresh-or-delete public stats within 30 days. Titles/descriptions stay on the 30-day refresh rule even if stats storage is later approved (then stats may be kept up to 36 months).
- YouTube scraping is prohibited. Unofficial scrapers are not a fallback.
- Instagram/Facebook Graph access is account-scoped. There is no free firehose of SEA public posts.
- TikTok Research Tools are academic/non-profit, limited regions, and **commercial users are ineligible**. Display API is the authorizing user’s own content.
- Official X/Twitter documentation could not be fetched (HTTP 403). Do not treat X as a $0 read source until official access tiers are verified in a logged-in developer portal.
- Official Reddit Data API wiki could not be fetched (Cloudflare). Treat Reddit as unverified; a product like Trendora is likely commercial use.
- OpenAlex remains useful for scholarly context but now has usage-based API billing with a free daily allowance. Confirm current pricing before any pipeline depends on it.
- Local PostgreSQL is installed (Homebrew `postgresql@18`) but was **not running** during this audit.

## 11. Documentation files created

See the `docs/` directory listing in the Phase 0 report. `docs/03_DATA_SOURCES.md` is the only fully researched document.

## 12. Blockers

1. Default shell `python3` is still Apple 3.9.6. Always activate `.venv` (3.12.14) or put it on PATH.
2. GitHub remote now exists; GitHub MCP still needs a PAT if you want that MCP.
3. Local PostgreSQL is optional. V1 uses the existing Supabase project. Local `postgres-mcp` still needs a running local server if you enable it.
4. Supabase project exists; keep MCP scoped to development. Prefer `read_only=true` for inspection.
5. YouTube analytics storage / derived metrics need an explicit Google audit path before multi-month historical stats are policy-compliant.
6. Meta/TikTok/X/Reddit cannot legally supply a market-wide SEA social firehose on a $0 budget.
7. Docker is not installed (needed only if the local GitHub MCP Docker path is chosen).
8. `DATABASE_URL` is not committed. Create a local `.env` from `.env.example` before running Alembic from this machine.

## 13. Recommended next step

Phase 0 originally stopped here. Milestone 1 (schema) is now done. Do **not** start the YouTube connector until that milestone is requested.

If continuing setup only:

1. Confirm `.venv` is active (Python 3.12.14) and `pip install -e ".[dev]"` has been run.
2. Copy `.env.example` to `.env` and set `DATABASE_URL` from Supabase → Project Settings → Database. Never commit `.env`.
3. Optional: start local PostgreSQL later if you want a second portable target. Not required for V1.
4. Optionally add GitHub MCP with a PAT.
5. When the next milestone is requested: implement the YouTube connector only (curated watchlist + snapshot collection), staying inside 10,000 units/day and the 30-day storage rule.

Do not start the YouTube connector in this milestone.
