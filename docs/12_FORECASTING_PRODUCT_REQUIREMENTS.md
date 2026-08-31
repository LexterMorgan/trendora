# 12 — Forecasting Product Requirements

## 1. Status and decision authority

**Status:** The V1 forecasting product requirements are **decided** to the extent the repository evidence allows. The product scope is intentionally narrow: one source, one subject class, two metrics, one model, one interval, one horizon, one persistence strategy. Everything outside that slice is explicitly deferred or rejected, so that the next implementation milestone is unambiguous.

**Decision authority:** This document is the M9 product-requirements decision. Decisions here are **product decisions made in M9**, not facts inferred from the repository. The repository establishes mechanical capability and constraints; this document chooses which of those become the V1 product promise. Where the repository genuinely cannot support a decision, the decision is marked **OPEN** with the exact evidence that is missing.

The rule from M8 still governs: **engineering convenience is not a product requirement.** A choice here is REQUIRED only when it is (a) mechanically supported by M1–M8 code/schema, (b) consistent with documented source/data policy, and (c) a defensible reading of the documented product goal ([00_PROJECT_OVERVIEW.md](00_PROJECT_OVERVIEW.md), [README.md](../README.md), [08_DASHBOARD_SPEC.md](08_DASHBOARD_SPEC.md)). Every REQUIRED choice below is labeled either as repository-established or as a **provisional product choice**; provisional choices are explicit decisions by the product owner, not observed facts, and are flagged for re-review when real series accumulate.

This document resolves the open decisions recorded in [11_FORECASTING_PRODUCT_SPEC.md](11_FORECASTING_PRODUCT_SPEC.md) (M8). [06_ML_FORECASTING.md](06_ML_FORECASTING.md) remains the technical forecasting/evaluation reference and is unchanged in substance.

---

## 2. Product objective

Trendora's core question ([00](00_PROJECT_OVERVIEW.md)) includes **“what is likely to happen next.”** The [08_DASHBOARD_SPEC.md](08_DASHBOARD_SPEC.md) “What is likely next” view is the intended user surface for forecasts: Python-computed forecasts shown **with interval and sample-size caveats**, never mislabeled as official source data.

M9 therefore defines the smallest credible V1 forecasting product that:

- fits Trendora's **actual stored data** (append-only `metric_snapshots`, operator-driven ingestion, short series),
- respects the M5/M6 architecture (forecasting consumes only M5 `MetricSeries`; no second SQL path),
- does not pretend irregular snapshots are a regular time series,
- does not overclaim forecast quality,
- does not fabricate history,
- is explainable,
- can feed the dashboard/API later,
- can be implemented cleanly in one later milestone.

The objective is **not** academic sophistication. It is an honest, bounded, implementable forecast feature.

---

## 3. Current repository evidence

Facts the decision below relies on (all verified against the current repository):

| Area | Fact | Evidence |
| --- | --- | --- |
| Architecture | connectors → persistence → `metric_snapshots` → M5 → `MetricSeries` → M6A/M6C/M7. No second SQL read path. | [06](06_ML_FORECASTING.md) §1; [01_ARCHITECTURE.md](01_ARCHITECTURE.md) |
| M6A | naive / moving average / simple exponential smoothing; explicit positive `interval` and `horizon`; in-memory; no resampling/imputation/fabrication. Forecast points at `latest observed_at + n*interval`. | `src/trendora/forecasting/service.py`, `models.py`; [06](06_ML_FORECASTING.md) §1 |
| M6C | naive vs one caller-selected challenger; `challenger_beats_naive = challenger_mae < naive_mae`; evaluation artifact only. | [06](06_ML_FORECASTING.md) §1 |
| M7 | deterministic diagnostics: `observation_count`, gaps, cadence, duplicate `observed_at`, deltas, monotonicity. No score, no recommendation. | `src/trendora/diagnostics/`; [06](06_ML_FORECASTING.md) §9 |
| Provenance | `origin=trendora_forecast` (`ForecastResult`/`EvaluationResult`/`ComparisonResult`); `trendora_derived` (aggregates); `trendora_diagnostic` (diagnostics). | forecasting/analytics/diagnostics service `_ORIGIN` constants; [06](06_ML_FORECASTING.md) Constraints |
| Stored metrics | YouTube video `view_count`/`like_count`/`comment_count`; YouTube channel `view_count`/`subscriber_count`/`video_count`; HN `score`/`comment_count`; SE `score`/`view_count`/`answer_count`; GitHub `stargazer_count`/`fork_count`/`open_issue_count`/`watcher_count`. | `src/trendora/connectors/*/normalizer.py`; [06](06_ML_FORECASTING.md) §2 |
| Timestamps | All connectors set `observed_at = collected_at` at ingest; ingestion is manual/operator-driven, not a scheduler; no guaranteed regular grid. | [04_INGESTION_PIPELINE.md](04_INGESTION_PIPELINE.md); [06](06_ML_FORECASTING.md) §1, §5 |
| History reality | Read-only dev-DB count (2026-08-23, **not** a product rule): 1921 `metric_snapshots`; 1861 series with 1 observation; 30 with 2; 0 with 3+. | [06](06_ML_FORECASTING.md) §9 |
| YouTube policy | Non-authorized stats ≤30 days unless amendment; derived metrics (scores/leaderboards/derived artifacts) generally prohibited unless analytics amendment accepted (III.E.4.h; amendment path from 2026-06-01); scraping prohibited. | [03_DATA_SOURCES.md](03_DATA_SOURCES.md); [05_ANALYTICS_SPEC.md](05_ANALYTICS_SPEC.md) |
| GitHub | No derived-metric restriction documented for public repository reads. | [03_DATA_SOURCES.md](03_DATA_SOURCES.md) |
| Dashboard | “What is likely next” view; interval and sample-size caveats; freshness; source mix; “not from YouTube” disclosure for Trendora-calculated fields; no imputed markets. | [08_DASHBOARD_SPEC.md](08_DASHBOARD_SPEC.md) |
| API | `forecasts / anomalies` listed as a later read-model resource group; pagination and `collected_at` filters; OpenAPI contract. No endpoint or response shape defined. | [09_API_SPEC.md](09_API_SPEC.md) |

