# Trendora

AI-powered Social Media Intelligence Platform for Southeast Asian education, AI, and technology markets.

**Status:** Milestone 2A (YouTube watchlist), Milestone 2B (regional YouTube `mostPopular`), and Milestone 3A (Hacker News stories) ingest into the existing schema. FastAPI, Streamlit, analytics, ML, WebSub, and other source connectors are not implemented.

## What Trendora will answer

> What is happening across Southeast Asian education and technology markets, why is it happening, what is likely to happen next, and what should we do next?

Primary markets: Indonesia, Thailand, Malaysia, Singapore, Vietnam, Philippines.

Primary domain: AI education, technology education, data science, programming, digital skills, STEM, online learning, scholarships, and technology/career education.

## Core principle

Python owns the truth. AI owns the explanation.

Python will calculate KPIs, trends, forecasts, anomalies, and statistical results. An LLM, if used at all, interprets structured outputs. The LLM will not receive unrestricted raw database access.

The product dashboard will remain Streamlit. The frontend will not be switched to React/Vite.

## Current milestone

Milestones 2A, 2B, and 3A are the implemented ingestion paths: a curated YouTube watchlist, regional YouTube `mostPopular` charts, and Hacker News top/new/best stories. See:

- [docs/04_INGESTION_PIPELINE.md](docs/04_INGESTION_PIPELINE.md) — connectors, config, and how to run them
- [PROJECT_PREP.md](PROJECT_PREP.md) — environment, MCP, and setup notes
- [docs/01_ARCHITECTURE.md](docs/01_ARCHITECTURE.md) — layer boundaries and V1 database decision
- [docs/02_DATABASE_SCHEMA.md](docs/02_DATABASE_SCHEMA.md) — tables, constraints, migrations
- [docs/03_DATA_SOURCES.md](docs/03_DATA_SOURCES.md) — verified source research (read this before any connector work)

## Technology direction

| Layer | Direction | Now |
| --- | --- | --- |
| Language | Python 3.12+ | Installed |
| Database | PostgreSQL via SQLAlchemy + Alembic | Installed |
| V1 development DB | Existing Supabase PostgreSQL project | In use |
| HTTP | httpx (YouTube Data API v3 client) | Installed |
| Connectors | YouTube watchlist + mostPopular; Hacker News stories | M2A + M2B + M3A |
| API | FastAPI | Not installed |
| Dashboard | Streamlit + Plotly | Not installed |
| Data / ML | Pandas, NumPy, scikit-learn, statsmodels | Not installed |
| AI | Provider-agnostic, optional, $0-safe | Not installed |

Do not make the core system depend on paid APIs, paid datasets, paid LLMs, paid scrapers, or paid infrastructure.

## Local setup

Python 3.12 is required. The macOS Command Line Tools `python3` on this machine is 3.9.6 and is past end-of-life.

A project virtualenv is already present (CPython 3.12.14):

```bash
source .venv/bin/activate
python --version
pip install -e ".[dev]"
```

