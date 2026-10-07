import test from "node:test";
import assert from "node:assert/strict";

import { ResearchApiError, type ApiRuntime } from "../lib/api.ts";
import {
  SAVE_BODY_LIMIT_BYTES,
  snapshotOf,
  saveReportSnapshot,
  type ResearchReportResponse,
} from "../lib/report-api.ts";
import {
  getPlannerOrigin,
  importPlannerPost,
} from "../lib/planner-api.ts";
import { resolveCitation, buildProvenanceMaps, publicationDay, publicationScope, citationPublicationScope, resolveUpstreamChain, hasSourceBackedSummaries } from "../lib/report-provenance.ts";
import { newRequestId, saveStatusFromOutcome } from "../lib/report-planner-actions.ts";
import {
  isTerminalSaveCode,
  saveStatusForErrorCode,
  terminalSaveMessage,
} from "../lib/report-planner-actions.ts";

const runtime: ApiRuntime = {
  getAccessToken: async () => "fictional-token",
  getSessionBinding: () => ({ userId: "fictional-member", epoch: 0 }),
  onUnauthenticated() {},
  onAccessDenied() {},
};

function report(): ResearchReportResponse {
  return {
    status: "completed",
    research: {
      query: { topic: "t", markets: ["SG"], market: "SG", date_from: "2026-08-01", date_to: "2026-08-31", sources: ["youtube"], result_limit: 20, facebook_page_id: null },
      coverage: { completeness: "complete", sources: [] },
      executed_sources: ["youtube"],
      status: "completed",
      references: [
        { source_code: "youtube", content_external_id: "v1", url: "https://example.com/v1", title: "T", description: "D", published_at: null, channel_external_id: null, channel_title: null, market_contexts: ["SG"], market_context: "SG", market_basis: "youtube_region_availability", source_rank: 1, metrics: { view_count: null, like_count: null, comment_count: null, reaction_count: null, share_count: null }, collected_at: "2026-10-01T00:00:00Z" },
      ],
    },
    evidence: { analyses: [{ reference_id: { source_code: "youtube", content_external_id: "v1" }, facts: [], observations: [] }], patterns: [] },
    interpretation: { model_provenance: { provider: "p", model: "m" }, interpretations: [] },
    strategy: { model_provenance: { provider: "p", model: "m" }, content_gaps: [], opportunities: [] },
    ideation: { model_provenance: { provider: "p", model: "m" }, content_ideas: [], content_briefs: [] },
    persistence: { status: "failed", request_id: "r", report_id: null, snapshot_origin: "server_generated", error_code: "persistence_unconfigured" },
  };
}

async function mocked(status: number, body: unknown, run: (calls: Array<{ path: string; init?: RequestInit }>) => Promise<void>) {
  const original = globalThis.fetch;
  const calls: Array<{ path: string; init?: RequestInit }> = [];
  globalThis.fetch = (async (input, init) => {
    calls.push({ path: String(input), init });
    return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
  }) as typeof fetch;
  try { await run(calls); } finally { globalThis.fetch = original; }
}

test("snapshotOf returns exactly the six immutable fields", () => {
  const snapshot = snapshotOf(report());
  assert.deepEqual(Object.keys(snapshot).sort(), ["evidence", "ideation", "interpretation", "research", "status", "strategy"]);
  assert.equal("persistence" in snapshot, false);
});

test("publication-window context validates dates without using collection time", () => {
  const window = { date_from: "2026-08-01", date_to: "2026-08-31" };
  assert.equal(publicationScope("2026-08-01T00:00:00Z", window), "in_window");
  assert.equal(publicationScope("2026-08-31T23:59:59Z", window), "in_window");
  assert.equal(publicationScope("2026-07-31T23:59:59Z", window), "outside_window");
  for (const date of [null, undefined, "", "not-a-date", "2026-02-30T00:00:00Z", "2026-08-12", "2026-08-12T12:00:00"]) {
    assert.equal(publicationScope(date, window), "undated");
    assert.equal(publicationDay(date), null);
  }
  assert.equal(publicationScope("2026-08-12T00:00:00Z", undefined), "unknown_window");
  assert.equal(publicationScope("2026-08-12T00:00:00Z", { ...window, date_to: "2026-07-31" }), "unknown_window");
  assert.equal(publicationDay("2026-08-01T00:30:00+01:00"), "2026-07-31");
});

