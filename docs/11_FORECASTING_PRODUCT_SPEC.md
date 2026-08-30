# 11 — Forecasting Product Specification

## Status

- **M8 status:** The M8 product contract is written, but the contract is **not fully specified**.
- **Product contract fully specified:** **NO**. Most product-level forecasting decisions remain **OPEN**.
- **Implementation unblocked:** **NO** for any product-facing slice. The in-memory M6A/M6C/M7 mechanics and provenance labels are established, but no user-facing forecast is specified (target, interval, horizon, minimum history, model policy, persistence, API, dashboard).
- **Major remaining blockers:** (1) the first forecasting product question (level vs increment vs volume, and for which metric/subject) has no repository evidence; (2) no forecast interval or horizon is chosen; (3) no minimum history for displaying a forecast; (4) no model-selection or resampling policy; (5) YouTube derived-metric policy is unresolved for forecasts of YouTube official fields; (6) no forecast persistence decision.

**M9 update:** [12_FORECASTING_PRODUCT_REQUIREMENTS.md](12_FORECASTING_PRODUCT_REQUIREMENTS.md) resolves the decisions above for V1 (naive **level** forecasts of GitHub repository `stargazer_count`/`fork_count`, 4 points at 7-day spacing, on demand from M5, ≥4 observations, `origin=trendora_forecast`). Items resolved by M9 are the product decisions; the technical evaluation notes below remain valid. YouTube-derived forecasts remain POLICY/LEGAL REVIEW REQUIRED. This document records the M8 contract; M9 is the decision authority for V1 scope.

This document is the product-level contract. Technical forecasting/evaluation behavior remains in [06_ML_FORECASTING.md](06_ML_FORECASTING.md). It was produced under the rule **engineering convenience is not a product requirement**: mechanical capability (M6A can emit a number for any series) is not treated as product intent.

Source of truth priority applied: implemented code contracts > schema contracts > project documentation > explicit product requirements > tests > connector/source constraints > engineering inference. Only items supported by the first six may be treated as established; engineering inference is marked OPEN, never silently made a requirement.

---

## 1. Purpose

### Forecasting capability (established)

The repository can, in memory, forecast a **future level** of a single stored official metric for a single subject, given an explicit interval and horizon, using naive, moving average, or simple exponential smoothing over an M5 `MetricSeries` (M6A, commit `9660908`). It can compare naive vs one caller-chosen challenger on the same series and holdout by MAE (M6C, commit `7e9a815`). It can report deterministic series facts such as history length, gaps, cadence, duplicate `observed_at`, deltas, and monotonicity (M7, commit `98b6368`). Nothing is persisted, resampled, imputed, or fabricated. See [06_ML_FORECASTING.md](06_ML_FORECASTING.md).

### Forecasting product (NOT established)

The product question that forecasting answers is **not specified**. The closest documented product statements are:

- [08_DASHBOARD_SPEC.md](08_DASHBOARD_SPEC.md) lists an intended view **“What is likely next”** — Python forecasts “with interval and sample-size caveats”.
- [README.md](../README.md) frames the platform as answering “what is likely to happen next”.

These state that forecasting should support a “what is likely next” view and that interval/sample-size caveats are required in the UI. They do **not** specify which metric, subject, interval, horizon, or model.

### Forecasting implementation (established, partial)

Implementation exists for the in-memory mechanics only (M6A/M6C/M7). No product layer (persisted forecasts, API, dashboard) exists. No second SQL read path exists; forecasting and diagnostics consume only M5 `MetricSeries`.

---

## 2. Product Question

**OPEN.** The first forecasting product question is not resolved by the repository.

Three candidate concepts exist, with different levels of support:

| Candidate | Repository evidence |
| --- | --- |
| Future **level** of an official stored metric | Mechanical support: M6A forecasts stored levels (06 section 2, forecasting/service.py). Dashboard “What is likely next” intent ([08](08_DASHBOARD_SPEC.md)). Not chosen as the product answer. |
| **Increment / change** of a cumulative-looking counter | Not implemented. Differencing is explicitly forbidden to enable silently (06 sections 2, 4). No product decision exists. |
| **Volume / activity** (e.g. new videos/day) | Named historically in docs/03/05 as a planned problem, but depends on aggregation/resampling rules the repository forbids inventing (06 section 2). |

