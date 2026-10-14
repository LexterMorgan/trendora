# 13 — Forecasting API Contract

## Status

- **M11A (this document):** API contract specification only.
- **M10 product:** implemented and tested (`src/trendora/product/github_forecast.py`).
- **M11B (implemented):** a thin FastAPI adapter now exists in [src/trendora/api](../../src/trendora/api/) exposing exactly the single read endpoint below, per §16. Full suite: 354 passing.
- **FastAPI implementation:** **implemented** as an adapter over M10. No forecasting logic, SQL, connectors, auth, persistence, or rate limiting live in the API layer.
- **Contract discipline:** every decision below is labeled **ESTABLISHED** (directly supported by repository implementation/docs), **PROPOSED** (a minimal API design choice needed to make the HTTP contract concrete, not previously product-specified), or **OPEN** (cannot safely be resolved from the repository). Proposals are concrete enough to implement but are not product law.

The API exposes exactly what M10 already does. It is an adapter over M10, not a new forecasting engine.

---

## 1. Purpose

Expose the implemented M10 GitHub forecasting product (`GitHubForecastProduct`) as an HTTP read model for future consumers (eventually the Streamlit dashboard, per [08_DASHBOARD_SPEC.md](08_DASHBOARD_SPEC.md) and [09_API_SPEC.md](09_API_SPEC.md)).

What it returns: a **Trendora-derived, in-memory forecast** of the future **level** of a GitHub repository `stargazer_count` or `fork_count`, computed on demand from stored `metric_snapshots`, plus the factual history/freshness/cadence context needed to present it honestly.

It must **not** answer arbitrary analytics questions, mutate data, or bypass M10.

---

## 2. Scope

Exactly the M10 V1 contract is exposed ([12_FORECASTING_PRODUCT_REQUIREMENTS.md](12_FORECASTING_PRODUCT_REQUIREMENTS.md), [src/trendora/product/github_forecast.py](../../src/trendora/product/github_forecast.py)):

- **source:** `github` (implicit; not a client input)
- **subject:** repository `content_item`
- **metrics:** `stargazer_count` or `fork_count` only
- **model:** `naive` (fixed; not a client input)
- **forecast type:** future level of the stored metric (no differencing, no increments, no volume)
- **horizon:** exactly 4 points (fixed; not a client input)
- **interval:** 7 days, a **generation/labeling convention**, not a claim that snapshots are weekly (fixed; not a client input)
- **minimum history:** ≥ 4 actual M5 observations; fewer is an error, never a fabricated forecast
- **storage:** in-memory, computed on demand, nothing persisted
- **provenance:** `origin = "trendora_forecast"`
- **history:** unchanged, not resampled, not interpolated, not forward-filled, not zero-filled

Out of scope (non-goals in §17): every other M5/M6/M7 capability, API-side forecasting, model selection, diagnostics-as-an-endpoint, other sources/subjects, persistence, auth, rate limiting.

---

## 3. Architecture

```text
HTTP request
  → future FastAPI adapter (M11B)
  → M10 GitHubForecastProduct  (src/trendora/product/github_forecast.py)
      → M5  AnalyticsService.get_metric_series
      → M6A ForecastingService.forecast  (naive, horizon=4, interval=7 days)
      → M7  DiagnosticsService.diagnose   (cadence / gap facts)
  → M10 GitHubForecastResult
  → HTTP response
```

**ESTABLISHED:** the adapter must call `GitHubForecastProduct` and nothing else for forecast computation. It must not query `metric_snapshots`, issue SQL, call connectors, fit models, resample, or persist. There is exactly one data read path (M5), used internally by M10. No second SQL path is introduced by the API.

---

## 4. Resource / Endpoint

**PROPOSED.** [09_API_SPEC.md](09_API_SPEC.md) lists `forecasts / anomalies` as a likely later resource group but defines **no endpoint path**; it mentions `/v1` versioning as “not started”. The path below is therefore a proposal, not established law.

```text
GET /api/v1/forecasts/github/{content_item_id}?metric={metric}
```