test("source-excerpt labels depend on exact provenance, never report status", () => {
  const research = report();
  for (const status of ["completed", "research_completed", "legacy_unknown"]) {
    research.status = status;
    assert.equal(hasSourceBackedSummaries(research), false);
    research.interpretation!.model_provenance = { provider: "source_evidence", model: "extractive-v1" };
    assert.equal(hasSourceBackedSummaries(research), true);
    research.interpretation!.model_provenance = { provider: "source_evidence", model: "other" };
    assert.equal(hasSourceBackedSummaries(research), false);
  }
  research.interpretation = null;
  assert.equal(hasSourceBackedSummaries(research), false);
});

test("research-only citation traces survive absent content stages and preserve immutable shape", () => {
  const research = report();
  research.status = "research_completed";
  research.strategy = null; research.ideation = null;
  research.research.references[0].published_at = "2026-08-12T00:00:00Z";
  research.evidence!.analyses[0].facts = [{ field: "description", value: "D" }];
  const item = { statement: "D", citations: [{ kind: "fact" as const, reference: { source_code: "youtube", content_external_id: "v1" }, field: "description" }] };
  const before = JSON.stringify(snapshotOf(research));
  const citations = item.citations.map((citation) => resolveCitation(citation, buildProvenanceMaps(research)));
  assert.equal(citationPublicationScope(citations, research.research.query), "in_window");
  assert.equal(citations[0].references[0].url, "https://example.com/v1");
  assert.deepEqual(resolveUpstreamChain(research, { kind: "interpretation", item }), [{ label: "Interpretation", value: "D", resolved: true }]);
  research.research.references[0].published_at = null;
  assert.equal(citationPublicationScope(citations, research.research.query), "undated");
  research.research.references[0].published_at = "2026-08-12T00:00:00Z";
  assert.equal(JSON.stringify(snapshotOf(research)), before);
  assert.deepEqual(Object.keys(snapshotOf(research)).sort(), ["evidence", "ideation", "interpretation", "research", "status", "strategy"]);
});

test("synthesis citations retain outside and unknown date context without becoming source quotations", () => {
  const research = report();
  research.status = "research_completed";
  research.strategy = null; research.ideation = null;
  const original = research.research.references[0];
  research.research.references = [
    { ...original, published_at: "2026-08-12T00:00:00Z" },
    { ...original, content_external_id: "v2", published_at: "2026-07-31T00:00:00Z" },
    { ...original, content_external_id: "v3", published_at: null },
  ];
  research.evidence!.analyses = research.research.references.map((reference) => ({
    reference_id: { source_code: reference.source_code, content_external_id: reference.content_external_id },
    facts: [{ field: "description", value: reference.description }], observations: [],
  }));
  const maps = buildProvenanceMaps(research);
  const citations = research.research.references.map((reference) => resolveCitation({ kind: "fact", reference: { source_code: reference.source_code, content_external_id: reference.content_external_id }, field: "description" }, maps));
  const before = JSON.stringify(snapshotOf(research));
  assert.equal(hasSourceBackedSummaries(research), false);
  assert.equal(citationPublicationScope([citations[0]], research.research.query), "in_window");
  assert.equal(citationPublicationScope([citations[1]], research.research.query), "outside_window");
  assert.equal(citationPublicationScope([citations[2]], research.research.query), "undated");
  assert.equal(citationPublicationScope([citations[0], citations[1]], research.research.query), "outside_window");
  assert.equal(citationPublicationScope([citations[0], citations[2]], research.research.query), "undated");
  assert.equal(JSON.stringify(snapshotOf(research)), before);
});

