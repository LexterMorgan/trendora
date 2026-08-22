# 10 — Testing and evaluation

Status: Phase 0 placeholder for API/dashboard tests. Application unit/integration tests exist under `tests/`. Forecast evaluation for M6A is implemented as observation-count chronological holdout + MAE; the protocol and open decisions live in [06_ML_FORECASTING.md](06_ML_FORECASTING.md).

## Later layers

| Layer | Intent |
| --- | --- |
| Unit | validators, quota math, normalization |
| Connector contract | recorded official JSON fixtures (no live quota burn in CI by default) |
| Analytics | KPI formulas vs golden snapshots |
| Forecast | M6A: chronological observation holdout, MAE, positional compare on irregular times. Naive-vs-challenger **comparison object** and calendar-time holdouts: see [06](06_ML_FORECASTING.md) (open / next slice) |
| API | FastAPI TestClient |
| Dashboard | smoke that Streamlit pages import |

## Evaluation of intelligence (not code tests)

- Coverage: watchlist size vs quota
- Freshness: time since last successful YouTube pull
- Policy: jobs that would retain YouTube non-authorized stats > 30 days must fail CI/config checks
- Cost: zero paid API calls in default config

## Not chosen

Coverage targets, load tests, annotation workflow for NLP quality.