---

## 4. V1 product promise

**V1 promise (provisional product decision):**

> For tracked GitHub repositories, Trendora may show a cautious, clearly-labeled forecast of the likely future **level** of `stargazer_count` and `fork_count` — the next 4 points at 7-day spacing after the last observation — computed in memory from the stored `metric_snapshots` history via the M5 `MetricSeries`, using the naive model, **only when the series has at least 4 observations**. Every forecast is labeled `origin=trendora_forecast`, never presented as an official GitHub field, and always accompanied by its sample size, history span, freshness, and an irregular-sampling caveat when the stored snapshots do not follow a constant cadence.

Why this promise, in one line: it is the only forecast shape (level) that M6A already implements, on the only source (GitHub) whose metrics are cumulative growth signals with no documented derived-metric policy gate, bounded to a horizon and minimum history small enough not to overclaim.

The promise does **not** include: increment/delta forecasts, volume forecasts, daily/hourly precision, resampling, any YouTube-derived forecast, any other source, any other model, any persisted forecast, or any claim of guaranteed accuracy.

---

## 5. V1 scope

### 5.1 Sources

**Decision:** V1 forecast source = `github` only.

- **Status:** REQUIRED V1 (provisional product choice, constrained by policy and value evidence).
- **Rationale:** GitHub repository `stargazer_count`/`fork_count` are cumulative adoption signals over long-lived subjects with **no documented derived-metric policy gate** ([03](03_DATA_SOURCES.md)). This makes them the only stored series that are simultaneously (a) forecastable with the existing level machinery, (b) policy-clean to display as Trendora-derived values, and (c) meaningful as “what is likely next” within Trendora's tech-education domain.
- **Evidence:** only four connectors write snapshots ([04](04_INGESTION_PIPELINE.md)); YouTube carries a derived-metric policy gate ([03](03_DATA_SOURCES.md)); GitHub public reads have no equivalent restriction ([03](03_DATA_SOURCES.md)).
- **Consequence:** the YouTube derived-forecast question (Decision 19) does **not** block the V1 slice, because YouTube is outside V1 scope.

| Source | V1 status | Reason |
| --- | --- | --- |
| `github` | **REQUIRED** | Cumulative adoption metrics, long-lived subjects, no derived-metric policy gate, tech-education signal |
| `youtube` | **DEFERRED (policy-gated)** | Derived-metric policy question OPEN; see Decision 19 |
| `hacker_news` | **DEFERRED** | Story `score`/`comment_count` are volatile or decay after the story ages; global tech attention, not a growth series; low forecasting value |
| `stack_exchange` | **DEFERRED** | Question scores stabilize; `view_count` is cumulative but questions age; not a primary growth signal; not SEA-specific |

### 5.2 Subjects

**Decision:** V1 forecast subject class = **content_item** (specifically GitHub repository `content_items`, `content_type=repository`).

- **Status:** REQUIRED V1.
- **Rationale:** GitHub snapshots are stored against repository `content_items`; `publisher_id`/`market_id` are unset for GitHub rows ([04](04_INGESTION_PIPELINE.md)). The only publisher-subject series in the repository are YouTube channels, which are outside V1 scope (Decision 19).
- **Evidence:** `metric_snapshots` subject XOR constraint (`content_item_id` xor `publisher_id`, `models/metrics.py`); GitHub connector writes repository content snapshots only ([04](04_INGESTION_PIPELINE.md)); [06](06_ML_FORECASTING.md) §2.
- **Consequence:** every V1 forecast request is keyed by `content_item_id` for a GitHub repository.