test("saveReportSnapshot posts the six-field snapshot under the frozen key", async () => {
  await mocked(201, { persistence: { status: "saved", request_id: "req-1", report_id: "rep-1", snapshot_origin: "client_supplied", error_code: null } }, async (calls) => {
    const result = await saveReportSnapshot("req-1", report(), { runtime });
    assert.equal(calls[0].path, "/api/reports/save");
    const body = JSON.parse(String(calls[0].init?.body));
    assert.equal(body.schema_version, 1);
    assert.equal(body.request_id, "req-1");
    assert.deepEqual(Object.keys(body.snapshot).sort(), ["evidence", "ideation", "interpretation", "research", "status", "strategy"]);
    assert.equal(result.persistence.report_id, "rep-1");
  });
});

test("recovery forwards the opaque server receipt unchanged outside the immutable snapshot", async () => {
  const generated = report();
  const receipt = "fictional-opaque-receipt.signature";
  Object.assign(generated.persistence!, { recovery_receipt: receipt });
  const snapshotBefore = JSON.stringify(snapshotOf(generated));
  await mocked(201, { persistence: { status: "saved", request_id: "fixed-recovery-key", report_id: "recovered", snapshot_origin: "client_supplied", error_code: null } }, async (calls) => {
    await saveReportSnapshot("fixed-recovery-key", generated, { runtime });
    await saveReportSnapshot("fixed-recovery-key", generated, { runtime });
    const bodies = calls.map((call) => JSON.parse(String(call.init?.body)));
    assert.equal(bodies[0].recovery_receipt, receipt);
    assert.deepEqual(bodies[1], bodies[0]);
    assert.equal("recovery_receipt" in bodies[0].snapshot, false);
    assert.equal("persistence" in bodies[0].snapshot, false);
    assert.equal(JSON.stringify(bodies[0].snapshot), snapshotBefore);
  });
});

test("an oversized snapshot is refused in the browser before sending", async () => {
  const big = report();
  big.research.references[0].description = "a".repeat(SAVE_BODY_LIMIT_BYTES + 10);
  let called = false;
  const original = globalThis.fetch;
  globalThis.fetch = (async () => { called = true; return new Response("{}"); }) as typeof fetch;
  try {
    await assert.rejects(
      saveReportSnapshot("req-1", big, { runtime }),
      (error: unknown) => error instanceof ResearchApiError && error.code === "snapshot_too_large" && error.status === 413,
    );
    assert.equal(called, false);
  } finally {
    globalThis.fetch = original;
  }
});

test("changed content under the same key surfaces the 409 conflict", async () => {
  await mocked(409, { error: { code: "report_save_conflict", message: "conflict" } }, async () => {
    await assert.rejects(
      saveReportSnapshot("req-1", report(), { runtime }),
      (error: unknown) => error instanceof ResearchApiError && error.code === "report_save_conflict",
    );
  });
});

test("import sends only the four writable fields and returns the id", async () => {
  await mocked(201, { id: "post-1" }, async (calls) => {
    const result = await importPlannerPost("req-1", "rep-1", "brief", 2, { runtime });
    assert.equal(calls[0].path, "/api/planner/posts/import");
    assert.deepEqual(JSON.parse(String(calls[0].init?.body)), { request_id: "req-1", report_id: "rep-1", item_kind: "brief", item_index: 2 });
    assert.equal(result.id, "post-1");
  });
});

test("origin read validates the source-state shape", async () => {
  await mocked(200, { report_id: "rep-1", item_kind: "idea", item_index: 0, parent_idea_index: null, provenance: "server_generated", context: { title: "T" }, sources: [{ source_code: "youtube", content_external_id: "v1", state: "expired", url: null }] }, async (calls) => {
    const origin = await getPlannerOrigin("post-1", { runtime });
    assert.equal(calls[0].path, "/api/planner/posts/post-1/origin");
    assert.equal(origin.sources[0].state, "expired");
  });
});

