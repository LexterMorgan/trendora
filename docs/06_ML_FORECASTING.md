# 06 — ML and forecasting

Status: Milestone 6A implements in-memory forecasting baselines over M5 `MetricSeries`. It is not a complete ML platform.

## M6A — forecasting baselines (implemented)

Flow:

```text
ForecastRequest → AnalyticsService → MetricSeries → baseline → ForecastResult
```

Forecasting never queries `metric_snapshots` directly. History comes from M5. Results stay in memory. No forecast tables, migrations, FastAPI, Streamlit, or scheduler.

### Models

| Model | Fit | Multi-step |
| --- | --- | --- |
| `naive` | last observed value | that value repeated for every horizon step |
| `moving_average` | explicit `window`; mean of the latest `window` values | recursive: each prediction is appended and reused in the next window |
| `simple_exponential_smoothing` | explicit `alpha` where `0 < alpha <= 1` | initialize level at the first observation; `level_t = alpha * y_t + (1 - alpha) * level_(t-1)`; every future step equals the final level |

No trend, seasonality, ARIMA, Prophet, ensembles, or neural models.

Naive and SES need at least one observation. Moving average needs `window >= 1` and `window <=` history length. Empty history is an error, not zeros.

### Request / result

- `ForecastRequest`: M5 `ObservationQuery` (source, metric, subject, optional time window) plus `model`, positive `horizon`, positive `interval` (`timedelta`), `window` (MA only), `alpha` (SES only).
- Interval is **explicit**. It is never inferred from irregular snapshot gaps.
- Forecast timestamps: `latest observed_at + n * interval` for `n = 1..horizon`. Timezone-aware only. Naive datetimes are rejected.
- `ForecastResult` / `ForecastPoint`: model, interval, horizon, history range, origin `trendora_forecast`, timestamped float values. Not pandas/NumPy objects.
- Source observations are not altered, interpolated, resampled, or filled.

### Evaluation

Chronological holdout only. `holdout` is an explicit test-set size (later observations). Training is strictly earlier. MAE is the only metric.

On irregular series, split by M5 observation order. Generate `holdout` forecast steps with the supplied interval. Compare **positionally** (forecast `i` vs held-out observation `i`). Held-out timestamps bound the test window; they need not equal generated forecast timestamps.

Invalid splits (empty train, empty test, holdout covering all history, window larger than training history) are rejected. Test observations do not participate in fitting.

### Dependencies and persistence

No new packages. No pandas, NumPy, scikit-learn, or statsmodels. No database writes.

## Limitations / not M6A

- No stored forecasts.
- No daily resampling of snapshot counts.
- No prediction intervals.
- YouTube series may still be short (≤ 30-day public stats) until storage permission exists.
- Candidate KPI formulas remain unfinalized (`docs/05`).

## Later M6 work (not built)

| Problem | Depends on |
| --- | --- |
| Short-horizon volume forecast beyond these baselines | explicit daily aggregation rules (not defined here) |
| Anomaly detection | residual vs baseline |
| Topic clustering / NLP | titles/descriptions with 30-day refresh |
| Classification (education vs off-topic) | labeled watchlist, not a purchased dataset |
| Feature store, retraining cadence, model registry | not chosen |

## Constraints

- No paid AutoML.
- No LLM-as-forecaster for numeric KPIs.
- Do not train on scraped prohibited data.
- Do not fabricate observations.