### 5.3 Metrics

**Decision:** V1 forecast metrics = `github` / repository / `stargazer_count` and `fork_count`.

| Source | Subject | Metric | V1 status | What it measures | Behavior | Why meaningful / caveats |
| --- | --- | --- | --- | --- | --- | --- |
| `github` | repository | `stargazer_count` | **REQUIRED** | Official GitHub field: total stargazers | Cumulative, typically non-decreasing | Canonical repo-adoption signal; long-lived growth series. Caveat: naive on cumulative levels can look accurate without meaning — forecast is a level, not growth proof. |
| `github` | repository | `fork_count` | **REQUIRED** | Official GitHub field: total forks | Cumulative, typically non-decreasing | Complementary adoption signal. Same cumulative caveat. |
| `github` | repository | `open_issue_count` | **DEFERRED** | Official GitHub field: open issues | Current state; can fall | Not a growth signal; forecasting a can-fall current count is low-value and semantically muddier |
| `github` | repository | `watcher_count` | **DEFERRED** | Stored from `subscribers_count` (legacy `watchers_count` is a stargazers alias) | Cumulative-ish | Redundant/low-signal; stored from a secondary payload field |
| `youtube` | video | `view_count`/`like_count`/`comment_count` | **DEFERRED (policy-gated)** | Official fields; current cumulative counters | Non-decreasing | Mechanically forecastable, but YouTube-derived artifact policy OPEN (Decision 19) |
| `youtube` | channel | `view_count`/`subscriber_count`/`video_count` | **DEFERRED (policy-gated)** | Official fields; cumulative counters | Non-decreasing | Same policy gate; only publisher-subject series in repo |
| `hacker_news` | story | `score`/`comment_count` | **DEFERRED** | Official fields; observed score / count | `score` moves both ways | Volatile/decaying; low product value |
| `stack_exchange` | question | `score`/`view_count`/`answer_count` | **DEFERRED** | Official fields; score / cumulative views / current answers | mixed | Stabilizes/ages; not a primary growth series |

Statuses used: **REQUIRED V1**, **DEFERRED**, **DEFERRED (policy-gated)**, **REJECTED**. No metric is marked “unsuitable” categorically; all stored metrics are mechanically forecastable, which is exactly why product selection is required and is done above.

### 5.4 Level / increment / volume

**Decision:** V1 forecasts **stored levels** only. Increment and volume forecasting are **DEFERRED** (see Decision 5).

---

## 6. Forecast semantics

### 6.1 Interval

**Decision:** V1 default forecast interval = **7 days (weekly spacing)**.

- **Status:** REQUIRED V1 — **provisional product choice**.
- **Rationale:** For a stargazer/fork growth series, weekly points are the natural communication unit; 4 weekly points stay within ~1 month, which is a conservative claim on short history. **This interval is a generation/labeling convention, not an assertion that the underlying snapshots follow a weekly cadence.** M6A already treats `interval` as an explicit generation parameter that is not inferred from — and not proven by — history spacing ([06](06_ML_FORECASTING.md) §1, §5).
- **Evidence:** M6A accepts any positive `timedelta` and generates timestamps as `latest observed_at + n*interval` (`forecasting/service.py`); connectors set `observed_at = collected_at` under operator-driven runs ([04](04_INGESTION_PIPELINE.md)).
- **Consequence:** a 7-day interval for **level** forecasting requires **no resampling and no aggregation**, because M6A forecasts values directly from stored observations; the interval only labels output timestamps. The product must display the interval as “points spaced 7 days after the last observation,” never as a claim of daily/weekly data collection.
- **Rejected/deferred alternatives:** daily is DEFERRED (finer granularity than a manual-ingestion cadence can support as a claim of precision; it is not wrong mechanically, just not a V1 product claim); hourly is REJECTED for these metrics (meaningless for repository growth).
- **Re-review condition:** if a scheduler/regular cadence is added later, this interval choice is revisited and can be tied to the actual collection grid.

### 6.2 Horizon

**Decision:** V1 default horizon = **4 points** (≈ 28 days at the 7-day interval).

- **Status:** REQUIRED V1 — **provisional product choice**.
- **Rationale:** 4 points is short enough to be credible on the small histories V1 allows (minimum 4 observations, Decision 8) and long enough to be a useful “next month” growth reading. It deliberately does not reach beyond ~1 month, so no long-horizon accuracy is implied.
- **Evidence:** M6A requires `horizon >= 1`; nothing in the repository establishes a larger horizon, and current series are too short to validate one ([06](06_ML_FORECASTING.md) §9).
- **Consequence:** horizon is a fixed V1 default and remains an explicit M6A parameter; callers may pass other values through the existing machinery, but the V1 product surface ships 4 points.

