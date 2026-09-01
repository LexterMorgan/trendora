# 18 — Research Workspace (M16)

## Status

**M16 (this document + implementation):** the first user-facing Trendora product surface — a web research workspace. It makes the existing M15 research engine usable in a browser.

**Flow implemented:**

```text
user opens Trendora
  → structured research request
  → Next.js same-origin proxy
  → POST /api/v1/research (M15)
  → truthful coverage + execution state
  → real YouTube references
  → open original content
```

No new content intelligence. No AI, patterns, opportunities, ideas, briefs, reports, persistence, auth, additional sources, derived metrics, ranking, or forecasting UI.

**Backend baseline:** 455 passing (unchanged). Frontend: typecheck + lint + production build pass.

---

## 1. Purpose

Establish trust in Trendora's evidence layer: a user performs a real research request and sees exactly what was requested, what source coverage was available, which source was actually executed, how many references came back, and the real YouTube references with raw source facts — with truthful market and coverage framing throughout.

M16 does not yet answer "why is this content good", "what pattern exists", "what opportunity exists", or "what should I create".

---

## 2. Frontend architecture

- **Stack:** Next.js 16.3.4 (App Router) + React 19.2.8 + TypeScript 5, plain CSS. Package manager: npm (scaffolded with `create-next-app@latest`).
- **Location:** `web/` — an isolated frontend directory. The Python package, connectors, analytics, and research domain are untouched.
- **Boundary:** the frontend is a pure consumer of the M15 API. No research logic, no YouTube interpretation, no derived metrics, no ranking, no coverage invention.
- **State:** native `fetch` + React `useState`. No Redux/Zustand/TanStack Query/Axios/UI/chart/form libraries.

### Directory layout

```text
web/
  app/
    layout.tsx              # root layout + metadata
    page.tsx                # research workspace page (client)
    globals.css             # styles
    api/research/route.ts   # thin same-origin BFF proxy → FastAPI
  components/
    ResearchForm.tsx        # topic/market/dates/sources/result limit
    CoveragePanel.tsx       # capability + execution truth
    ReferenceCard.tsx       # one YouTube reference card
    ReferenceList.tsx       # responsive grid of cards
    EmptyState.tsx          # completed + zero references
    ErrorState.tsx          # error envelope → readable message
    MarketCaveat.tsx        # YouTube market-context caveat
  lib/
    trendora-api.ts         # public API types + submit helper
    format.ts               # presentation-only number/date formatting
  .env.example              # TRENDORA_API_BASE_URL
  README.md                 # local dev + deploy notes
```

---

## 3. User workflow

1. User opens Trendora.
2. Enters topic, market, date range, source (YouTube), result limit.
3. Presses **Research**.
4. UI submits the structured request through the same-origin proxy to `POST /api/v1/research`.
5. UI shows: research complete, coverage panel (capability + execution per source), reference count, real reference cards, and the market caveat.
6. **View original** opens the real YouTube URL in a new tab.

---

## 4. API integration / BFF proxy

- Browser → `POST /api/research` (Next.js route handler) → `${TRENDORA_API_BASE_URL}/api/v1/research` → response passed through.
- The proxy forwards the structured JSON body, the backend status, and the safe public body (including the `{"error":{code,message}}` envelope). It performs no research logic.
- Proxy-level conditions: missing `TRENDORA_API_BASE_URL` → `500 backend_not_configured`; backend connection failure → `502 backend_unreachable`. Both use the same envelope.
- **Why the same-origin proxy:** avoids backend CORS work and keeps browser→API traffic simple; matches the recommended M16 architecture. No backend CORS was added.
- No caching, no retries, no queueing, no transformations.

---

## 5. Environment configuration

| Variable | Where | Purpose |
| --- | --- | --- |
| `TRENDORA_API_BASE_URL` | `web/.env.local` (dev) / Vercel | FastAPI backend base URL forwarded to by the proxy, e.g. `http://127.0.0.1:8000` |

`web/.env.example` documents it. No secrets are committed. There is no hard-coded production API URL.

Local run:

```text
Terminal 1 (backend):  source .venv/bin/activate && uvicorn trendora.api.app:create_app --factory --port 8000
Terminal 2 (frontend): cd web && npm run dev
```

---

## 6. Research form

Fields map exactly to M15: `topic`, `market`, `date_from`, `date_to`, `sources`, `result_limit`.

- **Market:** canonical codes ID/TH/MY/SG/VN/PH with friendly labels; canonical codes are submitted.
- **Result limit:** choices 10/20/50/100 (backend range 1..100).
- **Sources:** YouTube is shown as the only available research source (a non-interactive chip, not a fake selectable omnichannel list).
- **Client validation:** only prevents `date_from > date_to` submission; all domain validation remains authoritative in `ResearchQuery`.

---

## 7. Coverage UI

Coverage and execution are always shown separately:

```text
YouTube    Capability: available    Execution: Searched
Instagram  Capability: unavailable  Execution: Not searched
```

- `Capability` comes from `coverage.sources[i].status`.
- `Execution` comes from `executed_sources` (never inferred from availability).
- Partial coverage is shown truthfully: available sources searched, unavailable sources not searched; the request is not presented as failed.

