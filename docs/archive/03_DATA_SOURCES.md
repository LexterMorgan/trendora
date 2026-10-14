# 03 — Data sources

Status: Phase 0 research. **No connectors implemented.**

Research date: 2026-08-18.

Official documentation was preferred. Where an official page could not be retrieved (HTTP 403, Cloudflare, timeout), the source is classified **POSSIBLE / NEEDS FURTHER VERIFICATION** or **NOT SUITABLE**, not guessed into MVP.

## Classification

| Label | Meaning |
| --- | --- |
| **APPROVED FOR MVP** | Official, $0-feasible, legally usable for a first pipeline, with documented limits we can design around |
| **POSSIBLE / NEEDS FURTHER VERIFICATION** | Official path may exist, but access, commercial terms, quotas, or pages could not be fully verified |
| **NOT SUITABLE** | No legitimate $0 market-intelligence path for Trendora V1 |

MCPs are **not** data sources. Production ingestion will use Python HTTP/API clients.

## V1 recommendation (smallest realistic set)

1. YouTube Data API v3 (public reads + curated watchlist + regional `mostPopular`)
2. YouTube Atom topic URL / WebSub (new-video notices; no stats)
3. Hacker News official API (global tech attention)
4. Stack Exchange API (programming / data-science Q&A)
5. GitHub REST API (public tech-education repo activity)
6. Wikimedia Action API (context, not social KPIs)
7. GDELT 2.0 HTTP file drops (news/event context; not BigQuery-dependent)

Everything else is deferred.

---

## YouTube Data API v3

**Classification: APPROVED FOR MVP**

### Official API availability

Yes. YouTube Data API v3.

- Overview: https://developers.google.com/youtube/v3/getting-started
- Videos.list: https://developers.google.com/youtube/v3/docs/videos/list
- Video resource (statistics): https://developers.google.com/youtube/v3/docs/videos#resource
- Quota calculator: https://developers.google.com/youtube/v3/determine_quota_cost
- Terms: https://developers.google.com/youtube/terms/api-services-terms-of-service
- Developer policies: https://developers.google.com/youtube/terms/developer-policies
- Derived metrics / storage amendment: https://developers.google.com/youtube/terms/derived-metrics-policy
- Push notifications (WebSub): https://developers.google.com/youtube/v3/guides/push_notifications

### Authentication

- Google Cloud project + YouTube Data API enabled.
- **API key** for public `list` methods.
- **OAuth 2.0** for user-authorized methods and Authorized Data (channel owner uploads, private stats such as dislikes).

Trendora V1 should use an API key for public data only, unless later we onboard owned channels.

### Free access

No per-call monetary fee is documented. Access is quota-gated, not credit-card-gated. Extra quota requires a compliance audit / quota extension form; approval is not guaranteed.

### Free quota / limits (official, as of the quota calculator page)

Projects that enable the API have:

- **10,000 units per day** combined for endpoints other than the two buckets below
- **100 `search.list` calls per day** (own quota bucket; 1 unit per call)
- **100 `videos.insert` calls per day** (own bucket; not needed for read-only intelligence)
- Daily reset at midnight Pacific Time
- Invalid requests still cost quota
- Each extra results page costs another call

Selected read costs from the official calculator:

| Method | Cost |
| --- | --- |
| `videos.list` | 1 |
| `channels.list` | 1 |
| `playlistItems.list` | 1 |
| `commentThreads.list` | 1 |
| `comments.list` | 1 |
| `videoCategories.list` | 1 |
| `i18nRegions.list` | 1 |
| `search.list` | 1, **capped at 100 calls/day** |

Do not treat blog “100 searches × 100 units” figures as current; official June 2026 granular quotas put search in its own 100-call bucket.

### Available metrics (public `videos.list` `part=statistics`)

Official fields:

- `viewCount`
- `likeCount`
- `commentCount`
- `dislikeCount` — **private since 2021-12-13**; only the video owner with OAuth sees it
- `favoriteCount` — deprecated, always `0`