### 6.3 Timestamp behavior

- Forecast points are generated at `latest observed_at + n*interval`, `n = 1..horizon`, timezone-aware (M6A). The first forecast point is never before the last observation.
- History bounds (`history_start`, `history_end`, `history_count`) and `generated_at` (computation time) are part of the forecast result and must be surfaced to the user (Decision 17, Decision 18).

### 6.4 Irregularity

**Decision:** V1 allows irregular observations; forecasting proceeds in M5 observation order with the explicit interval. No resampling, no regularity gate.

- **Status:** REQUIRED V1.
- **Rationale:** Stored snapshots are operator-driven and not a regular grid ([04](04_INGESTION_PIPELINE.md)); M6A is defined to operate on observation order with an explicit interval and to evaluate positionally ([06](06_ML_FORECASTING.md) §1, §4). Requiring regularity would block nearly all current data; resampling would require aggregation semantics the repository forbids inventing.
- **Evidence:** M6A compares forecasts positionally against held-out observations regardless of spacing; M7 reports cadence facts (`cadence` class, gap stats) without imposing a requirement.
- **Consequence:** the product does **not** claim that stored spacing proves a calendar cadence. When M7 reports `cadence != effectively_constant_cadence`, the forecast is shown with an **irregular-sampling caveat** (Decision 18). `resample` and `require-regularity` are REJECTED for V1.

### 6.5 Missingness

**Decision:** Missing observations stay missing. No imputation, interpolation, forward-fill, or zero-fill. Missing snapshots are not treated as zero activity.

- **Status:** REQUIRED V1.
- **Rationale:** This is the existing M5/M6 behavior and is already a documented constraint ([06](06_ML_FORECASTING.md) Constraints; [05](05_ANALYTICS_SPEC.md)). The product does not fabricate history.
- **Consequence:** the minimum-history rule (Decision 8) and the sample-size caveat are the product's only responses to missingness in V1; a series with gaps is forecast from whatever observations exist, with the gap facts surfaced.

---

## 7. History requirements

**Decision:** V1 displays a forecast only when the series has **at least 4 observations**. Below that, the product suppresses the forecast and shows an “insufficient data” state.

- **Status:** REQUIRED V1 — **provisional product choice**.
- **Rationale:** This is deliberately distinct from the M6A fit minima (naive/SES need ≥1 observation; MA needs `1 <= window <= history`). The display threshold is a **product choice**, not an observed fact: at 4 observations, (a) every V1 model can fit, (b) a 1-step chronological observation-count holdout evaluation can run (3 train / 1 test), and (c) the series is long enough that the 4-point horizon does not exceed the observed history span. It is conservative relative to the current dev-DB reality (1861 one-observation and 30 two-observation series, 0 with 3+), which means most current series will correctly show “insufficient data” until more ingestion occurs — that is the intended honest behavior.
- **Evidence:** M6A fit minima and holdout rule (`_split_holdout` requires holdout < history length, `forecasting/service.py`); dev-DB series distribution documented in [06](06_ML_FORECASTING.md) §9 (**not** a rule).
- **Consequence:** the dev-DB counts do not become a product rule; they are context. The 4-observation threshold is provisional and flagged for re-review when real series reach it.

---

## 8. Model policy

### 8.1 V1 production model

**Decision:** **naive** is the V1 production model for the level-forecast slice.

- **Status:** REQUIRED V1.
- **Rationale:** naive is the only model with (a) a fully specified product meaning (last observed level repeated forward), (b) no free hyperparameters to invent, and (c) established standing as the evaluation baseline ([10_TESTING_EVALUATION.md](10_TESTING_EVALUATION.md)). It is the honest, explainable default for sticky cumulative levels and cannot be accused of overfitting short series.
- **Evidence:** M6A implements naive with no window/alpha; docs already treat naive as the required comparison baseline ([10](10_TESTING_EVALUATION.md); [06](06_ML_FORECASTING.md) §3).
- **Consequence:** moving average and SES remain implemented and usable for evaluation research via M6A/M6C, but are **not** V1 production models because their `window`/`alpha` are unspecified (Decisions 12–13).

### 8.2 Model selection rule

**Decision:** There is no per-series production selection in V1. M6C's `challenger_beats_naive` remains an **evaluation artifact** and is never used to pick the displayed forecast.

- **Status:** REQUIRED V1 (behavior) / DEFERRED (any selection rule).
- **Rationale:** the repository explicitly forbids treating M6C's comparison as a production winner ([06](06_ML_FORECASTING.md) §1, §4). No selection rule is needed in V1 because V1 ships one model.
- **Consequence:** a future selection rule (e.g., “challenger only if strictly lower MAE”) stays DEFERRED until challenger hyperparameters are specified and real series support evaluation.

### 8.3 MA window / SES alpha

