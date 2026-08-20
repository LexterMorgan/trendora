# 04 — Ingestion pipeline

Status: Milestone 2A implements a curated YouTube watchlist connector. Milestone 2B adds a sibling regional `mostPopular` ingest. Other sources, WebSub, Atom, FastAPI, and scheduling are not implemented.

## Implemented flow (M2A — curated watchlist)

```text
YOUTUBE_CHANNEL_IDS (explicit UC… watchlist)
        ↓
YouTube Data API v3 (httpx)
  channels.list
  playlistItems.list (uploads playlist, paginated, capped)
  videos.list (batched by id)
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

## Implemented flow (M2B — regional mostPopular)

```text
regionCode (ID, TH, MY, SG, VN, PH)
        ↓
videoCategories.list (per requested region)
        ↓
videos.list?chart=mostPopular (paginated, maxResults ≤ 50, capped)
        ↓
unique channel IDs from chart videos
        ↓
channels.list (hydrate identity/statistics only)
        ↓
group chart videos by channel → normalize → attach chart metadata → persist
```

M2B is a second YouTube social-observation signal: what is currently popular in each seeded SEA market. It reuses the existing M1/M2A tables. There is no schema migration.

Chart-only channels are **not** added to `YOUTUBE_CHANNEL_IDS` and are **never** crawled with `playlistItems.list`. `search.list` is not used.

### regionCode vs market_id

`regionCode` is the chart observation origin. It is stored as additive `source_metadata` on the video (`chart`, `region_codes`, category title, optional `chart_positions_by_region`).

`publisher.market_id` / `content_item.market_id` still come only from the channel `snippet.country` when that country is one of `ID`, `TH`, `MY`, `SG`, `VN`, `PH`. Otherwise `market_id` remains unset.

Example: a US publisher appearing on the Indonesian mostPopular chart is stored with `region_codes = ["ID"]` and `market_id = NULL`.

If the same video appears in multiple regional charts in one run, region codes are merged before persist. One timezone-aware `collected_at` is used for the whole run, so there is one metric snapshot set for that timestamp rather than one per region.

YouTube category IDs are not mapped onto Trendora topics.

## How to configure

Set these in `.env` (never commit the real key):

| Variable | Role |
| --- | --- |
| `YOUTUBE_API_KEY` | YouTube Data API v3 key from Google Cloud Console. Required for both M2A and M2B. |
| `YOUTUBE_CHANNEL_IDS` | Comma-separated 24-character channel IDs starting with `UC`. Required for M2A only. M2B does not use this list. |
| `YOUTUBE_MAX_VIDEOS_PER_CHANNEL` | Cap on uploads fetched per watchlist channel (default 50). M2A only. |

Missing API key fails with an actionable error. Handles (`@name`) and channel URLs are rejected for the watchlist. M2B rejects unknown market codes.

## How to run (manual)

Watchlist (M2A), unchanged:

```bash
source .venv/bin/activate
python -m trendora.connectors.youtube
```

Regional mostPopular (M2B):

```bash
python -m trendora.connectors.youtube most-popular
python -m trendora.connectors.youtube most-popular --markets ID,SG
python -m trendora.connectors.youtube most-popular --max-videos 20
```

Defaults for `most-popular`: markets `ID,TH,MY,SG,VN,PH`; 50 videos per market. Pagination stops when that cap is reached. `maxResults` is never greater than 50.

Neither command is started by tests, install, or a scheduler.

## What is stored

Using the existing schema only (no M2A/M2B migration):

- `publishers` — YouTube channel identity `(source=youtube, external_id=channel_id)`
- `content_items` — videos `(source=youtube, external_id=video_id)`, `content_type=video`
- `metric_snapshots` — append-only observations:
  - video: `view_count`, `like_count`, `comment_count` when the API provides them
  - channel: `view_count`, `subscriber_count`, `video_count` when the API provides them
- Source-specific extras go in `source_metadata` JSONB (duration, category, custom URL, M2B chart/region metadata, etc.)
- `market_id` is set only when `snippet.country` matches a seeded SEA market code (ID, TH, MY, SG, VN, PH). Other countries are left unset.

YouTube does not provide historical series. `observed_at` and `collected_at` are both the timezone-aware ingest timestamp for these current snapshots.

Re-running ingestion upserts publisher/content identity rows and inserts **new** snapshots when `collected_at` differs. The same `collected_at` does not duplicate a metric row. An M2B chart video that overlaps an M2A identity reuses that row.

## Retention

M2A and M2B use the existing policies from Milestone 1 / [03_DATA_SOURCES.md](03_DATA_SOURCES.md):

- `youtube_non_authorized_stats` (30 days) on metric snapshots (`retention_policy_id`, `retain_until`)
- `youtube_non_authorized_metadata` (30 days) on publisher and content `retain_until`

No new retention period was invented. Cleanup jobs are still not implemented.

## Tests and quota

Unit tests inject `httpx.MockTransport` or a fake client. They must not call Google and do not need a real API key.

PostgreSQL persistence tests are integration tests: they skip without `DATABASE_URL` / `TRENDORA_TEST_DATABASE_URL`, roll back, and never call YouTube. Assertions are scoped to fixture `external_id` values because the database may already contain real M2A watchlist rows.

Approximate Data API costs (1 unit each): `videoCategories.list`, `videos.list`, `channels.list`. A six-market M2B run at 50 videos/market is on the order of tens of quota units. Do not use `search.list`.

## Package layout

```text
src/trendora/connectors/
  base.py                 # Connector protocol + IngestionResult
  youtube/
    client.py             # HTTP only
    schemas.py            # API resource models
    normalizer.py         # YouTube → domain records
    persistence.py        # SQLAlchemy writes
    connector.py          # M2A watchlist orchestration
    most_popular.py       # M2B regional chart orchestration
    watchlist.py
    cli.py
```

Future sources should add a sibling package. Do not put Instagram/TikTok/etc. stubs here.

## Hard rules still in force

- Honor YouTube quota. Prefer `videos.list` / `playlistItems.list` / `channels.list` / `videoCategories.list` (1 unit each).
- Batch video/channel IDs in list calls. Paginated `mostPopular` uses `maxResults` ≤ 50.
- Never scrape YouTube.
- Do not silently swallow HTTP, API, validation, or database integrity errors.

## Not in M2A / M2B

- Scheduler / cron / workers
- OAuth / YouTube Analytics API
- WebSub / Atom
- `search.list` / playlist crawling of chart-discovered channels
- Other source connectors
- FastAPI / Streamlit / analytics / ML / AI