Also from `snippet` / `contentDetails` (metadata, not engagement history): title, description, tags, categoryId, publishedAt, channelId, duration, etc.

`channels.list` can return public `statistics` such as subscriberCount / viewCount / videoCount (hidden subscriber counts may be omitted).

YouTube Analytics API / Reporting API exist but are **channel-owner** tools, not third-party market firehoses. They are out of V1 unless Trendora analyzes channels we authenticate.

### Historical data

**Not provided.** `videos.list` returns the current cumulative counts. There is no official “views per day for the last 90 days” for arbitrary public videos.

Any Trendora time series would be **our own snapshots**. That immediately collides with storage policy (below).

### Real-time data

Not a streaming engagement API. Near-real-time **upload / title / description** notices are available via WebSub (below). Engagement still requires a later `videos.list`.

### Public data

Public videos and channels can be read with an API key. Private/unlisted content and owner-only parts require OAuth.

### Rate limits

Quota units (above) are the documented limiter. There is no separate published QPS table on the quota calculator page. Clients should still backoff on `403` / quota errors.

### Restrictions / commercial use

- Comply with API TOS + Developer Policies.
- Privacy policy required if the client collects user information.
- **Scraping YouTube or Google applications is prohibited.**
- Must not store YouTube audiovisual content.
- Must not replace API metrics with independently invented stand-ins for the same metric (e.g. fake like counts).
- Derived scores (influence scores, sentiment, leaderboards) are generally prohibited **unless** the analytics amendment is accepted (policy III.E.4.h and section L, effective for the extra path from 2026-06-01).
- Attribution / branding rules apply if YouTube brand features are shown.

### Storage policy (critical for Trendora)

Default Developer Policies (III.E.4):

- **Non-Authorized Data** (API key, no channel-owner OAuth): store only as long as needed, **not longer than 30 calendar days**, then **delete or refresh**.
- Explicit example: do **not** store a channel subscriber count more than 30 days without authorization from the channel owner.
- UI must show the freshest API data; historical values may be shown **only if presented accurately in a time context**.
- From 2026-06-01, longer statistical storage and additional derived metrics apply **only** to audited developers who applied via the quota extension form and accepted the analytics use-case amendment.

If that amendment is accepted, official derived-metrics policy allows storing statistical endpoint metrics (views, likes, subscriber counts, comment counts) and derived metrics for **up to 36 calendar months**. Titles, creator names, descriptions, and comment text remain on the **30-day refresh/delete** rule.

**V1 implication:** snapshot public stats, refresh within 30 days, do not promise multi-year YouTube history until Google approves the analytics storage path.

### Python integration

Official option: Google APIs client (`google-api-python-client`) plus `google-auth`. Raw HTTPS to `https://www.googleapis.com/youtube/v3/...` is also valid. **Not installed in Phase 0.**

### Suitable for Trendora MVP?

Yes, as the **primary social source**, with a design that:

1. Maintains a **curated watchlist** of SEA education/tech channels (use `channels.list` + uploads playlist `playlistItems.list` + batched `videos.list`; all cost 1/unit).
2. Takes daily **regional `videos.list?chart=mostPopular&regionCode=`** snapshots for `ID`, `TH`, `MY`, `SG`, `VN`, `PH`. Confirm category IDs per region with `videoCategories.list` (do not hard-code IDs without a live list).
3. Treats `search.list` as a rare, human-supervised discovery tool (100 calls/day), not a crawler.
4. Enforces 30-day refresh/delete unless/until the derived-metrics amendment is approved.

### Fallback

YouTube Atom topic URL / WebSub for **new video IDs only**. Then hydrate stats with `videos.list`. There is **no legitimate scrape fallback**.

---

## YouTube Atom feed / WebSub

**Classification: APPROVED FOR MVP** (discovery only)

### Official availability

Yes. Documented as the WebSub topic URL:

`https://www.youtube.com/feeds/videos.xml?channel_id=CHANNEL_ID`

Guide: https://developers.google.com/youtube/v3/guides/push_notifications

Hub: `https://pubsubhubbub.appspot.com`

### Authentication

