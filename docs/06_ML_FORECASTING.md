# 06 — ML and forecasting

Status: Phase 0 placeholder. No models.

## Direction

- Libraries later: scikit-learn, statsmodels (and NumPy/Pandas).
- Forecast **our snapshot series**, not imaginary vendor history.
- Until YouTube storage permission is granted, series length may be ≤ 30 days of public stats. Short windows make seasonal models weak; V1 may be limited to simple baselines (moving average, naive, exponential smoothing) once retention is lawful.

## Planned problem types (not built)

| Problem | Depends on |
| --- | --- |
| Short-horizon volume forecast | daily snapshot counts |
| Anomaly detection | residual vs baseline |
| Topic clustering / NLP | titles/descriptions with 30-day refresh |
| Classification (education vs off-topic) | labeled watchlist, not a purchased dataset |

## Constraints

- No paid AutoML.
- No LLM-as-forecaster for numeric KPIs.
- Do not train on scraped prohibited data.
- Evaluate with holdout time splits, documented in [10_TESTING_EVALUATION.md](10_TESTING_EVALUATION.md) later.

## Open

Model list, feature store, retraining cadence — not chosen.
