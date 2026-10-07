import test from "node:test";
import assert from "node:assert/strict";
import * as members from "../app/api/planner/members/route.ts";
import * as posts from "../app/api/planner/posts/route.ts";
import * as post from "../app/api/planner/posts/[id]/route.ts";
import * as archive from "../app/api/planner/posts/[id]/archive/route.ts";
import * as restore from "../app/api/planner/posts/[id]/restore/route.ts";

const ID = "00000000-0000-4000-8000-000000000001";
const context = { params: Promise.resolve({ id: ID }) };
const snapshot = {
  title: "Fictional draft", platform: "", caption: "Line one\nLine two",
  hook: "", creative_brief: "", asset_links: ["https://example.com/asset"],
  notes: "", planned_date: "2026-10-01", assignee_id: null,
};

function mockUpstream(handler: (url: string, init: RequestInit) => Response) {
  const original = globalThis.fetch;
  const originalBase = process.env.TRENDORA_API_BASE_URL;
  const calls: { url: string; init: RequestInit }[] = [];
  process.env.TRENDORA_API_BASE_URL = "http://backend.test/";
  globalThis.fetch = (async (input, init = {}) => {
    const url = String(input);
    calls.push({ url, init });
    return handler(url, init);
  }) as typeof fetch;
  return {
    calls,
    restore() {
      globalThis.fetch = original;
      if (originalBase === undefined) delete process.env.TRENDORA_API_BASE_URL;
      else process.env.TRENDORA_API_BASE_URL = originalBase;
    },
  };
}

function request(method = "GET", body?: string, query = "") {
  return new Request(`http://frontend.test/api/planner/posts${query}`, {
    method, body,
    headers: { authorization: "Bearer fictional-token", cookie: "private=ignored" },
  });
}

const writes = [
  { name: "create", method: "POST", path: "posts", run: (r: Request) => posts.POST(r) },
  { name: "update", method: "PUT", path: `posts/${ID}`, run: (r: Request) => post.PUT(r, context) },
  { name: "archive", method: "POST", path: `posts/${ID}/archive`, run: (r: Request) => archive.POST(r, context) },
  { name: "restore", method: "POST", path: `posts/${ID}/restore`, run: (r: Request) => restore.POST(r, context) },
];

test("planner read routes use fixed endpoints, bearer auth, and private responses", async () => {
  const mock = mockUpstream(() => Response.json([]));
  try {
    for (const [run, path] of [
      [(r: Request) => members.GET(r), "members"],
      [(r: Request) => posts.GET(r), "posts"],
      [(r: Request) => post.GET(r, context), `posts/${ID}`],
    ] as const) {
      const response = await run(request());
      const call = mock.calls.at(-1)!;
      assert.equal(call.url, `http://backend.test/api/v1/planner/${path}`);
      assert.equal(call.init.method, "GET");
      assert.equal(new Headers(call.init.headers).get("authorization"), "Bearer fictional-token");
      assert.equal(new Headers(call.init.headers).get("cookie"), null);
      assert.equal(call.init.cache, "no-store");
      assert.equal(call.init.redirect, "error");
      assert.equal(response.headers.get("cache-control"), "private, no-store");
    }
  } finally { mock.restore(); }
});

test("planner list forwards only encoded contract queries", async () => {
  const mock = mockUpstream(() => Response.json([]));
  try {
    await posts.GET(request("GET", undefined, "?archived=true&limit=25&offset=50&url=https://evil.test&host=evil.test"));
    assert.equal(mock.calls[0].url, "http://backend.test/api/v1/planner/posts?archived=true&limit=25&offset=50");
    await posts.GET(request("GET", undefined, "?limit=1%26url%3Dhttps%3A%2F%2Fevil.test"));
    const url = new URL(mock.calls[1].url);
    assert.equal(url.origin, "http://backend.test");
    assert.equal(url.searchParams.get("limit"), "1&url=https://evil.test");
    assert.equal(url.searchParams.has("url"), false);
    await members.GET(request("GET", undefined, "?url=https://evil.test&limit=1"));
    assert.equal(mock.calls[2].url, "http://backend.test/api/v1/planner/members");
  } finally { mock.restore(); }
});

test("all planner writes forward exact bytes and preserve acknowledged status", async () => {
  const mock = mockUpstream((url) => Response.json({ id: ID }, {
    status: url.endsWith("/posts") ? 201 : 200,
  }));
  try {
    for (const write of writes) {
      const body = JSON.stringify(write.name === "create"
        ? { ...snapshot, request_id: ID }
        : write.name === "update"
          ? { ...snapshot, status: "working", expected_version: 3 }
          : { expected_version: 3 });
      const response = await write.run(request(write.method, body));
      const call = mock.calls.at(-1)!;
      assert.equal(call.url, `http://backend.test/api/v1/planner/${write.path}`);
      assert.equal(call.init.method, write.method);
      assert.equal(new TextDecoder().decode(call.init.body as ArrayBuffer), body);
      assert.equal(new Headers(call.init.headers).get("content-type"), "application/json");
      assert.equal(new Headers(call.init.headers).get("authorization"), "Bearer fictional-token");
      assert.equal(response.status, write.name === "create" ? 201 : 200);
      assert.deepEqual(await response.json(), { id: ID });
    }
  } finally { mock.restore(); }
});

