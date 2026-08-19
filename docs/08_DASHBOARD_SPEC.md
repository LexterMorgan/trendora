# 08 — Dashboard spec

Status: Phase 0 placeholder. Streamlit is not installed.

## Non-negotiable

The dashboard **must remain Streamlit**. Do not migrate the frontend to React, Vite, Next.js, or similar.

Visualization library direction: Plotly.

## Intended views (later)

Aligned with the product question:

1. **What is happening** — current snapshots by market and topic (YouTube regional charts + watchlist).
2. **Why** — explanations from the AI layer over structured stats (optional).
3. **What is likely next** — Python forecasts, with interval and sample-size caveats.
4. **What we should do** — recommendations generated from rules + optional LLM prose, always citing the KPI IDs.

## Constraints to show in the UI

- Data freshness (`collected_at`, quota exhausted flags)
- Source mix (YouTube vs HN vs SO, etc.)
- “Not from YouTube” disclosure for any Trendora-calculated field shown beside API fields
- Markets without data rather than imputed numbers

## Out of scope for V1 UI

- Posting to social networks
- Ad-manager style campaign buying
- Live TikTok/Instagram firehoses