---

## 8. Market semantics

The UI shows:

> **YouTube market context: Singapore** — reflects regional availability/viewability and does not establish creator nationality or content origin.

It never shows "Singapore creators", "Singapore-origin videos", or "Videos from Singapore". No creator/publisher/origin country is inferred or displayed.

---

## 9. Reference cards

Each card shows: source badge (YouTube), channel name, title, description (source metadata, clamped to 3 lines), raw metrics (views/likes/comments), publication date, source position (`Source position #N` — never "Trendora Rank"), and a **View original** button that opens the real YouTube URL in a new tab (`rel="noopener noreferrer"`). The description is YouTube source metadata, never labeled transcript/summary/analysis.

---

## 10. Metrics presentation

- Exactly `view_count`, `like_count`, `comment_count`.
- Human-readable compact formatting (e.g. `421K`, `1.2M`) is presentation only; the underlying value is unchanged.
- Missing (`null`) renders as `—`; zero renders as `0`. Null and zero stay distinct.
- No engagement rate, views/day, velocity, score, popularity, performance, or Trendora Score.

---

## 11. Empty state

A successful `completed` run with `references: []` shows:

> No matching YouTube references were found for this research request. Try a broader topic wording or a wider date range.

It is never presented as a retrieval failure.

---

## 12. Error states

The `{"error":{code,message}}` envelope is mapped to readable messages:

| Code | User-visible behavior |
| --- | --- |
| `invalid_request` / `invalid_research_request` | Check the form and retry |
| `research_no_coverage` | No requested source can satisfy this capability |
| `research_source_not_configured` | Source not configured on the server (backend may need a YouTube API key) |
| `research_upstream_error` | YouTube research temporarily unavailable |
| `backend_unreachable` | Backend could not be reached |
| `backend_not_configured` | `TRENDORA_API_BASE_URL` missing |
| `internal_error` | Unexpected error |

No stack traces, raw JSON dumps as primary UX, exception class names, or secrets. Zero results, service-not-configured, and upstream failure are never blurred.

---

## 13. Visual direction

Clean, professional research workspace: neutral off-white background, white panels/cards, restrained accent, strong typography (Geist), generous spacing, cards optimized for scanning references. Emphasis is Query → Coverage → References, not dashboard metrics. Responsive: single-column form/results on small screens, two-column reference grid on desktop.

---

## 14. Responsive / accessibility

- Responsive layout: desktop, laptop, tablet, and reasonable mobile widths.
- Semantic HTML (`form`, `label`, `section`, `article`, `dl/dt/dd`, `aside`), labels connected to controls, keyboard-accessible links/buttons, visible focus states, reasonable contrast, and form errors associated with the form (`role="alert"`).

---

## 15. Backend / database / AI

- Backend research-domain behavior unchanged (`pytest -q`: 455 passing).
- No DB/schema/migrations/persistence; the frontend adds no localStorage "saved research".
- No AI, no embeddings, no vector DB.
- No additional research sources; only YouTube is presented as available.
- No derived metrics or ranking.

---

## 16. Vercel readiness

Structurally deployable as-is with Next.js defaults: root directory `web`, build command `npm run build`, and the `TRENDORA_API_BASE_URL` environment variable set in Vercel to the hosted FastAPI backend base URL. No Vercel-specific config files were added. Not deployed in M16.

---

## 17. Testing / build results

- `npm install` — succeeded (347 packages, 0 vulnerabilities).
- `npm run typecheck` (`tsc --noEmit`) — clean.
- `npm run lint` (`eslint`) — clean.
- `npm run build` (`next build`) — production build succeeded; routes: `/` (static), `/_not-found`, `/api/research` (dynamic).
- Runtime smoke test: production server served the page and the proxy forwarded both a 200 research envelope and a 422 error envelope from a mock backend correctly.
- Backend `pytest -q` — 455 passed (unchanged).

---

## 18. Non-goals

No AI/analysis/patterns/gaps/opportunities/ideas/briefs/reports, no sentiment, no embeddings/vector DB, no additional research sources (Instagram/TikTok/Facebook/Google Trends), no saved references, no persistence, no database/schema changes, no auth/users/teams/workspaces, no async jobs/queues/alerts/scheduling/publishing, no social inbox, no forecasting dashboard, no derived metrics, no custom ranking, no admin panel.

---

## 19. Readiness for next milestone

M17 (content intelligence / evidence analysis contract) can now assume a stable research workspace that truthfully surfaces coverage, execution, market context, and raw reference facts — the evidence foundation that pattern/opportunity analysis will build on.

---

## 20. Files

- `web/` — Next.js app (App Router, TypeScript, plain CSS)
- `web/app/api/research/route.ts` — BFF proxy
- `web/lib/trendora-api.ts`, `web/lib/format.ts`
- `web/components/` — ResearchForm, CoveragePanel, ReferenceCard, ReferenceList, EmptyState, ErrorState, MarketCaveat
- `web/.env.example`, `web/README.md`
- `web/package.json`, `web/tsconfig.json`, `web/next.config.ts`, `web/eslint.config.mjs` (scaffolded)
