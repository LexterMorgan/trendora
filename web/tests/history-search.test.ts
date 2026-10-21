import test from "node:test";
import assert from "node:assert/strict";

// Keep the real API client offline even when public auth variables are exported.
process.env.NEXT_PUBLIC_SUPABASE_URL = "";
process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = "";
const { listReports } = await import("../lib/trendora-api.ts");

test("history client sends literal topic, stored outcome, window bounds and pagination", async (t) => {
  let requested = "";
  let init: RequestInit | undefined;
  t.mock.method(globalThis, "fetch", async (input: RequestInfo | URL, options?: RequestInit) => {
    requested = String(input);
    init = options;
    return Response.json([]);
  });
  const controller = new AbortController();
  const params = {
    q: "  100%_climate & education/\\  ",
    status: "research_completed",
    date_from: "2026-08-01",
    date_to: "2026-08-31",
    offset: 50,
    limit: 51,
  };
  assert.deepEqual(await listReports(params, { signal: controller.signal }), []);
  const url = new URL(requested, "http://offline.test");
  assert.equal(url.pathname, "/api/reports");
  assert.deepEqual(Object.fromEntries(url.searchParams), {
    limit: "51", offset: "50", q: params.q.trim(), status: params.status,
    date_from: params.date_from, date_to: params.date_to,
  });
  assert.equal(init?.signal, controller.signal);
  assert.equal(init?.cache, "no-store");
});

test("empty filters are omitted while zero offset and one-sided dates survive", async (t) => {
  const requested: string[] = [];
  t.mock.method(globalThis, "fetch", async (input: RequestInfo | URL) => {
    requested.push(String(input));
    return Response.json([]);
  });
  await listReports({ q: "   ", status: "", date_from: "", date_to: "", offset: 0 });
  await listReports({ date_from: "2026-08-01" });
  await listReports({ date_to: "2026-08-31" });
  await listReports();
  assert.deepEqual(requested, [
    "/api/reports?offset=0",
    "/api/reports?date_from=2026-08-01",
    "/api/reports?date_to=2026-08-31",
    "/api/reports",
  ]);
});

test("superseded history requests can abort without cancelling the next search", async (t) => {
  let calls = 0;
  let started!: () => void;
  const dispatched = new Promise<void>((resolve) => { started = resolve; });
  t.mock.method(globalThis, "fetch", (_input: RequestInfo | URL, init?: RequestInit) => {
    if (calls++ > 0) return Promise.resolve(Response.json([]));
    started();
    return new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
    });
  });
  const controller = new AbortController();
  const first = listReports({ q: "old" }, { signal: controller.signal });
  const rejected = assert.rejects(first, { name: "AbortError" });
  await dispatched;
  controller.abort();
  await rejected;
  assert.deepEqual(await listReports({ q: "new" }), []);
});
