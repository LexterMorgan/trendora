import test from "node:test";
import assert from "node:assert/strict";

import {
  createSessionStore,
  gateDecision,
  type AuthAdapter,
  type AuthEventName,
  type AuthSessionLike,
  type AuthSignOutScope,
} from "../lib/auth/session.ts";

function fakeAdapter(initial: AuthSessionLike | null = null) {
  let current = initial;
  let listener:
    | ((event: AuthEventName, session: AuthSessionLike | null) => void)
    | null = null;
  let subscribeCalls = 0;
  const scopes: AuthSignOutScope[] = [];

  const adapter: AuthAdapter = {
    async getInitialSession() {
      return current;
    },
    onAuthChange(cb) {
      subscribeCalls += 1;
      listener = cb;
      return () => {
        listener = null;
      };
    },
    async signOut(scope) {
      scopes.push(scope);
    },
  };

  return {
    adapter,
    emit(event: AuthEventName, session: AuthSessionLike | null) {
      current = session;
      listener?.(event, session);
    },
    get subscribeCalls() {
      return subscribeCalls;
    },
    get signOutCalls() {
      return scopes.length;
    },
    get scopes() {
      return scopes;
    },
  };
}

const flush = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

test("start resolves initial session to signedIn", async () => {
  const fake = fakeAdapter({ user: { id: "user-a" }, access_token: "t1" });
  const store = createSessionStore(fake.adapter);

  assert.equal(store.getSessionState().status, "loading");
  assert.equal(gateDecision(store.getSessionState().status), "loading");

  let notified = 0;
  const unsubscribe = store.subscribe(() => {
    notified += 1;
  });
  store.start();
  await flush();

  const state = store.getSessionState();
  assert.equal(state.status, "signedIn");
  assert.equal(state.userId, "user-a");
  assert.equal(state.epoch, 0);
  assert.equal(gateDecision(state.status), "render");
  assert.equal(await store.getAccessToken(), "t1");
  assert.ok(notified >= 1);

  fake.emit("TOKEN_REFRESHED", { user: { id: "user-a" }, access_token: "t2" });
  assert.equal(await store.getAccessToken(), "t2");

  const seen = notified;
  unsubscribe();
  fake.emit("SIGNED_OUT", null);
  assert.equal(notified, seen, "unsubscribed listener not recalled");
});

test("start with no session lands signedOut (login gate)", async () => {
  const fake = fakeAdapter(null);
  const store = createSessionStore(fake.adapter);
  store.start();
  await flush();

  assert.equal(store.getSessionState().status, "signedOut");
  assert.equal(gateDecision(store.getSessionState().status), "login");
  assert.equal(await store.getAccessToken(), null);
});

test("missing adapter yields unavailable without throwing", () => {
  const store = createSessionStore(null);
  assert.equal(store.getSessionState().status, "unavailable");
  assert.equal(gateDecision(store.getSessionState().status), "unavailable");
  store.start();
  store.invalidate();
  assert.equal(store.getSessionState().status, "unavailable");
});

test("signOut clears session and bumps epoch", async () => {
  const fake = fakeAdapter({ user: { id: "user-a" }, access_token: "t1" });
  const store = createSessionStore(fake.adapter);
  store.start();
  await flush();
  assert.equal(store.getSessionState().status, "signedIn");

  await store.signOut();

  const state = store.getSessionState();
  assert.equal(state.status, "signedOut");
  assert.equal(state.userId, null);
  assert.ok(state.epoch >= 1, "epoch bumps so content remounts");
  assert.deepEqual(fake.scopes, ["global"], "a deliberate sign-out is the user's call");
  assert.equal(await store.getAccessToken(), null);
});

test("cross-tab SIGNED_OUT event from adapter clears the store", async () => {
  const fake = fakeAdapter({ user: { id: "user-a" }, access_token: "t1" });
  const store = createSessionStore(fake.adapter);
  store.start();
  await flush();

  fake.emit("SIGNED_OUT", null);

  assert.equal(store.getSessionState().status, "signedOut");
  assert.equal(store.getSessionState().userId, null);
});

test("account switch keeps signedIn but bumps epoch", async () => {
  const fake = fakeAdapter({ user: { id: "user-a" }, access_token: "t1" });
  const store = createSessionStore(fake.adapter);
  store.start();
  await flush();
  const firstEpoch = store.getSessionState().epoch;

  fake.emit("SIGNED_IN", { user: { id: "user-b" }, access_token: "tb" });

  const state = store.getSessionState();
  assert.equal(state.status, "signedIn");
  assert.equal(state.userId, "user-b");
  assert.equal(state.epoch, firstEpoch + 1);
  assert.equal(await store.getAccessToken(), "tb");
});

test("invalidate forces signedOut after a 401 and drops the stored session", async () => {
  const fake = fakeAdapter({ user: { id: "user-a" }, access_token: "t1" });
  const store = createSessionStore(fake.adapter);
  store.start();
  await flush();

  store.invalidate();

  assert.equal(store.getSessionState().status, "signedOut");
  assert.ok(store.getSessionState().epoch >= 1);
  assert.equal(await store.getAccessToken(), null);
  assert.equal(
    fake.signOutCalls,
    1,
    "stored Supabase session must go too, or a valid-looking local token resurrects the bounce",
  );
  assert.deepEqual(
    fake.scopes,
    ["local"],
    "forced invalidation clears this browser only, never the user's other devices",
  );
});

