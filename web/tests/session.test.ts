import test from "node:test";
import assert from "node:assert/strict";

import {
  SessionWaitError,
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


function stalledAdapter() {
  let resolve!: (value: AuthSessionLike | null) => void;
  let reject!: (reason: unknown) => void;
  let calls = 0;
  const adapter: AuthAdapter = {
    getInitialSession: () => {
      calls += 1;
      return new Promise<AuthSessionLike | null>((res, rej) => {
        resolve = res;
        reject = rej;
      });
    },
    onAuthChange: () => () => {},
    signOut: async () => {},
  };
  return {
    adapter,
    get calls() { return calls; },
    resolve(value: AuthSessionLike | null) { resolve(value); },
    reject(reason: unknown) { reject(reason); },
  };
}

test("a never-settling initial lookup becomes a retryable loading state", async () => {
  const pending = stalledAdapter();
  const store = createSessionStore(pending.adapter, { initialTimeoutMs: 0 });
  store.start();
  await flush();

  assert.equal(store.getSessionState().status, "loading");
  assert.equal(store.getSessionState().initializationFailed, true);
  assert.equal(gateDecision(store.getSessionState().status), "loading");

  store.retryInitialization();
  assert.equal(store.getSessionState().initializationFailed, false);
  pending.resolve({ user: { id: "user-a" }, access_token: "t1" });
  await flush();
  assert.equal(store.getSessionState().status, "signedIn");
  assert.equal(store.getSessionState().userId, "user-a");
});

test("a rejected initial lookup stays retryable instead of forcing logout", async () => {
  let attempts = 0;
  const adapter: AuthAdapter = {
    async getInitialSession() {
      attempts += 1;
      if (attempts === 1) throw new Error("fictional transient auth failure");
      return { user: { id: "user-a" }, access_token: "t1" };
    },
    onAuthChange: () => () => {},
    signOut: async () => {},
  };
  const store = createSessionStore(adapter, { initialTimeoutMs: 1_000 });
  store.start();
  await flush();
  assert.equal(store.getSessionState().status, "loading");
  assert.equal(store.getSessionState().initializationFailed, true);

  store.retryInitialization();
  await flush();
  assert.equal(store.getSessionState().status, "signedIn");
  assert.equal(store.getSessionState().userId, "user-a");
  assert.equal(store.getSessionState().initializationFailed, false);
});

test("token lookup timeout is temporary and does not clear the signed-in session", async () => {
  const pending = stalledAdapter();
  const store = createSessionStore(pending.adapter, { initialTimeoutMs: 1_000, tokenTimeoutMs: 0 });
  store.start();
  pending.resolve({ user: { id: "user-a" }, access_token: "t1" });
  await flush();
  assert.equal(store.getSessionState().status, "signedIn");

  await assert.rejects(store.getAccessToken(), (err: unknown) => {
    assert.ok(err instanceof SessionWaitError);
    assert.equal(err.code, "auth_timeout");
    return true;
  });
  assert.equal(store.getSessionState().status, "signedIn");
  assert.equal(store.getSessionState().userId, "user-a");
  assert.equal(store.getSessionState().epoch, 0);
});


function queuedAdapter() {
  const pending: Array<{
    resolve: (value: AuthSessionLike | null) => void;
    reject: (reason: unknown) => void;
  }> = [];
  let listener:
    | ((event: AuthEventName, session: AuthSessionLike | null) => void)
    | null = null;
  const adapter: AuthAdapter = {
    getInitialSession: () => new Promise<AuthSessionLike | null>((resolve, reject) => {
      pending.push({ resolve, reject });
    }),
    onAuthChange(cb) {
      listener = cb;
      return () => {
        listener = null;
      };
    },
    signOut: async () => {},
  };
  return {
    adapter,
    get waiting() { return pending.length; },
    resolve(index: number, session: AuthSessionLike | null) { pending[index].resolve(session); },
    reject(index: number, reason: unknown) { pending[index].reject(reason); },
    emit(event: AuthEventName, session: AuthSessionLike | null) { listener?.(event, session); },
  };
}

test("a late non-null INITIAL_SESSION cannot replace a newer account", async () => {
  const auth = queuedAdapter();
  const store = createSessionStore(auth.adapter, { initialTimeoutMs: 1_000 });
  store.start();
  auth.resolve(0, { user: { id: "user-a" }, access_token: "tok-a" });
  await flush();
  auth.emit("SIGNED_IN", { user: { id: "user-b" }, access_token: "tok-b" });
  store.denyAccess(store.getSessionBinding(), "auth_not_member", "Fictional denial");
  const newer = store.getSessionState();

  auth.emit("INITIAL_SESSION", { user: { id: "user-a" }, access_token: "tok-a" });

  assert.equal(store.getSessionState().userId, "user-b");
  assert.equal(store.getSessionState().epoch, newer.epoch);
  assert.equal(store.getSessionState().establishedToken, "tok-b");
  assert.equal(store.getSessionState().denied?.code, "auth_not_member");
});

test("a late non-null INITIAL_SESSION cannot resurrect a logged-out session", async () => {
  const auth = queuedAdapter();
  const store = createSessionStore(auth.adapter, { initialTimeoutMs: 1_000 });
  store.start();
  auth.resolve(0, { user: { id: "user-a" }, access_token: "tok-a" });
  await flush();
  store.invalidate();

  auth.emit("INITIAL_SESSION", { user: { id: "user-a" }, access_token: "tok-a" });

  assert.equal(store.getSessionState().status, "signedOut");
  assert.equal(store.getSessionState().userId, null);
  assert.equal(store.getSessionState().establishedToken, null);
});

test("retry B wins when the timed-out lookup A resolves later", async () => {
  const auth = queuedAdapter();
  const store = createSessionStore(auth.adapter, { initialTimeoutMs: 0 });
  store.start();
  await flush();
  assert.equal(store.getSessionState().initializationFailed, true);

  store.retryInitialization();
  auth.resolve(1, { user: { id: "user-b" }, access_token: "tok-b" });
  await flush();
  const newer = store.getSessionState();
  assert.equal(newer.userId, "user-b");

  auth.resolve(0, { user: { id: "user-a" }, access_token: "tok-a" });
  await flush();

  assert.equal(store.getSessionState().userId, "user-b");
  assert.equal(store.getSessionState().epoch, newer.epoch);
  assert.equal(store.getSessionState().establishedToken, "tok-b");
});

test("late lookup A cannot overwrite retry B, including its denial state", async () => {
  const auth = queuedAdapter();
  const store = createSessionStore(auth.adapter, { initialTimeoutMs: 1_000 });
  store.start();
  store.retryInitialization();
  auth.resolve(1, { user: { id: "user-b" }, access_token: "tok-b" });
  await flush();
  store.denyAccess(store.getSessionBinding(), "auth_not_member", "Fictional denial");
  const newer = store.getSessionState();

  auth.resolve(0, { user: { id: "user-a" }, access_token: "tok-a" });
  await flush();

  assert.equal(store.getSessionState().userId, "user-b");
  assert.equal(store.getSessionState().epoch, newer.epoch);
  assert.equal(store.getSessionState().establishedToken, "tok-b");
  assert.equal(store.getSessionState().denied?.code, "auth_not_member");
});

test("legitimate initial and password-recovery events still establish sessions", async () => {
  const auth = queuedAdapter();
  const store = createSessionStore(auth.adapter, { initialTimeoutMs: 1_000 });
  store.start();
  auth.emit("INITIAL_SESSION", { user: { id: "user-a" }, access_token: "tok-a" });
  assert.equal(store.getSessionState().userId, "user-a");

  auth.emit("SIGNED_OUT", null);
  assert.equal(store.getSessionState().status, "signedOut");
  auth.emit("PASSWORD_RECOVERY", { user: { id: "user-b" }, access_token: "tok-b" });
  assert.equal(store.getSessionState().status, "signedIn");
  assert.equal(store.getSessionState().userId, "user-b");
  assert.equal(store.getSessionState().establishedToken, "tok-b");
});