**Decision:** No V1 default for `window` or `alpha`.

- **Status:** DEFERRED.
- **Rationale:** M6A requires explicit `window`/`alpha` and forbids inventing defaults ([06](06_ML_FORECASTING.md) §1, §8). Since MA/SES are not V1 production models, no default is needed. Evaluation experiments must continue to pass explicit values through the existing M6A/M6C contracts.
- **Consequence:** the next implementation milestone needs no window/alpha decision.

### 8.4 Advanced models

| Model | V1 status | Conditions under which it could become viable later |
| --- | --- | --- |
| Holt (linear trend) | **DEFERRED** | Requires an explicit regularity/resampling policy and longer histories; not viable on the current operator-driven grid |
| Holt–Winters / seasonal methods | **DEFERRED** | Requires long, regular seasonality; current histories are far too short and public YouTube stats are ≤30 days |
| ARIMA / SARIMA | **DEFERRED** | Requires regular or resampled series, a defined interval policy, longer histories, and a `statsmodels` dependency (not installed) |
| Prophet / gradient boosting / neural | **DEFERRED** | Requires rich regular series, new dependencies, and opacity that contradicts the explainability goal |
| LLM-as-forecaster | **REJECTED** | Forbidden for numeric KPIs (Python owns the truth) |
| Paid AutoML | **REJECTED** | Violates the $0 constraint |

No dependency is installed in M9. Advanced models are not “bad,” they are unsupported by current data and policy.

---

## 9. Evaluation policy

**Decision:** V1 evaluation uses the existing **chronological observation-count holdout + MAE**, on **levels**, with no random split and no calendar-time holdout.

- **Status:** REQUIRED V1 (existing M6A/M6C behavior becomes the V1 evaluation baseline).
- **Rationale:** this is the implemented, documented protocol ([06](06_ML_FORECASTING.md) §4; [10](10_TESTING_EVALUATION.md)); observation-count holdout is the only split the data can support today (series are too short for calendar windows or rolling-origin validation).
- **Evidence:** `evaluate_series` / `compare_series` in `forecasting/service.py`; [06](06_ML_FORECASTING.md) §4.
- **Consequences:**
  - Calendar-time holdout: **DEFERRED** (requires a defined cadence).
  - Rolling-origin / walk-forward: **DEFERRED** (better for small N but not required for a V1 naive slice).
  - Differenced (increment) evaluation: **DEFERRED** — level MAE stays, and its known weakness (naive on cumulative levels looks strong) is surfaced as a caveat rather than silently fixed by differencing.
  - RMSE / MAPE / MASE: **DEFERRED**; MAE is the only V1 metric. MAPE is unstable near zero and some counts can be 0 ([06](06_ML_FORECASTING.md) §4).

---

## 10. Provenance

- Official GitHub fields are returned by M5 exactly as stored; they are not rewritten.
- V1 forecasts carry `origin=trendora_forecast` and are **never** presented as official GitHub fields.
- Trendora-derived aggregates carry `origin=trendora_derived`; diagnostics carry `origin=trendora_diagnostic`.
- User-facing labeling requirement: any Trendora-calculated field shown beside official API fields is labeled as Trendora-derived, matching the dashboard's disclosure rule ([08](08_DASHBOARD_SPEC.md); [06](06_ML_FORECASTING.md) Constraints).

**Status:** REQUIRED V1 — repository-established.

---

## 11. API requirements

**Decision:** V1 defines the **minimum product-level response fields** for a future forecast read model. No endpoint paths are invented ([09](09_API_SPEC.md) defines none).

**Status:** REQUIRED (as a product-level contract) — implementation deferred to the API milestone.

A future forecast response must communicate, at minimum:

| Field group | Required content |
| --- | --- |
| Subject | `content_item_id` and `external_id` (GitHub `owner/repo`) |
| Metric | exact `metric_name` (`stargazer_count` / `fork_count`) |
| Model | `naive` |
| Interval / horizon | `interval` (7 days), `horizon` (4), and each forecast timestamp |
| Forecast values | the 4 points (`at`, `value`) |
| Origin | `origin=trendora_forecast` |
| History / sample size | `history_count`, `history_start`, `history_end` |
| Freshness | last `observed_at` and `generated_at` |
| Caveats | irregular-sampling flag (from M7 `cadence`), sample-size state, insufficient-history state |

Remaining undefined (deferred to the API milestone, not resolvable here): endpoint paths, authn/z, pagination wiring, OpenAPI shape.

---

## 12. Dashboard requirements

**Decision:** V1 dashboard behavior for the “What is likely next” view:

**Status:** REQUIRED (as a product-level contract) — implementation deferred to the dashboard milestone.