The repository proves forecasting is *intended to answer “what is likely next”* (README, docs/08), and that the only mechanically implemented answer shape is “future level of a stored official metric”. It does **not** establish that the future level is the correct or first product deliverable.

**Decision required:** choose one of level / increment / volume (or a defined combination) with the supporting evidence above. **OPEN — not decidable from the repository.**

---

## 3. V1 Scope

| Dimension | V1 Contract | Status | Evidence |
| --- | --- | --- | --- |
| Sources | No forecast source chosen. Established: only `youtube`, `hacker_news`, `stack_exchange`, `github` connectors write snapshots; `wikimedia`/`gdelt` are seeded registry rows with no connector. | **Open** | [04_INGESTION_PIPELINE.md](04_INGESTION_PIPELINE.md); [02_DATABASE_SCHEMA.md](02_DATABASE_SCHEMA.md) |
| Subject type | Both `content_item` and `publisher` subjects exist in the schema and in `metric_snapshots` (subject XOR). Publisher-subject snapshots exist only for YouTube channels. No forecast subject class is chosen. | **Open** | `models/metrics.py` (`subject_xor`); 06 section 2 |
| Metrics | Mechanical capability: any stored `(source, metric, single subject)` series. No product selection. | **Open** | 06 section 2 |
| Level vs increment | M6A forecasts the stored **level**. Increments/deltas are not implemented; differencing must not be silently enabled. | **Established** (behavior) / **Open** (product choice) | 06 sections 1, 2, 4 |
| Forecast interval | M6A requires an explicit positive `interval`; it never infers one from gap spacing. No product interval (hour/day/week) is chosen. | **Open** | forecasting/service.py; 06 sections 1, 5 |
| Horizon | M6A requires a positive integer `horizon`. No product horizon (points or calendar duration) is chosen. | **Open** | forecasting/models.py; 06 |
| Minimum history | M6A fit minima: naive/SES need ≥1 observation; MA needs `1 <= window <= history`. No minimum history to **display** a forecast exists. | **Established** (fit) / **Open** (display) | forecasting/service.py; 06 section 5 |
| Missingness | Missing snapshots stay missing; no imputation, interpolation, or fabricated observations anywhere. Product policy on missingness is not chosen. | **Established** (behavior) / **Open** (product) | M5/M6; 06 sections 1, 4, 5 |
| Irregular timestamps | M6A uses M5 observation order with the explicit interval; evaluation compares positionally; nothing is resampled. Product behavior for irregular snapshots (forecast / require cadence / resample / reject / warn) is not chosen. | **Established** (behavior) / **Open** (product) | 06 sections 1, 4 |
| Resampling | Forbidden unless a later milestone defines the rule. No resampling policy is defined. | **Established** | 06 Constraints; 06 section 2 |
| Model selection | M6C naive-vs-challenger `challenger_beats_naive` is an evaluation artifact, not a production winner. No production selection rule exists. | **Established** (artifact) / **Open** (product) | 06 sections 1, 4 |
| Persistence | In-memory only; no forecast tables exist. Persistence vs recompute-on-demand is not decided. | **Established** (current) / **Open** (decision) | 06 section 6; [02_DATABASE_SCHEMA.md](02_DATABASE_SCHEMA.md) |
| Provenance | Forecasts carry `origin=trendora_forecast`; must never be presented as official source fields. | **Established** | forecasting/service.py (`_ORIGIN`); 06 Constraints |

No row is marked “proposed”: the repository contains no supported proposal that rises above documented intent, and engineering convenience must not become a requirement.

---

## 4. Forecast Targets

Metric names below are the exact strings written by the connectors (verified in `src/trendora/connectors/*/normalizer.py`). The “Type / behavior” column records **connector/source observations**, not a semantic registry (the repository deliberately has no metric-semantics registry; see 06 section 2 and M7). V1 status is **Open** for every target because no metric/subject is selected.