test("creation replay and backend failures keep their status and exact envelope", async () => {
  const cases = [
    { status: 200, body: { id: ID } },
    { status: 401, body: { error: { code: "auth_unauthenticated", message: "missing token" } } },
    { status: 403, body: { error: { code: "auth_inactive", message: "inactive" } } },
    { status: 409, body: { error: { code: "planner_create_conflict", message: "creation key conflict" } } },
    { status: 409, body: { error: { code: "planner_version_conflict", message: "stale version" } } },
    { status: 409, body: { error: { code: "planner_post_archived", message: "archived" } } },
    { status: 422, body: { error: { code: "planner_assignee_invalid", message: "inactive assignee" } } },
    { status: 503, body: { error: { code: "data_unavailable", message: "unavailable" } } },
  ];
  for (const expected of cases) {
    const mock = mockUpstream(() => Response.json(expected.body, {
      status: expected.status,
      headers: { "set-cookie": "backend-secret=ignored", "x-provider-key": "ignored" },
    }));
    try {
      const response = await posts.POST(request("POST", JSON.stringify({ ...snapshot, request_id: ID })));
      assert.equal(response.status, expected.status);
      assert.deepEqual(await response.json(), expected.body);
      assert.equal(response.headers.get("cache-control"), "private, no-store");
      assert.equal(response.headers.get("set-cookie"), null);
      assert.equal(response.headers.get("x-provider-key"), null);
    } finally { mock.restore(); }
  }
});

test("canonical UUID paths reject traversal or arbitrary targets before forwarding", async () => {
  const mock = mockUpstream(() => Response.json({}));
  try {
    for (const id of ["..", "../members", "https://evil.test", `${ID}/archive`, "%2f%2fevil.test", "not-a-uuid"]) {
      const response = await post.GET(request(), { params: Promise.resolve({ id }) });
      assert.equal(response.status, 422);
      assert.equal(response.headers.get("cache-control"), "private, no-store");
    }
    assert.equal(mock.calls.length, 0);
  } finally { mock.restore(); }
});

test("missing authorization remains absent upstream", async () => {
  const mock = mockUpstream(() => Response.json([]));
  try {
    await members.GET(new Request("http://frontend.test/api/planner/members"));
    assert.equal(new Headers(mock.calls[0].init.headers).get("authorization"), null);
  } finally { mock.restore(); }
});

test("missing or unsafe server configuration fails privately without fetch", async () => {
  const mock = mockUpstream(() => Response.json({}));
  try {
    for (const base of [undefined, "", "file:///private/file", "http://user:secret@backend.test", "http://backend.test?url=evil", "http://backend.test/#secret"]) {
      if (base === undefined) delete process.env.TRENDORA_API_BASE_URL;
      else process.env.TRENDORA_API_BASE_URL = base;
      const response = await members.GET(request());
      assert.equal(response.status, 500);
      assert.deepEqual(await response.json(), { error: {
        code: "backend_not_configured", message: "Trendora backend is not configured.",
      } });
      assert.equal(response.headers.get("cache-control"), "private, no-store");
    }
    assert.equal(mock.calls.length, 0);
  } finally { mock.restore(); }
});

test("network errors do not expose token, configuration, or body", async () => {
  const mock = mockUpstream(() => { throw new Error("fictional-token PRIVATE-DRAFT"); });
  try {
    const response = await posts.POST(request("POST", "PRIVATE-DRAFT"));
    assert.equal(response.status, 502);
    assert.deepEqual(await response.json(), { error: {
      code: "backend_unreachable", message: "Trendora backend could not be reached.",
    } });
    assert.equal(response.headers.get("cache-control"), "private, no-store");
  } finally { mock.restore(); }
});

test("131072 UTF-8 bytes are accepted unchanged regardless of Content-Length", async () => {
  const body = `"${"é".repeat(65_535)}"`;
  assert.equal(new TextEncoder().encode(body).byteLength, 131_072);
  const mock = mockUpstream(() => Response.json({ id: ID }, { status: 201 }));
  try {
    const req = request("POST", body);
    req.headers.set("content-length", "999999");
    const response = await posts.POST(req);
    assert.equal(response.status, 201);
    assert.equal(new TextDecoder().decode(mock.calls[0].init.body as ArrayBuffer), body);
  } finally { mock.restore(); }
});

for (const write of writes) {
  test(`${write.name} stops an oversized stream before buffering its remainder`, async () => {
    let pulls = 0;
    let cancelled = false;
    const stream = new ReadableStream<Uint8Array>({
      pull(controller) {
        pulls += 1;
        controller.enqueue(new Uint8Array(pulls <= 2 ? 65_536 : 1));
      },
      cancel() { cancelled = true; },
    }, { highWaterMark: 0 });
    const init: RequestInit & { duplex: "half" } = {
      method: write.method, body: stream, duplex: "half",
      headers: { "content-length": "1" },
    };
    const mock = mockUpstream(() => Response.json({}));
    try {
      const response = await write.run(new Request("http://frontend.test/api/planner/posts", init));
      assert.equal(response.status, 413);
      assert.equal((await response.json()).error.code, "planner_request_too_large");
      assert.equal(response.headers.get("cache-control"), "private, no-store");
      assert.equal(pulls, 3);
      assert.equal(cancelled, true);
      assert.equal(mock.calls.length, 0);
    } finally { mock.restore(); }
  });
}

test("invalid JSON is validated upstream without altering the request", async () => {
  const mock = mockUpstream(() => Response.json({ error: {
    code: "invalid_request", message: "Invalid JSON.",
  } }, { status: 422 }));
  try {
    const response = await posts.POST(request("POST", "{incomplete"));
    assert.equal(response.status, 422);
    assert.equal(new TextDecoder().decode(mock.calls[0].init.body as ArrayBuffer), "{incomplete");
    assert.equal((await response.json()).error.code, "invalid_request");
  } finally { mock.restore(); }
});
