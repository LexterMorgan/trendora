import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import * as nodeModule from "node:module";

// The proxy routes import "next/server". `next` ships no package "exports"
// map, so ESM cannot resolve that extensionless subpath even though CJS
// require can. Redirect the specifier (and load NextRequest the CJS way)
// before the dynamic route imports below. `registerHooks` exists on Node
// >= 23.5 but is not yet in @types/node@20, hence the local typing.
interface ModuleInternals {
  registerHooks(hooks: {
    resolve(
      specifier: string,
      context: unknown,
      nextResolve: (
        specifier: string,
        context?: unknown,
      ) => { url: string },
    ): { url: string };
  }): void;
}

(nodeModule as unknown as ModuleInternals).registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier === "next/server") {
      return nextResolve("next/server.js", context);
    }
    return nextResolve(specifier, context);
  },
});

const require = createRequire(import.meta.url);
const { NextRequest } = require("next/server") as typeof import("next/server");

// Import one route while the backend env var is absent (module scope reads it).
const noConfigRoute = await import("../app/api/reports/route.ts");

process.env.TRENDORA_API_BASE_URL = "http://backend.test";

const researchRoute = await import("../app/api/research/route.ts");
const reportRoute = await import("../app/api/report/route.ts");
const reportsPath = "../app/api/reports/route.ts?withconfig";
const reportsRoute = (await import(reportsPath)) as typeof noConfigRoute;
const reportByIdRoute = await import("../app/api/reports/[id]/route.ts");

interface UpstreamCall {
  input: string;
  init?: RequestInit;
}

function stubFetch(
  handler: (input: string, init?: RequestInit) => Response,
): { calls: UpstreamCall[]; restore: () => void } {
  const original = globalThis.fetch;
  const calls: UpstreamCall[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ input: url, init });
    return handler(url, init);
  }) as typeof fetch;
  return {
    calls,
    restore: () => {
      globalThis.fetch = original;
    },
  };
}

const upstreamOk = () =>
  new Response(JSON.stringify({ references: [] }), {
    status: 200,
    headers: { "content-type": "application/json" },
  });

test("missing backend config returns a 500 envelope", async () => {
  delete process.env.TRENDORA_API_BASE_URL;
  try {
    const res = await noConfigRoute.GET(
      new NextRequest("http://localhost:3000/api/reports"),
    );
    assert.equal(res.status, 500);
    const body = (await res.json()) as { error?: { code?: string } };
    assert.equal(body.error?.code, "backend_not_configured");
  } finally {
    process.env.TRENDORA_API_BASE_URL = "http://backend.test";
  }
});

test("research POST forwards the bearer token and private response headers", async () => {
  const stub = stubFetch(upstreamOk);
  try {
    const request = new NextRequest("http://localhost:3000/api/research", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: "Bearer browser-token",
      },
      body: JSON.stringify({ topic: "skincare" }),
    });
    const res = await researchRoute.POST(request);

    assert.equal(stub.calls.length, 1);
    assert.equal(stub.calls[0].input, "http://backend.test/api/v1/research");
    const headers = stub.calls[0].init?.headers as Record<string, string>;
    assert.equal(headers.authorization, "Bearer browser-token");
    assert.equal(headers["content-type"], "application/json");
    assert.equal(stub.calls[0].init?.cache, "no-store");

    assert.equal(res.status, 200);
    assert.equal(res.headers.get("cache-control"), "private, no-store");
    assert.deepEqual(await res.json(), { references: [] });
  } finally {
    stub.restore();
  }
});

test("research POST omits authorization when the browser sent none", async () => {
  const stub = stubFetch(upstreamOk);
  try {
    const request = new NextRequest("http://localhost:3000/api/research", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ topic: "skincare" }),
    });
    await researchRoute.POST(request);
    const headers = stub.calls[0].init?.headers as Record<string, string>;
    assert.equal(headers.authorization, undefined);
  } finally {
    stub.restore();
  }
});

test("research POST passes backend status and envelope through", async () => {
  const stub = stubFetch(
    () =>
      new Response(
        JSON.stringify({
          error: { code: "auth_not_member", message: "no membership" },
        }),
        { status: 403, headers: { "content-type": "application/json" } },
      ),
  );
  try {
    const request = new NextRequest("http://localhost:3000/api/research", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: "Bearer browser-token",
      },
      body: JSON.stringify({ topic: "skincare" }),
    });
    const res = await researchRoute.POST(request);
    assert.equal(res.status, 403);
    const body = (await res.json()) as { error?: { code?: string } };
    assert.equal(body.error?.code, "auth_not_member");
  } finally {
    stub.restore();
  }
});

test("report POST forwards the bearer token to the report endpoint", async () => {
  const stub = stubFetch(upstreamOk);
  try {
    const request = new NextRequest("http://localhost:3000/api/report", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: "Bearer browser-token",
      },
      body: JSON.stringify({ topic: "skincare" }),
    });
    const res = await reportRoute.POST(request);
    assert.equal(stub.calls[0].input, "http://backend.test/api/v1/research/report");
    const headers = stub.calls[0].init?.headers as Record<string, string>;
    assert.equal(headers.authorization, "Bearer browser-token");
    assert.equal(new TextDecoder().decode(stub.calls[0].init?.body as ArrayBuffer), JSON.stringify({ topic: "skincare" }));
    assert.equal(stub.calls[0].init?.redirect, "error");
    assert.equal(res.status, 200);
    assert.equal(res.headers.get("cache-control"), "private, no-store");
  } finally {
    stub.restore();
  }
});