| Source | Subject | Metric | Type / behavior | V1 status | Reason |
| --- | --- | --- | --- | --- | --- |
| `youtube` | video (content) | `view_count` | Official source field; current/cumulative-looking counter; stored snapshot | **Open** | Not selected. Derived-artifact question for forecasts of official YouTube fields. |
| `youtube` | video (content) | `like_count` | Official source field; current/cumulative-looking counter | **Open** | Not selected. |
| `youtube` | video (content) | `comment_count` | Official source field; current/cumulative-looking counter | **Open** | Not selected. |
| `youtube` | channel (publisher) | `view_count` | Official source field; cumulative-looking counter | **Open** | Only publisher-subject series in the repo. |
| `youtube` | channel (publisher) | `subscriber_count` | Official source field; cumulative-looking counter (hidden counts may be omitted by the API) | **Open** | Not selected. |
| `youtube` | channel (publisher) | `video_count` | Official source field; cumulative-looking counter | **Open** | Not selected. |
| `hacker_news` | story (content) | `score` | Official source field; mutable, can move either way | **Open** | Not selected. |
| `hacker_news` | story (content) | `comment_count` | Official source field; observed count (from `descendants`) | **Open** | Not selected. |
| `stack_exchange` | question (content) | `score` | Official source field; mutable | **Open** | Not selected. |
| `stack_exchange` | question (content) | `view_count` | Official source field; typically non-decreasing | **Open** | Not selected. |
| `stack_exchange` | question (content) | `answer_count` | Official source field; current count | **Open** | Not selected. |
| `github` | repository (content) | `stargazer_count` | Official source field; usually non-decreasing | **Open** | Not selected. |
| `github` | repository (content) | `fork_count` | Official source field; usually non-decreasing | **Open** | Not selected. |
| `github` | repository (content) | `open_issue_count` | Official source field; can fall | **Open** | Not selected. |
| `github` | repository (content) | `watcher_count` | Official source field; stored from `subscribers_count` (legacy `watchers_count` is a stars alias) | **Open** | Not selected. |

Semantics that are **explicitly not** claimed by the repository:

- A non-decreasing M7 `monotonicity` result is **not** a “cumulative” label ([06](06_ML_FORECASTING.md) section 9). GitHub `open_issue_count` and HN/SE `score` are the stored counterexamples.
- A numeric `metric_value` is not, by itself, a meaningful forecast target ([06](06_ML_FORECASTING.md) section 2).

---

## 5. Forecasting Behavior

### Established behavior

- **Input series:** one M5 `MetricSeries` (single `source_code` + `metric_name` + one `content_item_id` **xor** one `publisher_id`), plus explicit `model`, positive `horizon`, positive `interval`, and model params (`window` for MA, `alpha` for SES). Timezone-aware timestamps only; naive datetimes are rejected.
- **Ordering:** M5 order — `observed_at`, then `collected_at`, then snapshot id.
- **Timestamp generation:** forecast points at `latest observed_at + n * interval` for `n = 1..horizon`. Interval is a generation parameter; it is never inferred from snapshot spacing and is not proven by it.
- **Output:** `ForecastResult` with `points` (timestamp + float value), `history_start`/`history_end`/`history_count`, `origin=trendora_forecast`, subject identity.
- **Missing observations:** remain missing. Nothing is interpolated, resampled, forward-filled, or fabricated.
- **Irregular observations:** evaluation compares forecast `i` to held-out observation `i` positionally; held-out timestamps need not equal generated forecast timestamps.
- **Cumulative counters:** M6A forecasts the stored **level**; no differencing is applied or silently enabled.
- **Errors/warnings:** empty series raise `InsufficientHistoryError` (not zero-filled). Naive/SES need ≥1 observation. MA needs `1 <= window <= history`. Invalid horizon/interval/window/alpha and missing identity raise `ForecastingValidationError`. There is currently **no warning channel** (only errors); sample-size warnings for short series do not exist.

### Product decisions still required

- Which series are shown to users (source, subject class, metric names).
- Whether output is a level, an increment, or a volume — and the per-metric semantics behind it.
- Product interval and horizon.
- Minimum history before a forecast is displayed (vs the M6A fit minima).
- Policy for irregular snapshots (forecast from order / require cadence / resample / reject / warn) — resampling must not be chosen without a defined rule.
- Policy for missing observations (stay missing / block / warn).
- Warnings/sample-size caveats surfaced to users.
- Persistence and freshness of displayed forecasts.

---

## 6. Model Policy

