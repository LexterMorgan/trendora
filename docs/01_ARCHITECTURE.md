# 01 - Architecture

Current architecture. For scope and requirements see
[14_PRODUCT_ARCHITECTURE_REBASELINE.md](14_PRODUCT_ARCHITECTURE_REBASELINE.md);
for running it see [DEPLOYMENT.md](DEPLOYMENT.md). Superseded milestone
architecture is in [archive/](archive/README.md).

## Services and boundaries

| Piece | Location | Responsibility |
| --- | --- | --- |
| Web app | `web/` (Next.js) | Research form, report reader, past-reports history, planner UI. Holds no provider secrets and never touches the database. |
| Same-origin API routes | `web/app/api/` | Thin proxies that forward browser requests to the backend with the session token. They enforce request body limits and deadlines; they hold no business logic beyond forwarding. |
| Backend | `src/trendora/api/` (FastAPI) | Auth verification, membership checks, request validation, research orchestration, report persistence, planner operations. The only component with database or provider access. |
| Research core | `src/trendora/research/` | Query validation, capability coverage, retrievers, evidence, interpretation, reporting, snapshot recovery. |
| Planner | `src/trendora/planner.py`, `src/trendora/models/planner.py` | Editable content records and their report origin. |
| Retention | `src/trendora/retention.py` | Explicit, dry-run-first expiry of source-bearing report bodies. |
| Database | `src/trendora/models/`, `alembic/` | PostgreSQL via SQLAlchemy; schema via Alembic. |

External services: the YouTube Data API, a public-web search backend (Serper, or
a self-hosted SearXNG instance), an optional Meta Graph API access path for
public Facebook Pages, and an OpenAI-compatible AI endpoint. Each is
operator-configured; none is required for the app to start.

```text
browser
  -> Next.js pages and components (web/)
  -> same-origin Next API routes (proxy: session token, body caps, deadlines)
  -> FastAPI (src/trendora/api)
       -> auth: verify session JWT, then active-membership check
       -> research: capabilities -> retrievers -> evidence -> AI or fallback
       -> persistence: immutable snapshots, planner records
  -> PostgreSQL
```

## Research data flow

1. **Request adaptation.** `research/adapter.py` accepts either the full contract
   or a simplified topic-first request and fills defaults (global markets, last
   30 days, YouTube plus public web) before validation. Explicit regional
   requests keep their behaviour.
2. **Query validation.** `ResearchQuery` normalizes and validates topic, markets,
   dates, sources, and limits. Invalid input is rejected before any collection.
3. **Coverage resolution.** `research/service.py` resolves each requested source
   against static capability declarations and records completeness. Availability
   is a capability claim, not proof that a source ran.
4. **Collection.** `research/application.py` builds one retrieval target per
   source (one per selected market for YouTube, one each for Facebook and public
   web) and executes them in request order, splitting the result limit
   deterministically. A configured-but-failing source is skipped so surviving
   sources still produce an honestly partial report; if every target fails, the
   run fails closed. `executed_sources` records what was actually attempted.
5. **Normalization and merge.** Each retriever returns normalized references,
   merged in target order and deduplicated by source identity plus URL identity.
   Missing metrics stay `None`; they are never replaced with zero. `source_rank`
   is source order, not a Trendora ranking.
6. **Evidence.** `research/evidence.py` derives immutable facts and deterministic
   observations per reference. `research/patterns.py` aggregates boolean
   observations into sample prevalences. These describe the returned sample.
7. **Interpretation.** `research/reporting.py` builds a compacted evidence input,
   calls the grounded provider behind a shared monotonic deadline, and validates
   citations against exactly that input. Findings must cite supplied source text.
   On unavailability, malformed output, emptiness, or rejection, it falls back to
   exact labelled source excerpts with `source_evidence/extractive-v1`
   provenance. `research/ai_input.py` owns the compaction.
8. **Optional content.** With explicit opt-in, grounded strategy and ideation run
   against the full evidence pack. Their failure yields `content_unavailable` and
   leaves research intact.
9. **Response and saving.** The API serializes the report. Saving stores the
   six-field snapshot plus a canonical fingerprint; see "Invariants" below.
10. **History.** List and detail reads apply the same membership and history
    rules as import. Expired reports read as a terminal tombstone.

## Source mechanisms

| Source code | Mechanism | Notes |
| --- | --- | --- |
| `youtube` | YouTube Data API v3 search plus enrichment | Supports a requested region and publication filters. |
| `public_web` | Serper API or self-hosted SearXNG | Indexed results only. With SearXNG the backend runs one bounded general query plus bounded platform queries, merges them by URL identity, and can report partial execution through coverage. |
| `facebook` | Meta Graph public Page posts | Opt-in, configured separately, no keyword search. |
| `hacker_news`, `stack_exchange`, `github` | Capability declarations only | No retriever in the topic-research flow, so they resolve as unavailable or skipped. |

## Persistence

Alembic revisions `0001` through `0008` cover the initial schema, research
reports, memberships and history, planner posts, report save and recovery,
planner research origin, origin collection-time nullability, and report source
expiry. The migrations are the source of truth for schema; historical schema
notes are archived.

The three persistence concerns are deliberately separate:

- **Immutable research snapshots.** Six fields plus schema version, with a
  canonical fingerprint. Nothing rewrites them.
- **Editable planner records.** Title, platform, caption, hook, creative brief,
  asset links, notes, planned date, status (`idea` or `working`), assignee,
  archive state, and version. Independent of snapshot content.
- **Retention.** An explicit command, dry-run first, replaces source-bearing
  bodies with a tombstone while preserving identity and fingerprints. It is not
  scheduled.

## Access boundaries

- The browser authenticates through Supabase Auth; the backend verifies the
  session JWT and then requires an active membership row.
- Ordinary members see the rolling 30-day report history; administrators can
  read all retained history. The rule is applied to list, detail, and import.
- Planner membership gates planner records independently of report history.
- Provider keys, recovery signing secrets, and database credentials exist only
  in backend configuration.

## Invariants

- A saved snapshot is immutable. Its canonical hash is computed over the six
  snapshot fields only; recovery metadata lives outside it.
- Saving and importing are idempotent per request key. A replayed key returns the
  original outcome; a different payload for the same key is refused.
- Planner edits are version-checked. A stale version is refused, never silently
  merged.
- Recovery receipts are server-signed and bind the actor, key, hash, and original
  expiry. Recovery never restarts retention.
- Expiry changes a report to a tombstone; new imports cannot use it, and an old
  replay still resolves its original identity.
- AI output is untrusted: strict parsing, structural grounding, and text support
  are checked before display. This proves the cited evidence exists, not that a
  statement is true.
- Compaction applies to the model request only. Stored reports keep full material.
- The backend never hands the database to the model. Providers receive evidence
  derived from collected references, not SQL access.