| Component | Value | Status |
| --- | --- | --- |
| Method | `GET` | **PROPOSED** (see below) |
| Version prefix | `/api/v1/` | **PROPOSED** — consistent with docs/09’s explicit `/v1` note |
| Resource group | `forecasts` | **PROPOSED** — matches docs/09’s `forecasts / anomalies` group |
| Source segment | `github` | **PROPOSED** — makes `source` implicit; M10 fixes source to `github` |
| Path parameter | `content_item_id` (UUID) | **PROPOSED** (type ESTABLISHED from M10) |
| Query parameter | `metric` ∈ {`stargazer_count`, `fork_count`} | **PROPOSED** (values ESTABLISHED from M10) |

**Method rationale (PROPOSED):** M10 computes on demand, writes nothing, and mutates no state; [09_API_SPEC.md](09_API_SPEC.md) says the API exposes **read models of Python-computed results**. A `GET` read-style operation is the natural mapping. No `POST` and no persistence endpoints are created.

**Not exposed as inputs (ESTABLISHED from M10):** `horizon`, `interval`, `model`, `alpha`, `window`, `holdout`, persistence options. `source` is not a client input (inferred from the `github` segment).

**Open:** final path naming/versioning sign-off; docs/09 gives no path convention beyond the `/v1` mention.

---

## 5. Request

### Path parameter

| Name | Type | Required | Description | Status |
| --- | --- | --- | --- | --- |
| `content_item_id` | UUID (canonical lowercase string) | Yes | The repository `content_item` identity from M5/M10. | **ESTABLISHED** (type) / **PROPOSED** (as path param) |

### Query parameter

| Name | Type | Required | Description | Status |
| --- | --- | --- | --- | --- |
| `metric` | string | Yes | Exactly one of `stargazer_count` or `fork_count`. | **ESTABLISHED** (values) / **PROPOSED** (as query param) |

No request body. No other parameters. If `metric` is omitted or invalid, the request is rejected (§10). `source` is never a client input.

### Client responsibilities

- Provide a valid UUID for `content_item_id`.
- Provide exactly one approved metric value.
- Understand that the forecast uses the fixed M10 defaults (naive, 4 points, 7-day interval); these are not negotiable per request.

---

## 6. Response

**PROPOSED** (shape). Field names mirror M10 `GitHubForecastResult` wherever possible; `interval` (a Python `timedelta`) is serialized as `interval_days` (§11).

HTTP 200 body:

```json
{
  "source_code": "github",
  "metric_name": "stargazer_count",
  "content_item_id": "88888888-8888-4888-8888-888888888801",
  "content_external_id": "openai/openai-python",
  "model": "naive",
  "horizon": 4,
  "interval_days": 7,
  "origin": "trendora_forecast",
  "observation_count": 5,
  "history_start": "2026-08-02T09:00:00+00:00",
  "history_end": "2026-08-30T09:00:00+00:00",
  "latest_observed_at": "2026-08-30T09:00:00+00:00",
  "cadence": "effectively_constant_cadence",
  "irregular_cadence": false,
  "points": [
    { "at": "2026-09-06T09:00:00+00:00", "value": 1234.0 },
    { "at": "2026-09-13T09:00:00+00:00", "value": 1234.0 },
    { "at": "2026-09-20T09:00:00+00:00", "value": 1234.0 },
    { "at": "2026-09-27T09:00:00+00:00", "value": 1234.0 }
  ]
}
```

| Field | Source (M10) | Meaning |
| --- | --- | --- |
| `source_code` | `source_code` | `"github"` |
| `metric_name` | `metric_name` | `"stargazer_count"` or `"fork_count"` |
| `content_item_id` | `content_item_id` | Repository content item UUID |
| `content_external_id` | `content_external_id` | GitHub `owner/repo` string when present; null otherwise |
| `model` | `model` | `"naive"` |
| `horizon` | `horizon` | `4` |
| `interval_days` | `interval` (timedelta) | `7` — whole-day serialization, §11 |
| `origin` | `origin` | `"trendora_forecast"` |
| `observation_count` | `observation_count` | Number of stored M5 observations used |
| `history_start` | `history_start` | First `observed_at` of the series |
| `history_end` | `history_end` | Last `observed_at` of the series |
| `latest_observed_at` | `latest_observed_at` | Same as `history_end`; freshness fact |
| `cadence` | `cadence` | One of `no_gap_data` / `effectively_constant_cadence` / `variable_cadence` |
| `irregular_cadence` | `irregular_cadence` | `true` when `cadence == "variable_cadence"` |
| `points` | `points` | Exactly 4 forecast points (§7) |

