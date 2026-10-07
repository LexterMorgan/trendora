import test from "node:test";
import assert from "node:assert/strict";

import {
  ResearchApiError,
  classifyApiError,
  requestJson,
  type ApiRuntime,
} from "../lib/api.ts";
import {
  createSessionStore,
  type AuthAdapter,
  type AuthEventName,
  type AuthSessionLike,
  type SessionStore,
} from "../lib/auth/session.ts";
import type { SessionBinding } from "../lib/auth/session.ts";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

interface FetchCapture {
  input?: string;
  init?: RequestInit;
  calls: number;
}

function withFetch(
  impl: (capture: FetchCapture) => Response | Promise<Response>,
  run: (capture: FetchCapture) => Promise<void>,
): Promise<void> {
  const original = globalThis.fetch;
  const capture: FetchCapture = { calls: 0 };
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    capture.input = String(input);
    capture.init = init;
    capture.calls += 1;
    return impl(capture);
  }) as typeof fetch;
  return run(capture).finally(() => {
    globalThis.fetch = original;
  });
}

interface RuntimeCapture {
  invalidated: number;
  denied: Array<{ code: string; message: string }>;
}

function capture(): RuntimeCapture {
  return { invalidated: 0, denied: [] };
}

function runtime(
  cap: RuntimeCapture,
  token: string | null = "tok-123",
  binding: SessionBinding = { userId: "user-a", epoch: 0 },
): ApiRuntime {
  return {
    getAccessToken: async () => token,
    getSessionBinding: () => ({ ...binding }),
    onUnauthenticated: () => {
      cap.invalidated += 1;
    },
    onAccessDenied: (_b, code, message) => {
      cap.denied.push({ code, message });
    },
  };
}

