# 10 — Testing and evaluation

Status: Phase 0 placeholder for API/dashboard tests. Application unit/integration tests exist under `tests/`. Forecast evaluation for M6A is observation-count chronological holdout + MAE. M6C adds naive-vs-challenger MAE comparison. M7 adds in-memory series diagnostics. Protocol and open decisions live in [06_ML_FORECASTING.md](06_ML_FORECASTING.md).

## Later layers

| Layer | Intent |
| --- | --- |
| Unit | validators, quota math, normalization |
| Connector contract | recorded official JSON fixtures (no live quota burn in CI by default) |
| Analytics | KPI formulas vs golden snapshots |
| Forecast | M6A: chronological observation holdout, MAE, positional compare on irregular times. M6C: naive-vs-challenger MAE comparison object (in-memory). M7: series diagnostics over M5 `MetricSeries` (in-memory). Calendar-time holdouts remain open in [06](06_ML_FORECASTING.md) |
| API | FastAPI TestClient |
| Dashboard | smoke that Streamlit pages import |

## Evaluation of intelligence (not code tests)

- Coverage: watchlist size vs quota
- Freshness: time since last successful YouTube pull
- Policy: jobs that would retain YouTube non-authorized stats > 30 days must fail CI/config checks
- Cost: zero paid API calls in default config

## Not chosen

Coverage targets, load tests, annotation workflow for NLP quality.