No success `status` field is added; errors use the envelope in §10. No nested objects are introduced for grouping. No fields are renamed without a serialization reason (`interval` → `interval_days`).

---

## 7. Forecast point

**ESTABLISHED** semantics from M10/M6A; **PROPOSED** JSON shape.

Each point is:

```json
{ "at": "2026-09-06T09:00:00+00:00", "value": 1234.0 }
```

- `at`: `latest observed_at + n × 7 days`, for `n = 1..4` (M6A `_forecast_timestamp`). Exactly 4 points.
- `value`: naive level forecast — the last observed `metric_value`, repeated (float).

**Timestamp honesty (ESTABLISHED):** these `at` timestamps are **Trendora-generated forecast timestamps**, not source observation timestamps. They do **not** imply the source collects weekly, that the database holds a weekly grid, or that the latest observation is exactly 7 days after the previous one. The response already carries the true history timing in `history_start` / `history_end` / `latest_observed_at` so consumers can tell generated forecast times apart from observed times.

---

## 8. Provenance

**ESTABLISHED.** The response carries `origin = "trendora_forecast"` (M10 `GitHubForecastResult.origin`). Forecast values are Trendora-derived; they must never be presented as official GitHub fields. The field is **not** renamed to `source`, `provider`, `official`, or `generated_by`.

Distinction preserved in the response:

- `source_code` / `metric_name` / `content_external_id` identify the **official source subject and metric** being described.
- `origin` declares that the **values in `points` are Trendora-derived**.

---

## 9. History / cadence context

**ESTABLISHED** facts from M7 (via M10 `GitHubForecastResult`), surfaced verbatim for consumers to present sample-size, freshness, and irregular-sampling caveats:

- `observation_count`
- `history_start` / `history_end`
- `latest_observed_at`
- `cadence` (M7 `CadenceClass.value`)
- `irregular_cadence` (boolean convenience derived from `cadence`)

Rules:

- **No invented thresholds or scores.** No `stale_after`, `freshness_score`, `forecastability_score`, `confidence_score`, `reliability_score`. Freshness is the factual `latest_observed_at`. No boolean `fresh` field exists.
- **An irregular series is not invalid (ESTABLISHED).** `cadence = "variable_cadence"` (or `irregular_cadence = true`) is a factual caveat, never a rejection, a `forecast_invalid` state, or a `low_confidence` signal. The forecast is still returned.

---

## 10. Errors

**PROPOSED** mapping (repository has no HTTP error contract; docs/09 defines none). Exception types are **ESTABLISHED** (M10/M5).

Minimal error envelope:

```json
{
  "error": {
    "code": "forecast_insufficient_history",
    "message": "GitHub V1 forecast requires at least 4 observations; found 2"
  }
}
```

Optional `detail` (object) may be added per code when useful. No enterprise error framework.

| Condition | Source exception | HTTP status | Error code | Notes |
| --- | --- | --- | --- | --- |
| `metric` omitted or not `stargazer_count`/`fork_count` | adapter request validation (or M10 `ForecastingValidationError`) | 422 | `invalid_metric` | |
| `content_item_id` is not a valid UUID | request parsing | 422 | `invalid_request` | FastAPI/Pydantic default |
| No such content item (valid UUID, nothing stored for it) | adapter M5 identity check (thin read; **PROPOSED**) | 404 | `forecast_not_found` | §10.1 |
| Content item exists but < 4 observations | M10 `InsufficientHistoryError` | 422 | `forecast_insufficient_history` | §10.2 |
| Underlying M5 query failure | M5 `AnalyticsQueryError` | 500 | `analytics_query_error` | adapter/query bug |
| Unexpected failure | — | 500 | `internal_error` | |

Status conventions:

