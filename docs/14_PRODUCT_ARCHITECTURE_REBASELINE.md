# 14 - Trendora product requirements (authoritative PRD)

## Status and authority

This is the single authoritative product requirements document. It replaces the
older milestone-roadmap framing of this path and all superseded product plans.
Where anything else disagrees about intended scope, this document wins; where it
disagrees with the code about behaviour, the code wins.

- [01_ARCHITECTURE.md](01_ARCHITECTURE.md) describes how the product is built.
- [DEPLOYMENT.md](DEPLOYMENT.md) covers running it and deployment prerequisites.
- [10_TESTING_EVALUATION.md](10_TESTING_EVALUATION.md) covers tests and the limits
  of the evidence they provide.
- [archive/](archive/README.md) holds historical milestone records. Nothing there
  is a current requirement.
- Forecasting and ingestion capabilities that still exist in the code are
  secondary. Their requirements live in the archive and govern only themselves.

Items marked **PROPOSED** are recommendations from this review. They are not
approved commitments.

## 1. Who it is for and what problem it solves

Trendora is built for one owner plus a small shared workflow: a person doing
personal marketing work who needs to understand a topic before writing about it.
It is not a company-wide content management platform, and it has no multi-team
tenancy or billing.

The problem is assembling a defensible picture of a topic. Search results and
platform feeds are fragmented, undated, and easy to over-read. Trendora collects
material for one topic and timeframe, shows what the material actually supports,
and keeps the limits visible: what was searched, what was found, when it was
published, what is unknown, and which statements are source text rather than
interpretation.

A report must be useful on its own. Reading, saving, and reopening research
never requires generating content.

## 2. Purpose and core workflow

**Core journey:** topic and timeframe → collect evidence → review source-backed
findings → save the research → optionally develop content → plan a post.

Each step is optional after saving. Content ideas, briefs, and the planner are
downstream conveniences, not prerequisites and not the product's purpose.

The main questions a report should help answer:

- What do the collected sources describe about this topic in this window?
- Which sources support each statement, and how fresh are they?
- Where is the evidence thin, undated, or outside the requested window?

## 3. Requirements and acceptance criteria

### 3.1 Research

| Area | Requirement | Acceptance |
| --- | --- | --- |
| Topic and timeframe | Accept a chosen topic and an explicit timeframe, including a short recent window. The default UI flow is **global** (no country restriction) across the sources it selects. | The report shows the normalized topic, dates actually used, and requested sources. Typing a phrase such as "this week" does not by itself select dates. |
| Sources | YouTube API discovery and public-web indexing are **distinct mechanisms** with different coverage. Facebook public Pages are a separate, opt-in mechanism. | The report names each source, whether it was searched, and why a source returned nothing or was skipped. |
| Evidence | Each reference keeps its identity, URL, title, description, publication date (nullable), and collection timestamp. | References render with their source link; missing dates stay unknown. |
| Findings | Findings must rest on source text (title or description) supplied to the model. | A finding whose citations are only patterns, observations, or engagement counts is not accepted as a research finding. |
| Presentation | Four things stay distinguishable: AI findings, sample observations, limited-evidence interpretations, and exact source excerpts. | The reader labels each group and never presents a fallback excerpt as synthesis. |
| Freshness | Publication date and collection date are separate facts. Unknown dates stay unknown. | The report does not infer a publication date from a URL, snippet, or collection time. Public-web results carry the unverified-timeframe caveat. |
| Attention and trends | Current counts and sample prevalence describe the returned sample only. | No growing-attention claim is made without comparable observations across time. No trend score is invented. |
| Coverage honesty | Requested sources, capability coverage, sources actually searched, collection dates, reference counts, and gap reasons are visible. | "Complete" capability coverage is never presented as complete coverage of the internet. |

### 3.2 Saving, history, and access

| Area | Requirement | Acceptance |
| --- | --- | --- |
| Snapshots | A saved report is an immutable six-field snapshot with a canonical fingerprint. | Reopening shows the stored findings, citations, coverage, and references. Snapshot content does not change after save. |
| Recovery | Saving is idempotent per request key, including after a lost response. | The same key returns the original outcome without re-running collection or AI. A conflicting payload for the same key is refused. |
| Expiry | Source-bearing report bodies expire on a documented retention rule; the identity and replay fingerprint survive. | An expired report reads as a terminal tombstone, cannot be used for new imports, and an old import replay still resolves its original identity. |
| Visibility | Active members share one workspace. Reports are readable by any active member within the rolling 30-day history window; administrators can read all retained history. | The same rule applies to listing, detail, and report-to-planner import. Reads are scoped by membership and history, not by who created the report. |
| Shared planner | Planner records are shared workspace records, visible and editable by active members. The assignment list returns active members with their emails so an authorized member can assign work. | Member emails are shown only to authenticated, active members. There is no per-owner private planner space. |
| Isolation | Account and membership checks gate every report and planner read. | A previous account's client state never leaks after a switch: stale recovery snapshots and unsaved drafts are discarded, and delayed responses from the previous account are ignored. This is guard behaviour, not a privacy boundary between members. |
| Retention | Visibility is not deletion. Hiding or ageing out a report does not delete stored source material. | Deletion is a separate, explicit, dry-run-first operation, and it is not scheduled today. |

