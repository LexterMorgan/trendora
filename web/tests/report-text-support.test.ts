import test from "node:test";
import assert from "node:assert/strict";

import type { CitationJson, ResearchReportResponse } from "../lib/report-api.ts";
import {
  buildProvenanceMaps,
  hasResolvedTextSupport,
  resolveCitation,
} from "../lib/report-provenance.ts";

const REF = { source_code: "youtube", content_external_id: "v1" };
const CITATION: CitationJson = { kind: "fact", reference: REF, field: "description" };

function reportWithDescriptionValue(value: unknown, referenceDescription = "Reference text is present"): ResearchReportResponse {
  return {
    research: {
      references: [{
        ...REF,
        url: null,
        title: "A real title",
        description: referenceDescription,
        published_at: null,
        channel_external_id: null,
        channel_title: null,
        market_contexts: [],
        market_context: null,
        market_basis: null,
        source_rank: 1,
        metrics: { view_count: null, like_count: null, comment_count: null, reaction_count: null, share_count: null },
        collected_at: "2026-10-01T00:00:00Z",
      }],
    },
    evidence: {
      analyses: [{ reference_id: REF, facts: [{ field: "description", value }], observations: [] }],
      patterns: [],
    },
  } as unknown as ResearchReportResponse;
}

function supportFor(value: unknown, referenceDescription?: string) {
  const maps = buildProvenanceMaps(reportWithDescriptionValue(value, referenceDescription));
  return { maps, citation: resolveCitation(CITATION, maps) };
}

test("a nonblank string fact value supports the finding", () => {
  const { maps, citation } = supportFor("Real source text");
  assert.equal(hasResolvedTextSupport(maps, [citation]), true);
});

test("a null fact value does not support the finding, even when the reference has text", () => {
  const { maps, citation } = supportFor(null, "Reference text is present");
  assert.equal(hasResolvedTextSupport(maps, [citation]), false);
});

test("whitespace and non-string fact values do not support the finding", () => {
  for (const value of ["   ", 42, [], {}, true]) {
    const { maps, citation } = supportFor(value);
    assert.equal(hasResolvedTextSupport(maps, [citation]), false, JSON.stringify(value));
  }
});

test("generic citation resolution is preserved: a null-valued fact still resolves structurally", () => {
  const { maps, citation } = supportFor(null, "Reference text is present");
  assert.equal(citation.resolved, true, "The field exists, so the citation resolves");
  assert.equal(citation.references.length, 1);
  assert.equal(hasResolvedTextSupport(maps, [citation]), false, "Resolution alone is not support");
});

test("metric-only and unresolved citations do not support the finding", () => {
  const metricMaps = buildProvenanceMaps({
    research: { references: [{ ...REF }] },
    evidence: { analyses: [{ reference_id: REF, facts: [{ field: "view_count", value: 5 }], observations: [] }], patterns: [] },
  } as unknown as ResearchReportResponse);
  const metricCitation = resolveCitation({ kind: "fact", reference: REF, field: "description" }, metricMaps);
  assert.equal(hasResolvedTextSupport(metricMaps, [metricCitation]), false);

  const unresolvedMaps = buildProvenanceMaps({
    research: { references: [] },
    evidence: { analyses: [], patterns: [] },
  } as unknown as ResearchReportResponse);
  const unresolvedCitation = resolveCitation(CITATION, unresolvedMaps);
  assert.equal(unresolvedCitation.resolved, false);
  assert.equal(hasResolvedTextSupport(unresolvedMaps, [unresolvedCitation]), false);
});
