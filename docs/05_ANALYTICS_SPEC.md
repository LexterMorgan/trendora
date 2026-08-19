# 05 — Analytics spec

Status: Phase 0 placeholder.

## Principle

Python computes all KPIs. The dashboard and any LLM consume **precomputed** results.

## Candidate KPI families (not finalized)

Driven by the product question and by what V1 sources actually return:

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

Details to specify in a later phase: window lengths, missing-data rules, language detection, topic taxonomy.