| Model | Implementation status | Product status | Prerequisites | Unresolved decisions |
| --- | --- | --- | --- | --- |
| Naive | **Implemented** (M6A) | Selected only as the evaluation baseline ([10](10_TESTING_EVALUATION.md)); **not** selected as the product model | none | Whether naive is ever the user-facing forecast model |
| Moving average | **Implemented** (M6A) | Not selected for production | explicit `window` | Default/derivation of `window` (fixed vs per-series vs tuned) — must not be invented |
| Simple exponential smoothing | **Implemented** (M6A) | Not selected for production | explicit `alpha` (`0 < alpha <= 1`) | Default/derivation of `alpha` (fixed vs per-series vs tuned) — must not be invented |
| M6C naive-vs-challenger | **Implemented** (M6C) | Evaluation artifact only; **not** a production winner | same series/holdout/interval; one caller-selected challenger; `challenger_beats_naive` is `challenger_mae < naive_mae` | Whether comparison becomes a selection rule, and the tie/selection semantics |
| Holt (linear trend) | **Deferred** | Not V1 | explicit regularity/resampling policy + longer history | Advanced-model scope; needs the interval/grid policy first |
| Seasonal (Holt–Winters, seasonal naive) | **Deferred** | Not V1 | long, regular seasonality; public YouTube history may be ≤30 days | Advanced-model scope |
| AR / ARIMA / SARIMA | **Deferred** | Not V1 | regular or resampled series, `statsmodels` dependency | Advanced-model scope |
| Prophet / neural / gradient boosting | **Deferred** | Not V1 | rich regular series; dependencies not installed | Advanced-model scope |
| LLM-as-forecaster | **Rejected** | n/a | n/a | n/a |
| Paid AutoML | **Rejected** | n/a | n/a | n/a |

Advanced models (Holt, seasonal, ARIMA family, neural/boosting) remain **blocked** until three things are specified: a resampling/regularity policy, product interval and horizon, and the history that displays. The repository forbids inventing any of these ([06](06_ML_FORECASTING.md) sections 3, 5, 8; Constraints). No dependency is added in M8.

---

## 7. Evaluation Policy

### Existing implementation (established)

- Chronological split only; no random train/test.
- Holdout = last **N observations** (explicit `holdout`), not a calendar duration; train is the strict prefix.
- MAE on positional pairs; no RMSE/MAPE/MASE in code.
- No leakage: test values never enter fitting.
- Irregular timestamps are allowed; evaluation does not resample.
- Missing snapshots stay missing; fabricated times are not scored.
- M6C: naive and one challenger evaluated on the same series/holdout/interval; `challenger_beats_naive` is a strict comparison (ties are false) and is an evaluation artifact.

### Product contract

**None defined.** The evaluation protocol is an engineering artifact; no V1 evaluation requirement is documented beyond the implementation itself.

### Open decisions

- Calendar-time holdout vs observation-count holdout vs rolling-origin as the V1 selection protocol (06 section 4, [10](10_TESTING_EVALUATION.md)).
- Minimum test length and whether multiple evaluation windows are used.
- Level vs differenced evaluation for cumulative-looking counters.
- The model-selection rule (e.g. challenger must strictly beat naive) and tie handling — documented as a *proposed* experimental rule in [06](06_ML_FORECASTING.md) section 4, not product law.
- Whether RMSE or MASE is ever added.

---

## 8. Data Sufficiency & Quality

M7 (`SeriesDiagnostics`, `origin=trendora_diagnostic`) reports deterministic facts about any M5 series: observation count, first/last `observed_at`, elapsed duration, gap statistics (min/max/mean/median, count, CV), cadence class, duplicate-`observed_at` facts, delta statistics, and monotonicity class. These facts can inform — but do not decide — product policy:

- **Observation count** informs the minimum-history-to-display decision (below).
- **Elapsed duration / cadence / gaps** inform whether a product interval and regularity policy are credible.
- **Duplicate `observed_at`** facts inform whether same-timestamp collapse is ever needed.
- **Delta sign structure / monotonicity** provide *evidence* about which metrics behave like cumulative counters, but are **not** a cumulative-metric registry and **not** a semantic classification.

Evidence from the current development database (read-only count, 2026-08-23, in [06](06_ML_FORECASTING.md) section 9 — **not** a product rule): 1921 `metric_snapshots`; 1861 subject+metric series had **one** observation and 30 had **two**; none had three or more. Short series therefore cannot support holdout evaluation today, and user-facing forecasts on such series would have no evaluation basis. This supports caution; it does not choose any product rule.

No numeric forecastability score exists or is created. M7 explicitly has no `forecastable` flag, no 0–1 score, and no model recommendation.

---

## 9. Forecast Provenance

