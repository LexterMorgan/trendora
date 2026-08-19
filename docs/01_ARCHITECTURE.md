# 01 — Architecture

Status: Target architecture is unchanged. Milestone 1 implemented the configuration layer, SQLAlchemy models, and Alembic schema only. Connectors, APIs, ML, AI, and Streamlit are not implemented.

## Target pipeline

```text
DATA SOURCES
    ↓
PYTHON INGESTION
    ↓
VALIDATION
    ↓
NORMALIZATION
    ↓
POSTGRESQL
    ↓
ANALYTICS + ML
    ↓
AI ORCHESTRATOR
    ↓
FASTAPI
    ↓
STREAMLIT
    ↓
BROWSER
```

## Layer responsibilities

| Layer | Owns | Must not |
| --- | --- | --- |
| Connectors | Fetching allowed public/API payloads | Scraping prohibited surfaces; calling paid vendors |
| Validation / normalization | Canonical records, IDs, timestamps, locale | Inventing metrics the source did not provide |
| PostgreSQL | Source of operational truth | Direct LLM query access |
| Analytics + ML | KPIs, trends, forecasts, anomalies | Delegating numeric truth to an LLM |
| AI orchestrator | Explanation of **structured** Python outputs | Unrestricted DB dumps or raw comment firehoses |
| FastAPI | Internal/read APIs for the dashboard | Becoming a scraping proxy |
| Streamlit | Interactive dashboard | Being replaced by React/Vite |

## Database portability

V1 development database: the existing Supabase PostgreSQL project (`https://ymzloduyggkcmapmiics.supabase.co`, database `postgres`).

The same SQLAlchemy models and Alembic migrations remain portable to local PostgreSQL. Point `DATABASE_URL` at whichever Postgres instance you are using.

The application talks to Postgres through SQLAlchemy and Alembic only. Avoid Supabase-only APIs (PostgREST, Edge Functions, Realtime) in the core data path so local Postgres remains first-class. Models must not hard-code Supabase-specific behavior.

Row Level Security is enabled on application tables (with no policies in Milestone 1) as a PostgreSQL privilege boundary for PostgREST roles. Table owners and the database URL used by Alembic still have access. This is not a domain-layer dependency on Supabase.

## Provider-agnostic AI

Any LLM adapter must be behind an interface with:

- no-op / disabled mode (default, $0-safe)
- optional local/open models later
- optional paid providers only if explicitly enabled

The product must still produce dashboards and statistical results when no LLM is configured.

## Security notes for later phases

- Store API keys only in environment variables / secret managers, never in the repo.
- Development MCPs (GitHub, Supabase, Postgres) are **not** production components and must not be reachable from the Streamlit app.
- If a database MCP is enabled, use read-only or restricted access and never against production data.

## Open decisions (do not implement yet)

- Watchlist size for YouTube channels vs regional `mostPopular` snapshots (quota-bound).
- Whether to apply for YouTube analytics/derived-metrics storage permission (30-day vs 36-month stats).
- Whether Instagram Business Discovery is worth App Review after V1.
- Job scheduler (cron vs later worker) — not chosen.
