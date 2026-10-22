import test from "node:test";
import assert from "node:assert/strict";
import { POST } from "../app/api/reports/[id]/ask/route.ts";

const context = { params: Promise.resolve({ id: "report/1" }) };
const question = JSON.stringify({ question: "What does this source say?" });
function request(body = question, signal?: AbortSignal) {
  return new Request("http://frontend.test/api/reports/report/ask", {
    method: "POST", body, signal,
    headers: { authorization: "Bearer fictional", cookie: "session=never-forward" },
  });
}

test("Ask proxy bounds requests and the whole upstream exchange, forwards auth only", async () => {
  const originalFetch = globalThis.fetch;
  const originalBase = process.env.TRENDORA_API_BASE_URL;
  const originalTimeout = AbortSignal.timeout;
  let deadline = new AbortController();
  let calls = 0;
  process.env.TRENDORA_API_BASE_URL = "http://backend.test/";
  AbortSignal.timeout = (ms) => { assert.equal(ms, 180_000); return deadline.signal; };
  try {
    globalThis.fetch = async (url, init) => {
      calls++;
      assert.equal(url, "http://backend.test/api/v1/research/reports/report%2F1/ask");
      assert.equal(new TextDecoder().decode(init!.body as ArrayBuffer), question);
      assert.equal(new Headers(init!.headers).get("authorization"), "Bearer fictional");
      assert.equal(new Headers(init!.headers).get("cookie"), null);
      assert.equal(init!.redirect, "error");
      assert.equal(init!.cache, "no-store");
      assert.ok(init!.signal);
      return Response.json({ error: { code: "report_expired" } }, { status: 410 });
    };
    const response = await POST(request(), context);
    assert.equal(response.status, 410);
    assert.equal(response.headers.get("cache-control"), "private, no-store");
    assert.equal((await response.json()).error.code, "report_expired");
    assert.equal((await POST(request("x".repeat(65_537)), context)).status, 413);
    assert.equal((await POST(request("not JSON"), context)).status, 422);
    assert.equal(calls, 1);

    // Headers arrive, but the response body is still in flight when time expires.
    globalThis.fetch = async (_url, init) => new Response(new ReadableStream({
      start(controller) {
        init!.signal!.addEventListener("abort", () => controller.error(new Error("private upstream detail")));
        queueMicrotask(() => deadline.abort());
      },
    }));
    const timedOut = await POST(request(), context);
    assert.equal(timedOut.status, 504);
    assert.equal((await timedOut.json()).error.code, "ask_timeout");

    deadline = new AbortController();
    globalThis.fetch = async () => { throw new Error("private upstream detail"); };
    const failed = await POST(request(), context);
    assert.equal(failed.status, 502);
    assert.doesNotMatch(await failed.text(), /private upstream detail/);

    const cancelled = new AbortController();
    cancelled.abort();
    globalThis.fetch = async () => { assert.fail("cancelled request must not be sent"); };
    assert.equal((await POST(request(question, cancelled.signal), context)).status, 502);
  } finally {
    globalThis.fetch = originalFetch;
    AbortSignal.timeout = originalTimeout;
    if (originalBase === undefined) delete process.env.TRENDORA_API_BASE_URL;
    else process.env.TRENDORA_API_BASE_URL = originalBase;
  }
});
