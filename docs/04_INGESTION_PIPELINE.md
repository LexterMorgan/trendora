# 04 — Ingestion pipeline

Status: Milestone 2A implements a curated YouTube watchlist connector only. Other sources, WebSub, regional `mostPopular`, and scheduling are not implemented.

## Implemented flow (M2A)

```text
YOUTUBE_CHANNEL_IDS (explicit UC… watchlist)
        ↓
YouTube Data API v3 (httpx)
  channels.list
  playlistItems.list (uploads playlist, paginated, capped)
  videos.list (batched)
        ↓
validate resource shape
        ↓
normalize to publisher / content_item / metric_snapshot records
        ↓
SQLAlchemy persist (existing Milestone 1 tables)
        ↓
PostgreSQL
```

`search.list` is not used. There is no discovery crawler.

## How to configure

Set these in `.env` (never commit the real key):

| Variable | Role |
| --- | --- |
| `YOUTUBE_API_KEY` | YouTube Data API v3 key from Google Cloud Console |
| `YOUTUBE_CHANNEL_IDS` | Comma-separated 24-character channel IDs starting with `UC` |
| `YOUTUBE_MAX_VIDEOS_PER_CHANNEL` | Cap on uploads fetched per channel (default 50) |

Missing API key or an empty watchlist fails with an actionable error. Handles (`@name`) and channel URLs are rejected.

## How to run (manual)

```bash
source .venv/bin/activate
python -m trendora.connectors.youtube
```

This loads settings, fetches the watchlist, normalizes, persists, and logs a summary. It is not started by tests, install, or a scheduler.

## What is stored

Using the existing schema only (no M2A migration):

- `publishers` — YouTube channel identity `(source=youtube, external_id=channel_id)`
- `content_items` — videos `(source=youtube, external_id=video_id)`, `content_type=video`
- `metric_snapshots` — append-only observations:
  - video: `view_count`, `like_count`, `comment_count` when the API provides them
  - channel: `view_count`, `subscriber_count`, `video_count` when the API provides them
- Source-specific extras go in `source_metadata` JSONB (duration, category, custom URL, etc.)
- `market_id` is set only when `snippet.country` matches a seeded SEA market code (ID, TH, MY, SG, VN, PH). Other countries are left unset.

YouTube does not provide historical series. `observed_at` and `collected_at` are both the timezone-aware ingest timestamp for these current snapshots.

Re-running ingestion upserts publisher/content identity rows and inserts **new** snapshots when `collected_at` differs. The same `collected_at` does not duplicate a metric row.

## Retention

M2A uses the existing policies from Milestone 1 / [03_DATA_SOURCES.md](03_DATA_SOURCES.md):

- `youtube_non_authorized_stats` (30 days) on metric snapshots (`retention_policy_id`, `retain_until`)
- `youtube_non_authorized_metadata` (30 days) on publisher and content `retain_until`

No new retention period was invented. Cleanup jobs are still not implemented.

## Tests and quota

Unit tests inject `httpx.MockTransport` or a fake client. They must not call Google and do not need a real API key.

PostgreSQL persistence tests are integration tests: they skip without `DATABASE_URL` / `TRENDORA_TEST_DATABASE_URL`, roll back, and never call YouTube.

## Package layout

```text
src/trendora/connectors/
  base.py                 # Connector protocol + IngestionResult
  youtube/
    client.py             # HTTP only
    schemas.py            # API resource models
    normalizer.py         # YouTube → domain records
    persistence.py        # SQLAlchemy writes
    connector.py          # orchestration
    watchlist.py
    cli.py
```

Future sources should add a sibling package. Do not put Instagram/TikTok/etc. stubs here.

## Hard rules still in force

- Honor YouTube quota. Prefer `videos.list` / `playlistItems.list` / `channels.list` (1 unit each).
- Batch video IDs in `videos.list`.
- Never scrape YouTube.
- Do not silently swallow HTTP, API, validation, or database integrity errors.

## Not in M2A

- Scheduler / cron / workers
- OAuth / YouTube Analytics API
- WebSub / Atom
- Regional `mostPopular`
- Other source connectors
- FastAPI / Streamlit / analytics / ML / AI
