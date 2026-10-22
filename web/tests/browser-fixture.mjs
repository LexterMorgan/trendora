import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { writeFile } from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import zlib from "node:zlib";

import { plannerWorkspaceRegressions } from "./planner-workspace.browser.mjs";

const A = "00000000-0000-4000-8000-000000000001";
const B = "00000000-0000-4000-8000-000000000002";
// First-party image hosts the report may load directly. The isolated harness
// answers them locally (never a real network call) so the no-external-request
// guard stays intact for every other origin.
const IMAGE_HOSTS = new Set(["i.ytimg.com", "img.youtube.com", "ytimg.com"]);

// A minimal solid-colour PNG of exact pixel dimensions, so a successful preview
// carries realistic naturalWidth/naturalHeight (a 1x1 PNG would prove nothing
// about resolution). No dependency: IHDR/IDAT/IEND with CRC32.
const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) c = (c & 1) ? (0xedb88320 ^ (c >>> 1)) : (c >>> 1);
    table[n] = c >>> 0;
  }
  return table;
})();
function crc32(buffer) {
  let c = 0xffffffff;
  for (let i = 0; i < buffer.length; i += 1) c = CRC_TABLE[(c ^ buffer[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}
function pngChunk(type, data) {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length, 0);
  const body = Buffer.from(type, "ascii");
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(Buffer.concat([body, data])), 0);
  return Buffer.concat([length, body, data, crc]);
}
const PNG_CACHE = new Map();
function png(width, height) {
  const key = `${width}x${height}`;
  const cached = PNG_CACHE.get(key);
  if (cached) return cached;
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8;  // bit depth
  ihdr[9] = 2;  // colour type: truecolour
  const row = Buffer.alloc(1 + width * 3);
  const raw = Buffer.concat(Array.from({ length: height }, () => row));
  const signature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  const buffer = Buffer.concat([
    signature,
    pngChunk("IHDR", ihdr),
    pngChunk("IDAT", zlib.deflateSync(raw)),
    pngChunk("IEND", Buffer.alloc(0)),
  ]);
  PNG_CACHE.set(key, buffer);
  return buffer;
}
// `null` means the image is unavailable (404); a pair is the served dimensions.
// YouTube's higher-resolution files are not guaranteed, and a missing file
// returns its ~120x90 placeholder rather than an error.
function previewSize(file, mode) {
  const isMaxres = file.includes("maxresdefault");
  const isHq = file.includes("hqdefault");
  if (mode === "broken") return null;
  if (mode === "missing-high") return isMaxres ? null : isHq ? [480, 360] : [320, 180];
  if (mode === "placeholder") return isMaxres ? [120, 90] : isHq ? [480, 360] : [320, 180];
  return isMaxres ? [1280, 720] : isHq ? [480, 360] : [320, 180];
}
const fields = ["title", "platform", "caption", "hook", "creative_brief", "asset_links", "notes", "planned_date", "assignee_id"];
const snapshotFields = ["status", "research", "evidence", "interpretation", "strategy", "ideation"];
const blank = () => ({ title: "", platform: "", caption: "", hook: "", creative_brief: "", asset_links: [], notes: "", planned_date: null, assignee_id: null, status: "idea" });
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function waitFor(predicate) {
  for (let i = 0; i < 500; i++) { if (await predicate()) return; await delay(10); }
  assert(await predicate(), "Expected request or rendered state did not arrive");
}
const user = (id) => ({ id, aud: "authenticated", role: "authenticated", email: id === A ? "a@example.test" : "b@example.test", email_confirmed_at: "2026-10-01T00:00:00Z", app_metadata: { provider: "email", providers: ["email"] }, user_metadata: {}, identities: [], created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z" });
function token(id) {
  return [Buffer.from(JSON.stringify({ alg: "HS256", typ: "JWT" })).toString("base64url"), Buffer.from(JSON.stringify({ sub: id, exp: Math.floor(Date.now() / 1000) + 3600, role: "authenticated" })).toString("base64url"), "fictional-test-signature"].join(".");
}
function actorFrom(request) {
  try {
    const bearer = request.headers.authorization ?? "";
    const { sub } = JSON.parse(Buffer.from(bearer.split(".")[1], "base64url"));
    return [A, B].includes(sub) && bearer.endsWith(".fictional-test-signature") ? sub : null;
  } catch { return null; }
}
function fictionalReport(topic, options = {}) {
  const source = options.publicWeb ? "public_web" : "youtube";
  // Echo the requested markets/sources when the mock was given them, so a
  // saved snapshot reflects the real global request (markets [], both sources).
  const markets = options.requestMarkets ?? ["SG"];
  const sources = options.requestSources ?? [source];
  const ref = { source_code: source, content_external_id: "fictional-1" };
  // A valid synthesis rests on real source text (a title/description fact).
  const citations = [{ kind: "fact", reference: ref, field: "description" }];
  const model_provenance = { provider: "fictional", model: "fixture-only" };
  const report = {
    status: "completed",
    research: {
      status: "completed", query: { topic, markets, market: markets.length === 1 ? markets[0] : null, date_from: options.dateFrom ?? "2026-08-01", date_to: options.dateTo ?? "2026-08-31", sources, result_limit: 20, facebook_page_id: null },
      coverage: { completeness: "complete", sources: sources.map((code) => ({ source_code: code, capability: "keyword_search", status: "available", reason: null })) }, executed_sources: sources,
      references: [{ ...ref, url: "https://example.test/fictional", title: "Fictional source", description: options.oversized ? "a".repeat(8_388_609) : "Fictional evidence", published_at: null, channel_external_id: null, channel_title: null, market_contexts: markets.length ? markets.slice(0, 1) : [], market_context: markets.length === 1 ? markets[0] : null, market_basis: markets.length ? "youtube_region_availability" : null, source_rank: 1, metrics: { view_count: 0, like_count: null, comment_count: null, reaction_count: null, share_count: null }, collected_at: "2026-10-01T00:00:00Z" }],
    },
    evidence: { analyses: [{ reference_id: ref, facts: [{ field: "title", value: "Fictional source" }, { field: "description", value: "Fictional evidence" }, { field: "view_count", value: 0 }], observations: [] }], patterns: [] },
    interpretation: { model_provenance, interpretations: [{ statement: "Fictional interpretation", citations }] },
    strategy: { model_provenance, content_gaps: [{ statement: "Fictional gap", supporting_interpretation_indexes: [0], citations }], opportunities: [{ statement: "Fictional opportunity", gap_indexes: [0], citations }] },
    ideation: { model_provenance, content_ideas: [{ title: "Fictional import idea", angle: "Fictional angle", opportunity_indexes: [0], citations }], content_briefs: [{ idea_index: 0, objective: "Fictional objective", format: "Video", hook: "Fictional hook", outline: ["Fictional step"], citations }] },
    persistence: { status: "failed", request_id: options.missingKey ? null : randomUUID(), report_id: null, snapshot_origin: "server_generated", error_code: "data_unavailable" },
  };
  if (options.researchFirst) {
    const original = report.research.references[0];
    report.research.query.sources = ["youtube", "public_web", "facebook"];
    report.research.executed_sources = ["youtube", "public_web"];
    report.research.coverage = { completeness: "partial", sources: [
      { source_code: "youtube", capability: "keyword_search", status: "available", reason: null },
      { source_code: "public_web", capability: "keyword_search", status: "available", reason: null },
      { source_code: "facebook", capability: "page_search", status: "unavailable", reason: "Fictional Page access unavailable" },
    ] };
    report.research.references = [
      { ...original, title: "Fictional in-window source", published_at: "2026-08-12T12:00:00Z" },
      { ...original, content_external_id: "fictional-2", title: "Fictional outside-window source", url: "https://example.test/outside", published_at: "2026-07-31T12:00:00Z" },
      { ...original, source_code: "public_web", content_external_id: "fictional-3", title: "Fictional undated web source", url: "https://example.test/undated", metrics: { view_count: null, like_count: null, comment_count: null, reaction_count: null, share_count: null } },
    ];
    const ids = report.research.references.map(({ source_code, content_external_id }) => ({ source_code, content_external_id }));
    report.evidence.patterns = [{ observation_type: "title_has_numeral", analyzed_count: 3, matching_count: 1, non_matching_count: 2, ratio: 1 / 3, matching_reference_ids: ids.slice(0, 1), non_matching_reference_ids: ids.slice(1) }];
  }
  if (options.partialSearch) {
    // The source still appears in executed_sources; only its coverage reason
    // says the batch was partial. Warnings must be derived from the reason.
    for (const source of report.research.coverage.sources) {
      if (source.source_code === "public_web") source.reason = "search_partial";
    }
  }
  if (options.manySources) {
    const count = options.manySources;
    const original = report.research.references[0];
    report.research.references = Array.from({ length: count }, (_, i) => ({
      ...original,
      content_external_id: `fictional-${i + 1}`,
      title: `Fictional source ${i + 1}`,
      url: `https://example.test/source-${i + 1}`,
      published_at: "2026-08-12T12:00:00Z",
    }));
    report.research.references[count - 1] = {
      ...report.research.references[count - 1],
      source_code: "public_web",
      title: `Fictional web source ${count}`,
      metrics: { view_count: null, like_count: null, comment_count: null, reaction_count: null, share_count: null },
    };
  }
  if (options.invalidYoutubeId) {
    for (const reference of report.research.references) {
      if (reference.source_code === "youtube") reference.content_external_id = "not-valid-id";
    }
  }
  if (options.socialWeb) {
    const url = "https://www.reddit.com/r/webdev/comments/1/fictional-topic/";
    report.research.query.sources = ["youtube", "public_web"];
    report.research.executed_sources = ["youtube", "public_web"];
    const reference = report.research.references[0];
    report.research.references = [{
      ...reference,
      source_code: "public_web",
      content_external_id: url,
      url,
      title: "Fictional Reddit thread",
      description: "Fictional indexed excerpt",
      channel_title: "www.reddit.com",
      channel_external_id: null,
      published_at: null,
      metrics: { view_count: null, like_count: null, comment_count: null, reaction_count: null, share_count: null },
    }];
  }
  if (options.observationOnly || options.mixedFindings) {
    const ids = report.research.references.map(({ source_code, content_external_id }) => ({ source_code, content_external_id }));
    const observation_type = "title_has_numeral";
    report.evidence.patterns = [{ observation_type, analyzed_count: 3, matching_count: 1, non_matching_count: 2, ratio: 1 / 3, matching_reference_ids: ids.slice(0, 1), non_matching_reference_ids: ids.slice(1) }];
    const observation = { statement: "Fictional sample observation", citations: [{ kind: "pattern", observation_type }] };
    report.interpretation.interpretations = options.observationOnly
      ? [observation]
      : [{ statement: "Fictional sourced finding", citations: [{ kind: "fact", reference: ref, field: "description" }] }, observation];
  }
  if (options.unresolvedFinding) {
    const missing = { source_code: "youtube", content_external_id: "absent-reference" };
    report.interpretation.interpretations = [{ statement: "Fictional unresolved finding", citations: [{ kind: "fact", reference: missing, field: "description" }] }];
  }
  if (options.blankTextFact || options.nullMetricFact || options.metadataOnlyFact) {
    const analysis = report.evidence.analyses[0];
    if (options.blankTextFact) {
      report.interpretation.interpretations = [{ statement: "Fictional blank-text finding", citations: [{ kind: "fact", reference: ref, field: "description" }] }];
      analysis.facts = analysis.facts.map((fact) => fact.field === "description" ? { ...fact, value: null } : fact);
    }
    if (options.nullMetricFact) {
      report.interpretation.interpretations = [{ statement: "Fictional null-metric finding", citations: [{ kind: "fact", reference: ref, field: "view_count" }] }];
      analysis.facts = analysis.facts.map((fact) => fact.field === "view_count" ? { ...fact, value: null } : fact);
    }
    if (options.metadataOnlyFact) {
      report.interpretation.interpretations = [{ statement: "Fictional metadata-only finding", citations: [{ kind: "fact", reference: ref, field: "url" }] }];
      analysis.facts = [...analysis.facts, { field: "url", value: "https://example.test/fictional" }];
    }
  }
  if (options.legacy) {
    delete report.research.query;
    delete report.research.coverage;
    delete report.research.executed_sources;
    for (const reference of report.research.references) {
      for (const field of ["published_at", "collected_at", "metrics", "market_contexts"]) delete reference[field];
    }
    report.evidence = { analyses: null, patterns: null };
    report.interpretation = null;
    report.strategy = null;
  }
  if (options.sourceSummaries || options.researchOnly || options.contentUnavailable || options.insufficient || options.researchUnavailable) {
    report.status = options.contentUnavailable ? "content_unavailable" : options.insufficient ? "insufficient_evidence" : options.researchUnavailable ? "research_unavailable" : "research_completed";
    if (options.insufficient) for (const reference of report.research.references) { reference.title = null; reference.description = null; }
    report.evidence.analyses = report.research.references.map((reference) => ({
      reference_id: { source_code: reference.source_code, content_external_id: reference.content_external_id },
      facts: [{ field: "title", value: reference.title }, { field: "description", value: reference.description }, { field: "view_count", value: reference.metrics.view_count }], observations: [],
    }));
    const fallback = options.interpretationFailure || options.insufficient;
    report.interpretation = options.researchUnavailable ? null : {
      model_provenance: fallback ? { provider: "source_evidence", model: "extractive-v1" } : model_provenance,
      interpretations: options.insufficient ? [] : report.research.references.map((reference) => {
        const text = reference.description.trim();
        let excerpt = text.slice(0, 300);
        if (text.length > 300 && excerpt.includes(" ")) excerpt = excerpt.slice(0, excerpt.lastIndexOf(" "));
        return { statement: fallback ? excerpt : `Fictional sourced synthesis ${reference.content_external_id}: context from collected source material.`, citations: [{ kind: "fact", reference: { source_code: reference.source_code, content_external_id: reference.content_external_id }, field: "description" }] };
      }),
    };
    if (options.researchOnly || options.contentUnavailable || options.insufficient || options.researchUnavailable) {
      report.strategy = null;
      report.ideation = null;
    }
  }
  if (options.noEvidence) {
    report.status = "no_evidence";
    report.research.status = "no_evidence";
    report.research.references = [];
    for (const field of ["evidence", "interpretation", "strategy", "ideation"]) report[field] = null;
  }
  if (options.mixedPlatforms) {
    const original = report.research.references[0];
    report.research.references = [
      { ...original, title: "Fictional video source", url: "https://youtu.be/fictional-video", published_at: "2026-08-12T12:00:00Z" },
      { ...original, source_code: "public_web", content_external_id: "fictional-reddit", title: "Fictional Reddit source", url: "https://www.reddit.com/r/fictional", published_at: null, metrics: { view_count: null, like_count: null, comment_count: null, reaction_count: null, share_count: null } },
      { ...original, source_code: "public_web", content_external_id: "fictional-spoof", title: "Fictional Reddit spoof", url: "https://reddit.com.evil.example/fictional", published_at: "2026-02-30T00:00:00Z", metrics: { view_count: null, like_count: null, comment_count: null, reaction_count: null, share_count: null } },
      { ...original, source_code: "public_web", content_external_id: "fictional-undated", title: "Fictional undated source", url: null, published_at: null, metrics: { view_count: null, like_count: null, comment_count: null, reaction_count: null, share_count: null } },
    ];
  }
  if ("evidenceText" in options) {
    const fact = report.evidence?.analyses?.[0]?.facts.find((entry) => entry.field === "description");
    if (fact) fact.value = options.evidenceText;
  }
  if (options.diagnostics !== false) {
    const retried = options.interpretationFailure === "malformed";
    const bytes = 2048;
    report.run_details = {
      elapsed_ms: 1234,
      stage_durations_ms: { collection: 500, interpretation: retried ? 1200 : 600, persistence: 134 },
      ai_requests: [
        { stage: "interpretation", request_bytes: bytes, elapsed_ms: 590, prompt_tokens: 100, completion_tokens: 0, total_tokens: 100 },
        ...(retried ? [{ stage: "interpretation", request_bytes: bytes + 1, elapsed_ms: 610, prompt_tokens: null, completion_tokens: null, total_tokens: null }] : []),
      ],
      retry_count: retried ? 1 : 0,
      finding_mode: report.interpretation?.model_provenance?.provider === "source_evidence" ? "source_excerpts" : report.interpretation ? "ai_interpretation" : "none",
    };
  }
  return report;
}

// Fictional auth and a shared in-memory backend, adapted from the retained P2B harness.
export async function createMockBackend() {
  const records = new Map(), reports = new Map(), keys = new Map(), origins = new Map(), receiptProofs = new Map(), calls = [], optionalCalls = [], interpretationCalls = [];
  const nonce = randomUUID();
  let frontend, origin, fault = null, held = null, generationOptions = {}, imageMode = "ok";
  const post = (values, actor) => ({ ...blank(), id: randomUUID(), version: 1, content_revision: 1, created_by: actor, updated_by: actor, created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z", archived_at: null, ...values });
  function reply(response, status, body) {
    response.writeHead(status, { "content-type": "application/json", "cache-control": "no-store", "access-control-allow-origin": frontend ?? "null", "access-control-allow-headers": "authorization,apikey,content-type,x-client-info,x-supabase-api-version", "access-control-allow-methods": "GET,POST,PUT,OPTIONS" });
    response.end(JSON.stringify(body));
  }
  const error = (response, status, code) => reply(response, status, { error: { code, message: "Fictional verification rejection" } });
  async function backend(request, response) {
    const url = new URL(request.url, origin), pathname = url.pathname;
    if (request.method === "OPTIONS") return reply(response, 200, {});
    if (pathname === "/__owner") return reply(response, 200, { nonce });
    let raw = ""; for await (const chunk of request) raw += chunk;
    let body; try { body = raw ? JSON.parse(raw) : null; } catch { return error(response, 422, "invalid_request"); }
    if (pathname === "/auth/v1/token") {
      const id = body?.email === "b@example.test" ? B : A;
      return reply(response, 200, { access_token: token(id), refresh_token: `fictional-refresh-${id}`, token_type: "bearer", expires_in: 3600, expires_at: Math.floor(Date.now() / 1000) + 3600, user: user(id) });
    }
    if (pathname === "/auth/v1/user") return reply(response, 200, user(actorFrom(request) ?? A));
    if (pathname === "/auth/v1/logout") return reply(response, 200, {});
    const actor = actorFrom(request), call = { method: request.method, path: pathname, actor, body, completed: false };
    calls.push(call);
    try {
      if (!actor) return error(response, 401, "auth_missing");
      const askMatch = pathname.match(/^\/api\/v1\/research\/reports\/([^/]+)\/ask$/);
      const changesMatch = pathname.match(/^\/api\/v1\/research\/reports\/([^/]+)\/changes$/);
      const action = askMatch ? "ask" : changesMatch ? "changes" : pathname === "/api/v1/research/report" ? "generate" : pathname === "/api/v1/research/reports/save" ? "save" : pathname.startsWith("/api/v1/research/reports/") ? "report" : pathname.endsWith("/import") ? "import" : pathname.endsWith("/origin") ? "origin" : pathname.endsWith("/archive") ? "archive" : pathname.endsWith("/restore") ? "restore" : request.method === "PUT" ? "update" : request.method === "POST" ? "create" : pathname.endsWith("/members") ? "members" : pathname.endsWith("/posts") ? "list" : "get";
      const currentFault = fault?.action === action ? fault : null;
      if (currentFault) {
        fault = null;
        if (currentFault.mode === "reject") return error(response, currentFault.status ?? 422, currentFault.code ?? "invalid_request");
        if (currentFault.mode === "delay-before") await new Promise((resolve) => { held = resolve; });
      }
      async function finish(status, payload) {
        if (currentFault?.mode === "drop-after") return response.destroy();
        if (currentFault?.mode === "delay-after") await new Promise((resolve) => { held = resolve; });
        reply(response, status, payload);
      }
      if (action === "generate") {
        if (!generationOptions.insufficient && !generationOptions.noEvidence) {
          interpretationCalls.push("interpretation");
          if (generationOptions.interpretationFailure === "malformed") interpretationCalls.push("interpretation");
        }
        if (body.include_content_tools === true) optionalCalls.push("strategy", ...(generationOptions.contentUnavailable ? [] : ["ideation"]));
        const report = fictionalReport(body.topic, { ...generationOptions, publicWeb: body.sources?.[0] === "public_web", requestMarkets: body.markets, requestSources: body.sources, sourceSummaries: body.include_content_tools !== undefined, researchOnly: body.include_content_tools === false });
        const receipt = `fictional-opaque.${randomUUID()}`;
        report.persistence.recovery_receipt = receipt;
        receiptProofs.set(receipt, { actor, snapshot: JSON.stringify(Object.fromEntries(snapshotFields.map((field) => [field, report[field]]))) });
        return await finish(200, report);
      }
      if (pathname === "/api/v1/research/reports" && request.method === "GET") {
        const limit = Number(url.searchParams.get("limit") ?? 50), offset = Number(url.searchParams.get("offset") ?? 0);
        const q = (url.searchParams.get("q") ?? "").trim().toLowerCase();
        const status = url.searchParams.get("status");
        const dateFrom = url.searchParams.get("date_from"), dateTo = url.searchParams.get("date_to");
        // Mirrors the backend: filters run across the whole authorized history
        // before counting/pagination, on the stored outcome and requested window.
        const summaries = [...reports.entries()].reverse()
          .filter(([, entry]) => {
            const query = entry.report.research?.query ?? {};
            const topic = (query.topic ?? "").toLowerCase();
            if (q && !topic.includes(q)) return false;
            if (status && entry.report.status !== status) return false;
            if (dateFrom && String(query.date_to ?? "") < dateFrom) return false;
            if (dateTo && String(query.date_from ?? "") > dateTo) return false;
            return true;
          })
          .map(([id, entry]) => ({ id, created_at: "2026-10-01T00:00:00Z", status: entry.report.status, topic: entry.report.research?.query?.topic ?? "Fictional saved report", markets: entry.report.research?.query?.markets ?? ["SG"], source_codes: entry.report.research?.query?.sources ?? ["youtube"] }));
        return reply(response, 200, summaries.slice(offset, offset + limit));
      }
      if (action === "ask") {
        const saved = reports.get(decodeURIComponent(askMatch[1]));
        if (!saved) return error(response, 404, "not_found");
        const source = saved.report.research?.references?.[0];
        return await finish(200, {
          answer: "Fictional answer grounded in the report sources.",
          citations: source ? [{ source_code: source.source_code, content_external_id: source.content_external_id }] : [],
          model_provenance: { provider: "fictional", model: "fixture-only" },
        });
      }
      if (action === "changes") {
        const saved = reports.get(decodeURIComponent(changesMatch[1]));
        if (!saved) return error(response, 404, "not_found");
        if (saved.comparisonStatus) {
          return reply(response, saved.comparisonStatus, {
            error: {
              code: saved.comparisonCode ?? "report_expired",
              message: "The previous report's source data has expired.",
            },
          });
        }
        const normalize = (value) => value.split(/\s+/).filter(Boolean).join(" ").toLowerCase();
        const current = (saved.report.interpretation?.interpretations ?? []).map((item) => item.statement);
        const previous = saved.previousStatements ?? null;
        if (!previous) return await finish(200, {
          previous_report_id: null, previous_created_at: null, new_findings: [], dropped_findings: [],
        });
        const currentKeys = new Set(current.map(normalize));
        const previousKeys = new Set(previous.map(normalize));
        return await finish(200, {
          previous_report_id: "fictional-previous",
          previous_created_at: saved.previousCreatedAt ?? "2026-09-01T00:00:00Z",
          new_findings: current.filter((statement) => !previousKeys.has(normalize(statement))),
          dropped_findings: previous.filter((statement) => !currentKeys.has(normalize(statement))),
        });
      }
      if (action === "report") {
        const saved = reports.get(pathname.split("/").at(-1));
        return saved ? reply(response, 200, saved.report) : error(response, 404, "not_found");
      }
      if (action === "save" || action === "import" || action === "create") {
        const key = `${actor}:${action}:${body.request_id}`, digest = JSON.stringify(body), previous = keys.get(key);
        if (previous && previous.digest !== digest) return error(response, 409, action === "save" ? "report_save_conflict" : "planner_create_conflict");
        if (previous) return await finish(200, previous.payload);
        let payload;
        if (action === "save") {
          const proof = receiptProofs.get(body.recovery_receipt);
          if (!proof || proof.actor !== actor || proof.snapshot !== JSON.stringify(body.snapshot)) return error(response, 422, "invalid_report_snapshot");
          const id = randomUUID();
          const persistence = { status: "saved", request_id: body.request_id, report_id: id, snapshot_origin: "client_supplied", error_code: null };
          reports.set(id, { report: { ...body.snapshot, persistence }, outOfHistory: false });
          payload = { persistence };
        } else if (action === "import") {
          const source = reports.get(body.report_id);
          if (!source || source.outOfHistory) return error(response, 404, "planner_report_not_found");
          assert.deepEqual(Object.keys(body).sort(), ["item_index", "item_kind", "report_id", "request_id"]);
          const item = body.item_kind === "idea" ? source.report.ideation.content_ideas[body.item_index] : source.report.ideation.content_briefs[body.item_index];
          const created = post({ title: item.title ?? "Fictional imported brief", hook: item.hook ?? "", creative_brief: item.angle ?? item.objective }, actor);
          records.set(created.id, created);
          origins.set(created.id, { report_id: body.report_id, item_kind: body.item_kind, item_index: body.item_index, parent_idea_index: item.idea_index ?? null, provenance: source.report.persistence.snapshot_origin, context: { title: created.title }, sources: [] });
          payload = { id: created.id };
        } else {
          assert.deepEqual(Object.keys(body).sort(), [...fields, "request_id"].sort());
          const created = post(Object.fromEntries(fields.map((key) => [key, body[key]])), actor);
          records.set(created.id, created); payload = { id: created.id };
        }
        keys.set(key, { digest, payload }); return await finish(201, payload);
      }
      if (action === "members") return reply(response, 200, [A, B].map((id) => ({ user_id: id, email: user(id).email })));
      if (action === "list") return reply(response, 200, [...records.values()].filter((p) => Boolean(p.archived_at) === (url.searchParams.get("archived") === "true")).slice(Number(url.searchParams.get("offset") ?? 0), Number(url.searchParams.get("offset") ?? 0) + Number(url.searchParams.get("limit") ?? 25)));
      const id = pathname.split("/")[5], current = records.get(id);
      if (action === "origin") return origins.has(id) ? reply(response, 200, origins.get(id)) : error(response, 404, "planner_origin_not_found");
      if (!current) return error(response, 404, "planner_post_not_found");
      if (action === "get") return await finish(200, current);
      assert.deepEqual(Object.keys(body).sort(), (action === "update" ? [...fields, "status", "expected_version"] : ["expected_version"]).sort());
      if (body.expected_version !== current.version) return error(response, 409, "planner_version_conflict");
      const changed = action === "update" ? { ...current, ...Object.fromEntries([...fields, "status"].map((key) => [key, body[key]])) } : { ...current, archived_at: action === "archive" ? "2026-10-02T00:00:00Z" : null };
      changed.version++; changed.updated_by = actor; changed.updated_at = new Date().toISOString();
      if (action === "update" && fields.some((key) => JSON.stringify(changed[key]) !== JSON.stringify(current[key]))) changed.content_revision++;
      records.set(id, changed); return await finish(200, changed);
    } finally { call.completed = true; }
  }
  const server = http.createServer((request, response) => backend(request, response).catch((err) => { calls.push({ mockError: String(err.stack) }); if (!response.headersSent) error(response, 500, "mock_error"); else response.destroy(); }));
  await new Promise((resolve, reject) => { server.once("error", reject); server.listen(0, "127.0.0.1", resolve); });
  origin = `http://127.0.0.1:${server.address().port}`;
  return {
    origin, nonce, calls, optionalCalls, interpretationCalls, records, reports, setFrontend(value) { frontend = value; },
    reset() { assert.equal(held, null); records.clear(); reports.clear(); keys.clear(); origins.clear(); receiptProofs.clear(); calls.length = 0; optionalCalls.length = 0; interpretationCalls.length = 0; fault = null; generationOptions = {}; imageMode = "ok"; },
    fault(value) { assert.equal(fault, null); fault = value; },
    setImageMode(value) { imageMode = value; },
    imageMode() { return imageMode; },
    stalled: () => waitFor(() => typeof held === "function"),
    async release() { assert.equal(typeof held, "function"); held(); held = null; await waitFor(() => calls.every((call) => call.completed !== false)); },
    generationOptions(value) { generationOptions = value; },
    seedSavedReport(options = {}) {
      const id = randomUUID(), report = fictionalReport(options.topic ?? "Fictional saved report", options);
      // Saved snapshots keep only the six immutable fields; diagnostics are
      // fresh-response metadata and are not reconstructed on read.
      delete report.run_details;
      report.persistence = { status: "saved", request_id: null, report_id: id, snapshot_origin: "server_generated", error_code: null };
      reports.set(id, {
        report,
        outOfHistory: options.outOfHistory ?? false,
        previousStatements: options.previousStatements ?? null,
        previousCreatedAt: options.previousCreatedAt ?? null,
        comparisonStatus: options.comparisonStatus ?? null,
        comparisonCode: options.comparisonCode ?? null,
      }); return id;
    },
    seedSavedReports(optionsList) {
      return optionsList.map((options) => this.seedSavedReport(options));
    },
    async close() { if (held) { held(); held = null; } server.closeAllConnections(); await new Promise((resolve) => server.close(resolve)); },
  };
}

export async function runBrowserScenarios({ chromium, origin, mock, root, env, executablePath, registerBrowserCleanup }) {
  const results = [], diagnostics = [], blocked = [], images = [];
  const output = (name, value) => writeFile(path.join(root, name), JSON.stringify(value, null, 2));
  mock.setFrontend(origin);
  const browser = await chromium.launch({ headless: true, executablePath, downloadsPath: path.join(root, "runtime"), tracesDir: path.join(root, "runtime"), env, args: ["--disable-gpu", "--disable-background-networking", "--disable-component-update", "--disable-sync", "--disable-domain-reliability", "--no-first-run", "--metrics-recording-only", "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"] });
  registerBrowserCleanup(() => browser.close());
  const names = plannerWorkspaceRegressions({}).map(([name]) => name);
  try {
    for (let index = 0; index < names.length; index++) {
      mock.reset();
      const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: index === 9 ? 2 : 1, serviceWorkers: "block" });
      await context.route("**/*", (route) => {
        const url = new URL(route.request().url());
        if ([origin, mock.origin].includes(url.origin)) return route.continue();
        if (IMAGE_HOSTS.has(url.hostname)) {
          // Answered locally; never a real network call. The image mode decides
          // which candidate resolutions are available so fallback is exercised.
          const file = url.pathname.split("/").pop();
          images.push({ index, url: url.origin + url.pathname, file });
          const size = previewSize(file, mock.imageMode());
          if (!size) return route.fulfill({ status: 404, contentType: "image/png", body: Buffer.alloc(0) });
          return route.fulfill({ status: 200, contentType: "image/png", body: png(size[0], size[1]) });
        }
        blocked.push({ index, url: url.origin + url.pathname }); return route.abort("blockedbyclient");
      });
      const page = await context.newPage(); page.setDefaultTimeout(5000);
      page.on("pageerror", (err) => diagnostics.push({ index, type: "pageerror", message: err.message }));
      page.on("console", (message) => { if (message.type() === "error") diagnostics.push({ index, type: "console", message: message.text() }); });
      page.on("dialog", (dialog) => dialog.accept());
      const snapshot = async (name, { fullPage = true } = {}) => {
        await page.evaluate(() => document.fonts.ready.then(() => {}));
        return page.screenshot({ path: path.join(root, `${index + 1}-${name}.png`), fullPage, scale: "css", animations: "disabled" });
      };
      let selectedReport = null;
      const fixture = {
        page, origin, A, B, calls: mock.calls, optionalCalls: mock.optionalCalls, interpretationCalls: mock.interpretationCalls, records: mock.records, reports: mock.reports, waitFor, snapshot,
        newPost: async () => { await page.goto(origin + "/planner/new"); await page.getByLabel("Title", { exact: true }).waitFor(); },
        openResearch: async () => { await page.goto(origin + (selectedReport ? `/report/${selectedReport}` : "/")); await (selectedReport ? page.locator(".report") : page.getByRole("button", { name: "Generate research report", exact: true })).waitFor(); },
        submitResearch: async (topic, options = {}) => { mock.generationOptions(options); await page.getByLabel("Topic", { exact: true }).fill(topic); await page.getByRole("checkbox", { name: "Generate content ideas and briefs", exact: true }).setChecked(!options.researchOnly); await page.getByRole("button", { name: "Generate research report", exact: true }).click(); await page.locator(".report").waitFor(); },
        seedSavedReport: async (options) => { selectedReport = mock.seedSavedReport(options); return selectedReport; },
        seedSavedReports: (optionsList) => mock.seedSavedReports(optionsList),
        fault: (value) => mock.fault(value), stalled: () => mock.stalled(), release: () => mock.release(),
        setImageMode: (value) => mock.setImageMode(value),
        images,
        async switchAccount(id) {
          const previousWorkspace = await page.locator("main.workspace").elementHandle();
          assert(previousWorkspace, "Authenticated workspace must be mounted before switching");
          const tab = await context.newPage(); await tab.goto(origin + "/");
          await tab.evaluate(async ({ mockOrigin, id }) => {
            const payload = await (await fetch(mockOrigin + "/auth/v1/token?grant_type=password", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ email: id.endsWith("2") ? "b@example.test" : "a@example.test", password: "fictional" }) })).json();
            const key = Object.keys(localStorage).find((key) => key.startsWith("sb-") && key.endsWith("-auth-token"));
            if (!key) throw Error("No fictional SDK session to switch");
            localStorage.setItem(key, JSON.stringify(payload));
            const channel = new BroadcastChannel(key); channel.postMessage({ event: "SIGNED_IN", session: payload }); channel.close();
          }, { mockOrigin: mock.origin, id });
          await waitFor(() => previousWorkspace.evaluate((element) => !element.isConnected));
          await previousWorkspace.dispose();
          await tab.close();
        },
        async randomness(mode) {
          const change = (mode) => {
            window.testCryptoOriginal ??= { randomUUID: crypto.randomUUID, getRandomValues: crypto.getRandomValues };
            Object.defineProperty(crypto, "randomUUID", { configurable: true, value: mode === "normal" ? window.testCryptoOriginal.randomUUID : undefined });
            Object.defineProperty(crypto, "getRandomValues", { configurable: true, value: mode === "none" ? undefined : window.testCryptoOriginal.getRandomValues });
          };
          await page.addInitScript(change, mode); await page.evaluate(change, mode);
        },
        async metrics(label) {
          const data = await page.evaluate(() => ({ viewport: innerWidth, scrollWidth: document.documentElement.scrollWidth, bodyWidth: document.body.scrollWidth, controls: [...document.querySelectorAll("a,button,input,textarea,select,summary")].filter((e) => e.getClientRects().length).map((e) => { const r = e.getBoundingClientRect(); return { id: e.id, text: e.innerText, width: r.width, height: r.height, left: r.left, right: r.right }; }) }));
          await output(`${index + 1}-${label}-metrics.json`, data);
          assert(data.scrollWidth <= data.viewport + 1); assert(data.bodyWidth <= data.viewport + 1);
          assert(!data.controls.some((c) => c.left < -1 || c.right > data.viewport + 1), "Clipped control"); return data;
        },
      };
      try {
        await page.goto(origin + "/login"); await page.getByLabel("Email", { exact: true }).fill("a@example.test"); await page.getByLabel("Password", { exact: true }).fill("fictional-only-password");
        await page.getByRole("button", { name: "Sign in", exact: true }).click(); await page.waitForURL(origin + "/");
        await plannerWorkspaceRegressions(fixture)[index][1]();
        assert(!diagnostics.some((e) => e.index === index && e.type === "pageerror"), "Uncaught browser error");
        assert(!mock.calls.some((c) => c.mockError), "Mock backend assertion failed");
        assert(!blocked.some((c) => c.index === index), "Unexpected external service request");
        results.push({ name: names[index], status: "passed" }); console.log("PASS " + names[index]);
      } catch (err) {
        results.push({ name: names[index], status: "failed", error: String(err.stack ?? err) }); console.error("FAIL " + names[index] + ": " + err.message); await snapshot("failure").catch(() => {});
      } finally {
        await context.close();
        await mock.release().catch(() => {});
        await output(`${index + 1}-mock-requests.json`, mock.calls);
        await output("browser-results.json", results);
      }
    }
  } finally { await browser.close(); await output("browser-diagnostics.json", diagnostics); await output("blocked-requests.json", blocked); await output("image-requests.json", images); }
  return { passed: results.filter((r) => r.status === "passed").length, failed: results.filter((r) => r.status === "failed").length, skipped: names.length - results.length, total: names.length };
}