- **Official source metrics** are stored as collected in `metric_snapshots` and returned unchanged by M5. They are not rewritten into new business metrics ([05](05_ANALYTICS_SPEC.md)).
- **Trendora-derived outputs** carry explicit `origin` labels:
  - `trendora_forecast` — `ForecastResult`, `EvaluationResult`, `ComparisonResult` (forecasting/service.py `_ORIGIN`).
  - `trendora_derived` — `AggregateSummary` (analytics/service.py `_ORIGIN`).
  - `trendora_diagnostic` — `SeriesDiagnostics` (diagnostics/service.py `_ORIGIN`).
- **Labeling expectations:** forecasts must never be presented as official source fields ([06](06_ML_FORECASTING.md) Constraints). The dashboard must disclose “not from YouTube” for Trendora-calculated fields shown beside API fields ([08](08_DASHBOARD_SPEC.md)). This labeling contract is established; the exact UI/API presentation is not.

---

## 10. Persistence

- **Current state:** in-memory only. No forecast tables exist; [02_DATABASE_SCHEMA.md](02_DATABASE_SCHEMA.md) lists forecast tables as outside `0001_initial_schema`.
- **Specified persistence:** none. Before any persistence, decide retention of derived forecasts vs recompute-on-read; keying by subject/metric/model/interval/horizon; and that writes never mutate `metric_snapshots` ([06](06_ML_FORECASTING.md) section 6).
- **Implication for later work:** the API and dashboard cannot rely on stored forecasts today; any product slice must either recompute on demand or first resolve the persistence decision. No tables are created in M8.

---

## 11. API Readiness

**Existing API documentation** ([09_API_SPEC.md](09_API_SPEC.md)):

- FastAPI between PostgreSQL analytics results and Streamlit; read models of Python-computed results, not raw connector dumps or ad-hoc SQL.
- `forecasts / anomalies` is listed as a later read-model resource group.
- Pagination and `collected_at` filters from day one; OpenAPI generated by FastAPI is the contract.
- No forecast request/response shape, model visibility, horizon/interval fields, warnings, provenance, sample-size fields, source fields, or derived-forecast labeling are defined.

**Remaining undefined:** the entire forecast API contract.

**Must be decided before API implementation:** the first product question, V1 series scope, interval, horizon, minimum history, model-selection policy, persistence, and the API-specific presentation of provenance/warnings/sample-size. No FastAPI is built in M8.

---

## 12. Dashboard Readiness

**Existing dashboard documentation** ([08_DASHBOARD_SPEC.md](08_DASHBOARD_SPEC.md)):

- Must remain Streamlit (Plotly direction).
- Intended view **“What is likely next”** — Python forecasts “with interval and sample-size caveats”.
- Required UI constraints: data freshness (`collected_at`, quota-exhausted flags); source mix; “not from YouTube” disclosure for Trendora-calculated fields beside API fields; markets without data rather than imputed numbers.

**Remaining undefined:** where forecasts appear, what exactly users see (values/spans), horizon/interval display, model selection visibility, warning text, sample-size caveat mechanics, freshness semantics for recomputed forecasts, and provenance labeling details.

**Must be decided before dashboard implementation:** the same product decisions as the API (targets, interval, horizon, min history, model policy, persistence), plus the dashboard presentation rules above. No Streamlit is built in M8.

---

## 13. Source / Policy Constraints

Documented constraints that constrain any forecast product, from [03_DATA_SOURCES.md](03_DATA_SOURCES.md) and [05_ANALYTICS_SPEC.md](05_ANALYTICS_SPEC.md):

- **YouTube derived metrics:** derived scores/leaderboards/derived metrics based on API data are generally **prohibited** unless the analytics/derived-metrics amendment is accepted (policy III.E.4.h; amendment path effective from 2026-06-01). A forecast of `view_count` / `subscriber_count` etc. is a Trendora-calculated field over YouTube data and therefore falls under this derived-artifact question. **Whether forecasting YouTube official fields is an allowed derived artifact is OPEN** and needs the amendment/legal decision; M8 makes no legal claim beyond the documented policy.
- **YouTube storage:** non-authorized statistics must not be stored more than 30 days (delete or refresh) unless the amendment is accepted (then up to 36 months for approved statistical metrics). Trendora does not promise multi-year YouTube history until approval. Historical values may be shown only if presented accurately in a time context.
- **YouTube scraping is prohibited.** Must not replace API metrics with invented stand-ins for the same metric.
- **Forecast/data retention:** no forecast-specific retention is defined. YouTube 30-day rules apply to the underlying non-authorized snapshots; cleanup jobs are still not implemented.