| Requirement | V1 behavior |
| --- | --- |
| Actual vs forecast | History (actual stored values) and forecast points are visually distinct; forecast region clearly marked as Trendora-derived |
| Interval/horizon display | “4 points at 7-day spacing after <last observed date>” — never “weekly data” |
| Sample-size caveat | Always show `history_count`; when at the 4-observation minimum, show an explicit “minimal history” caveat |
| Insufficient history | `< 4` observations → suppress forecast, show “insufficient data” state (no numbers) |
| Irregular-data caveat | When M7 reports `cadence != effectively_constant_cadence`, show an irregular-sampling note |
| Freshness | Show last `observed_at` and generated time; stale-data disclosure per [08](08_DASHBOARD_SPEC.md) |
| Source/provenance | “Trendora forecast — not an official GitHub field” disclosure |
| Missingness | Gaps stay gaps; no imputed markets or fabricated points ([08](08_DASHBOARD_SPEC.md)) |

The dashboard may use M7 `SeriesDiagnostics` for the caveat inputs; it must not invent thresholds.

---

## 13. YouTube / data-policy boundary

**Decision:** YouTube is **excluded from V1 forecast scope**, and whether Trendora may display a forecast derived from official YouTube fields (`view_count`, `subscriber_count`, etc.) is **POLICY/LEGAL REVIEW REQUIRED — OPEN**.

- **Status:** OPEN (policy), with a concrete scoping consequence: YouTube is DEFERRED, not blocking V1.
- **Rationale / evidence:** [03_DATA_SOURCES.md](03_DATA_SOURCES.md) states derived scores/leaderboards/derived metrics based on API data are generally prohibited unless the analytics/derived-metrics amendment is accepted (policy III.E.4.h; amendment path from 2026-06-01). A forecast of a YouTube official field is a Trendora-calculated value over YouTube data; the repository does not establish whether that is an approved derived artifact. M9 makes **no legal claim**.
- **Consequence:** GitHub V1 proceeds; YouTube-derived forecasts remain unavailable until the amendment/product-review outcome is known. If the review approves derived forecasts, YouTube can be re-scoped in a later milestone using the same level/naive/interval machinery.

---

## 14. Persistence and retention

### 14.1 Forecast persistence

**Decision:** V1 computes forecasts **on demand from M5** (in-memory). No forecast persistence.

- **Status:** REQUIRED V1.
- **Rationale:** forecasts must always reflect the latest snapshots; no forecast tables exist and [02_DATABASE_SCHEMA.md](02_DATABASE_SCHEMA.md) leaves them out of `0001_initial_schema`; derived-data semantics and retention are simpler while nothing is stored ([06](06_ML_FORECASTING.md) §6). Recompute-on-read keeps the schema unchanged.
- **Consequence:** the API/dashboard call the in-memory M6A path per request. Persistence is DEFERRED until (a) an API/dashboard need for stable, versioned forecasts exists and (b) a derived-forecast retention policy is defined.

### 14.2 Retention

- **Technical:** with no forecast persistence, there is no forecast-retention problem in V1. Source snapshots keep their existing documented retention (YouTube non-authorized stats ≤30 days; no GitHub-specific retention policy documented).
- **Policy/legal:** multi-year YouTube history requires the analytics storage amendment — OPEN, same as Decision 19. Forecast retention, should persistence ever be added, would be a separate derived-data policy and is OPEN.

**Status:** REQUIRED V1 (recompute, no tables) / retention policy items OPEN.

---

## 15. Explicitly deferred capabilities

| Capability | Status | Blocked by |
| --- | --- | --- |
| Increment/delta forecasting | DEFERRED | differencing + increment evaluation policy; not implemented in M6A |
| Volume/activity forecasting (e.g., new videos/day) | DEFERRED | aggregation/resampling rules that do not exist |
| YouTube-derived forecasts | DEFERRED (policy-gated) | Decision 19 (POLICY/LEGAL REVIEW REQUIRED) |
| HN / SE forecast scope | DEFERRED | low product value; not a growth series |
| Publisher/channel forecast scope | DEFERRED | only YouTube channels have publisher series; policy-gated |
| Moving average as production model | DEFERRED | `window` policy unspecified |
| SES as production model | DEFERRED | `alpha` policy unspecified |
| Per-series model selection | DEFERRED | challenger hyperparameters unspecified; M6C is artifact-only |
| Calendar-time holdout / rolling-origin evaluation | DEFERRED | requires defined cadence / additional machinery |
| RMSE / MAPE / MASE | DEFERRED | MAE is sufficient for V1; MAPE unstable near zero |
| Holt / seasonal / ARIMA / Prophet / boosting / neural | DEFERRED | regularity/resampling policy, history, dependencies, opacity |
| Forecast persistence | DEFERRED | no API/dashboard need yet; derived-retention policy undefined |
| FastAPI | DEFERRED | separate milestone |
| Streamlit dashboard | DEFERRED | separate milestone |
| LLM-as-forecaster | REJECTED | forbidden for numeric KPIs |
| Paid AutoML | REJECTED | $0 constraint |
| Resampling / imputation / interpolation / forward-fill | REJECTED | forbidden to invent |