### 3.3 Planner

Verified from `src/trendora/models/planner.py` and `src/trendora/planner.py`.

| Area | Requirement | Acceptance |
| --- | --- | --- |
| Records | A planner post holds title, platform, caption, hook, creative brief, asset links, notes, an optional **planned date**, a status, and an optional assignee. | The fields above exist and are editable. |
| Status | The only statuses are `idea` and `working`. | No calendar, approval, scheduled, or published state is claimed. |
| Import | Importing from a report requires an explicit action and an accessible report. | The server resolves the selected item, keeps its origin link, and the post stays editable and independent of the snapshot. |
| AI-independent operation | Planner work must not depend on AI availability. | Creating, editing, archiving, restoring, and importing work with no AI provider configured. |
| Requested, not implemented | Calendar or board views, an optional review/approval step, a published URL, and an actual publication date were requested for the planner. | None exists today. `planned_date` is a planned date only. These remain agreed requests, not cancelled scope, and not enterprise features. No implementation is authorized here. |
| Publishing | A planned date does not trigger publication. | Nothing in the product publishes content anywhere. |
| Concurrency | Edits are version-checked; creation and import are idempotent per request key. | A stale version is refused rather than silently overwritten; a replayed request returns the original result. |

## 4. Capability status

| Capability | Status | Notes |
| --- | --- | --- |
| Topic + timeframe research, global default | Implemented | Simplified request defaults to global, last 30 days, YouTube + public web. |
| YouTube discovery and enrichment | Implemented | YouTube Data API v3; publication filters where the source supports them. |
| Public-web indexing (Serper) | Implemented | Paid provider; used only when selected. |
| Public-social discovery (SearXNG) | Implemented, bounded | One general query plus bounded platform queries; merged and deduplicated. Indexed results only. |
| Facebook public Page research | Implemented, opt-in | Requires configured Meta access. No keyword search; it is not a general Facebook source. |
| Grounded AI findings | Implemented, live quality unverified | Text-supported findings required; structural grounding is not factual verification. |
| Excerpt fallback | Implemented | Used when synthesis is unavailable, malformed, empty, or rejected. Clearly labeled. |
| Sample observations vs limited evidence | Implemented | Separate reader groups; a citation that cannot be validated against supplied evidence is not shown as a finding. |
| Save, recovery, history, expiry | Implemented; retention command not scheduled | Snapshot and recovery behaviour are tested offline. Expiry has been applied against a real disposable PostgreSQL instance with synthetic data; it has not run against production data and has no schedule. |
| Optional content tools | Implemented, opt-in | Gaps, opportunities, ideas, and briefs; failure preserves research. |
| Planner with report import | Implemented | `idea`/`working`, archive/restore, origin tracking. |
| Auth and membership | Implemented | Supabase JWT verification plus active-membership checks. |
| AI request deadline | Implemented | One shared monotonic budget bounds in-flight I/O; see section 5. |
| Token or cost visibility | Planned | No reporting of AI input/output size or spend per request. |
| Input compaction | Implemented | Bounded, source-fair selection (24 references) with blank-safe truncation. Stored material is untouched. |
| HN, Stack Exchange, GitHub research | Declared but not wired | Capability declarations exist; no retrievers in the topic-research flow, so they report as skipped. |
| Ingestion, analytics, forecasting | Secondary | Still in the code. Not part of the research journey and not required for it. |
| Enterprise tenancy, billing | Out of scope | Not planned. Multi-team administration is not a goal. |
| Planner calendar/board, review/approval step, published URL, actual publication date | Requested, unimplemented | Agreed requests for the small shared workflow. They are not enterprise features and are not cancelled. No work is authorized in this pass. |
| Automatic publishing | Out of scope | Not planned; nothing publishes. |
| General web crawler, full-page extraction | Out of scope | Public-web work is indexed search results only. |
| Authenticated social scraping, complete feeds | Out of scope | No login-based scraping, and no complete-platform coverage is claimed. |
| Trend or growth scores | Out of scope | Requires time-series evidence the product does not collect. |

