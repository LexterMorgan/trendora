<div align="center">

# Trendora

**A research-first workspace for building a defensible picture of a topic before you write or plan anything about it.**

[![ci](https://github.com/LexterMorgan/trendora/actions/workflows/ci.yml/badge.svg)](https://github.com/LexterMorgan/trendora/actions/workflows/ci.yml)
![status](https://img.shields.io/badge/status-alpha%20v0.1-black)
![python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![next](https://img.shields.io/badge/Next.js-16-black?logo=nextdotjs)
![postgres](https://img.shields.io/badge/PostgreSQL-4169E1?logo=postgresql&logoColor=white)

</div>

> Local alpha. No public deployment yet. AI prose quality is unverified.
> Reading, saving, and reopening research never requires a model call.

---

## The problem

Search results are fragmented, often undated, and easy to over-read. A person
who needs to write or plan something usually ends up with a pile of tabs and no
record of which source each sentence cites.

Trendora collects material for one topic and one window, shows which supplied
source each statement cites, and keeps the limits visible instead of hiding
them. The report is meant to be useful on its own.

**Who it is for:** one person doing marketing or research work, plus a small
shared workflow. Not company-wide content management.

---

## What it does

| Area | Behavior |
| --- | --- |
| **Research** | Topic plus timeframe. Collects material from the configured sources only. |
| **Grounded findings** | Findings must cite supplied source text. Citations are structural, not proof the statement is true. |
| **On-demand content** | A saved report can generate gaps, opportunities, ideas, and briefs with its own bounded operation. Failure leaves research intact. |
| **Ask this report** | A question against a saved report. Answers cite source identities the report already holds, not exact supporting fields. |
| **Run-over-run diff** | Compares findings with the nearest older report of the same topic. Exact match only. |
| **Discover** | Public-web gateway search. No YouTube, no AI, no scoring, no research handoff. |
| **Planner** | Save a report, then optionally develop ideas, briefs, and planned posts. |

Everything after saving is optional. Nothing publishes automatically.

Default discovery is global, using YouTube and public web search. Public-web
items are indexed titles and snippets, not fetched full pages, and YouTube
evidence is source metadata rather than transcripts or media analysis.

---

## How a report is built

```mermaid
flowchart LR
    Q[Topic + timeframe] --> C{Coverage check}
    C -->|no source can satisfy| X[Refused]
    C --> Y[YouTube]
    C --> W[Public web search]
    C --> F[Facebook public page]
    Y --> N[Normalize references]
    W --> N
    F --> N
    N --> E[Evidence pack]
    E --> A[Grounded interpretation]
    E --> X2[Labelled source excerpts]
    A --> V{Citation validation}
    V -->|passes| R[Report snapshot]
    V -->|fails| X2
    X2 --> R
    R --> DB[(PostgreSQL)]
```

1. **Query.** Topic and date window. The default is global discovery; explicit
   market context remains part of the report data. Nothing runs without a source
   that can satisfy the request.
2. **Collection.** Configured retrievers only: YouTube, public web search, and
   Facebook public Pages. No scraping behind a login.
3. **Normalization.** Results become references with stable ids, a source code,
   and fields the reader can inspect.
4. **Evidence.** A bounded evidence pack is derived from those references:
   facts, observations, patterns.
5. **Interpretation.** An OpenAI-compatible endpoint writes findings that must
   cite supplied evidence. Findings may not contain recommendation language.
6. **Validation.** Findings with no resolvable citation are refused. If
   synthesis is unavailable, malformed, or rejected, the report falls back to
   labelled excerpt text instead of inventing prose.
7. **Snapshot.** The finished report is stored as one immutable row. Reading it
   later needs no model call.
8. **Optional content, later.** A completed saved report can generate strategy,
   ideas, and briefs on demand. That operation has its own budget and appends a
   new completed snapshot; the original research snapshot is never edited.

---

## System architecture

```mermaid
flowchart TB
    B[Browser] --> NX[Next.js app]
    NX -->|same-origin /api proxy| API[FastAPI]
    API --> DB[(PostgreSQL)]
    API --> YT[YouTube Data API]
    API --> SR[Serper or SearXNG]
    API --> FB[Facebook Graph]
    API --> AI[OpenAI-compatible endpoint]
    NX -.bearer token.-> SA[Supabase Auth]
```

The browser never calls the backend directly. Next.js route handlers proxy every
request same-origin and forward the bearer token, so cookies and CORS stay
simple. Every read is gated by session verification plus an active membership.

---

## Persistence

| Table | Holds |
| --- | --- |
| `research_reports` | Append-only report snapshots: query, coverage, references, evidence, interpretation, strategy, ideation. On-demand content adds a derived completed snapshot rather than editing the source row. |
| `planner_posts` | Planned content: title, platform, caption, brief, planned date, status, assignee. |
| `planner_post_origin_sources` | Which saved report a planner post came from. |
| `planner_post_activity` | Append-only activity log. |
| `memberships` | Who may read reports. |

Reports are append-only. Nothing edits a saved snapshot. Expiry is a separate,
explicit operation.

---

## Grounding rules

- Every finding must cite supplied evidence. An uncited finding is rejected,
  not softened.
- Citation validation proves the evidence was supplied. It does not prove a
  statement is true or significant.
- Findings may not contain recommendation or action language. Plans and ideas
  live in the optional ideation layer.
- "Ask this report" answers cite source identities the saved report already
  holds. Citations are source-level; they do not identify exact supporting
  fields and do not prove semantic support.
- Cancelling Ask or on-demand content ends this browser's wait. The router or
  upstream provider may still finish the request, and cancellation does not
  guarantee a refund or that a derived report was not written.
- On-demand content is validated against the stored evidence and findings.
  Successful content is persisted as a new completed report snapshot. A failed
  operation does not replace the source report or previously valid content.
- Run-over-run diff is exact match after whitespace and case normalization.
  No fuzzy matching, no similarity score. Expired prior reports cannot be
  compared.

---

## Tech stack

### Backend

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.x-D71F00)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-database-4169E1?logo=postgresql&logoColor=white)
![Supabase](https://img.shields.io/badge/Supabase-auth-3ECF8E?logo=supabase&logoColor=white)

### Frontend

![Next.js](https://img.shields.io/badge/Next.js-16-000000?logo=nextdotjs&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white)

### Sources and AI

![OpenAI-compatible](https://img.shields.io/badge/AI-OpenAI--compatible-412991)
![YouTube](https://img.shields.io/badge/YouTube-Data%20API-FF0000?logo=youtube&logoColor=white)
![Serper](https://img.shields.io/badge/Serper-web%20search-4285F4)
![SearXNG](https://img.shields.io/badge/SearXNG-self--hosted-3050FF)

---

## Quick start

Python 3.12 and a project virtualenv are required, plus a PostgreSQL target.

Backend, in one terminal (no auto-reload by default):

```bash
.venv/bin/python -m uvicorn trendora.api.app:create_app --factory \
  --host 127.0.0.1 --port 8000
```

Frontend, in another terminal:

```bash
cd web
npm run dev -- --webpack --hostname 127.0.0.1 --port 3000
```

Open <http://127.0.0.1:3000>. Use the same `127.0.0.1` origin everywhere,
including the Supabase Site URL and redirect allowlist, or the session will not
resolve.

Neither command installs dependencies or migrates a database. Stop each server
with Ctrl+C in its own terminal; do not use `pkill` patterns or old PIDs.

Required variable names, the search container, and the optional AI router are
covered in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Alpha status and known limits

This is **v0.1.0-alpha**, not production-ready.

- Research synthesis is bounded by a shared AI-phase deadline and at most one
  malformed-output retry. A retry is skipped when the remaining time is shorter
  than the failed attempt. Truncated, malformed, or ungrounded output falls back
  to labelled source excerpts.
- The configured model route is probabilistic. Structural citations prove that
  evidence was supplied and resolves to a stored field; they do not prove
  factual support. The saved evaluation cases include wrong-reference and
  unsupported-qualifier examples for review.
- On-demand content requires a saved, non-expired report with findings. It runs
  separately from research and shares one budget across strategy and ideation.
  Cancellation stops the browser wait, not necessarily upstream work.
- Public-web results are indexed titles/snippets, not fetched pages. The search
  adapter does not enforce the requested timeframe and publication dates may be
  missing or unverified.
- Saved reports omit fresh `run_details`; capture the fresh response when
  diagnosing timing or retries.
- Four live examples do not establish general reliability.

## Tests

```bash
.venv/bin/python -m pytest tests/unit -q     # offline, guarded, no services
cd web && npm test                           # frontend unit tests
cd web && npm run lint && npx tsc --noEmit   # lint and typecheck
```

CI runs the backend unit suite, frontend unit tests, lint, typecheck, Next route
type generation, and the isolated browser regressions, which build the
production Webpack bundle. Database-backed integration tests need an explicitly
approved disposable target; see [docs/10_TESTING_EVALUATION.md](docs/10_TESTING_EVALUATION.md).

## Evaluating reports

The evaluator is offline and structural. It never calls a model or the network.

```bash
.venv/bin/python -m trendora.research.evaluation \
  --corpus tests/fixtures/research_quality/cases.json
```

Seven adversarial fixture cases, one finding each:

| Case | Citations | Resolved | Cited text present |
| --- | ---: | ---: | --- |
| exact_description_citation | 1 | 1 | yes |
| title_description_mismatch | 1 | 1 | yes |
| unsupported_specific_claim | 2 | 2 | no |
| publication_event_date_confusion | 1 | 1 | no |
| promotional_attribution | 1 | 1 | no |
| missing_evidence | 1 | 0 | no |
| extractive_fallback | 1 | 1 | yes |

Aggregate: 7 of 8 citations resolve, 3 of 7 findings cite nonblank source text.
Resolution proves the cited value exists in the report; it does not prove the
claim is true. "Cited text present" is only a presence check: at least one
resolved title or description citation carries nonblank text. It says nothing
about entailment, negation, numbers, paraphrase, or language. Human review is
separate and starts unreviewed.

### Quality and cost benchmark

The offline benchmark wraps the evaluator with 24 fictional cases (16
development, 8 held-out), two named configurations, recorded outputs, explicit
missing-data accounting, and a Markdown comparison. It never calls a provider or
the network.

```bash
.venv/bin/python -m trendora.research.quality_benchmark evaluate \
  --dataset tests/fixtures/research_quality/benchmark_v1.json \
  --run tests/fixtures/research_quality/runs/baseline.json \
  --split development \
  --output /tmp/trendora-benchmark-evaluate

.venv/bin/python -m trendora.research.quality_benchmark compare \
  --dataset tests/fixtures/research_quality/benchmark_v1.json \
  --baseline tests/fixtures/research_quality/runs/baseline.json \
  --candidate tests/fixtures/research_quality/runs/candidate.json \
  --split development \
  --output /tmp/trendora-benchmark-comparison
```

The commands write run JSON or `comparison.json`, plus `worksheet.json` and a
Markdown report. Recordings
carry prepared hashes for the dataset, source snapshot, compacted evidence,
prompt, and configuration; stale or missing identities are rejected. Rejected
outputs remain failed diagnostic rows, not fallback successes. The shipped
example runs cover a six-case development subset; they demonstrate the
machinery, not the full split, and do not show live model quality, latency, or
savings. Human judgments start unreviewed.
See [docs/RESEARCH_QUALITY.md](docs/RESEARCH_QUALITY.md) for the dataset, run
file, metrics, review workflow, and the requirements for any future authorized
live experiment.

## Major limitations

- **Freshness.** Publication dates are often unknown, and public-web search does
  not enforce the requested timeframe, so its results stay labelled unverified.
- **Coverage.** Indexed public results are not authenticated scraping and are not
  a complete feed of any platform.
- **Evidence honesty.** Citation validation proves the cited evidence was
  supplied. It does not prove a statement is true or significant.
- **Attention claims.** Current counts and sample prevalence describe the
  returned sample. They do not show growth, and no trend score is invented.
- **Known limits.** Reference selection is bounded at 24 references and is
  source-fair, so a limit below the source count cannot cover every source;
  whitespace-only text is never treated as evidence.
- **Live verification.** AI prose quality and full deployment have not been
  verified. Local operation is not public deployment, and local-first is not
  offline operation.

## Documentation

Start at [docs/README.md](docs/README.md), which states which documents are
authoritative and which are historical.

- [docs/14_PRODUCT_ARCHITECTURE_REBASELINE.md](docs/14_PRODUCT_ARCHITECTURE_REBASELINE.md)
  is the authoritative product scope, capability status, and known gaps.
- [docs/01_ARCHITECTURE.md](docs/01_ARCHITECTURE.md) covers services, data flow,
  persistence, and access boundaries.
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) covers local operation and deployment
  prerequisites.
- [docs/10_TESTING_EVALUATION.md](docs/10_TESTING_EVALUATION.md) covers tests.
- [docs/archive/](docs/archive/README.md) holds superseded milestone records.
  Do not drive new work from them.

## Repository layout

```text
src/trendora/          # backend package
  api/                 #   FastAPI app, auth, research, planner, ask and diff routes
  research/            #   query, coverage, retrievers, evidence, interpretation, saving
  connectors/          #   YouTube, web search, Facebook, plus legacy ingestion clients
  analytics/           #   legacy analytics read layer
  forecasting/         #   legacy forecasting
  models/              #   SQLAlchemy models
  planner.py           #   planner records and report import
  retention.py         #   explicit, dry-run-first expiry
web/                   # Next.js research workspace, report reader, discover, planner UI
alembic/               # migrations
tests/unit/            # offline, guarded
tests/integration/     # requires an approved disposable database
docs/                  # current guides and the historical archive
deploy/                # search container configuration
```

## License

MIT. See [LICENSE](LICENSE).