---

## 16. Decision matrix

| # | Decision | V1 choice | Status | Evidence / rationale |
| --- | --- | --- | --- | --- |
| 1 | First forecasting question | Next **level** of a stored official metric | **REQUIRED** | Only shape M6A implements; aligns with “What is likely next” ([08](08_DASHBOARD_SPEC.md)); increment/volume DEFERRED (mechanics absent) |
| 2 | V1 sources | `github` only | **REQUIRED** | Cumulative growth metrics, no derived-metric policy gate ([03](03_DATA_SOURCES.md)); others DEFERRED (policy/value) |
| 3 | V1 subject class | `content_item` (GitHub repository) | **REQUIRED** | GitHub writes repository content snapshots; publisher subjects are only YouTube channels ([04](04_INGESTION_PIPELINE.md); `subject_xor`) |
| 4 | V1 metrics | `stargazer_count`, `fork_count` | **REQUIRED** | Primary adoption signals; `open_issue_count`/`watcher_count` DEFERRED; all YouTube/HN/SE metrics DEFERRED |
| 5 | Level vs increment | Stored **level** | **REQUIRED** | M6A level-only; differencing forbidden to enable silently ([06](06_ML_FORECASTING.md) §2, §4) |
| 6 | Forecast interval | **7-day spacing** (weekly labels) | **REQUIRED** (provisional product choice) | Generation/label convention, not data cadence; M6A interval is explicit ([06](06_ML_FORECASTING.md) §1); no resampling required |
| 7 | Horizon | **4 points** (~28 days) | **REQUIRED** (provisional product choice) | Conservative on short history; does not exceed ~1 month |
| 8 | Minimum history to display | **4 observations** | **REQUIRED** (provisional product choice) | Product floor, not M6A fit minima; dev-DB counts are context, not rule ([06](06_ML_FORECASTING.md) §9) |
| 9 | Irregular timestamps | Forecast in observation order with explicit interval; **no resampling, no regularity gate** | **REQUIRED** | Stored cadence is operator-driven ([04](04_INGESTION_PIPELINE.md)); M6A is order-based; resampling needs unspecified aggregation semantics |
| 10 | Missing observations | **Keep gaps; no fill; no zero-activity** | **REQUIRED** | Existing M5/M6 behavior; imputation forbidden ([06](06_ML_FORECASTING.md) Constraints) |
| 11 | Model selection | **naive** is the V1 production model; no per-series selection | **REQUIRED** | No hyperparameters to invent; M6C `challenger_beats_naive` stays artifact-only ([06](06_ML_FORECASTING.md) §1) |
| 12 | MA window | **No V1 default** | **DEFERRED** | MA not a V1 production model; explicit `window` per evaluation call |
| 13 | SES alpha | **No V1 default** | **DEFERRED** | SES not a V1 production model; explicit `alpha` per evaluation call |
| 14 | Advanced models | All **DEFERRED** (LLM/AutoML REJECTED) | **DEFERRED** | Regularity/resampling policy, history, dependencies, opacity ([06](06_ML_FORECASTING.md) §3) |
| 15 | Evaluation protocol | Chronological **observation-count holdout + MAE on levels** | **REQUIRED** | Implemented in M6A/M6C; only split current data supports ([06](06_ML_FORECASTING.md) §4) |
| 16 | Forecast persistence | **Recompute from M5 on demand (in-memory)** | **REQUIRED** | No tables; freshness; derived-retention undefined ([06](06_ML_FORECASTING.md) §6) |
| 17 | API contract | Minimum response fields defined (subject, metric, model, interval, horizon, points, origin, history, freshness, caveats) | **REQUIRED** (implemented by M11B) | Maps to existing `ForecastResult`; no endpoints invented ([09](09_API_SPEC.md)). Concrete HTTP contract defined in [13_FORECASTING_API_CONTRACT.md](13_FORECASTING_API_CONTRACT.md); implemented as one FastAPI read endpoint (M11B) |
| 18 | Dashboard contract | “What is likely next” with actual-vs-forecast, interval/horizon labels, sample-size caveat, insufficient-history suppression, irregular-cadence caveat, provenance | **REQUIRED** (spec only) | [08](08_DASHBOARD_SPEC.md); M7 `cadence`/`observation_count` supply the caveats |
| 19 | YouTube derived-forecast policy | **POLICY/LEGAL REVIEW REQUIRED — OPEN**; YouTube excluded from V1 | **OPEN** | [03](03_DATA_SOURCES.md) III.E.4.h; amendment path from 2026-06-01; no legal claim made |
| 20 | Data retention | No forecast persistence → no forecast retention in V1; source retention unchanged; multi-year YouTube history OPEN | **REQUIRED** (technical) / **OPEN** (policy) | [03](03_DATA_SOURCES.md); [02_DATABASE_SCHEMA.md](02_DATABASE_SCHEMA.md) |

