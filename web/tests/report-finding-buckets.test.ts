import test from "node:test";
import assert from "node:assert/strict";

import type { CitationJson, ResearchReportResponse } from "../lib/report-api.ts";
import {
  buildProvenanceMaps,
  classifyFindingSupport,
  resolveCitation,
} from "../lib/report-provenance.ts";

const REF = { source_code: "youtube", content_external_id: "v1" };
const PATTERN = "title_has_numeral";
const OBSERVATION = "description_present";

interface ReportParts {
  facts?: { field: string; value: unknown }[];
  patterns?: unknown[];
  observations?: unknown[];
  includeReference?: boolean;
}

function makeReport({ facts = [], patterns = [], observations = [], includeReference = true }: ReportParts = {}): ResearchReportResponse {
  return {
    research: { references: includeReference ? [{ ...REF, title: "A title", description: "A description" }] : [] },
    evidence: {
      analyses: includeReference ? [{ reference_id: REF, facts, observations }] : [],
      patterns,
    },
  } as unknown as ResearchReportResponse;
}

function classifier(report: ResearchReportResponse) {
  const maps = buildProvenanceMaps(report);
  return (citations: CitationJson[]) => classifyFindingSupport(maps, citations.map((citation) => resolveCitation(citation, maps)));
}

const TEXT_CITATION: CitationJson = { kind: "fact", reference: REF, field: "description" };
const METRIC_CITATION: CitationJson = { kind: "fact", reference: REF, field: "view_count" };
const PATTERN_CITATION: CitationJson = { kind: "pattern", observation_type: PATTERN };
const OBSERVATION_CITATION: CitationJson = { kind: "observation", reference: REF, observation_type: OBSERVATION };
const PATTERNS = [{ observation_type: PATTERN, analyzed_count: 3, matching_count: 1, non_matching_count: 2, ratio: 1 / 3, matching_reference_ids: [REF], non_matching_reference_ids: [] }];
const OBSERVATIONS = [{ observation_type: OBSERVATION, value: true, evidence_fields: ["description"], analysis_basis: "description" }];

test("valid source text is a research finding", () => {
  const classify = classifier(makeReport({ facts: [{ field: "description", value: "Real source text" }] }));
  assert.equal(classify([TEXT_CITATION]), "finding");
});

test("resolved pattern, observation, and numeric metric are sample observations", () => {
  assert.equal(classifier(makeReport({ patterns: PATTERNS }))([PATTERN_CITATION]), "observation");
  assert.equal(classifier(makeReport({ observations: OBSERVATIONS }))([OBSERVATION_CITATION]), "observation");
  assert.equal(classifier(makeReport({ facts: [{ field: "view_count", value: 5 }] }))([METRIC_CITATION]), "observation");
  assert.equal(classifier(makeReport({ facts: [{ field: "view_count", value: 0 }] }))([METRIC_CITATION]), "observation");
});

test("missing, unresolved, blank, null, and metadata-only citations are limited evidence", () => {
  assert.equal(classifier(makeReport())([]), "limited", "no citations");
  assert.equal(classifier(makeReport({ includeReference: false }))([TEXT_CITATION]), "limited", "unresolved reference");
  assert.equal(classifier(makeReport({ facts: [{ field: "description", value: null }] }))([TEXT_CITATION]), "limited", "null text");
  assert.equal(classifier(makeReport({ facts: [{ field: "description", value: "   " }] }))([TEXT_CITATION]), "limited", "blank text");
  assert.equal(classifier(makeReport({ facts: [{ field: "description", value: 42 }] }))([TEXT_CITATION]), "limited", "non-string text");
  assert.equal(classifier(makeReport({ facts: [{ field: "view_count", value: null }] }))([METRIC_CITATION]), "limited", "null metric");
  assert.equal(classifier(makeReport({ facts: [{ field: "view_count", value: -1 }] }))([METRIC_CITATION]), "limited", "negative metric");
  assert.equal(classifier(makeReport({ facts: [{ field: "view_count", value: "5" }] }))([METRIC_CITATION]), "limited", "non-numeric metric");
  assert.equal(classifier(makeReport({ facts: [{ field: "url", value: "https://example.test/x" }] }))([{ kind: "fact", reference: REF, field: "url" }]), "limited", "metadata-only");
  assert.equal(classifier(makeReport({ facts: [{ field: "collected_at", value: "2026-10-01T00:00:00Z" }] }))([{ kind: "fact", reference: REF, field: "collected_at" }]), "limited", "collection date");
});

test("valid text alongside an unresolved citation is limited evidence", () => {
  const missing: CitationJson = { kind: "fact", reference: { source_code: "youtube", content_external_id: "absent" }, field: "description" };
  const classify = classifier(makeReport({ facts: [{ field: "description", value: "Real source text" }] }));
  assert.equal(classify([TEXT_CITATION, missing]), "limited");
});

test("classification does not mutate its inputs", () => {
  const report = makeReport({ facts: [{ field: "description", value: "Real source text" }, { field: "view_count", value: 5 }], patterns: PATTERNS, observations: OBSERVATIONS });
  const before = JSON.stringify(report);
  const maps = buildProvenanceMaps(report);
  const citations = [TEXT_CITATION, METRIC_CITATION, PATTERN_CITATION].map((citation) => resolveCitation(citation, maps));
  const citationsBefore = JSON.stringify(citations);
  classifyFindingSupport(maps, citations);
  assert.equal(JSON.stringify(report), before, "input report must be unchanged");
  assert.equal(JSON.stringify(citations), citationsBefore, "resolved citations must be unchanged");
});