None for the public Atom topic. A callback URL is required for push subscribe.

### Free access / quota

No YouTube Data API quota is consumed by WebSub notifications. The feed itself is not a substitute for the Data API.

### Metrics

Atom entries include video id, channel id, title, published/updated timestamps, links. **No view/like/comment counts.**

Notifications fire when a channel uploads a video or updates title/description — not when views change.

### Historical / real-time

Not a history archive (typically a short recent-window feed). Push is near-real-time for the events above.

### Restrictions

Still YouTube API Services surface when used as documented with the Data API. Do not scrape watch pages to “enrich” the feed.

### Python integration

HTTP GET of the Atom URL and/or a small WebSub callback (e.g. FastAPI later). XML parsing via stdlib or `feedparser` (not installed).

### Suitable for MVP?

Yes, as a quota-free **watchlist new-video detector**. Always follow with `videos.list` for metrics.

### Fallback

Poll `playlistItems.list` on the channel uploads playlist (costs Data API quota).

---

## Instagram (Meta Instagram Platform)

**Classification: POSSIBLE / NEEDS FURTHER VERIFICATION** for a later phase; **not V1**

### Official API availability

Yes. Instagram Platform (professional accounts only).

- Overview (updated 2026-06-30): https://developers.facebook.com/documentation/instagram-platform/overview
- Business Discovery (updated 2026-08-12): https://developers.facebook.com/docs/instagram-api/reference/ig-user/business_discovery

Two setups:

| Setup | Host | Notes |
| --- | --- | --- |
| Facebook Login for Business | `graph.facebook.com` | Page-linked professional accounts; hashtag search available |
| Business Login for Instagram | `graph.instagram.com` | Instagram-only professional accounts; **no hashtag search** |

### Authentication

Meta developer account + app. OAuth: short-lived token (~1 hour) exchanged for long-lived (~60 days), refreshable. Permissions are login-type specific (`instagram_basic`, `instagram_manage_insights`, `pages_read_engagement`, etc.).

### Free access

No per-call fee is stated on the overview. Access is gated by app roles, **Standard vs Advanced Access**, App Review, and Business Verification for apps serving accounts you do not manage.

Standard Access is for people with roles on the app (development/testing or accounts you manage). Market-wide monitoring of arbitrary education creators generally needs **Advanced Access + App Review**.

### Metrics

For **your** professional account: insights, comments, publishing, messaging (product-dependent).

For **other** professional accounts, Business Discovery can return public fields such as `followers_count`, `media_count`, and media `comments_count` / `like_count` / `view_count` (sample official request). Limitations:

- Target must be Business or Creator (not personal consumer accounts).
- Age-gated businesses return no data.
- Ordering not supported.
- `media_url` omitted in several copyright / downloads-off cases.

Hashtag search requires Facebook Login setup plus the **Instagram Public Content Access** feature. Allowed uses in the overview are campaign hashtags, brand sentiment, contests, support — not an unrestricted firehose.

### Historical / real-time

No documented historical insights warehouse for third-party accounts. User Insights is noted as the edge with time-based pagination; Business Discovery media is cursor-paginated, not a multi-year archive. Webhooks are recommended to reduce polling.

### Rate limits (official overview)

Most endpoints: Instagram Business Use Case limiting:

`Calls within 24 hours = 4800 * Number of Impressions`

Impressions = times the **app user’s** professional-account content entered a screen in the last 24 hours. Small education accounts therefore have small call budgets.

Business Discovery and Hashtag Search use **Platform Rate Limiting** instead (see Meta platform rate-limit docs before implementation; not copied here because the overview does not publish a single number).

### Commercial / restrictions

Platform terms, App Review, no consumer-account graph, no scraping. Insights for accounts you do not authenticate are limited to the public Business Discovery fields.

### Python integration

HTTPS to Graph API. Facebook/Meta official SDKs exist; raw `httpx` is enough. Not installed.

### Suitable for Trendora MVP?

**No.** V1 cannot depend on App Review, a professional account, Page linkage, or impression-scaled rate limits. Revisit after YouTube V1, if a Trendora-owned IG professional account exists.