function deferred(): { promise: Promise<void>; resolve: () => void } {
  let resolve!: () => void;
  const promise = new Promise<void>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

/** Adapter whose every session lookup is queued, so a test can stall it. */
function pendingAuth() {
  const queue: Array<{
    resolve: (session: AuthSessionLike | null) => void;
    reject: (error: unknown) => void;
  }> = [];
  let listener:
    | ((event: AuthEventName, session: AuthSessionLike | null) => void)
    | null = null;

  const adapter: AuthAdapter = {
    getInitialSession: () =>
      new Promise<AuthSessionLike | null>((resolve, reject) => {
        queue.push({ resolve, reject });
      }),
    onAuthChange(cb) {
      listener = cb;
      return () => {
        listener = null;
      };
    },
    async signOut() {},
  };

  return {
    adapter,
    get waiting(): number {
      return queue.length;
    },
    resolveNext(session: AuthSessionLike | null): void {
      queue.shift()?.resolve(session);
    },
    rejectNext(error: unknown): void {
      queue.shift()?.reject(error);
    },
    emit(event: AuthEventName, session: AuthSessionLike | null): void {
      listener?.(event, session);
    },
  };
}

function storeRuntime(store: SessionStore): ApiRuntime {
  return {
    getAccessToken: () => store.getAccessToken(),
    getSessionBinding: () => store.getSessionBinding(),
    onUnauthenticated: (binding) => store.invalidate(binding),
    onAccessDenied: (binding, code, message) =>
      store.denyAccess(binding, code, message),
  };
}

async function settled(p: Promise<unknown>): Promise<unknown> {
  return p.then(
    () => null,
    (err: unknown) => err,
  );
}

const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

test("attaches bearer token, JSON content type, and no-store", async () => {
  await withFetch(
    () => jsonResponse(200, { ok: true }),
    async (fetchCap) => {
      const payload = await requestJson<{ ok: boolean }>("/api/research", {
        method: "POST",
        body: { topic: "x" },
        runtime: runtime(capture()),
      });
      assert.deepEqual(payload, { ok: true });
      assert.equal(fetchCap.input, "/api/research");
      const headers = fetchCap.init?.headers as Headers;
      assert.equal(headers.get("authorization"), "Bearer tok-123");
      assert.equal(headers.get("content-type"), "application/json");
      assert.equal(fetchCap.init?.cache, "no-store");
      assert.equal(fetchCap.init?.method, "POST");
    },
  );
});

test("omits authorization header when signed out", async () => {
  await withFetch(
    () => jsonResponse(200, []),
    async (fetchCap) => {
      await requestJson("/api/reports", {
        runtime: runtime(capture(), null),
      });
      const headers = fetchCap.init?.headers as Headers;
      assert.equal(headers.get("authorization"), null);
      assert.equal(headers.get("content-type"), null, "GET sends no body header");
    },
  );
});

test("401 maps to unauthenticated with friendly message and invalidation", async () => {
  const cap = capture();
  await withFetch(
    () =>
      jsonResponse(401, {
        error: { code: "auth_invalid_token", message: "invalid JWT" },
      }),
    async () => {
      const err = await settled(requestJson("/api/reports", { runtime: runtime(cap) }));
      assert.ok(err instanceof ResearchApiError);
      assert.equal(err.kind, "unauthenticated");
      assert.equal(err.code, "auth_invalid_token");
      assert.equal(err.status, 401);
      assert.equal(err.message, "Your session has expired. Sign in again to continue.");
      assert.equal(cap.invalidated, 1);
      assert.deepEqual(cap.denied, []);
    },
  );
});

test("403 membership codes map to forbidden with distinct copy", async () => {
  const cases: Array<[string, string]> = [
    ["auth_not_member", "This account isn't a member of this Trendora workspace."],
    [
      "auth_inactive",
      "This account's access has been turned off. Ask an administrator to restore it.",
    ],
    ["auth_forbidden_admin", "You don't have access to this action."],
  ];
  for (const [code, message] of cases) {
    const cap = capture();
    await withFetch(
      () => jsonResponse(403, { error: { code, message: "raw" } }),
      async () => {
        const err = await settled(requestJson("/api/x", { runtime: runtime(cap) }));
        assert.ok(err instanceof ResearchApiError, code);
        assert.equal(err.kind, "forbidden", code);
        assert.equal(err.code, code, code);
        assert.equal(err.message, message, code);
        assert.equal(cap.invalidated, 0, "403 never signs the user out");
      },
    );
  }
});

test("membership 403 asks the store to purge access; other 403 does not", async () => {
  for (const code of ["auth_not_member", "auth_inactive"]) {
    const cap = capture();
    await withFetch(
      () => jsonResponse(403, { error: { code, message: "raw" } }),
      async () => {
        await settled(requestJson("/api/x", { runtime: runtime(cap) }));
        assert.equal(cap.denied.length, 1, code);
        assert.equal(cap.denied[0].code, code);
        assert.ok(cap.denied[0].message.length > 0);
      },
    );
  }

  const cap = capture();
  await withFetch(
    () => jsonResponse(403, { error: { code: "auth_forbidden_admin", message: "raw" } }),
    async () => {
      await settled(requestJson("/api/x", { runtime: runtime(cap) }));
      assert.deepEqual(cap.denied, [], "a per-action 403 must not revoke workspace access");
    },
  );
});

test("503 maps to unavailable with availability copy", async () => {
  await withFetch(
    () =>
      jsonResponse(503, {
        error: { code: "data_unavailable", message: "history query failed" },
      }),
    async () => {
      const err = await settled(
        requestJson("/api/x", { runtime: runtime(capture()) }),
      );
      assert.ok(err instanceof ResearchApiError);
      assert.equal(err.kind, "unavailable");
      assert.equal(err.message, "Trendora is temporarily unavailable. Try again in a moment.");
    },
  );
});

test("422 keeps the backend message", async () => {
  await withFetch(
    () =>
      jsonResponse(422, {
        error: { code: "invalid_request", message: "topic is required" },
      }),
    async () => {
      const err = await settled(
        requestJson("/api/x", { runtime: runtime(capture()) }),
      );
      assert.ok(err instanceof ResearchApiError);
      assert.equal(err.kind, "invalid_request");
      assert.equal(err.message, "topic is required");
    },
  );
});

test("network failure becomes a retryable network error", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = (async () => {
    throw new TypeError("fetch failed");
  }) as typeof fetch;
  try {
    const err = await settled(
      requestJson("/api/x", { runtime: runtime(capture()) }),
    );
    assert.ok(err instanceof ResearchApiError);
    assert.equal(err.code, "backend_unreachable");
    assert.equal(err.kind, "network");
  } finally {
    globalThis.fetch = original;
  }
});

test("AbortError propagates untouched (cancellation, not failure)", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = (async () => {
    throw new DOMException("aborted", "AbortError");
  }) as typeof fetch;
  try {
    const err = await settled(
      requestJson("/api/x", { runtime: runtime(capture()) }),
    );
    assert.ok(err instanceof DOMException);
    assert.equal(err.name, "AbortError");
  } finally {
    globalThis.fetch = original;
  }
});

test("a failed POST is never replayed automatically", async () => {
  let calls = 0;
  const original = globalThis.fetch;
  globalThis.fetch = (async () => {
    calls += 1;
    throw new TypeError("fetch failed");
  }) as typeof fetch;
  try {
    const err = await settled(
      requestJson("/api/report", {
        method: "POST",
        body: { topic: "x" },
        runtime: runtime(capture()),
      }),
    );
    assert.ok(err instanceof ResearchApiError);
    await tick();
    await tick();
    assert.equal(calls, 1, "research/report POSTs are only ever sent by a user action");
  } finally {
    globalThis.fetch = original;
  }
});

