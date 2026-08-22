# 06 — ML and forecasting

Status: **M6A implemented** (in-memory baselines). **M6B is documentation only** (evaluation and model-selection research). This is not a complete ML platform and not a dashboard/API.

Architecture (unchanged):

```text
connectors → persistence → metric_snapshots
  → M5 AnalyticsRepository / AnalyticsService → MetricSeries
  → M6A ForecastingService → ForecastResult / EvaluationResult
```

Forecasting must consume M5. It must not query `metric_snapshots` directly, call connectors, or add a second SQL path.

---

## 1. Current implementation (M6A)

M6A is the source of truth for what is built (`src/trendora/forecasting/`, commit `9660908`).

Flow: `ForecastRequest` → `AnalyticsService.get_metric_series` → `MetricSeries` → baseline → `ForecastResult`.

| Model | Fit | Multi-step |
| --- | --- | --- |
| `naive` | last observed value | that value repeated for every horizon step |
| `moving_average` | explicit `window`; mean of the latest `window` values | recursive: each prediction is appended and reused in the next window |
| `simple_exponential_smoothing` | explicit `alpha` where `0 < alpha <= 1` | initialize level at the first observation; `level_t = alpha * y_t + (1 - alpha) * level_(t-1)`; every future step equals the final level |

No trend, seasonality, ARIMA, Prophet, ensembles, neural nets, or LLM-as-forecaster.

**Request:** M5 `ObservationQuery` (source, metric, subject, optional `observed_from` / `observed_until`) plus `model`, positive `horizon`, positive `interval` (`timedelta`), `window` (MA only), `alpha` (SES only). Interval is never inferred from snapshot gaps.

**Timestamps:** `latest observed_at + n * interval` for `n = 1..horizon`. Timezone-aware only. Naive datetimes rejected.

**History rules:** empty series errors (not zeros). Naive/SES need ≥1 observation. MA needs `1 <= window <=` history length. Observations are not interpolated, resampled, forward-filled, or fabricated. Ordering is M5: `observed_at`, `collected_at`, snapshot id.

**Evaluation (M6A):** chronological holdout of the last `holdout` observations. Train is the strict prefix. MAE only. Forecast `holdout` steps with the supplied interval; compare **positionally** (forecast `i` vs held-out observation `i`). Held-out timestamps need not equal generated forecast timestamps. Test rows do not enter fitting. Evaluation reuses `forecast_series`.

**Not in M6A:** persistence, FastAPI, Streamlit, scheduler, new dependencies, prediction intervals, daily aggregation, model-vs-naive comparison API, production model selection.

Connectors currently set `observed_at = collected_at` at ingest. Collection cadence is whatever the operator runs; it is not a regular daily grid.

---

## 2. Forecastable series

M6A will run on **any** M5 series that has a source, metric name, and subject (`content_item_id` xor `publisher_id`). That is a mechanical capability, not a product decision that every numeric metric should be forecast or shown.

There is **no** metric-semantic registry in code. The notes below are from connector persistence and [05_ANALYTICS_SPEC.md](05_ANALYTICS_SPEC.md), not from a finalized KPI spec.

| Source | Subject | Stored metrics | Typical shape | Forecast as stored level? |
| --- | --- | --- | --- | --- |
| YouTube | video (content) | `view_count`, `like_count`, `comment_count` | current/cumulative counters | Mechanically yes. Product/policy OPEN. |
| YouTube | channel (publisher) | `view_count`, `subscriber_count`, `video_count` | current/cumulative counters | Mechanically yes. Product/policy OPEN. |
| Hacker News | story (content) | `score`, `comment_count` | observed score / count; score can move either way | Mechanically yes. Usefulness OPEN. |
| Stack Exchange | question (content) | `score`, `view_count`, `answer_count` | mix of score, cumulative views, current answers | Mechanically yes. Usefulness OPEN. |
| GitHub | repository (content) | `stargazer_count`, `fork_count`, `open_issue_count`, `watcher_count` | mostly cumulative; `open_issue_count` can fall | Mechanically yes. Usefulness OPEN. |

HN/SE/GitHub content often has `market_id = NULL` and `publisher_id = NULL`. M6A does not infer markets.

**Supported now:** one subject + one official stored metric + explicit interval/horizon → forecast of **future levels of that metric**.

**Undefined (do not implement as if specified):**

- Daily/weekly **volume** (new videos/day, “snapshot counts per day”). Named historically as a planned problem; depends on aggregation/resampling rules that this repo **forbids inventing**.
- Increments / deltas of cumulative counters (next *new* views rather than next `view_count`).
- Cross-item or market-level series (all ID videos, watchlist volume).
- Composite metrics (engagement ratio, Trendora Score). YouTube derived-metric policy still applies ([05](05_ANALYTICS_SPEC.md), [03](03_DATA_SOURCES.md)).
- Topic velocity, sentiment, NLP series.

