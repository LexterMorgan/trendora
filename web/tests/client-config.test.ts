import test from "node:test";
import assert from "node:assert/strict";

// Config is read once at module load: start from a clean slate.
delete process.env.NEXT_PUBLIC_SUPABASE_URL;
delete process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

const unconfigured = await import("../lib/auth/client.ts");
const { gateDecision } = await import("../lib/auth/session.ts");

test("missing env yields null config and an unavailable store", () => {
  assert.equal(unconfigured.readPublicConfig(), null);
  assert.equal(unconfigured.hasPublicAuthConfig(), false);

  const store = unconfigured.getSessionStore();
  assert.equal(store.getSessionState().status, "unavailable");
  assert.equal(gateDecision(store.getSessionState().status), "unavailable");
  store.start();
  assert.equal(store.getSessionState().status, "unavailable");
});

test("explicit env values are trimmed, not validated beyond presence", () => {
  assert.deepEqual(
    unconfigured.readPublicConfig({
      url: "  https://example.supabase.co ",
      anonKey: " public-key ",
    }),
    { url: "https://example.supabase.co", anonKey: "public-key" },
  );
  assert.equal(unconfigured.readPublicConfig({ url: "", anonKey: "k" }), null);
  assert.equal(unconfigured.readPublicConfig({ url: "u", anonKey: "" }), null);
});

test("env present in the browser bundle flips config on", async () => {
  process.env.NEXT_PUBLIC_SUPABASE_URL = "https://example.supabase.co";
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = "public-anon-key";
  try {
    // Variable specifier: fresh module instance; TS does not resolve query strings.
    const configuredPath = "../lib/auth/client.ts?configured";
    const configured = (await import(configuredPath)) as typeof unconfigured;
    assert.equal(configured.hasPublicAuthConfig(), true);
    assert.deepEqual(configured.readPublicConfig(), {
      url: "https://example.supabase.co",
      anonKey: "public-anon-key",
    });
  } finally {
    delete process.env.NEXT_PUBLIC_SUPABASE_URL;
    delete process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  }
});

function fakeClient(
  initialize: () => Promise<{ error: { message: string } | null }>,
) {
  return { auth: { initialize } };
}

test("resolveCallbackAcceptance reports the SDK's URL verdict", async () => {
  assert.equal(
    await unconfigured.resolveCallbackAcceptance(),
    false,
    "no public auth config means no callback was ever processed",
  );
  assert.equal(
    await unconfigured.resolveCallbackAcceptance(
      fakeClient(async () => ({ error: null })),
    ),
    true,
    "the SDK accepted the link, so the callback counts as processed",
  );
  assert.equal(
    await unconfigured.resolveCallbackAcceptance(
      fakeClient(async () => ({ error: { message: "No session defined in URL" } })),
    ),
    false,
    "an SDK-rejected link opens nothing, whatever the hash carries",
  );
  assert.equal(
    await unconfigured.resolveCallbackAcceptance(
      fakeClient(async () => {
        throw new Error("interrupted");
      }),
    ),
    false,
    "an unreadable verdict is never treated as acceptance",
  );
});
