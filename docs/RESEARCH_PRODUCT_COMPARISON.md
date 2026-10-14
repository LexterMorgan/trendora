# Research improvements, 2026-10-11

This comparison uses public product documentation, not private implementations.
The owner authorized improvements beyond the current PRD. The selected changes
improve the existing research path without adding services, dependencies, schema
changes, or additional model calls.

## What similar products do

| Product | Documented behavior | Decision for Trendora |
| --- | --- | --- |
| [Feedly](https://docs.feedly.com/article/218-how-does-deduplication-work) | Content-based deduplication suppresses overlapping articles. | Reduce repeated evidence. Trendora only has search snippets, so implement conservative campaign-URL deduplication rather than infer that similar snippets represent the same article. |
| [Perplexity](https://www.perplexity.ai/help-center/en/articles/10352903-what-is-pro-search) | Synthesizes multiple sources, links citations, and supports follow-up questions. | Improve the existing synthesis instructions first: distinct findings, supporting source text, and attributed disagreements. A follow-up chat would add model calls and access/retention work, so it is deferred. |
| [BuzzSumo](https://help.buzzsumo.com/en/articles/1633277-how-to-use-trending) | Trending feeds rank recent stories using social shares over time. | Preserve the distinction between recent sources and measured growth. Trendora does not have comparable time-series evidence in this report flow, so no trend score is added. |
| [Feedly Market Intelligence](https://feedly.com/market-intelligence) | Topic monitoring, cited summaries, and newsletters. | Saved topic monitoring could help repeated research later. Scheduling, delivery, and ongoing quota use are outside this focused change. |

## Implemented

- Both SearXNG and Serper compare URLs without nine documented Google Analytics
  campaign parameters before applying their result limits. The first result's
  original URL, title, snippet, and citation identity stay intact. Other distinct
  results already in the response can fill the freed slots; no extra search runs.
- Query values/order, content IDs, pagination, unknown parameters, path case,
  fragments, and different hosts/schemes remain distinct. Identical short snippets
  are not evidence that pages are duplicates. This does not deduplicate syndicated
  stories, HTTP/HTTPS aliases, or every possible tracking parameter.
- The interpretation prompt asks for one distinct finding per interpretation,
  combines overlapping coverage, requests supporting title/description citations,
  and preserves conflicting claims and promotional attribution. These are model
  instructions, not new semantic validation. Existing citation validation, date
  caveats, and excerpt fallback remain in force.
- Interpretation requests use compact JSON separators. Source text and evidence
  values are unchanged. The shared evidence serializer and saved snapshot format
  are unchanged, as are optional strategy/ideation request formats.

The URL heuristic assumes recognized UTM parameters describe campaign attribution.
A site that uses them to select different content could be merged incorrectly;
the rule is deliberately narrower than arbitrary query stripping. Google's
[campaign parameter documentation](https://support.google.com/analytics/answer/10917952?hl=en)
defines the allowlist. Python's [URL parser](https://docs.python.org/3.12/library/urllib.parse.html)
supports preserving raw URL components, and its [JSON encoder](https://docs.python.org/3.12/library/json.html)
supports compact separators. Existing URL validation runs before comparison.

## Evidence and limits

Before implementation, two mocked gateway tests demonstrated duplicate campaign
URLs occupying both available result slots. A request test also failed the compact
JSON requirement. All three passed after the change. Tests cover both gateways
through normalization, original citation preservation, one search call, distinct
page preservation, exact UTM keys, encoded keys, and unchanged decoded evidence.

Verification: 326 focused unit tests passed across search, interpretation, research
fallback, and save/recovery; `git diff --check` passed. Two existing test-client
deprecation warnings remain. No full-suite or frontend rerun was needed for this
backend-only change.

A fictional 40-reference evidence pack shrank from 93,322 to 88,189 UTF-8 bytes
(5.5%) using compact separators. This measures evidence JSON only, not total
prompt tokens, latency, cache hits, or billing. No tokenizer or live model was used.

No live search/model evaluation, database operations, service restarts, installs,
or UI changes were performed. Better live prose remains unverified. Existing saved
reports are not regenerated; changes apply to new research after backend reload.

Next useful improvements, in order: reliable publication-date evidence and bounded
full-page extraction; then saved topics and report follow-ups. Each needs its own
scope and checks. Full-page fetching requires redirect and connection-time network
destination protection. Date metadata must retain provenance rather than silently
turn search snippets into verified event dates.
