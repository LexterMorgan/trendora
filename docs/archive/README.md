# Documentation archive

These files are historical milestone records. They describe what was planned,
decided, and verified at the time they were written. They are kept for
rationale, acceptance criteria, and traceability.

Rules for readers and coding agents:

- Do not use anything here as the current statement of behaviour or scope.
- The authoritative documents are listed in [../README.md](../README.md).
- Where an archived contract disagrees with the code, the code wins. Where it
  disagrees with [../14_PRODUCT_ARCHITECTURE_REBASELINE.md](../14_PRODUCT_ARCHITECTURE_REBASELINE.md),
  the PRD wins.
- Legacy ingestion, analytics, and forecasting capabilities described here may
  still exist in the code. They are secondary to the research-first product.
  Archiving these documents is not a claim that the capability was removed.
- Files were moved without editing, apart from relative links that had to be
  repointed one level up. Dates, status lines, and acceptance criteria are as
  originally written.
- Two links in `12_FORECASTING_PRODUCT_REQUIREMENTS.md` point at
  `00_PROJECT_OVERVIEW.md`, which was deleted before this archive existed.
  Nothing was restored to satisfy them.

## What is archived

| File | Original subject | Why it is here |
| --- | --- | --- |
| `02_DATABASE_SCHEMA.md` | Milestone 1 schema and `0001_initial_schema` | Milestone record. Schema has since grown to `0008`; the migrations are the source of truth. |
| `03_DATA_SOURCES.md` | Twelve candidate sources, connector policy | Milestone record kept because `src/trendora/reference.py` cites this path. |
| `04_INGESTION_PIPELINE.md` | Curated YouTube watchlist ingestion | Milestone record for a capability that is secondary to research. |
| `05_ANALYTICS_SPEC.md` | Observation and metric-series contracts | Milestone record for the legacy analytics layer. |
| `06_ML_FORECASTING.md` | Baselines, evaluation protocol, diagnostics | Milestone record for the legacy forecasting layer. |
| `07_AI_ORCHESTRATION.md` | Phase 0 placeholder ("No agents") | Superseded: AI grounded interpretation and optional content tools now exist. |
| `08_DASHBOARD_SPEC.md` | Phase 0 placeholder ("Streamlit is not installed") | Superseded: the current surface is the Next.js research workspace. |
| `09_API_SPEC.md` | Phase 0 placeholder ("FastAPI is not implemented") | Superseded: FastAPI routes are implemented. |
| `11_DEPLOYMENT.md` | Early deployment outline | Superseded by [../DEPLOYMENT.md](../DEPLOYMENT.md). |
| `11_FORECASTING_PRODUCT_SPEC.md` | Forecasting product contract and readiness gate | Milestone record for the legacy forecasting product. |
| `12_FORECASTING_PRODUCT_REQUIREMENTS.md` | V1 forecasting requirements | Milestone record. Its requirements govern only the forecasting capability. |
| `13_FORECASTING_API_CONTRACT.md` | Forecast API contract | Milestone record for the forecast endpoint that still exists at `/api/v1/forecasts/github/{content_item_id}`. |