HN/SE/GitHub public reads have no equivalent derived-metric restriction in the repository, but their usefulness as forecast targets is a separate, OPEN product question.

---

## 14. Open Product Decisions

1. **First forecasting product question** — future level of an official metric, increment of a cumulative counter, or volume/activity.
   - *Why:* determines every downstream contract.
   - *Evidence:* dashboard “What is likely next” intent ([08](08_DASHBOARD_SPEC.md)); M6A mechanically forecasts levels; increments/volume have no implementation and are blocked on aggregation rules ([06](06_ML_FORECASTING.md) sections 2, 8).
   - *Resolvable by:* an explicit product-requirements milestone (not by the repository).
2. **V1 forecast sources** — which of `youtube` / `hacker_news` / `stack_exchange` / `github`.
   - *Why:* scopes the API/dashboard and data-sufficiency work.
   - *Evidence:* only these four have connectors writing snapshots.
   - *Resolvable by:* product scope decision.
3. **V1 forecast subject class** — content items vs publishers (only YouTube channels have publisher-subject snapshots).
   - *Why:* changes series identity and volume.
   - *Evidence:* `subject_xor` constraint; 06 section 2.
   - *Resolvable by:* product scope decision.
4. **V1 forecast metrics** — which of the 15 stored metric names.
   - *Why:* a numeric field is not necessarily a meaningful target.
   - *Evidence:* exact metric strings verified in connectors; M7 non-decreasing evidence is factual, not a cumulative registry.
   - *Resolvable by:* product scope decision, informed by M7 diagnostics.
5. **Level vs increment** for cumulative-looking counters — forecast the stored level, the change, both, or neither; differencing must not be silently enabled.
   - *Why:* cumulative levels make naive MAE look strong without meaning.
   - *Evidence:* 06 sections 2, 4; M7 deltas/monotonicity.
   - *Resolvable by:* product decision + evaluation policy.
6. **Forecast interval** (hour/day/week/other) — M6A only requires an explicit positive value.
   - *Why:* the product must pick one; ingest cadence is operator-driven, not proof of a grid.
   - *Evidence:* 06 section 5; connectors set `observed_at = collected_at` at manual runs.
   - *Resolvable by:* product decision.
7. **Forecast horizon** (number of points / calendar duration).
   - *Why:* not inventable; M6A only requires positive.
   - *Resolvable by:* product decision.
8. **Minimum history to display** — distinct from M6A fit minima.
   - *Why:* current dev DB shows 1861 series with one observation, 30 with two, none ≥3; short-series forecasts have no evaluation basis.
   - *Evidence:* M7 observation counts; 06 section 9.
   - *Resolvable by:* product decision using M7 evidence.
9. **Irregular timestamp policy** — forecast from order / require cadence / resample / reject / warn.
   - *Why:* stored cadence is irregular; resampling is currently forbidden.
   - *Resolvable by:* product decision (resampling only via a defined rule).
10. **Missing observation policy** — stay missing / block / warn.
    - *Why:* currently missing stays missing; imputation is forbidden to invent.
    - *Resolvable by:* product decision.
11. **Model-selection rule** — always naive / fixed model / naive-vs-challenger / per-series selection.
    - *Why:* M6C’s boolean is an evaluation artifact, not a production winner.
    - *Resolvable by:* evaluation-policy milestone.
12. **MA `window`** — fixed / per-series / tuned; defaults must not be invented.
    - *Resolvable by:* model-policy decision.
13. **SES `alpha`** — fixed / per-series / tuned; defaults must not be invented.
    - *Resolvable by:* model-policy decision.
14. **Advanced models** (Holt / seasonal / ARIMA / neural / boosting) — whether ever in scope.
    - *Why:* blocked until regularity/resampling policy and history exist.
    - *Resolvable by:* product decision + data-sufficiency milestone.
15. **Evaluation protocol** — calendar vs observation-count vs rolling-origin; minimum test length; multiple windows; level vs differenced evaluation; selection rule.
    - *Why:* no V1 evaluation requirement exists beyond the implementation.
    - *Evidence:* 06 section 4; [10](10_TESTING_EVALUATION.md).
    - *Resolvable by:* evaluation-policy milestone.