Not every bigint in `metric_snapshots` is a good forecast target. Cumulative **levels** are easy for naive to look strong (last value is often close to next value). That does not mean the forecast answers “what is likely next” for SEA education markets.

---

## 3. Candidate models

V1 status uses only decisions the repo supports. **Selected** means chosen for a stated role. Implemented M6A models are not automatically the production dashboard model.

| Model | Series it wants | Irregular timestamps | Resampling | Min history | Strengths | Weaknesses | Cost / explainability | Suitability | V1 status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Naive | any univariate level | M6A: uses values in M5 order; interval is explicit | not used | 1 obs | honest baseline; cheap; matches short, sticky cumulative levels | no trend/season; interval does not change the value | trivial; fully explainable | required comparison baseline ([10](10_TESTING_EVALUATION.md)) | **Selected** as evaluation baseline. **Implemented** (M6A). Not selected as the only product forecast. |
| Moving average | local level | same as naive (order, not calendar spacing) | not used in M6A | `window` observations | smooths noise if `window` is set | `window` is a product/tuning choice; recursive multi-step drifts toward a mean | trivial; explainable | available today | **Implemented** (M6A). Production use **OPEN**. |
| Simple exponential smoothing | local level | same as naive | not used in M6A | 1 obs | `alpha` explicit; last level is the forecast | no trend/season; `alpha` OPEN | trivial; explainable | available today | **Implemented** (M6A). Production use **OPEN**. |
| Holt (linear trend) | roughly regular level + trend | poorly specified without regular spacing | would need a grid this repo does not define | more than SES | captures trend on cumulative counters | over-projects; needs interval regularity | low; explainable | only after OPEN resampling/interval policy | **Deferred** |
| Seasonal (Holt–Winters, seasonal naive) | long, regular seasonality | no | almost always | many seasonal cycles | useful on true daily/weekly season | YouTube public stats may be ≤ 30 days; seasonal models already called weak here | low–medium | not V1-shaped | **Deferred** (short windows). Not rejected forever. |
| AR / ARIMA / SARIMA | regular (or resampled) series | no, not as usually fitted | typically yes | tens+ of points | classical, well-studied | needs grid + deps (`statsmodels`); misspecified on irregular snapshots | medium; less obvious | not until regular series exist | **Deferred** |
| Prophet / neural / gradient boosting | rich regular series | no | typically yes | large | flexible | deps, opacity, not specified; overkill for ≤30-day sticky counters | high | not V1 | **Deferred** |
| LLM-as-forecaster | n/a | n/a | n/a | n/a | n/a | forbidden for numeric KPIs | n/a | n/a | **Rejected** |
| Paid AutoML | n/a | n/a | n/a | n/a | n/a | forbidden | n/a | n/a | **Rejected** |

Do not install pandas/NumPy/scikit-learn/statsmodels for a model that is Deferred.

---

## 4. Evaluation protocol

### Established (M6A + this repo)

- Chronological split only. No random train/test.
- Holdout = last **N observations** (explicit `holdout`), not a calendar duration.
- Training prefix occurs before the test suffix in **M5 observation order**.
- MAE on positional pairs. No RMSE/MAPE/MASE in code.
- No leakage: test values are not in the fit.
- Irregular timestamps: allowed; do not resample to evaluate.
- Missing snapshots stay missing; do not score fabricated times.
- Challenger fitting must use the same `forecast_series` path as production forecasts.

[10_TESTING_EVALUATION.md](10_TESTING_EVALUATION.md) still lists “time-based holdouts; naive baseline comparison”. M6A implemented **observation-count** holdout and per-model MAE. It does **not** implement a calendar-time holdout or a combined naive-vs-challenger result object.

### Proposed (not implemented; not product law)

- Report naive MAE on the **same** series/holdout/interval whenever a challenger is evaluated.
- Prefer a challenger only if its MAE is **strictly lower** than naive MAE on that split (ties keep naive). This is a proposed selection *rule for experiments*, not a dashboard requirement.
- Rolling-origin / walk-forward: better for small N, not built. Choosing it as the V1 standard is **OPEN**.
- RMSE: same units squared; not needed if MAE exists. **OPEN** whether to add.
- MAPE: unstable near zero; some counts can be 0. **Not justified** as a V1 requirement.
- MASE: scale-free vs naive; useful later if comparing heterogeneous metrics. **OPEN**.
- Minimum test length, multiple windows, which subjects to include: **OPEN**.

### Cumulative metrics

Evaluating **levels** of `view_count` / `stargazer_count` often yields low MAE for naive. That can look like “good forecasting” while saying little about growth. Differencing before fit/score is **OPEN** and must not be silently enabled.

---

## 5. Data requirements