---

## 17. Implementation readiness gate

| Requirement | Status | Blocking? | Evidence |
| --- | --- | --- | --- |
| Level forecasting machinery (M6A) | **PASS** | No | `forecasting/service.py`; tests |
| Naive model | **PASS** | No | M6A |
| M5 `MetricSeries` read path | **PASS** | No | `analytics/`; tests |
| Provenance labels | **PASS** | No | `origin=trendora_forecast` |
| V1 source/subject/metric scope | **PASS** (decided) | No | this document §5 |
| Interval/horizon | **PASS** (decided, provisional) | No | this document §6 |
| Minimum history to display | **PASS** (decided, provisional) | No | this document §7 |
| Irregularity/missingness behavior | **PASS** (decided) | No | this document §6 |
| Model policy | **PASS** (decided) | No | this document §8 |
| Evaluation baseline | **PASS** (decided) | No | this document §9 |
| Persistence strategy | **PASS** (decided) | No | this document §14 |
| Data policy boundary | **PASS** for GitHub V1 | No (YouTube out of scope) | this document §13 |
| API implementation | **NOT STARTED** | Yes (separate milestone) | [09](09_API_SPEC.md) |
| Dashboard implementation | **NOT STARTED** | Yes (separate milestone) | [08](08_DASHBOARD_SPEC.md) |
| Real series with ≥4 observations | **NOT MET** (dev DB: 0) | Yes for *display*, not for *implementation* | [06](06_ML_FORECASTING.md) §9 |
| YouTube derived-forecast policy | **OPEN** | No (out of V1 scope) | [03](03_DATA_SOURCES.md) |

**Gate result:**

- **implementation-ready: YES** — the slice “forecast GitHub repository `stargazer_count`/`fork_count` level, naive, 4 weekly points, on-demand from M5, ≥4 observations, `origin=trendora_forecast`, with history/freshness/irregularity caveats” is fully specified and uses only existing M6A machinery plus a thin product layer. No decision needed from an external authority to build it. **Implemented by M10** (`src/trendora/product/github_forecast.py`).
- **API-ready: NO** — FastAPI is a separate later milestone; [09](09_API_SPEC.md) defines no endpoints; this document defines only the minimum response fields.
- **dashboard-ready: NO** — Streamlit is a separate later milestone; product behavior is specified here, UI is not.
- **production-ready: NO** — (1) the dev database contains **no series with ≥4 observations**, so no real forecast can be displayed or validated yet; (2) interval/horizon/minimum-history are provisional product choices pending real-series re-review; (3) YouTube derived-forecast policy is OPEN (does not block the GitHub slice, but blocks any production claim for YouTube-derived forecasts); (4) no operator cadence, no forecast persistence, no evaluation history.

---

## 18. Next implementation milestone

**Recommended next milestone (M10): the V1 forecast product slice** — a thin in-memory layer over M6A, no schema change, no new dependencies:

1. A V1 product entry point that, given a GitHub repository `content_item` and metric (`stargazer_count` / `fork_count`), loads the M5 series, enforces **≥4 observations** (else returns an insufficient-history state), and produces a **naive** forecast with **horizon=4**, **interval=7 days**, labeled `origin=trendora_forecast`.
2. Result carries `history_count`, `history_start`/`history_end`, last `observed_at`, `generated_at`, and an irregular-cadence flag derived from M7 `SeriesDiagnostics`.
3. Reuses the existing M6A `ForecastService.forecast` path (no new models, no resampling, no persistence, no FastAPI, no Streamlit).

This is unambiguous because every parameter is fixed in this document. Deliberately **not** in M10: API, dashboard, persistence, increment/volume, other sources, other models, YouTube, resampling, evaluation changes.

**M10 status (implemented):** the slice above is implemented as a thin in-memory layer in `src/trendora/product/github_forecast.py` (`GitHubForecastProduct`), consuming M5 via `AnalyticsService`, M6A naive via `ForecastingService.forecast`, and M7 `SeriesDiagnostics` for the cadence caveat. It enforces `≥4` observations (`InsufficientHistoryError` otherwise), rejects unsupported source/metric/publisher-subject requests (`ForecastingValidationError`), emits exactly 4 points at the 7-day interval with `origin=trendora_forecast`, and exposes `observation_count`, `history_start`/`history_end`, `latest_observed_at`, and the cadence fact. No SQL, no connectors, no persistence, no resampling, no new dependencies; API and dashboard remain unimplemented.

If the V1 slice is not yet wanted, the alternative is no implementation at all until the product wants the “What is likely next” view populated — the requirements above remain the contract either way.