### Fallback

None that is official and $0 for market-wide Instagram. Do not scrape.

---

## Facebook (Meta Graph API / Pages)

**Classification: NOT SUITABLE** for V1 market intelligence

### Official API

Graph API: https://developers.facebook.com/docs/graph-api/overview

Almost all endpoints need an access token. Pages, posts, photos, comments are nodes you can read **when authorized**.

### Why it fails Trendora V1

There is no documented free public search of all Facebook posts in SEA education. Page insights and engagement reads are for Pages the user can administer (or otherwise authorized). Consumer profiles are not a research firehose.

Treat Facebook as a later **owned-Page analytics** feature, not a market sensor.

### Fallback

None legitimate for third-party Page markets on $0.

---

## TikTok

**Classification: NOT SUITABLE** for V1 market intelligence

### Research Tools / Research API

Official: https://developers.tiktok.com/products/research-api  
FAQ: https://developers.tiktok.com/doc/research-api-faq/  
Terms: https://www.tiktok.com/legal/page/global/terms-of-service-research-api/en

Qualifying researchers in limited regions (academic institutions in US, EEA, UK, Switzerland; some EU non-profits; beta in additional European states). Applicants must be **independent from commercial interests** and work non-commercially. Creators, advertisers, and **commercial users are ineligible**.

Trendora is a product/platform. This API is not a V1 path.

### Display API

Official getting started: https://developers.tiktok.com/doc/display-api-get-started

OAuth Login Kit + `user.info.basic` / `video.list`. Returns **the authorizing user’s** profile and videos for display in *your* app. Not other creators’ market data. Not SEA education discovery.

### Other TikTok products

Content posting, marketing, and commercial content APIs are for publishing/ads, not third-party market intelligence. They were not adopted for V1. Do not assume they are free or that they expose competitor metrics.

### Fallback

No official $0 fallback. Unofficial scrapers / paid aggregators are out of scope.

---

## X (Twitter)

**Classification: NOT SUITABLE** until official access tiers are verified in a developer account

Official documentation URLs (`docs.x.com`, `developer.x.com`) returned **HTTP 403** to this research environment. Per project rules, quotas and free-tier read access are **not guessed**.

Given the $0 constraint and the inability to verify official read access, X is excluded from V1. Re-verify inside a logged-in X developer portal before any later phase.

### Fallback

None verified.

---

## Reddit

**Classification: POSSIBLE / NEEDS FURTHER VERIFICATION**

Reddit operates an official Data API (OAuth). The official wiki (`support.reddithelp.com` Data API article) and `developers.reddit.com` returned bot-challenge / 403 in this environment, so **current free vs commercial terms and exact quotas are not treated as verified**.

Independent write-ups claim a non-commercial free path and paid commercial licensing. Trendora is positioned as a product, which is likely **commercial use**. Until Reddit’s current terms are read while logged in as a developer, Reddit is not in V1.

Do not use unauthenticated `.json` scraping; that is widely reported as blocked and would violate typical API terms.

### Fallback

Not selected.

---

## LinkedIn

**Classification: NOT SUITABLE**

LinkedIn’s Community Management / Marketing Developer products are partner-gated. Share-on-LinkedIn is for posting to a member’s own feed, not market listening. No verified $0 intelligence API for SEA education creators.

---

## Hacker News

**Classification: APPROVED FOR MVP** (supplementary global tech signal)

### Official API

https://github.com/HackerNews/API  
Base: `https://hacker-news.firebaseio.com/v0/`

### Authentication / cost / quota

None documented. Official README: **“There is currently no rate limit.”** Still poll politely.

### Metrics / payload

Items: `id`, `type`, `by`, `time`, `title`, `url`, `score`, `descendants` (comment count), `kids`, `text`. Users: `karma`, `submitted`.

Endpoints: `topstories`, `newstories`, `beststories`, `askstories`, `showstories`, `jobstories`, `maxitem`, `updates`, `item/{id}`, `user/{id}`.