test("report POST accepts exactly 64 KiB of UTF-8 bytes despite Content-Length", async () => {
  const body = `"${"é".repeat(32_767)}"`;
  assert.equal(new TextEncoder().encode(body).byteLength, 65_536);
  const stub = stubFetch(upstreamOk);
  try {
    const request = new NextRequest("http://localhost:3000/api/report", {
      method: "POST", body, headers: { "content-length": "999999" },
    });
    assert.equal((await reportRoute.POST(request)).status, 200);
    assert.equal(new TextDecoder().decode(stub.calls[0].init?.body as ArrayBuffer), body);
  } finally { stub.restore(); }
});

test("report POST stops oversized streamed bytes before fetch", async () => {
  let pulls = 0;
  let cancelled = false;
  const stream = new ReadableStream<Uint8Array>({
    pull(controller) {
      pulls += 1;
      controller.enqueue(new Uint8Array(pulls <= 2 ? 32_768 : 1));
    },
    cancel() { cancelled = true; },
  }, { highWaterMark: 0 });
  const init: NonNullable<ConstructorParameters<typeof NextRequest>[1]> & { duplex: "half" } = {
    method: "POST", body: stream, duplex: "half", headers: { "content-length": "1" },
  };
  const stub = stubFetch(upstreamOk);
  try {
    const response = await reportRoute.POST(new NextRequest("http://localhost:3000/api/report", init));
    assert.equal(response.status, 413);
    assert.equal((await response.json()).error.code, "report_request_too_large");
    assert.equal(response.headers.get("cache-control"), "private, no-store");
    assert.equal(pulls, 3);
    assert.equal(cancelled, true);
    assert.equal(stub.calls.length, 0);
  } finally { stub.restore(); }
});

test("report POST rejects malformed JSON and invalid UTF-8 before fetch", async () => {
  const stub = stubFetch(upstreamOk);
  try {
    for (const body of ["{incomplete", new Uint8Array([0xff])]) {
      const response = await reportRoute.POST(new NextRequest("http://localhost:3000/api/report", { method: "POST", body }));
      assert.equal(response.status, 422);
      assert.equal((await response.json()).error.code, "invalid_request");
      assert.equal(response.headers.get("cache-control"), "private, no-store");
    }
    assert.equal(stub.calls.length, 0);
  } finally { stub.restore(); }
});

test("report POST does not forward an already cancelled request", async () => {
  const controller = new AbortController();
  controller.abort();
  const stub = stubFetch(upstreamOk);
  try {
    const response = await reportRoute.POST(new NextRequest("http://localhost:3000/api/report", {
      method: "POST", body: "{}", signal: controller.signal,
    }));
    assert.equal(response.status, 502);
    assert.equal(stub.calls.length, 0);
  } finally { stub.restore(); }
});

for (const timedOut of [false, true]) {
  test(`report POST ${timedOut ? "deadline" : "client cancellation"} covers response-body consumption`, async (context) => {
    const controller = new AbortController();
    if (timedOut) {
      context.mock.method(AbortSignal, "timeout", (duration: number) => {
        assert.equal(duration, 180_000);
        return controller.signal;
      });
    }
    const stub = stubFetch((_url, init) => new Response(new ReadableStream({
      start(stream) {
        const signal = init?.signal;
        assert.ok(signal);
        signal.addEventListener("abort", () => stream.error(signal.reason), { once: true });
        queueMicrotask(() => controller.abort(new DOMException("fictional upstream detail", timedOut ? "TimeoutError" : "AbortError")));
      },
    })));
    try {
      const request = new NextRequest("http://localhost:3000/api/report", {
        method: "POST", body: "{}", ...(timedOut ? {} : { signal: controller.signal }),
      });
      const response = await reportRoute.POST(request);
      assert.equal(response.status, timedOut ? 504 : 502);
      assert.equal((await response.json()).error.code, timedOut ? "report_timeout" : "backend_unreachable");
      assert.equal(response.headers.get("cache-control"), "private, no-store");
      assert.equal(stub.calls[0].init?.signal?.aborted, true);
    } finally { stub.restore(); }
  });
}

test("reports GET forwards query string and bearer token", async () => {
  const stub = stubFetch(upstreamOk);
  try {
    const request = new NextRequest(
      "http://localhost:3000/api/reports?limit=51&offset=0",
      { headers: { authorization: "Bearer browser-token" } },
    );
    const res = await reportsRoute.GET(request);
    assert.equal(
      stub.calls[0].input,
      "http://backend.test/api/v1/research/reports?limit=51&offset=0",
    );
    const headers = stub.calls[0].init?.headers as Record<string, string>;
    assert.equal(headers.authorization, "Bearer browser-token");
    assert.equal(res.headers.get("cache-control"), "private, no-store");
  } finally {
    stub.restore();
  }
});

test("single-report GET forwards id segment and bearer token", async () => {
  const stub = stubFetch(upstreamOk);
  try {
    const request = new NextRequest("http://localhost:3000/api/reports/rep-9", {
      headers: { authorization: "Bearer browser-token" },
    });
    const res = await reportByIdRoute.GET(request, {
      params: Promise.resolve({ id: "rep-9" }),
    });
    assert.equal(
      stub.calls[0].input,
      "http://backend.test/api/v1/research/reports/rep-9",
    );
    const headers = stub.calls[0].init?.headers as Record<string, string>;
    assert.equal(headers.authorization, "Bearer browser-token");
    assert.equal(res.status, 200);
  } finally {
    stub.restore();
  }
});
