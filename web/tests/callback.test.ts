import test from "node:test";
import assert from "node:assert/strict";

import {
  deriveCallbackPhase,
  parseAuthCallback,
} from "../lib/auth/callback.ts";

test("parses invite callback hash with the link's access token", () => {
  const parsed = parseAuthCallback(
    "#access_token=link-tok&refresh_token=r&type=invite&expires_in=3600",
  );
  assert.equal(parsed.type, "invite");
  assert.equal(parsed.error, null);
  assert.equal(parsed.errorCode, null);
  assert.equal(parsed.accessToken, "link-tok");
});

test("parses recovery callback hash", () => {
  const parsed = parseAuthCallback(
    "#access_token=link-tok&type=recovery&expires_in=3600",
  );
  assert.equal(parsed.type, "recovery");
  assert.equal(parsed.accessToken, "link-tok");
});

test("parses expired-link error", () => {
  const parsed = parseAuthCallback(
    "#error=access_denied&error_code=otp_expired&error_description=Link+expired",
  );
  assert.equal(parsed.type, null);
  assert.equal(parsed.error, "access_denied");
  assert.equal(parsed.errorCode, "otp_expired");
  assert.equal(parsed.accessToken, null);
});

test("garbage hash parses to a neutral invalid state", () => {
  const parsed = parseAuthCallback("#nonsense");
  assert.deepEqual(parsed, {
    type: null,
    error: null,
    errorCode: null,
    accessToken: null,
  });
});

test("an empty access_token counts as absent", () => {
  assert.equal(parseAuthCallback("#type=invite&access_token=").accessToken, null);
});

test("query-string form works too", () => {
  const parsed = parseAuthCallback("?type=invite");
  assert.equal(parsed.type, "invite");
});

test("deriveCallbackPhase: checking while session resolves", () => {
  const parsed = parseAuthCallback("#access_token=link-tok&type=invite");
  assert.equal(
    deriveCallbackPhase(parsed, "invite", "loading", null, null),
    "checking",
  );
});

test("deriveCallbackPhase: form when Supabase adopted this link's token", () => {
  const parsed = parseAuthCallback("#access_token=link-tok&type=invite");
  assert.equal(
    deriveCallbackPhase(parsed, "invite", "signedIn", "link-tok", true),
    "form",
  );
});

test("deriveCallbackPhase: rejected link is invalid", () => {
  const parsed = parseAuthCallback("#error=access_denied&error_code=otp_expired");
  assert.equal(
    deriveCallbackPhase(parsed, "recovery", "signedIn", "link-tok", false),
    "invalid",
  );
});

test("deriveCallbackPhase: wrong type is invalid", () => {
  const recovery = parseAuthCallback("#access_token=link-tok&type=recovery");
  assert.equal(
    deriveCallbackPhase(recovery, "invite", "signedIn", "link-tok", true),
    "invalid",
  );
  const missing = parseAuthCallback("");
  assert.equal(
    deriveCallbackPhase(missing, "invite", "signedIn", "link-tok", true),
    "invalid",
  );
});

test("deriveCallbackPhase: matching type but no session is invalid", () => {
  const parsed = parseAuthCallback("#access_token=link-tok&type=recovery");
  assert.equal(
    deriveCallbackPhase(parsed, "recovery", "signedOut", null, true),
    "invalid",
  );
});

test("deriveCallbackPhase: stored session plus a link Supabase never took", () => {
  const parsed = parseAuthCallback("#access_token=link-tok&type=invite");
  assert.equal(
    deriveCallbackPhase(parsed, "invite", "signedIn", "stored-tok", true),
    "invalid",
    "an already-signed-in account must not adopt an unprocessed link",
  );
});

test("deriveCallbackPhase: incomplete callback stays invalid", () => {
  const noToken = parseAuthCallback("#type=recovery");
  assert.equal(
    deriveCallbackPhase(noToken, "recovery", "signedIn", "stored-tok", true),
    "invalid",
  );
  const emptyToken = parseAuthCallback("#type=recovery&access_token=");
  assert.equal(
    deriveCallbackPhase(emptyToken, "recovery", "signedIn", "stored-tok", true),
    "invalid",
  );
  const garbage = parseAuthCallback("#access_token=not-a-real-token&type=recovery");
  assert.equal(
    deriveCallbackPhase(garbage, "recovery", "signedIn", "stored-tok", true),
    "invalid",
  );
});

test("deriveCallbackPhase: a later token refresh keeps an accepted link open", () => {
  const parsed = parseAuthCallback("#access_token=link-tok&type=recovery");
  assert.equal(
    deriveCallbackPhase(parsed, "recovery", "signedIn", "link-tok", true),
    "form",
    "establishedToken ignores refreshes, so the form does not vanish mid-entry",
  );
});

test("deriveCallbackPhase: SDK rejected a hash that only repeats this session's token", () => {
  const parsed = parseAuthCallback("#type=recovery&access_token=stored-tok");
  assert.equal(
    deriveCallbackPhase(parsed, "recovery", "signedIn", "stored-tok", false),
    "invalid",
    "an already-signed-in account must not open the form on a link the SDK refused",
  );
});

test("deriveCallbackPhase: the SDK's verdict arrives after the session does", () => {
  const parsed = parseAuthCallback("#type=recovery&access_token=stored-tok");
  assert.equal(
    deriveCallbackPhase(parsed, "recovery", "signedIn", "stored-tok", null),
    "checking",
    "neither panel may flash before the SDK has answered",
  );
  assert.equal(
    deriveCallbackPhase(parsed, "recovery", "signedIn", "stored-tok", true),
    "form",
    "a callback the SDK accepted opens the form",
  );
});

test("deriveCallbackPhase: token checks still win over an accepted verdict", () => {
  const foreign = parseAuthCallback("#type=invite&access_token=other-tok");
  assert.equal(
    deriveCallbackPhase(foreign, "invite", "signedIn", "stored-tok", true),
    "invalid",
    "acceptance cannot move the form onto a different account",
  );
});