If you recreate the virtualenv, use [uv](https://docs.astral.sh/uv/) rather than the macOS system `python3`:

```bash
uv python install 3.12
uv venv --python 3.12
source .venv/bin/activate
pip install -e ".[dev]"
```

### Environment variables

Copy the template and fill in secrets locally. Never commit `.env`.

```bash
cp .env.example .env
```

Required for Alembic and any live database session:

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | PostgreSQL URL. Use `postgresql+psycopg://…?sslmode=require` for Supabase. `postgresql://` and `postgres://` are accepted and rewritten to the psycopg driver. |
| `APP_ENV` | Optional. Defaults to `development`. |
| `APP_NAME` | Optional. Defaults to `trendora`. |
| `LOG_LEVEL` | Optional. Defaults to `INFO`. |
| `YOUTUBE_API_KEY` | Required to run YouTube ingestion. YouTube Data API v3 key. Leave empty for unit tests. |
| `YOUTUBE_CHANNEL_IDS` | Comma-separated 24-character channel IDs (`UC…`). Handles and URLs are rejected. Required for watchlist ingest only; `most-popular` does not use this list. |
| `YOUTUBE_MAX_VIDEOS_PER_CHANNEL` | Optional. Caps uploads fetched per watchlist channel (default 50, max 500). |

V1 development uses the existing Supabase project (`https://ymzloduyggkcmapmiics.supabase.co`, database `postgres`). Copy the URI from Supabase → Project Settings → Database. Do not put the password in source, tests, or docs.

The same models work against a later local PostgreSQL URL. Do not hard-code Supabase APIs into the domain layer.

### Migrations

Alembic is the application migration tool. From the repository root, with `.venv` active and `DATABASE_URL` set:

```bash
alembic current
alembic upgrade head
```

The initial revision is `0001_initial_schema`. It creates Trendora application tables in `public` only. It does not drop unrelated Supabase schemas.

If the V1 database already has `alembic_version.version_num = 0001_initial_schema`, `alembic upgrade head` is a no-op.

### YouTube ingestion (Milestones 2A and 2B)

Manual, on-demand only. This is not a scheduler.

Watchlist (M2A):

```bash
python -m trendora.connectors.youtube
# equivalent:
trendora-ingest-youtube
```

Optional watchlist overrides:

```bash
python -m trendora.connectors.youtube --channel-ids UCxxxxxxxxxxxxxxxxxxxxxx --max-videos 20
```

Regional mostPopular (M2B). Default markets are ID, TH, MY, SG, VN, PH. Default cap is 50 videos per market. Does not require `YOUTUBE_CHANNEL_IDS`. Does not crawl discovered channels with `playlistItems.list`.

```bash
python -m trendora.connectors.youtube most-popular
python -m trendora.connectors.youtube most-popular --markets ID,SG
python -m trendora.connectors.youtube most-popular --max-videos 20
```

`regionCode` is stored as chart-origin metadata. `market_id` is still taken only from the channel `snippet.country` when it is a seeded SEA code.

Both paths store publishers, content items, and append-only `metric_snapshots` (view/like/comment counts, plus channel view/subscriber/video counts when present). YouTube non-authorized stats and metadata get `retain_until` from the existing 30-day policies. Neither path uses `search.list`.

Unit tests mock HTTP and never send `YOUTUBE_API_KEY` to Google.

### Hacker News ingestion (Milestone 3A)

Manual, on-demand only. This is not a scheduler. Uses the official Firebase API. Does not scrape. Does not ingest HN users.

```bash
python -m trendora.connectors.hackernews
# equivalent:
trendora-ingest-hackernews
```

Optional overrides:

```bash
python -m trendora.connectors.hackernews --feeds topstories --max-items 5
python -m trendora.connectors.hackernews --feeds topstories,beststories --max-items 20
```

Defaults are `topstories,newstories,beststories` and 50 items per feed. Stories are stored as `content_items` (`content_type=story`) with append-only `score` and `comment_count` snapshots. `market_id` is unset. HN authors are not created as publishers. Does not require YouTube configuration.

### Tests

```bash
pytest tests/unit -v
```

PostgreSQL integration tests are skipped unless `DATABASE_URL` (or `TRENDORA_TEST_DATABASE_URL`) is exported in the process environment:

```bash
pytest tests/integration -v
```

Do not point integration tests at a database you are not willing to read. Unit tests do not consume YouTube quota.

## Repository layout

```text
src/trendora/          # application package
  config.py            # pydantic-settings
  db/                  # engine, session, declarative Base
  models/              # SQLAlchemy models
  reference.py         # deterministic V1 seed rows
  connectors/          # YouTube (M2A/M2B) and Hacker News (M3A)
alembic/               # Alembic env + versions
tests/unit/            # no database required
tests/integration/     # PostgreSQL, skipped without DATABASE_URL
docs/                  # architecture and research documents
.cursor/               # MCP example config (not live credentials)
```

`.cursor/` is gitignored except for example files. Do not commit `.cursor/mcp.json` or `.env`.

## License

Proprietary unless a license is added later.
