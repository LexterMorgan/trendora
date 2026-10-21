# Trendora

Current release: **Alpha v0.1**, for local use. Public deployment remains unverified.

A research-first workspace: choose a topic and a timeframe, collect material
from available internet sources, review what those sources actually support, and
keep the result. Built for one owner plus a small shared workflow, not for
company-wide content management.

The point of a report is to be useful on its own. Reading, saving, and reopening
research never requires generating content.

## Who it is for

Personal marketing work: a person who needs a defensible picture of a topic
before writing or planning anything about it.

The problem it addresses is that search results and platform feeds are
fragmented, often undated, and easy to over-read. Trendora collects material for
one topic and window, shows which source supports each statement, and keeps the
limits visible instead of hiding them.

## Core journey

```text
topic + timeframe
  -> collect evidence from the selected sources
  -> review source-backed findings, dates, and coverage
  -> save the research
  -> optionally develop content ideas and briefs
  -> optionally plan a post
```

Everything after saving is optional.

## What works today

| Area | State |
| --- | --- |
| Topic and timeframe research, global by default | Works. YouTube and public web are the default sources. |
| YouTube discovery and enrichment | Works through the YouTube Data API. |
| Public-web search | Works through Serper, or a self-hosted SearXNG instance that also runs bounded public-social discovery. |
| Facebook public Pages | Works when separately configured. Opt-in, public Page posts only, no keyword search. |
| Grounded AI findings | Works. Findings must cite supplied source text; prose quality needs human review. |
| Excerpt fallback | Works. When synthesis is unavailable, malformed, or rejected by grounding, the report shows exact labelled source excerpts instead. |
| Saving, recovery, history, expiry | Works. Snapshots are immutable and recovery is idempotent per request key. The expiry command exists but is not scheduled. |
| Content ideas and briefs | Optional and off by default. Their failure never discards the research. |
| Planner and report import | Works. Statuses are `idea` and `working`; a planned date is a date, and nothing publishes automatically. |
| Auth and membership | Works. Session verification plus active-membership checks gate every read. |

Older ingestion, analytics, and forecasting capabilities still exist in the code.
They are secondary to the research journey and are not required by it.

## Quick start

Python 3.12 and a project virtualenv are required, plus a PostgreSQL target.

Backend, in one terminal (no auto-reload by default):

```bash
.venv/bin/python -m uvicorn trendora.api.app:create_app --factory \
  --host 127.0.0.1 --port 8000
```

Frontend, in another terminal:

```bash
cd web
npm run dev -- --webpack --hostname 127.0.0.1 --port 3000
```

Open <http://127.0.0.1:3000>. Use the same `127.0.0.1` origin everywhere,
including the Supabase Site URL and redirect allowlist, or the session will not
resolve.

Neither command installs dependencies or migrates a database. Stop each server
with Ctrl+C in its own terminal; do not use `pkill` patterns or old PIDs.

Required variable names, the search container, and the optional AI router are
covered in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Tests

```bash
.venv/bin/python -m pytest tests/unit -q     # offline, guarded, no services
cd web && npm test                          # frontend unit tests
cd web && npm run lint && npx tsc --noEmit  # lint and typecheck
```

Database-backed integration tests need an explicitly approved disposable target.
See [docs/10_TESTING_EVALUATION.md](docs/10_TESTING_EVALUATION.md) for those
prerequisites and for what mocked versus live evidence actually establishes.

## Major limitations

- **Freshness.** Publication dates are often unknown, and public-web search does
  not enforce the requested timeframe, so its results stay labelled unverified.
- **Coverage.** Indexed public results are not authenticated scraping and are not
  a complete feed of any platform.
- **Evidence honesty.** Citation validation proves the cited evidence was
  supplied. It does not prove a statement is true or significant.
- **Attention claims.** Current counts and sample prevalence describe the
  returned sample. They do not show growth, and no trend score is invented.
- **Known limits.** Reference selection is bounded at 24 references and is
  source-fair, so a small source keeps its place but a limit below the source
  count cannot cover every source; whitespace-only text is never treated as
  evidence. Live AI prose quality and full deployment remain unverified.
- **Live verification.** AI prose quality and full deployment have not been
  verified. Local operation is not public deployment, and local-first is not
  offline operation.

## Documentation

Start at [docs/README.md](docs/README.md), which states which documents are
authoritative and which are historical.

- [docs/14_PRODUCT_ARCHITECTURE_REBASELINE.md](docs/14_PRODUCT_ARCHITECTURE_REBASELINE.md)
  is the authoritative product scope, capability status, and known gaps.
- [docs/01_ARCHITECTURE.md](docs/01_ARCHITECTURE.md) covers services, data flow,
  persistence, and access boundaries.
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) covers local operation and deployment
  prerequisites.
- [docs/10_TESTING_EVALUATION.md](docs/10_TESTING_EVALUATION.md) covers tests.
- [docs/archive/](docs/archive/README.md) holds superseded milestone records.
  Do not drive new work from them.

## Repository layout

```text
src/trendora/          # backend package
  api/                 #   FastAPI app, auth, research and planner routes
  research/            #   query, coverage, retrievers, evidence, interpretation, saving
  connectors/          #   YouTube, web search, Facebook, plus legacy ingestion clients
  analytics/           #   legacy analytics read layer
  forecasting/         #   legacy forecasting
  models/              #   SQLAlchemy models
  planner.py           #   planner records and report import
  retention.py         #   explicit, dry-run-first expiry
web/                   # Next.js research workspace and planner UI
alembic/               # migrations (0001 through 0008)
tests/unit/            # offline, guarded
tests/integration/     # requires an approved disposable database
docs/                  # current guides and the historical archive
deploy/                # search container configuration
```

## License

Proprietary unless a license is added later.
