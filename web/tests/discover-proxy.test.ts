import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import * as nodeModule from "node:module";

interface ModuleInternals {
  registerHooks(hooks: {
    resolve(
      specifier: string,
      context: unknown,
      nextResolve: (specifier: string, context?: unknown) => { url: string },
    ): { url: string };
  }): void;
}

(nodeModule as unknown as ModuleInternals).registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier === "next/server") return nextResolve("next/server.js", context);
    return nextResolve(specifier, context);
  },
});

const require = createRequire(import.meta.url);
const { NextRequest } = require("next/server") as typeof import("next/server");

process.env.TRENDORA_API_BASE_URL = "http://backend.test";
const { GET } = await import("../app/api/discover/route.ts");

const originalFetch = globalThis.fetch;
const originalBase = process.env.TRENDORA_API_BASE_URL;
const originalTimeout = AbortSignal.timeout;

function request(signal?: AbortSignal): InstanceType<typeof NextRequest> {
  return new NextRequest(
    "http://frontend.test/api/discover?q=fictional&limit=10",
    {
      headers: {
        authorization: "Bearer fictional",
        cookie: "session=never-forward",
      },
      ...(signal ? { signal } : {}),
    },
  );
}

function restore(): void {
  globalThis.fetch = originalFetch;
  AbortSignal.timeout = originalTimeout;
  if (originalBase === undefined) delete process.env.TRENDORA_API_BASE_URL;
  else process.env.TRENDORA_API_BASE_URL = originalBase;
}

test("Discover proxy forwards only query, limit, and auth with a bounded exchange", async () => {
  process.env.TRENDORA_API_BASE_URL = "http://backend.test/";
  let calls = 0;
  let deadline = new AbortController();
  AbortSignal.timeout = (ms) => {
    assert.equal(ms, 65_000);
    return deadline.signal;
  };
  try {
    globalThis.fetch = async (url, init) => {
      calls += 1;
      assert.equal(url, "http://backend.test/api/v1/discover?q=fictional&limit=10");
      const headers = new Headers(init?.headers);
      assert.equal(headers.get("authorization"), "Bearer fictional");
      assert.equal(headers.get("cookie"), null);
      assert.equal(init?.redirect, "error");
      assert.equal(init?.cache, "no-store");
      assert.ok(init?.signal);
      return Response.json(
        {
          query: "fictional",
          status: "ok",
          sources: [
            {
              source_code: "public_web",
              content_external_id: "https://example.test/fictional",
              title: "Fictional result",
              url: "https://example.test/fictional",
              published_at: null,
              description: "Fictional description",
            },
          ],
        },
        { status: 200 },
      );
    };

    const response = await GET(request());
    assert.equal(response.status, 200);
    assert.equal(response.headers.get("cache-control"), "private, no-store");
    assert.equal((await response.json()).sources.length, 1);
    assert.equal(calls, 1);

    deadline = new AbortController();
    globalThis.fetch = async () =>
      Response.json(
        { error: { code: "source_unavailable", message: "Fictional unavailable" } },
        { status: 503 },
      );
    const unavailable = await GET(request());
    assert.equal(unavailable.status, 503);
    assert.equal((await unavailable.json()).error.code, "source_unavailable");
    assert.equal(unavailable.headers.get("cache-control"), "private, no-store");
  } finally {
    restore();
  }
});

test("Discover proxy times out before headers and while reading the body", async () => {
  process.env.TRENDORA_API_BASE_URL = "http://backend.test";
  let deadline = new AbortController();
  AbortSignal.timeout = () => deadline.signal;
  try {
    globalThis.fetch = (_url, init) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener(
        "abort",
        () => reject(new DOMException("private header detail", "AbortError")),
        { once: true },
      );
    });
    // The fetch has not resolved headers when the deadline fires.
    queueMicrotask(() => deadline.abort());
    let response = await GET(request());
    assert.equal(response.status, 504);
    const timeoutBody = await response.text();
    assert.match(timeoutBody, /"discover_timeout"/);
    assert.doesNotMatch(timeoutBody, /private detail/);

    deadline = new AbortController();
    globalThis.fetch = async (_url, init) => {
      queueMicrotask(() => deadline.abort());
      return new Response(new ReadableStream({
        start(controller) {
          controller.enqueue(new TextEncoder().encode('{"query":"fictional"'));
          init?.signal?.addEventListener("abort", () => controller.error(new Error("private body detail")), { once: true });
        },
      }));
    };
    response = await GET(request());
    assert.equal(response.status, 504);
    assert.equal((await response.json()).error.code, "discover_timeout");

    deadline = new AbortController();
    globalThis.fetch = async () => {
      throw new Error("private connection detail");
    };
    response = await GET(request());
    assert.equal(response.status, 502);
    const connectionBody = await response.text();
    assert.match(connectionBody, /"backend_unreachable"/);
    assert.doesNotMatch(connectionBody, /private connection detail/);
  } finally {
    restore();
  }
});

test("Discover proxy never forwards an already cancelled request", async () => {
  process.env.TRENDORA_API_BASE_URL = "http://backend.test";
  const controller = new AbortController();
  controller.abort();
  let calls = 0;
  try {
    globalThis.fetch = async () => {
      calls += 1;
      return Response.json({});
    };
    const response = await GET(request(controller.signal));
    assert.equal(response.status, 502);
    assert.equal((await response.json()).error.code, "backend_unreachable");
    assert.equal(calls, 0);
  } finally {
    restore();
  }
});