test("late INITIAL_SESSION null does not knock out signedIn", async () => {
  const fake = fakeAdapter(null);
  const store = createSessionStore(fake.adapter);
  store.start();
  await flush();
  fake.emit("SIGNED_IN", { user: { id: "user-a" }, access_token: "t1" });
  assert.equal(store.getSessionState().status, "signedIn");

  fake.emit("INITIAL_SESSION", null);

  assert.equal(store.getSessionState().status, "signedIn");
  assert.equal(store.getSessionState().userId, "user-a");
});

test("start is idempotent (single adapter subscription)", async () => {
  const fake = fakeAdapter({ user: { id: "user-a" }, access_token: "t1" });
  const store = createSessionStore(fake.adapter);
  store.start();
  store.start();
  await flush();
  assert.equal(fake.subscribeCalls, 1);
});

test("unavailable config keeps access token null", async () => {
  const store = createSessionStore(null);
  assert.equal(await store.getAccessToken(), null);
});

test("getSessionBinding reports the account and generation", async () => {
  const fake = fakeAdapter({ user: { id: "user-a" }, access_token: "t1" });
  const store = createSessionStore(fake.adapter);
  store.start();
  await flush();
  assert.deepEqual(store.getSessionBinding(), { userId: "user-a", epoch: 0 });
});

test("invalidate under an old binding leaves the newer session alone", async () => {
  const fake = fakeAdapter({ user: { id: "user-a" }, access_token: "t1" });
  const store = createSessionStore(fake.adapter);
  store.start();
  await flush();
  const oldBinding = store.getSessionBinding();

  fake.emit("SIGNED_IN", { user: { id: "user-b" }, access_token: "tb" });
  const newer = store.getSessionBinding();

  store.invalidate(oldBinding);

  assert.equal(store.getSessionState().status, "signedIn");
  assert.equal(store.getSessionState().userId, "user-b");
  assert.deepEqual(store.getSessionBinding(), newer);
  assert.equal(fake.signOutCalls, 0, "a stale 401 must not sign anyone out");

  store.invalidate(newer);
  assert.equal(store.getSessionState().status, "signedOut");
  assert.equal(fake.signOutCalls, 1);
});

test("denyAccess purges workspace access and survives refreshes", async () => {
  const fake = fakeAdapter({ user: { id: "user-a" }, access_token: "t1" });
  const store = createSessionStore(fake.adapter);
  store.start();
  await flush();

  store.denyAccess(
    store.getSessionBinding(),
    "auth_not_member",
    "This account isn't a member of this Trendora workspace.",
  );

  assert.equal(gateDecision(store.getSessionState().status), "render");
  assert.equal(store.getSessionState().denied?.code, "auth_not_member");
  assert.equal(store.getSessionState().epoch, 0, "denial gates content, it does not remount");

  fake.emit("TOKEN_REFRESHED", { user: { id: "user-a" }, access_token: "t2" });
  assert.ok(
    store.getSessionState().denied,
    "a token refresh must not quietly restore workspace content",
  );

  fake.emit("SIGNED_IN", { user: { id: "user-b" }, access_token: "tb" });
  assert.equal(
    store.getSessionState().denied,
    null,
    "a different account starts clean",
  );

  fake.emit("SIGNED_IN", { user: { id: "user-b" }, access_token: "tb" });
  store.denyAccess(store.getSessionBinding(), "auth_inactive", "Access turned off.");
  assert.equal(store.getSessionState().denied?.code, "auth_inactive");

  await store.signOut();
  assert.equal(store.getSessionState().denied, null);
});

test("denyAccess ignores a binding from a previous session", async () => {
  const fake = fakeAdapter({ user: { id: "user-a" }, access_token: "t1" });
  const store = createSessionStore(fake.adapter);
  store.start();
  await flush();
  const oldBinding = store.getSessionBinding();

  fake.emit("SIGNED_IN", { user: { id: "user-b" }, access_token: "tb" });

  store.denyAccess(oldBinding, "auth_not_member", "stale denial");

  assert.equal(store.getSessionState().denied, null);
});

test("establishedToken tracks the session, not the refreshes", async () => {
  const fake = fakeAdapter({ user: { id: "user-a" }, access_token: "t1" });
  const store = createSessionStore(fake.adapter);
  store.start();
  await flush();

  assert.equal(store.getSessionState().establishedToken, "t1");

  fake.emit("TOKEN_REFRESHED", { user: { id: "user-a" }, access_token: "t2" });
  assert.equal(store.getSessionState().establishedToken, "t1");
  assert.equal(await store.getAccessToken(), "t2");

  fake.emit("SIGNED_IN", { user: { id: "user-a" }, access_token: "t3" });
  assert.equal(
    store.getSessionState().establishedToken,
    "t3",
    "a link-driven session replaces the established token without an epoch bump",
  );
});
