import test from "node:test";
import assert from "node:assert/strict";

import type { CitationJson, ResearchReportResponse } from "../lib/report-api.ts";
import type { ResearchReferenceResponse } from "../lib/trendora-api.ts";
import { buildProvenanceMaps, filterReferences, referencePlatform, resolveCitation, resolveReportAnswerCitation } from "../lib/report-provenance.ts";
import { reportMarkdown, printReport } from "../lib/report-actions.ts";

const reference: ResearchReferenceResponse = {
  source_code: "public_web", content_external_id: "source/1", title: "Reference title",
  description: "Reference description must not replace evidence", url: "https://www.reddit.com/r/research/1",
  published_at: "2026-10-01T00:00:00Z", collected_at: "2026-10-21T00:00:00Z",
  channel_external_id: null, channel_title: "reddit.com", market_contexts: [], market_context: null,
  market_basis: null, source_rank: 1,
  metrics: { view_count: null, like_count: null, comment_count: null, reaction_count: null, share_count: null },
};
const citation: CitationJson = { kind: "fact", reference, field: "description" };

test("Ask response identities trace a source without claiming an exact fact field", () => {
  const identity = { source_code: reference.source_code, content_external_id: reference.content_external_id };
  const resolved = resolveReportAnswerCitation(identity, buildProvenanceMaps(fixture()));
  assert.equal(resolved.resolved, true);
  assert.equal(resolved.kind, "reference");
  assert.equal(resolved.references[0].url, reference.url);
  assert.equal(resolved.textEvidence, undefined);
  assert.match(resolved.detail, /no exact field/i);
  const missing = resolveReportAnswerCitation({ ...identity, content_external_id: "absent" }, buildProvenanceMaps(fixture()));
  assert.equal(missing.resolved, false);
  assert.equal(missing.references.length, 0);
});

function fixture(value: unknown = "  Exact evidence <script>alert(1)</script>\nSecond line  "): ResearchReportResponse {
  return {
    status: "complete",
    research: {
      status: "complete", query: { topic: "Research [topic]", markets: ["ID"], market: null,
        date_from: "2026-10-01", date_to: "2026-10-20", sources: ["public_web", "youtube", "facebook"],
        result_limit: 10, facebook_page_id: "page-1" },
      references: [reference], executed_sources: ["public_web", "youtube", "facebook"],
      coverage: { completeness: "partial", sources: [{ source_code: "public_web", capability: "search", status: "available", reason: "search_partial" }] },
    },
    evidence: { analyses: [{ reference_id: reference, facts: [{ field: "description", value }], observations: [] }], patterns: [] },
    interpretation: { model_provenance: { provider: "source_evidence", model: "extractive-v1" }, interpretations: [{ statement: "An excerpt", citations: [citation] }] },
    strategy: { model_provenance: { provider: "provider", model: "strategy-model" }, content_gaps: [{ statement: "A gap", supporting_interpretation_indexes: [0], citations: [citation] }], opportunities: [{ statement: "An opportunity", gap_indexes: [0], citations: [citation] }] },
    ideation: { model_provenance: { provider: "provider", model: "ideas-model" }, content_ideas: [{ title: "An idea", angle: "An angle", opportunity_indexes: [0], citations: [citation] }], content_briefs: [{ idea_index: 0, objective: "An objective", format: "An essay", hook: "A hook", outline: ["First", "Second"], citations: [citation] }] },
    persistence: { status: "saved", request_id: "request-1", report_id: "report-1", snapshot_origin: "client_supplied", error_code: null },
  };
}

test("citation text comes exactly from the evidence value, independently of reference text", () => {
  const report = fixture();
  const before = JSON.stringify(report);
  const resolved = resolveCitation(citation, buildProvenanceMaps(report));
  assert.deepEqual(resolved.textEvidence, { value: report.evidence!.analyses[0].facts[0].value, unavailableReason: null });
  assert.equal(JSON.stringify(report), before);
});

test("missing, null, blank and nontext evidence are unavailable without changing structural resolution", () => {
  for (const value of [null, " \n ", 0, false, {}, []]) {
    const report = fixture(value);
    const resolved = resolveCitation(citation, buildProvenanceMaps(report));
    assert.equal(resolved.resolved, true);
    assert.equal(resolved.textEvidence?.value, null);
    assert.ok(resolved.textEvidence?.unavailableReason);
  }
  const report = fixture();
  report.evidence!.analyses[0].facts = [];
  const missing = resolveCitation(citation, buildProvenanceMaps(report));
  assert.equal(missing.resolved, false);
  assert.match(missing.textEvidence!.unavailableReason!, /not found/i);
  const maps = buildProvenanceMaps(fixture("Actual title"));
  maps.analysisById.get("public_web:source/1")!.facts[0].field = "title";
  assert.equal(resolveCitation({ ...citation, field: "title" }, maps).textEvidence?.value, "Actual title");
  const unknown = resolveCitation(
    { ...citation, reference: { source_code: "public_web", content_external_id: "missing" } },
    maps,
  );
  assert.match(unknown.textEvidence!.unavailableReason!, /source is not present/i);
  const noAnalysis = fixture();
  noAnalysis.evidence!.analyses = [];
  assert.match(
    resolveCitation(citation, buildProvenanceMaps(noAnalysis)).textEvidence!.unavailableReason!,
    /no evidence analysis/i,
  );
});