test("logout during token retrieval prevents dispatch", async () => {
  const cap = capture();
  const gate = deferred();
  const binding: SessionBinding = { userId: "user-a", epoch: 0 };
  const rt: ApiRuntime = {
    getAccessToken: async () => {
      await gate.promise;
      return "tok-123";
    },
    getSessionBinding: () => ({ ...binding }),
    onUnauthenticated: () => {
      cap.invalidated += 1;
    },
    onAccessDenied: (_b, code, message) => {
      cap.denied.push({ code, message });
    },
  };

  await withFetch(
    () => jsonResponse(200, { ok: true }),
    async (fetchCap) => {
      const pending = settled(requestJson("/api/report", { method: "POST", body: {}, runtime: rt }));
      binding.userId = null;
      binding.epoch = 1;
      gate.resolve();
      const err = await pending;
      assert.ok(err instanceof ResearchApiError);
      assert.equal(err.kind, "stale");
      assert.equal(fetchCap.calls, 0, "request must not leave the browser");
      assert.equal(cap.invalidated, 0);
    },
  );
});

test("account switch during token retrieval prevents dispatch", async () => {
  const cap = capture();
  const gate = deferred();
  const binding: SessionBinding = { userId: "user-a", epoch: 0 };
  const rt: ApiRuntime = {
    getAccessToken: async () => {
      await gate.promise;
      return "tok-123";
    },
    getSessionBinding: () => ({ ...binding }),
    onUnauthenticated: () => {
      cap.invalidated += 1;
    },
    onAccessDenied: (_b, code, message) => {
      cap.denied.push({ code, message });
    },
  };

  await withFetch(
    () => jsonResponse(200, { ok: true }),
    async (fetchCap) => {
      const pending = settled(requestJson("/api/reports", { runtime: rt }));
      binding.userId = "user-b";
      binding.epoch = 1;
      gate.resolve();
      const err = await pending;
      assert.ok(err instanceof ResearchApiError);
      assert.equal(err.kind, "stale");
      assert.equal(fetchCap.calls, 0);
    },
  );
});

test("an old request's 401 does not invalidate the newer session", async () => {
  const cap = capture();
  const gate = deferred();
  const binding: SessionBinding = { userId: "user-a", epoch: 0 };
  const rt: ApiRuntime = {
    getAccessToken: async () => "tok-123",
    getSessionBinding: () => ({ ...binding }),
    onUnauthenticated: () => {
      cap.invalidated += 1;
    },
    onAccessDenied: (_b, code, message) => {
      cap.denied.push({ code, message });
    },
  };

  await withFetch(
    async () => {
      await gate.promise;
      return jsonResponse(401, {
        error: { code: "auth_invalid_token", message: "invalid JWT" },
      });
    },
    async (fetchCap) => {
      const pending = settled(requestJson("/api/reports", { runtime: rt }));
      await tick();
      assert.equal(fetchCap.calls, 1, "dispatched under the original session");
      binding.userId = null;
      binding.epoch = 1;
      gate.resolve();
      const err = await pending;
      assert.ok(err instanceof ResearchApiError);
      assert.equal(err.kind, "stale");
      assert.equal(cap.invalidated, 0, "the newer session stays signed in");
    },
  );
});

test("a delayed 401 under an unchanged session still invalidates", async () => {
  const cap = capture();
  const gate = deferred();
  const rt = runtime(cap);

  await withFetch(
    async () => {
      await gate.promise;
      return jsonResponse(401, {
        error: { code: "auth_missing", message: "no token" },
      });
    },
    async () => {
      const pending = settled(requestJson("/api/reports", { runtime: rt }));
      await tick();
      gate.resolve();
      const err = await pending;
      assert.ok(err instanceof ResearchApiError);
      assert.equal(err.kind, "unauthenticated");
      assert.equal(cap.invalidated, 1);
    },
  );
});

test("an old request's membership 403 does not deny the newer session", async () => {
  const cap = capture();
  const gate = deferred();
  const binding: SessionBinding = { userId: "user-a", epoch: 0 };
  const rt: ApiRuntime = {
    getAccessToken: async () => "tok-123",
    getSessionBinding: () => ({ ...binding }),
    onUnauthenticated: () => {
      cap.invalidated += 1;
    },
    onAccessDenied: (_b, code, message) => {
      cap.denied.push({ code, message });
    },
  };

  await withFetch(
    async () => {
      await gate.promise;
      return jsonResponse(403, {
        error: { code: "auth_not_member", message: "raw" },
      });
    },
    async () => {
      const pending = settled(requestJson("/api/reports", { runtime: rt }));
      await tick();
      binding.userId = "user-b";
      binding.epoch = 1;
      gate.resolve();
      const err = await pending;
      assert.ok(err instanceof ResearchApiError);
      assert.equal(err.kind, "stale");
      assert.deepEqual(cap.denied, []);
      assert.equal(cap.invalidated, 0);
    },
  );
});

