# 30 — Facebook Frontend Research Mode (M25E)

## Status

**M25E (this document + implementation):** the research workspace frontend can submit single-source Facebook Page research requests through the existing M23A report pipeline and M25D API wiring. Fully mocked; no live Meta verification.

## 1. Single-source selector

The static source roadmap in `ResearchForm` is replaced by an accessible radio group (`fieldset`/`legend`):

- **YouTube** — selectable, selected by default.
- **Facebook** — selectable; labeled "Requires Trendora server configuration".
- **Instagram, TikTok** — disabled, labeled "Planned". No functionality claimed.

Radios enforce exactly one source; mixed YouTube/Facebook requests are impossible from the UI (the backend also rejects them). Keyboard navigation, visible focus, selected/disabled states, and 42px mobile touch targets are preserved.

## 2. Public Facebook Page ID input

Selecting Facebook reveals a required `Facebook Page ID` text input (placeholder `123456789`). Only required/nonblank is validated in the browser; the backend remains authoritative for Page-ID format and safety. No Page discovery, URL parsing, username lookup, or OAuth exists in the frontend.

## 3. No end-user Facebook login

The Trendora user never signs into Facebook. Authentication is server-side only: Trendora's backend must have approved Meta access configured (`META_ACCESS_TOKEN`, `META_GRAPH_API_VERSION`). An unconfigured server surfaces the neutral 503 `research_source_not_configured` error.

## 4. Topic/market limitation

For Facebook, topic and market organize the report but do not filter which Page posts are collected. The form states this explicitly under the Page-ID input.

## 5. Request/display behavior

- YouTube submissions send `sources: ["youtube"]` and omit `facebook_page_id`.
- Facebook submissions send `sources: ["facebook"]` plus the trimmed Page ID.
- Edit-and-rerun restores the selected source, Page ID, topic, market, dates, and depth.
- Turn summaries show `Facebook · Page <id>`; report provenance uses source labels.
- Reference cards: Facebook shows Reactions/Comments/Shares with fallback title "Facebook post"; YouTube keeps Views/Likes/Comments and "Untitled video". Missing metrics stay `—`, zeros stay `0`. Reactions are never labeled as likes.

## 6. Exclusions and risk

No backend changes, authentication, Meta credentials in the browser, multiple Pages, mixed-source execution, Instagram/TikTok behavior, new dependencies, or test frameworks. Instagram/TikTok remain visibly disabled. Live Graph API compatibility and Meta approval/access remain unverified; Facebook mode fails closed with 503 until the server is configured.