test("library filters intersect title, hostname platform and valid publication dates without changing order or identity", () => {
  const references = [
    reference,
    { ...reference, content_external_id: "2", title: "RESEARCH notes", published_at: null },
    { ...reference, content_external_id: "3", title: "Research paper", url: "https://reddit.com.evil.example/x", published_at: "2026-02-30T00:00:00Z" },
    { ...reference, content_external_id: "4", title: null, url: "https://youtu.be/video" },
  ];
  const before = JSON.stringify(references);
  assert.equal(referencePlatform(references[2]), "Other / unknown");
  assert.equal(referencePlatform(references[3]), "YouTube");
  assert.equal(referencePlatform({ ...reference, url: "https://old.reddit.com/x" }), "Reddit");
  assert.equal(referencePlatform({ ...reference, url: "https://youtube.com.evil.test/x" }), "Other / unknown");
  const result = filterReferences(references, { query: " research ", platform: "Reddit", date: "undated" });
  assert.deepEqual(result, [references[1]]);
  assert.equal(result[0], references[1]);
  assert.deepEqual(filterReferences(references, { query: "", platform: "all", date: "dated" }), [reference, references[3]]);
  assert.equal(filterReferences(references, { query: "not present", platform: "all", date: "all" }).length, 0);
  assert.deepEqual(filterReferences(references, { query: "", platform: "all", date: "all" }), references);
  assert.equal(JSON.stringify(references), before);
});

test("full Markdown carries every stage, evidence values, stable links and coverage/date/provenance caveats", () => {
  const report = fixture("Evidence text");
  const before = JSON.stringify(report);
  const markdown = reportMarkdown(report);
  for (const text of ["An excerpt", "A gap", "An opportunity", "An idea", "An objective", "A hook", "Second", "Evidence text",
    "extractive-v1", "strategy-model", "ideas-model", "search_partial", "partial", "client_supplied",
    "not synthesized findings", "Event dates are unavailable", "not the whole internet", "not a measure of growth",
    "did not enforce the requested timeframe", "regional availability/viewability", "explicit Facebook Page", "Run diagnostics unavailable"]) {
    assert.ok(markdown.includes(text), text);
  }
  const anchors = [...markdown.matchAll(/<a id="([^"]+)"><\/a>/g)].map((match) => match[1]);
  const links = [...markdown.matchAll(/\]\(#([^)]*)\)/g)].map((match) => match[1]);
  assert.ok(links.length >= 5);
  for (const link of links) assert.ok(anchors.includes(link), `Unresolved exported link: ${link}`);
  assert.ok(markdown.includes("https://www.reddit.com/r/research/1"));
  assert.equal(reportMarkdown(report), markdown);
  assert.equal(JSON.stringify(report), before);
});

test("Markdown qualifies missing evidence and diagnostics, escapes source markup and preserves zero only when returned", () => {
  const report = fixture(null);
  report.research.executed_sources = undefined as unknown as string[];
  report.research.references[0] = { ...reference, title: "<img src=x onerror=alert(1)> [fake](javascript:bad)", published_at: null, url: "javascript:alert(1)" };
  const markdown = reportMarkdown(report);
  assert.match(markdown, /Cited text unavailable/);
  assert.match(markdown, /Execution details are unavailable/);
  assert.match(markdown, /Undated source context/);
  assert.match(markdown, /Missing diagnostics do not imply zero/);
  assert.ok(!markdown.includes("[Open source](<javascript:"));
  assert.ok(!markdown.includes("<img src="));
  assert.match(reportMarkdown({ ...report, run_details: { calls: 0 } } as unknown as ResearchReportResponse), /"calls": 0/);
});

test("printing opens disclosures for the selected report and restores them even if native print fails", () => {
  let marked = false;
  const details = [{ open: false }, { open: false }];
  const element = {
    querySelectorAll: () => details,
    setAttribute: () => { marked = true; },
    removeAttribute: () => { marked = false; },
    ownerDocument: { defaultView: { print: () => {
      assert.equal(marked, true);
      assert.ok(details.every((detail) => detail.open));
      throw new Error("print failed");
    } } },
  } as unknown as HTMLElement;
  assert.throws(() => printReport(element), /print failed/);
  assert.equal(marked, false);
  assert.ok(details.every((detail) => !detail.open));
});