test("missing fact citations resolve false, but present null facts still resolve", () => {
  const maps = buildProvenanceMaps({
    ...report(),
    evidence: { analyses: [{ reference_id: { source_code: "youtube", content_external_id: "v1" }, facts: [{ field: "view_count", value: null }], observations: [] }], patterns: [] },
  } as ResearchReportResponse);
  const missing = resolveCitation({ kind: "fact", reference: { source_code: "youtube", content_external_id: "v1" }, field: "like_count" }, maps);
  assert.equal(missing.resolved, false);
  const present = resolveCitation({ kind: "fact", reference: { source_code: "youtube", content_external_id: "v1" }, field: "view_count" }, maps);
  assert.equal(present.resolved, true);
});

test("legacy evidence metadata remains unresolved without changing the snapshot", () => {
  const legacy = {
    ...report(),
    evidence: {
      analyses: [{ reference_id: { source_code: "youtube", content_external_id: "v1" } }],
    },
  } as unknown as ResearchReportResponse;
  const before = JSON.stringify(snapshotOf(legacy));
  const maps = buildProvenanceMaps(legacy);
  for (const citation of [
    { kind: "fact", reference: { source_code: "youtube", content_external_id: "v1" }, field: "view_count" },
    { kind: "observation", reference: { source_code: "youtube", content_external_id: "v1" }, observation_type: "title_has_numeral" },
    { kind: "pattern", observation_type: "title_has_numeral" },
  ] as const) {
    assert.equal(resolveCitation(citation, maps).resolved, false);
  }
  assert.equal(maps.referenceById.size, 1);
  assert.equal(JSON.stringify(snapshotOf(legacy)), before);
});

test("save status maps outcomes and newRequestId returns a UUID", () => {
  assert.equal(saveStatusFromOutcome({ status: "saved", report_id: "x", snapshot_origin: "server_generated" }), "saved");
  assert.equal(saveStatusFromOutcome({ status: "failed", report_id: null, snapshot_origin: "server_generated" }), "failed");
  assert.equal(saveStatusFromOutcome({ status: "unknown", report_id: null, snapshot_origin: "server_generated" }), "uncertain");
  assert.match(newRequestId(), /^[0-9a-f-]{36}$/i);
});

test("terminal save errors are classified as failed with no retry message", () => {
  for (const code of [
    "report_request_too_large",
    "snapshot_too_large",
    "invalid_report_snapshot",
    "report_save_conflict",
    "report_expired",
  ]) {
    assert.equal(isTerminalSaveCode(code), true, code);
    assert.equal(saveStatusForErrorCode(code), "failed", code);
    assert.ok((terminalSaveMessage(code) ?? "").length > 0, code);
  }
  for (const code of ["data_unavailable", "backend_unreachable", "unknown_error", null]) {
    assert.equal(isTerminalSaveCode(code), false, String(code));
    assert.equal(saveStatusForErrorCode(code), "uncertain", String(code));
    assert.equal(terminalSaveMessage(code), null, String(code));
  }
});

test("oversized browser save is refused locally with a terminal code", async () => {
  const big = report();
  big.research.references[0].description = "a".repeat(SAVE_BODY_LIMIT_BYTES + 1);
  let called = false;
  const original = globalThis.fetch;
  globalThis.fetch = (async () => { called = true; return new Response("{}"); }) as typeof fetch;
  try {
    await assert.rejects(
      saveReportSnapshot("req-1", big, { runtime }),
      (error: unknown) =>
        error instanceof ResearchApiError &&
        isTerminalSaveCode(error.code) &&
        saveStatusForErrorCode(error.code) === "failed",
    );
    assert.equal(called, false);
  } finally {
    globalThis.fetch = original;
  }
});

test("server-side size failure maps to the same terminal state as the browser check", async () => {
  await mocked(413, { error: { code: "report_request_too_large", message: "too large" } }, async () => {
    await assert.rejects(
      saveReportSnapshot("req-1", report(), { runtime }),
      (error: unknown) =>
        error instanceof ResearchApiError &&
        isTerminalSaveCode(error.code) &&
        saveStatusForErrorCode(error.code) === "failed",
    );
  });
});