- **400 vs 422:** the contract uses **422** for request-validation and data-state failures, matching FastAPI/Pydantic’s default. A distinct 400 is not required. **PROPOSED.**
- **404:** only for an unknown `content_item_id`. **PROPOSED.**
- **409:** not used — a read operation has no genuine conflict. (No repo support for it.)
- **503:** not used — M10 reads stored data and has no external service dependency. **OPEN** if a service layer is ever added.

The API never fabricates a forecast: it does not return zeros, partial points, or a fallback when history is insufficient.

### 10.1 Unknown content item

**PROPOSED.** The adapter may resolve `content_item_id` existence through M5 (a thin read on the existing analytics path — not new SQL, not a connector call). If the item does not exist → `404 forecast_not_found`. If it exists but has 0–3 observations → `422 forecast_insufficient_history`. Without the existence check, a truly unknown item would surface as `422 forecast_insufficient_history` (found 0), which is an acceptable fallback; the 404 distinction is recommended but is an adapter decision.

**M11B implementation:** the fallback is implemented — a truly unknown `content_item_id` (or one with 0–3 observations) returns `422 forecast_insufficient_history`. The `404 forecast_not_found` distinction is **not** implemented because M5 exposes no content-item existence check, and adding one would require an architectural change (a new M5 method) that is outside a thin adapter; this matches the contract's acceptable fallback. It remains OPEN if the 404 distinction is ever required.

### 10.2 Insufficient history

**PROPOSED.** For an existing repository with 0 or 1–3 observations, M10 raises `InsufficientHistoryError`. The recommended HTTP representation is **422 `forecast_insufficient_history`**. Alternatives considered and left **OPEN** for sign-off:

- 404 (“no forecast resource exists for this repo”) — loses the “repo exists, just not enough data” distinction.
- 200 with a `status: "insufficient_history"` field and no points — a non-error success shape that conflicts with M10 raising an exception.

The contract recommends 422; it is a proposal, not an established rule.

---

## 11. Serialization

**PROPOSED** conventions (no application-level JSON conventions exist in the repository; connectors use `datetime.isoformat()` in `source_metadata`, which is the closest precedent).

| Type | JSON representation | Example |
| --- | --- | --- |
| UUID | canonical lowercase string (`str(uuid)` form) | `"88888888-8888-4888-8888-888888888801"` |
| datetime | ISO 8601 / RFC 3339, timezone-aware (UTC offset preserved); all M5/M6/M7 timestamps are already timezone-aware | `"2026-09-06T09:00:00+00:00"` |
| timedelta | integer whole days via `interval_days` | `7` |
| enum (`ForecastModel`, `CadenceClass`) | `.value` string | `"naive"`, `"variable_cadence"` |
| float | JSON number | `1234.0` |

**`interval` → `interval_days` rationale:** M10’s `interval` is a Python `timedelta`, which has no JSON form. The V1 interval is exactly 7 whole days, so an integer days value is explicit and unambiguous and cannot be mistaken for a data-cadence claim. If a non-whole-day interval is ever allowed, this field would need an ISO-8601 duration form (`P7D`) — **OPEN** then, not now.

No `repr()`, no dataclass internals, no SQLAlchemy models are exposed.

---

## 12. Security

**OPEN.** [09_API_SPEC.md](09_API_SPEC.md) states: “Authn/z for any non-local deployment (not designed yet).” No mechanism — JWT, API keys, OAuth, Supabase auth, role-based access control — is invented here.

Consequence:

- A local/development M11B adapter may run without auth (consistent with docs/09’s “not designed yet”).
- Any non-local deployment **must not** be exposed until auth is designed. This does not block contract or local implementation.

---

## 13. Rate limiting / operational behavior

**ESTABLISHED:** M10 reads already-stored `metric_snapshots` and does **not** call GitHub or any external API, so **GitHub API quotas do not apply** to this endpoint.

**OPEN:** public API rate limiting is not specified (docs/09 lists rate limits under “Not started”). No client-side rate limits are invented. Latency expectation: on-demand M5 read + in-memory naive forecast; small, but not benchmarked.

---

## 14. Caching / persistence

