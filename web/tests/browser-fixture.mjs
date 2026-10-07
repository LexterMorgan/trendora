import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { writeFile } from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import { plannerWorkspaceRegressions } from "./planner-workspace.browser.mjs";

const A = "00000000-0000-4000-8000-000000000001";
const B = "00000000-0000-4000-8000-000000000002";
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
  const ref = { source_code: "youtube", content_external_id: "fictional-1" };
  const citations = [{ kind: "fact", reference: ref, field: "view_count" }];
  const model_provenance = { provider: "fictional", model: "fixture-only" };
  const report = {
    status: "completed",
    research: {
      status: "completed", query: { topic, markets: ["SG"], market: "SG", date_from: "2026-08-01", date_to: "2026-08-31", sources: ["youtube"], result_limit: 20, facebook_page_id: null },
      coverage: { completeness: "complete", sources: [{ source_code: "youtube", capability: "keyword_search", status: "available", reason: null }] }, executed_sources: ["youtube"],
      references: [{ ...ref, url: "https://example.test/fictional", title: "Fictional source", description: options.oversized ? "a".repeat(8_388_609) : "Fictional evidence", published_at: null, channel_external_id: null, channel_title: null, market_contexts: ["SG"], market_context: "SG", market_basis: "youtube_region_availability", source_rank: 1, metrics: { view_count: 0, like_count: null, comment_count: null, reaction_count: null, share_count: null }, collected_at: "2026-10-01T00:00:00Z" }],
    },
    evidence: { analyses: [{ reference_id: ref, facts: [{ field: "view_count", value: 0 }], observations: [] }], patterns: [] },
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
  return report;
}

// Fictional auth and a shared in-memory backend, adapted from the retained P2B harness.
export async function createMockBackend() {
  const records = new Map(), reports = new Map(), keys = new Map(), origins = new Map(), receiptProofs = new Map(), calls = [], optionalCalls = [], interpretationCalls = [];
  const nonce = randomUUID();
  let frontend, origin, fault = null, held = null, generationOptions = {};
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
      const action = pathname === "/api/v1/research/report" ? "generate" : pathname === "/api/v1/research/reports/save" ? "save" : pathname.startsWith("/api/v1/research/reports/") ? "report" : pathname.endsWith("/import") ? "import" : pathname.endsWith("/origin") ? "origin" : pathname.endsWith("/archive") ? "archive" : pathname.endsWith("/restore") ? "restore" : request.method === "PUT" ? "update" : request.method === "POST" ? "create" : pathname.endsWith("/members") ? "members" : pathname.endsWith("/posts") ? "list" : "get";
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
        const report = fictionalReport(body.topic, { ...generationOptions, sourceSummaries: body.include_content_tools !== undefined, researchOnly: body.include_content_tools === false });
        const receipt = `fictional-opaque.${randomUUID()}`;
        report.persistence.recovery_receipt = receipt;
        receiptProofs.set(receipt, { actor, snapshot: JSON.stringify(Object.fromEntries(snapshotFields.map((field) => [field, report[field]]))) });
        return await finish(200, report);
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
    reset() { assert.equal(held, null); records.clear(); reports.clear(); keys.clear(); origins.clear(); receiptProofs.clear(); calls.length = 0; optionalCalls.length = 0; interpretationCalls.length = 0; fault = null; generationOptions = {}; },
    fault(value) { assert.equal(fault, null); fault = value; },
    stalled: () => waitFor(() => typeof held === "function"),
    async release() { assert.equal(typeof held, "function"); held(); held = null; await waitFor(() => calls.every((call) => call.completed !== false)); },
    generationOptions(value) { generationOptions = value; },
    seedSavedReport(options = {}) {
      const id = randomUUID(), report = fictionalReport(options.topic ?? "Fictional saved report", options);
      report.persistence = { status: "saved", request_id: null, report_id: id, snapshot_origin: "server_generated", error_code: null };
      reports.set(id, { report, outOfHistory: options.outOfHistory ?? false }); return id;
    },
    async close() { if (held) { held(); held = null; } server.closeAllConnections(); await new Promise((resolve) => server.close(resolve)); },
  };
}

export async function runBrowserScenarios({ chromium, origin, mock, root, env, executablePath, registerBrowserCleanup }) {
  const results = [], diagnostics = [], blocked = [];
  const output = (name, value) => writeFile(path.join(root, name), JSON.stringify(value, null, 2));
  mock.setFrontend(origin);
  const browser = await chromium.launch({ headless: true, executablePath, downloadsPath: path.join(root, "runtime"), tracesDir: path.join(root, "runtime"), env, args: ["--disable-background-networking", "--disable-component-update", "--disable-sync", "--disable-domain-reliability", "--no-first-run", "--metrics-recording-only", "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"] });
  registerBrowserCleanup(() => browser.close());
  const names = plannerWorkspaceRegressions({}).map(([name]) => name);
  try {
    for (let index = 0; index < names.length; index++) {
      mock.reset();
      const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: index === 9 ? 2 : 1, serviceWorkers: "block" });
      await context.route("**/*", (route) => {
        const url = new URL(route.request().url());
        if ([origin, mock.origin].includes(url.origin)) return route.continue();
        blocked.push({ index, url: url.origin + url.pathname }); return route.abort("blockedbyclient");
      });
      const page = await context.newPage(); page.setDefaultTimeout(5000);
      page.on("pageerror", (err) => diagnostics.push({ index, type: "pageerror", message: err.message }));
      page.on("console", (message) => { if (message.type() === "error") diagnostics.push({ index, type: "console", message: message.text() }); });
      page.on("dialog", (dialog) => dialog.accept());
      const snapshot = (name) => page.screenshot({ path: path.join(root, `${index + 1}-${name}.png`), fullPage: true });
      let selectedReport = null;
      const fixture = {
        page, origin, A, B, calls: mock.calls, optionalCalls: mock.optionalCalls, interpretationCalls: mock.interpretationCalls, records: mock.records, reports: mock.reports, waitFor, snapshot,
        newPost: async () => { await page.goto(origin + "/planner/new"); await page.getByLabel("Title", { exact: true }).waitFor(); },
        openResearch: async () => { await page.goto(origin + (selectedReport ? `/report/${selectedReport}` : "/")); await (selectedReport ? page.locator(".report") : page.getByRole("button", { name: "Generate research report", exact: true })).waitFor(); },
        submitResearch: async (topic, options = {}) => { mock.generationOptions(options); await page.getByLabel("Topic", { exact: true }).fill(topic); await page.getByRole("checkbox", { name: "Include content ideas and briefs", exact: true }).setChecked(!options.researchOnly); await page.getByRole("button", { name: "Generate research report", exact: true }).click(); await page.locator(".report").waitFor(); },
        seedSavedReport: async (options) => { selectedReport = mock.seedSavedReport(options); return selectedReport; },
        fault: (value) => mock.fault(value), stalled: () => mock.stalled(), release: () => mock.release(),
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
  } finally { await browser.close(); await output("browser-diagnostics.json", diagnostics); await output("blocked-requests.json", blocked); }
  return { passed: results.filter((r) => r.status === "passed").length, failed: results.filter((r) => r.status === "failed").length, skipped: names.length - results.length, total: names.length };
}
