# 10 — Testing and evaluation

Status: Phase 0 placeholder. No tests beyond an empty `tests/` directory.

## Later layers

| Layer | Intent |
| --- | --- |
| Unit | validators, quota math, normalization |
| Connector contract | recorded official JSON fixtures (no live quota burn in CI by default) |
| Analytics | KPI formulas vs golden snapshots |
| Forecast | time-based holdouts; naive baseline comparison |
| API | FastAPI TestClient |
| Dashboard | smoke that Streamlit pages import |

## Evaluation of intelligence (not code tests)

- Coverage: watchlist size vs quota
- Freshness: time since last successful YouTube pull
- Policy: jobs that would retain YouTube non-authorized stats > 30 days must fail CI/config checks
- Cost: zero paid API calls in default config

## Not chosen

Coverage targets, load tests, annotation workflow for NLP quality.
