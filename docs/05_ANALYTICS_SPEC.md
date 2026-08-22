# 05 — Analytics spec

Status: Milestone 5 implements a deterministic observation/query foundation over existing `metric_snapshots`. Candidate KPI families below are **not finalized** and are **not implemented as formulas** in M5.

## Principle

Python owns the truth. AI owns the explanation.

Python computes numerical results. Future dashboard, API, and LLM layers consume **precomputed** structured contracts. They must not recalculate the underlying observations.

M5 works with no AI provider. It does not add an LLM SDK.

## M5 — observation foundation (implemented)

M5 is a read-only analytics layer in `src/trendora/analytics/`. It queries the existing M1 schema. It does not add tables, migrations, or a second metrics store.

Contracts:

- `MetricObservation` — one stored snapshot (source, metric, value, subject, `observed_at`, `collected_at`, optional content/publisher/market identity)
- `MetricSeries` — deterministically ordered observations; empty series are valid; missing points are not fabricated
- `AggregateSummary` — Trendora-derived aggregates only, labeled `origin=trendora_derived`

Time filter on `observed_at`:

`observed_from <= observed_at < observed_until` (inclusive start, exclusive end). Timezone-naive datetimes are rejected.

Ordering: `observed_at`, then `collected_at`, then snapshot id.

Safe aggregations only:

- `count`
- `earliest_observed_at`
- `latest_observed_at`
- `latest_value` (requires a subject + metric_name)

`sum`, means, engagement ratios, market share, topic velocity, anomaly scores, and a composite Trendora Score are **not** implemented.

Source observations remain distinguishable from Trendora-derived aggregates. Official API fields (for example YouTube `view_count`) are returned as stored. They are not rewritten into new business metrics.

M5 is not a dashboard and not AI. M6A consumes these contracts for in-memory baselines.

## Candidate KPI families (not finalized)

Driven by the product question and by what V1 sources actually return. These remain candidates. M5 does not treat them as implemented formulas.

| Family | Example (YouTube-shaped) | Caveat |
| --- | --- | --- |
| Volume | new videos/day on watchlist; regional mostPopular counts | Search cannot enumerate “all SEA education” |
| Reach | current `viewCount` snapshots | Cumulative, not unique viewers; 30-day storage rule |
| Engagement | likes, comments vs views | Dislikes not public; ratios may be “derived metrics” needing YouTube amendment |
| Market mix | share of watchlist items by `regionCode` / language / categoryId | Category IDs must be fetched per region |
| Tech attention overlay | HN score, SO tag velocity, GitHub stars | Not SEA-specific |

## Explicitly not V1 until policy/access exists

- TikTok/Instagram market share
- Facebook Page competitive insights
- X keyword volumes
- Multi-year YouTube history without Google’s analytics storage approval
- Campaign lift / ad attribution (no ads APIs in V1)

## Derived metrics vs raw API fields

YouTube policy III.E.4.h restricts creating new metrics from API data unless the analytics amendment is accepted. Until then, prefer displaying official fields (viewCount, likeCount, commentCount) with timestamps, and keep any composite “Trendora score” behind a later legal review.

M5 preserves official observations as collected. It does not create an engagement ratio or other composite YouTube metrics.

Details to specify in a later phase: window lengths, missing-data rules, language detection, topic taxonomy.
