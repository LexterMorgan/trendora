# 04 — Ingestion pipeline

Status: Phase 0 placeholder. No ingestion code.

## Intended flow (later)

```text
watchlist / regional charts / public APIs
        ↓
Python connector (quota-aware, backoff, User-Agent)
        ↓
validate payload (schema, IDs, timestamps, region)
        ↓
normalize to canonical content + metric snapshot rows
        ↓
PostgreSQL
```

## V1 sources in scope (if Phase 1 is approved)

See [03_DATA_SOURCES.md](03_DATA_SOURCES.md):

- YouTube Data API v3 (watchlist + `mostPopular` by region)
- YouTube WebSub/Atom for new video IDs
- Hacker News, Stack Exchange, GitHub, Wikipedia, GDELT files

## Hard rules already known

- Honor YouTube quota (especially 100 `search.list`/day). Prefer `videos.list` / `playlistItems.list` / `channels.list`.
- Batch video IDs in `videos.list` (comma-separated ids) to save quota.
- Persist `collected_at` for every metric. YouTube does not supply historical series.
- Enforce YouTube 30-day refresh/delete for non-authorized stats unless Google approves longer storage.
- Never scrape YouTube, Instagram, TikTok, or Facebook.
- Record HTTP status, quota remaining (when provided), and backoff.

## Not specified yet

- Scheduler
- Retry policy numbers
- Idempotency keys
- Dead-letter storage
- Connector package layout

Those wait for Phase 1.