**Explicitly out of scope (ESTABLISHED):** M10 forecasts are on-demand and in-memory. The API contract introduces no forecast storage, no cache tables, no Redis, no background jobs, no scheduler, no refresh jobs.

Forecast caching (e.g., memoizing identical requests) may be considered a future **OPEN** operational decision if profiling ever justifies it; it is not required and not designed here.

---

## 15. API readiness gate

| Requirement | Status | Evidence |
| --- | --- | --- |
| M10 product implemented & tested | **PASS** | `src/trendora/product/github_forecast.py`; 335 tests |
| M11B FastAPI adapter implemented & tested | **PASS** | `src/trendora/api/`; 19 API tests; full suite 354 |
| Contract: request identity (UUID + metric) | **PASS** (implemented) | this document §5 |
| Contract: response shape | **PASS** (implemented) | this document §6 |
| Contract: provenance / caveats | **PASS** (ESTABLISHED semantics, implemented) | §8, §9 |
| Contract: error mapping | **PASS** (implemented, minus 404) | §10 |
| Endpoint path / versioning sign-off | **OPEN** | docs/09 defines none beyond `/v1` mention |
| 400-vs-422 and insufficient-history status final choice | **OPEN** (implementation follows §10 recommendation) | §10 |
| Authentication (non-local) | **OPEN** | docs/09 |
| Rate limiting | **OPEN** | docs/09 |
| OpenAPI generation | **ESTABLISHED** as the contract mechanism | docs/09; generated by FastAPI |

**Gate result:**

- **contract-ready: YES** — the request/response/error contract is concrete and implemented.
- **implementation-ready: YES** — the FastAPI read adapter (M11B) is implemented; auth is only required for non-local deployment.
- **dashboard-ready: NO** — Streamlit is a separate later milestone; this contract deliberately contains no UI fields.
- **production-ready: NO** — auth OPEN, rate limiting OPEN, endpoint/version sign-off OPEN, the `404 forecast_not_found` distinction OPEN, and the dev database still has no series with ≥4 observations ([06](06_ML_FORECASTING.md) §9), so nothing real can be served or validated yet.

---

## 16. M11B implementation boundary

**M11B is implemented.** The adapter lives in `src/trendora/api/` (`app.py`, `models.py`, `errors.py`) and builds **only**:

1. A FastAPI application (dependency: `fastapi>=0.115,<1`; ASGI server intentionally not added — `TestClient` needs none) with **exactly one** read endpoint per §4.
2. Request parsing: `content_item_id` (UUID) path parameter; `metric` query parameter validated against {`stargazer_count`, `fork_count`} at the boundary (omitted or invalid → `422 invalid_metric`).
3. An adapter that constructs `GitHubForecastRequest` and calls `GitHubForecastProduct.forecast(...)` — nothing else.
4. A Pydantic response model (`ForecastResponse`) serializing `GitHubForecastResult` per §6/§11.
5. Exception handlers mapping M10/M5 exceptions and FastAPI request-validation to the §10 envelope.
6. The §10.1 404 identity check was **not** implemented (see §10.1) — the acceptable fallback is used.

M11B does **not** add: other endpoints, auth, rate limiting, caching, persistence, pagination, model selection, diagnostics endpoints, connector calls, SQL, resampling, CORS, or a health endpoint. The full suite is 354 passing (19 new API tests).

---

## 17. Non-goals

The API contract explicitly does **not** provide:

- New forecasting models, or API-side forecasting of any kind
- `horizon` / `interval` / `model` / `alpha` / `window` as request inputs
- Database writes, forecast persistence, or forecast tables
- Cache/Redis/background jobs/scheduler/refresh jobs
- Connector calls or live GitHub reads
- Resampling, interpolation, imputation, or any observation fabrication
- Dashboard/UI behavior, charts, or frontend-specific fields
- Advanced ML (Holt, seasonal, ARIMA, neural, LLM, AutoML)
- YouTube / Hacker News / Stack Exchange / publisher forecasts
- Cross-source or market-level forecasts
- Model selection or naive-vs-challenger endpoints
- Authentication/authorization, rate limiting, or caching policies (OPEN, not invented)
- Anomaly detection, NLP, sentiment, or topic modeling