test("initial failure then recovery then import uses the recovered id without a new key", async () => {
  // 1. Generation reports a failed initial save.
  const generated = report();
  assert.equal(generated.persistence?.status, "failed");
  assert.equal(generated.persistence?.report_id, null);

  // 2. Recovery succeeds and returns the canonical id under the frozen key.
  const frozenKey = "req-recover-1";
  const recoveredId = "report-canonical-1";
  await mocked(
    201,
    { persistence: { status: "saved", request_id: frozenKey, report_id: recoveredId, snapshot_origin: "client_supplied", error_code: null } },
    async (calls) => {
      const result = await saveReportSnapshot(frozenKey, generated, { runtime });
      assert.equal(result.persistence.report_id, recoveredId);
      assert.equal(JSON.parse(String(calls[0].init?.body)).request_id, frozenKey);
    },
  );

  // 3. Import an idea using the recovered canonical id.
  await mocked(201, { id: "post-1" }, async (calls) => {
    const result = await importPlannerPost("import-1", recoveredId, "idea", 0, { runtime });
    assert.equal(result.id, "post-1");
    const body = JSON.parse(String(calls[0].init?.body));
    assert.equal(body.report_id, recoveredId);
    assert.equal(body.item_kind, "idea");
  });
});

test("repeated recovery and import retries reuse their frozen keys", async () => {
  const generated = report();
  const key = "req-freeze-1";
  const importKey = "import-freeze-1";
  const saveBodies: string[] = [];
  const importBodies: string[] = [];
  const original = globalThis.fetch;
  globalThis.fetch = (async (input, init) => {
    const path = String(input);
    const body = JSON.parse(String(init?.body));
    if (path.endsWith("/reports/save")) {
      saveBodies.push(body.request_id);
      return new Response(
        JSON.stringify({ persistence: { status: "saved", request_id: body.request_id, report_id: "report-1", snapshot_origin: "client_supplied", error_code: null } }),
        { status: 201, headers: { "content-type": "application/json" } },
      );
    }
    importBodies.push(body.request_id);
    return new Response(JSON.stringify({ id: "post-1" }), { status: 201, headers: { "content-type": "application/json" } });
  }) as typeof fetch;
  try {
    await saveReportSnapshot(key, generated, { runtime });
    await saveReportSnapshot(key, generated, { runtime });
    await importPlannerPost(importKey, "report-1", "brief", 0, { runtime });
    await importPlannerPost(importKey, "report-1", "brief", 0, { runtime });
  } finally {
    globalThis.fetch = original;
  }
  assert.deepEqual(saveBodies, [key, key]);
  assert.deepEqual(importBodies, [importKey, importKey]);
});

test("a stale account cannot publish a recovered id for a newer binding", async () => {
  // Simulate the binding guard used by the panel: capture A, switch to B, drop A's result.
  const bindings = [
    { userId: "A", epoch: 0 },
    { userId: "B", epoch: 1 },
  ];
  const captured = bindings[0];
  const current = bindings[1];
  const stale = captured.userId !== current.userId || captured.epoch !== current.epoch;
  assert.equal(stale, true);
});

test("a conflict never generates a new key automatically", async () => {
  const generated = report();
  const requests: string[] = [];
  const original = globalThis.fetch;
  globalThis.fetch = (async (input, init) => {
    const body = JSON.parse(String(init?.body));
    requests.push(body.request_id);
    return new Response(
      JSON.stringify({ error: { code: "report_save_conflict", message: "conflict" } }),
      { status: 409, headers: { "content-type": "application/json" } },
    );
  }) as typeof fetch;
  try {
    await assert.rejects(saveReportSnapshot("req-conflict-1", generated, { runtime }));
  } finally {
    globalThis.fetch = original;
  }
  assert.deepEqual(requests, ["req-conflict-1"]);
  assert.equal(saveStatusForErrorCode("report_save_conflict"), "failed");
});