### Historical / real-time

Item IDs are sequential; you can walk backward from `maxitem` (expensive). Firebase can push change notifications. Near-real-time for front-page lists (up to 500 top/new).

### Restrictions

Public HN data. Not SEA-local; English/global tech bias. Useful as a **technology attention** overlay, not as Indonesia/Thailand education volume.

### Python

Plain HTTP JSON (`httpx`/`requests`). Not installed.

### Fallback

None needed.

---

## Stack Exchange / Stack Overflow

**Classification: APPROVED FOR MVP** (supplementary)

### Official API

https://api.stackexchange.com/docs/throttle  
Wrapper object (quota fields): https://api.stackexchange.com/docs/wrapper

### Authentication

Optional `key` from registering an app. OAuth `access_token` for user-specific / write paths (not needed for public reads).

### Free quota (official)

- Concurrent: **30 requests/second per IP** (hard cutoff if exceeded)
- Default daily quota **10,000** (IP-shared without token; per user/app pair with token)
- Honor `backoff` seconds when present
- Do not repeat identical requests more than once per minute (caching guidance)

### Metrics

Question/answer scores, tags, view counts, creation dates, body text (filters apply). Sites include Stack Overflow and language/locale Stack Exchange sites. **Confirm** whether any SEA-local sites are useful; do not assume they exist.

### Historical

Public Q&A history is the product; the API pages through existing posts. This is closer to a historical archive than YouTube stats.

### Python

HTTPS JSON. Third-party wrappers exist; not required.

### Restrictions

CC BY-SA content attribution. Quota sharing on a keyless IP.

### Fallback

Stack Exchange data dumps (separate license/process) — not needed for V1 and not researched in depth here.

---

## GitHub REST API

**Classification: APPROVED FOR MVP** (supplementary tech-education signal)

### Official

https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api

### Authentication

Unauthenticated public reads **or** PAT / GitHub App.

### Free quota (official)

- Unauthenticated: **60 requests/hour** per IP — too small for a pipeline
- Authenticated user/PAT: **5,000 requests/hour**
- Search endpoints are more restrictive (see GitHub search rate-limit docs before using search)
- Secondary limits: concurrency, points/minute, CPU time

### Metrics

Stars, forks, issues, traffic (traffic is owner-only), public events. Good for **programming education materials** (syllabi, courses, awesome-lists), not Instagram-like social.

### Historical

Public events are limited windows; stargazer history is not a full official time series. Snapshot stars over time ourselves if needed.

### Python

`httpx` or PyGithub later. Not installed.

### Fallback

GraphQL API (separate rate-limit points). Not required for V1.

---

## Wikimedia / Wikipedia Action API

**Classification: APPROVED FOR MVP** (context only)

### Official

- Etiquette: https://www.mediawiki.org/wiki/API:Etiquette
- Rate limits: https://www.mediawiki.org/wiki/Wikimedia_APIs/Rate_limits

### Authentication

Optional. Identify with a descriptive User-Agent including contact info (required policy).

### Limits (official gateway table)

Per-minute, per user identity, examples:

| Client | Limit |
| --- | --- |
| Unidentified (IP only) | 10 req/min |
| User-Agent-only unauthenticated bots | 200 req/min |
| Established authenticated editors | 2000 req/min |

429 on exceed. No hard global “free commercial ban” in the etiquette page; still follow bot policy and maxlag for non-interactive jobs.

### Data

Article revisions, pageviews via separate Wikimedia Analytics APIs (not fully researched here — **verify pageview API terms before using**). Useful for topic context (e.g. “data science” in Indonesian Wikipedia), not creator engagement.

### Python

`httpx` to `https://en.wikipedia.org/w/api.php` (and `id.wikipedia.org`, `th.wikipedia.org`, etc.).

### Fallback

Wikimedia dumps — heavy, not V1.

---

## GDELT

**Classification: APPROVED FOR MVP** (news/event context)

### Official

https://www.gdeltproject.org/data.html

GDELT states the database is **100% free and open**, with:

- raw CSV/file download
- Analysis Service
- Google BigQuery-hosted tables (updated every 15 minutes)

### $0 caution

**Raw HTTP files** fit the $0 constraint. **BigQuery is not automatically $0**; Google Cloud query bytes can incur charges after any free cloud allowance. V1 should use file drops, not assume BigQuery.

### Metrics

Events, counts, themes, organizations, locations, tone (GKG). News coverage of education/AI policy in SEA, not TikTok engagement.

### Historical

Very long archives (project claims multi-decade). GDELT 2.0 is the current 15-minute stream; confirm which version we ingest before coding.

### Python

Download + parse CSV/ZIP. Volume can be large; sample before committing to full ingest.

### Fallback

Skip GDELT if disk/CPU is too heavy; YouTube + HN still form a V1.

---

## OpenAlex

**Classification: POSSIBLE / NEEDS FURTHER VERIFICATION**

Scholarly graph (works, authors, institutions). Official auth page (updated 2026-08-11): https://developers.openalex.org/api-reference/authentication

- Free API key from an OpenAlex account
- Keyless use is for casual/demo scale
- Paid plans exist to raise budget
- Hard limits: 100 req/s, `per_page` max 100, basic paging 10,000 then cursors

OpenAlex also published usage-based API pricing with a **daily free allowance**. Because billing models changed in 2026, **do not wire OpenAlex into a production job until the current Pricing page is accepted as $0 for our query volume**.

Useful later for “AI education research output in SEA institutions,” not social KPIs.

---

## Google Trends

**Classification: NOT SUITABLE** as a core source

No official public Google Trends API was found for general developers. Unofficial libraries (e.g. pytrends) scrape or reverse-engineer the website and are **not** an approved $0 official path.

---

## Google News RSS and other unofficial RSS

**Classification: POSSIBLE / NEEDS FURTHER VERIFICATION** (not V1)

Publisher RSS/Atom feeds that **the publisher offers** are legitimate. Google News RSS URLs are not a documented, supported Google API. Do not build V1 on unofficial Google News endpoints.

A later phase may maintain an allowlist of official university, ministry-of-education, and edtech **first-party RSS** feeds (need per-feed terms).

---

## Common Crawl

**Classification: POSSIBLE** (not V1)

Open web crawl archives exist and are widely used for research. They are delayed, huge, and not a social-metrics API. Revisit only if we need broad web text and have storage. Confirm current access method and ToS before use.

---

## Other sources explicitly out of V1

| Source | Reason |
| --- | --- |
| Paid social aggregators (Phyllo, Brandwatch, etc.) | Violates $0 constraint |
| TikTok/Instagram unofficial scrapers | ToS / legal risk |
| YouTube HTML scraping | Explicitly prohibited |
| Kaggle dumps | Not live social intelligence; dataset licenses vary |
| Coursera/Udemy APIs | Not verified; typically partner/commercial |
| Apple App Store / Play Store unofficial scrapers | Not official market APIs |

---

## Python client summary (do not install yet)

| Source | Likely client |
| --- | --- |
| YouTube Data API | `google-api-python-client` or `httpx` |
| YouTube Atom/WebSub | stdlib XML + HTTP |
| Hacker News | `httpx` |
| Stack Exchange | `httpx` |
| GitHub | `httpx` or PyGithub |
| Wikipedia | `httpx` |
| GDELT files | `httpx` + csv |
| Instagram Graph | `httpx` (later) |

---

## Open verification items (before any connector)

1. In Google Cloud Console, read the **live** YouTube quota screen after enabling the API (docs can lag Console).
2. Run `videoCategories.list?regionCode=` for each SEA market; persist actual category IDs.
3. If multi-month YouTube stats are required, apply for YouTube API compliance audit + analytics/derived-metrics amendment.
4. Log into X, Reddit, and Meta developer portals if those platforms are reconsidered.
5. Confirm OpenAlex pricing page vs daily free allowance for any scholarly job.
6. Confirm Wikimedia Pageviews API separately if pageview series are desired.

No connectors should be written until this list is either accepted or updated.