16. **Forecast persistence** — in-memory / recompute-on-demand / persisted.
    - *Why:* API and dashboard cannot depend on stored forecasts until decided.
    - *Evidence:* 06 section 6; schema has no forecast tables.
    - *Resolvable by:* implementation-policy milestone.
17. **API contract** — request/response shape, model visibility, horizon/interval fields, warnings, provenance, sample-size.
    - *Why:* nothing defined beyond “later read-model resource group”.
    - *Resolvable by:* API milestone, after decisions 1–16 relevant to it.
18. **Dashboard forecast UI** — where forecasts appear, what is shown, caveat mechanics, provenance labeling.
    - *Why:* docs only commit to a “What is likely next” view with interval/sample-size caveats.
    - *Resolvable by:* dashboard milestone.
19. **YouTube forecast policy** — whether forecasting YouTube official fields is an allowed derived artifact under III.E.4.h / the amendment.
    - *Why:* policy-gated; no legal conclusion is invented here.
    - *Evidence:* [03_DATA_SOURCES.md](03_DATA_SOURCES.md) derived-metrics policy; [05](05_ANALYTICS_SPEC.md).
    - *Resolvable by:* legal/product review, not code.
20. **Data retention** — forecast retention; multi-year YouTube history.
    - *Why:* only the 30-day non-authorized YouTube rule is documented; no retention job exists.
    - *Resolvable by:* product decision + storage-amendment outcome.

M7 does not close any of these; it only provides evidence that later decisions may use ([06](06_ML_FORECASTING.md) section 9).

---

## 15. Readiness Gate

| Requirement | Status | Blocking? | Evidence |
| --- | --- | --- | --- |
| In-memory forecasting mechanics (M6A) | **PASS** | No | forecasting/service.py; commit `9660908`; tests |
| Naive-vs-challenger comparison (M6C) | **PASS** | No | commit `7e9a815`; tests |
| Series diagnostics (M7) | **PASS** | No | commit `98b6368`; tests |
| Provenance labels (`trendora_forecast` / `_derived` / `_diagnostic`) | **PASS** | No | origin constants in code |
| Single SQL read path via M5 | **PASS** | No | 06 section 1; analytics layer |
| First product question | **OPEN** | **Yes** | this doc section 2 |
| V1 series scope (sources/subjects/metrics) | **OPEN** | **Yes** | this doc section 3 |
| Forecast interval and horizon | **OPEN** | **Yes** | this doc sections 3, 5 |
| Minimum history to display | **OPEN** | **Yes** | this doc section 8 |
| Irregular/missing/resampling policy | **OPEN** | **Yes** | this doc sections 3, 5 |
| Model-selection policy (incl. `window`/`alpha`) | **OPEN** | **Yes** | this doc section 6 |
| Evaluation protocol for V1 selection | **OPEN** | **Yes** | this doc section 7 |
| Forecast persistence | **OPEN** | **Yes** | this doc section 10 |
| API contract | **OPEN** | **Yes** | this doc section 11 |
| Dashboard forecast UI | **OPEN** | **Yes** | this doc section 12 |
| YouTube derived-forecast policy | **OPEN** | **Yes** | this doc section 13 |
| Forecast/data retention | **OPEN** | **Yes** | this doc section 13 |

**Gate result:** forecasting is **NOT implementation-ready**, **NOT API-ready**, **NOT dashboard-ready**, and **NOT production-ready**. The in-memory mechanics pass, but every product-facing requirement is OPEN and the product question itself is unresolved. Code existing (M6A/M6C/M7) does not make the product contract complete.

---

## 16. Next Milestone

**No implementation milestone is unambiguous today.**

Even the smallest product slice — “show a forecast for series X” — requires choosing the target metric/subject, the interval, the horizon, the minimum history to display, and the model policy. The repository resolves none of these, and the constraint **engineering convenience is not a product requirement** forbids inferring them.

The genuine next step is a **product-requirements decision milestone** (not an implementation milestone): an explicit decision on Open Product Decisions 1–5 (first product question, V1 sources, subject class, metrics, level vs increment), optionally informed by M7 diagnostics over the real series. Only after those five are decided does the smallest implementation slice become unambiguous. Until then, M8’s correct result is: *forecasting implementation remains blocked because product decisions remain unresolved.*