| Topic | Established | Open |
| --- | --- | --- |
| Identity | One source + metric + content **or** publisher | Which subjects are in-scope for V1 |
| History length | M6A minima above; YouTube non-authorized stats retention hook is 30 days | How many points before a forecast is *shown*; lawful multi-year YouTube storage |
| Timestamps | Aware `observed_at` / `collected_at`; M5 order; connectors set them equal at ingest | Operator ingest cadence; explicit product `interval` (hour vs day vs week) |
| Duplicates | Unique `(subject, metric, collected_at)`; same `observed_at` possible; tie-break `collected_at` then id | Whether to collapse same-`observed_at` rows |
| Missingness | Gaps stay gaps | Whether a minimum density is required |
| Cumulative vs observed | Documented as a KPI caveat in [05](05_ANALYTICS_SPEC.md); not modeled in code | Forecast level vs increment; per-metric registry |
| Resampling | Forbidden unless a later milestone defines it | Daily snapshot counts for “volume” |

Forecast `interval` is a **generation** parameter. It is not proven by the history’s spacing. Evaluation MAE does not require forecast times to match held-out `observed_at`.

---

## 6. Persistence

**Now:** in-memory only. No forecast tables. [02_DATABASE_SCHEMA.md](02_DATABASE_SCHEMA.md) lists forecast tables as not in `0001_initial_schema`.

**Before persisting:** decide retention of *derived* forecasts vs recompute-on-read; subject/metric/model/interval/horizon keying; that writes never mutate `metric_snapshots`. Until then, keep results in memory.

---

## 7. API / dashboard readiness

[08_DASHBOARD_SPEC.md](08_DASHBOARD_SPEC.md) wants “what is likely next” with **interval and sample-size caveats**, freshness, source mix, and “not from YouTube” on Trendora-calculated fields. [09_API_SPEC.md](09_API_SPEC.md) lists forecasts as a later read model.

Do not expose M6A until at least these are decided (all **OPEN** except the last bullet, which is already true in code):

1. Which series (source, subject class, metric names).
2. Horizon and interval shown in the UI.
3. Whether the UI shows naive, a challenger, or “winner vs naive”.
4. Sample-size / short-history behavior (hide vs warn).
5. Label `origin=trendora_forecast` beside official API fields (M6A already sets origin).
6. YouTube policy: whether a forecast of `view_count` is an allowed derived artifact.
7. On-demand compute vs persisted forecasts.
8. No imputation of empty markets ([08](08_DASHBOARD_SPEC.md)).

FastAPI and Streamlit remain future milestones.

---

## 8. Open product decisions

1. **First product question for forecasting:** next official-metric **level** for a single item (what M6A does), **increment** of a cumulative counter, or **volume** (e.g. new videos/day)? Volume is blocked on aggregation rules.
2. **Which metrics/subjects** are in V1 (YouTube video `view_count` vs HN `score` vs GitHub stars vs publisher series vs all of them).
3. **Forecast interval and horizon** for the product (M6A only requires they be positive and explicit).
4. **Minimum history** to *display* a forecast (distinct from M6A fit minima).
5. **Level vs differenced** evaluation for cumulative counters.
6. **Calendar holdout vs observation-count holdout vs rolling-origin** as the V1 selection protocol.
7. **Selection rule** (e.g. challenger MAE must beat naive) and whether a tie keeps naive.
8. **MA `window` and SES `alpha`** (fixed defaults vs per-series vs later search). Defaults must not be invented in code until chosen here.
9. **Whether Holt/ARIMA/etc. are ever in scope**, which requires an explicit regularity/resampling policy.
10. **Forecast persistence** vs always recompute from M5.
11. **YouTube terms:** displaying Python forecasts of official YouTube fields.
12. **Multi-year YouTube history** (storage amendment) vs living with ≤30-day public stats.

---

## 9. Next implementation slice

**Not next:** FastAPI, Streamlit, schema, resampling, Holt/ARIMA, pandas/sklearn, anomaly/NLP, connector changes, invented horizons.

**Smallest unambiguous code slice (M6C), only if requested:**

In-memory **naive comparison** on top of existing `ForecastingService.evaluate`:

- Same M5 query, same `holdout`, same `interval`.
- Evaluate `naive` and one implemented challenger (`moving_average` or `simple_exponential_smoothing`) with caller-supplied `window`/`alpha` (still explicit; no search).
- Return both MAEs, counts, holdout bounds, and whether challenger MAE is strictly less than naive MAE.
- No new models, no writes, no new dependencies, no dashboard.

That implements the “naive baseline comparison” intent in [10](10_TESTING_EVALUATION.md) without resolving decisions 1–12 as product law. It must **not** declare a dashboard winner or a default `window`/`alpha`.

Anything larger (volume KPIs, Holt, persistence, API) stays blocked on section 8.

---

## Constraints (all M6)

- No paid AutoML.
- No LLM-as-forecaster for numeric KPIs.
- Do not train on scraped prohibited data.
- Do not fabricate, interpolate, or resample observations unless a later milestone defines the rule.
- Do not label Trendora forecasts as official source metrics (`origin=trendora_forecast`).