## 5. Reliability, privacy, and evidence requirements

**Deadline and retries.** One monotonic AI-phase budget is shared by the
interpretation request, its single malformed-output retry, and the optional
content stages. It bounds in-flight HTTP I/O, and expiry cancels the request.
It is **not** a whole-report completion guarantee: collection, persistence, and
rendering sit outside it, and the frontend proxy has its own separate deadline.
Parsing, validation, and cleanup are not interrupted.

**Failure behaviour.** Synthesis that is unavailable, malformed, empty, or
rejected by grounding falls back to exact source excerpts labelled with their
extractive provenance. Optional content failure leaves research intact and
savable. Fallback never invents text.

**Evidence honesty.** Citation validation proves the cited evidence exists in
the supplied set. It does not prove the statement is entailed, true, or
significant. Text support is structural, not semantic. Source text is treated as
untrusted data, never as instructions to the model.

**Freshness honesty.** The requested window, publication date, and collection
timestamp are separate. A recent publication does not prove an event happened
then. Public-web collection does not enforce the requested window, so its
results stay marked as unverified for timeframe.

**Privacy and secrets.** Provider credentials and signing keys stay server-side.
The browser never receives provider keys, recovery signing secrets, or database
credentials.

**Shared visibility.** This is a small shared workspace, not a private
per-owner store. Any active member can read reports inside the history window,
and planner records are visible and editable by members. Assignment lists show
member emails to authenticated members. Do not describe reports or drafts as
owner-private.

**Stored data.** Compaction applies only to the model request. Stored reports,
snapshots, fingerprints, and references keep the original, full source material.

## 6. Known gaps and defects

Verified against the current source, not assumed fixed.

1. **Findings may add unsupported specifics.** Mocked tests prove the citation
   contract, not prose quality. Whether live findings introduce unsupported
   detail or drop a source's qualifications is unverified and needs human review
   of a live run.
2. **Public-web freshness is unenforced.** The window is not applied to indexed
   results, and publication dates are usually unavailable, so a public-web result
   cannot substantiate an in-period digest on its own.
3. **No token or cost visibility.** Request size is controlled but never
   reported, so cost cannot be reviewed per report.
4. **Retention is unexercised in production, but it has run once against a real
   database.** The expiry command exists and is covered by offline synthetic
   tests. It was also applied against a disposable PostgreSQL instance with
   synthetic data, as recorded in the dated evidence in
   [DEPLOYMENT.md](DEPLOYMENT.md) section F; that run's temporary artifacts are
   no longer available, which does not undo the reported result. It has not run
   against production data, has no schedule, and visibility is not deletion.
5. **Facebook coverage is narrow.** Public Page collection only, opt-in, no
   keyword search, and mocked in tests.

Two earlier compaction defects are fixed and covered by regressions:

- **Source starvation is fixed.** Selection is now source-fair: references are
  taken round-robin across sources in first-seen order, and inside a source
  round-robin across domains in first-seen order, skipping exhausted groups and
  redistributing their slots. The
  guarantee is bounded by the cap, so a limit below the source count fills in
  first-seen source order and does not claim full coverage.
- **Whitespace-only text can no longer become evidence.** Over-limit text is
  trimmed before clipping, whitespace-only text stays blank, and the truncation
  marker appears only when real text is kept and content was omitted. Blank
  evidence is rejected by text support and falls back to labelled excerpts.

## 7. Release prerequisites

- Owner review of a live research run, including human assessment of whether
  findings are supported by their cited text.
- An approved database target for migrations, taken with a backup plan.
- Provider and retention policy review before any public deployment.
- An explicit retention execution decision: target, cadence, and mechanism.
- Deployment prerequisites per [DEPLOYMENT.md](DEPLOYMENT.md). Local operation
  is not public deployment, and local-first is not offline operation.

## 8. Prioritized next work

Small and ordered. Everything here is **PROPOSED** unless already agreed.

1. **Research quality, live.** One owner-approved live acceptance run with
   human review of factual support, qualified claims, duplicates, and
   unsupported recency.
2. **Freshness quality.** Keep public-web timeframes labelled as unverified, and
   state the limitation where a reader would otherwise assume in-window results.
3. **Cost visibility.** Report the compacted input size and, where the provider
   returns them, token counts per request, without exposing prompts.
4. **Manual publication tracking.** Let a planner post record where it was
   published, as a manual field. No automatic publishing.

Out of scope for this list: tenancy, billing, crawlers, trend scoring, and any
automatic publishing.
