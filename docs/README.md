# Trendora documentation index

Start here. This page says which documents are authoritative, which are
supporting references, and which are historical.

## Reading order

For a human or a coding agent new to the repository:

1. [../README.md](../README.md) — what Trendora is, what works, how to run it.
2. [14_PRODUCT_ARCHITECTURE_REBASELINE.md](14_PRODUCT_ARCHITECTURE_REBASELINE.md)
   — authoritative product scope, capability status, gaps.
3. [01_ARCHITECTURE.md](01_ARCHITECTURE.md) — current service boundaries, data
   flow, persistence, and access boundaries.
4. [DEPLOYMENT.md](DEPLOYMENT.md) — how to run it locally, and what a real
   deployment still requires.
5. [10_TESTING_EVALUATION.md](10_TESTING_EVALUATION.md) — how to test it, and
   what the tests do and do not establish.

Read the supporting references below only when the task touches that mechanism.

## Authoritative

These describe the product as it is intended and built today. If they disagree
with each other, product scope comes from `14`, behaviour comes from the code,
and the code wins over both.

| Document | Covers |
| --- | --- |
| [../README.md](../README.md) | Project overview, capabilities, quick start, limitations |
| [14_PRODUCT_ARCHITECTURE_REBASELINE.md](14_PRODUCT_ARCHITECTURE_REBASELINE.md) | Product purpose, users, requirements, capability status, known gaps, next work |
| [01_ARCHITECTURE.md](01_ARCHITECTURE.md) | Services, data flow, persistence, access boundaries, invariants |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Local operation and future deployment prerequisites |
| [10_TESTING_EVALUATION.md](10_TESTING_EVALUATION.md) | Test commands, isolation, evidence limits |

## Supporting references

Technical detail for mechanisms that exist today, with **mixed status**. They use
milestone numbering from when they were written, and their "Status" lines record
that moment rather than current claims. Some are still in force; others are
partially superseded, as flagged below and in the document's own header note.
Where one disagrees with the code, the code wins; where it disagrees with the
PRD, the PRD wins.

| Document | Covers |
| --- | --- |
| [15_RESEARCH_CORE.md](15_RESEARCH_CORE.md) | Query validation, capabilities, coverage, run lifecycle |
| [16_YOUTUBE_RESEARCH_RETRIEVAL.md](16_YOUTUBE_RESEARCH_RETRIEVAL.md) | YouTube discovery and enrichment |
| [17_RESEARCH_API.md](17_RESEARCH_API.md) | `POST /api/v1/research` contract |
| [18_RESEARCH_WORKSPACE.md](18_RESEARCH_WORKSPACE.md) | The Next.js research workspace |
| [19_EVIDENCE_CONTENT_OBSERVATIONS.md](19_EVIDENCE_CONTENT_OBSERVATIONS.md) | Evidence facts and deterministic observations |
| [20_DETERMINISTIC_PATTERN_AGGREGATION.md](20_DETERMINISTIC_PATTERN_AGGREGATION.md) | Pattern aggregation over observations |
| [21_GROUNDED_AI_INTERPRETATION_CONTRACT.md](21_GROUNDED_AI_INTERPRETATION_CONTRACT.md) | Typed citations and grounding contract |
| [22_AI_PROVIDER_GROUNDED_EXECUTION.md](22_AI_PROVIDER_GROUNDED_EXECUTION.md) | Provider adapter and execution |
| [23_CONTENT_GAPS_OPPORTUNITIES.md](23_CONTENT_GAPS_OPPORTUNITIES.md) | Optional content gaps and opportunities |
| [24_CONTENT_IDEAS_BRIEFS.md](24_CONTENT_IDEAS_BRIEFS.md) | Optional content ideas and briefs |
| [25_RESEARCH_REPORT_PIPELINE_API.md](25_RESEARCH_REPORT_PIPELINE_API.md) | Report pipeline and report API |
| [26_FACEBOOK_PUBLIC_PAGE_CLIENT.md](26_FACEBOOK_PUBLIC_PAGE_CLIENT.md) | Facebook public Page client |
| [27_FACEBOOK_POST_NORMALIZATION.md](27_FACEBOOK_POST_NORMALIZATION.md) | Facebook post normalization |
| [28_FACEBOOK_RESEARCH_EXECUTION.md](28_FACEBOOK_RESEARCH_EXECUTION.md) | Facebook research execution |
| [29_FACEBOOK_API_WIRING.md](29_FACEBOOK_API_WIRING.md) | Facebook API wiring |
| [30_FACEBOOK_FRONTEND.md](30_FACEBOOK_FRONTEND.md) | Facebook frontend mode. **Partially superseded:** the source selector no longer exists. |
| [31_COMBINED_MULTI_SOURCE_EXECUTION.md](31_COMBINED_MULTI_SOURCE_EXECUTION.md) | Combined multi-source execution |
| [32_MULTI_MARKET_RESEARCH.md](32_MULTI_MARKET_RESEARCH.md) | Multi-market research. **Backend contract in force; frontend market controls and later validation details are superseded.** |
| [33_READER_EXPORT_HISTORY.md](33_READER_EXPORT_HISTORY.md) | Reader evidence display, source filters, Markdown/print export, history filters, run diagnostics |
| [RESEARCH_QUALITY.md](RESEARCH_QUALITY.md) | Offline research-quality evaluation CLI and human-review worksheet |

Component guides: [web/README.md](../web/README.md) (frontend) and
[deploy/searxng/README.md](../deploy/searxng/README.md) (public-web search
container).

## Historical

Do not drive new implementation from these.

| Location | What it is |
| --- | --- |
| [archive/](archive/README.md) | Superseded milestone records from the ingestion, analytics, and forecasting era |
| [03_DATA_SOURCES.md](03_DATA_SOURCES.md) | Pointer to the archived source-research document |
| [RESEARCH_PRODUCT_COMPARISON.md](RESEARCH_PRODUCT_COMPARISON.md) | An external-product comparison note dated 2026-10-11; not a requirement |
| `superpowers/` | Agent planning notes kept on disk for traceability; not reviewed here, not authoritative |

`docs/00_PROJECT_OVERVIEW.md` was deleted before this index was written. It is
not restored.