test("a delayed account-A lookup cannot answer a request under account B", async () => {
  const auth = pendingAuth();
  const store = createSessionStore(auth.adapter);
  store.start();
  auth.resolveNext({ user: { id: "user-a" }, access_token: "tok-a" });
  await tick();
  assert.equal(store.getSessionState().userId, "user-a");
  const runtime = storeRuntime(store);

  await withFetch(
    () => jsonResponse(200, { ok: true }),
    async (fetchCap) => {
      // A request under A starts, and its token lookup stalls.
      const old = settled(requestJson("/api/reports", { runtime }));
      assert.equal(auth.waiting, 1, "the lookup is in flight");

      // The account switches to B while that lookup is still pending.
      auth.emit("SIGNED_IN", { user: { id: "user-b" }, access_token: "tok-b" });

      // The stale A lookup resolves last, with A's session in hand.
      auth.resolveNext({ user: { id: "user-a" }, access_token: "tok-a" });
      const stale = await old;
      assert.ok(stale instanceof ResearchApiError);
      assert.equal(stale.kind, "stale");
      assert.equal(fetchCap.calls, 0, "the old request never leaves the browser");

      // The next lookup under B fails outright.
      const next = settled(requestJson("/api/reports", { runtime }));
      auth.rejectNext(new Error("auth service down"));
      assert.equal(await next, null, "a transient failure falls back to cache");

      assert.equal(fetchCap.calls, 1, "B's request is dispatched");
      const headers = fetchCap.init?.headers as Headers;
      assert.equal(
        headers.get("authorization"),
        "Bearer tok-b",
        "no request under B may carry A's credentials",
      );
    },
  );
});

test("a lookup that outlives a logout answers nothing", async () => {
  const auth = pendingAuth();
  const store = createSessionStore(auth.adapter);
  store.start();
  auth.resolveNext({ user: { id: "user-a" }, access_token: "tok-a" });
  await tick();

  const late = store.getAccessToken();
  await store.signOut();
  auth.resolveNext({ user: { id: "user-a" }, access_token: "tok-a" });

  assert.equal(await late, null, "the late answer dies with the session it came from");
  assert.equal(store.getSessionState().status, "signedOut");
  assert.equal(await store.getAccessToken(), null, "nothing resurrects the old token");
});

test("an unchanged account's refresh keeps lookups valid", async () => {
  const auth = pendingAuth();
  const store = createSessionStore(auth.adapter);
  store.start();
  auth.resolveNext({ user: { id: "user-a" }, access_token: "tok-1" });
  await tick();
  const runtime = storeRuntime(store);

  await withFetch(
    () => jsonResponse(200, { ok: true }),
    async (fetchCap) => {
      const pending = settled(requestJson("/api/reports", { runtime }));
      assert.equal(auth.waiting, 1, "the lookup is in flight");

      auth.emit("TOKEN_REFRESHED", {
        user: { id: "user-a" },
        access_token: "tok-2",
      });
      auth.resolveNext({ user: { id: "user-a" }, access_token: "tok-2" });

      const err = await pending;
      assert.equal(err, null, "a refresh is not a session change, so this dispatches");
      assert.equal(fetchCap.calls, 1);
      const headers = fetchCap.init?.headers as Headers;
      assert.equal(headers.get("authorization"), "Bearer tok-2");
      assert.equal(store.getSessionState().epoch, 0, "refresh never bumps the epoch");
      assert.equal(
        store.getSessionState().establishedToken,
        "tok-1",
        "the token the session was established with is untouched",
      );
    },
  );
});

test("classifyApiError covers the contract statuses", () => {
  assert.equal(classifyApiError(401, "auth_missing"), "unauthenticated");
  assert.equal(classifyApiError(403, "auth_not_member"), "forbidden");
  assert.equal(classifyApiError(404, "x"), "not_found");
  assert.equal(classifyApiError(422, "x"), "invalid_request");
  assert.equal(classifyApiError(503, "auth_unavailable"), "unavailable");
  assert.equal(classifyApiError(502, "backend_unreachable"), "network");
  assert.equal(classifyApiError(502, "research_upstream_error"), "upstream");
  assert.equal(classifyApiError(500, "backend_not_configured"), "unavailable");
  assert.equal(classifyApiError(500, "internal_error"), "unknown");
});
