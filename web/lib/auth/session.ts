/**
 * Framework-agnostic session store for Trendora's browser auth layer.
 *
 * The store wraps a Supabase adapter (see `./client.ts`) but has no runtime
 * dependency on it: tests inject a fake adapter directly. All state is kept
 * in plain objects so `useSyncExternalStore` can compare snapshots by
 * identity.
 *
 * `epoch` increments whenever the visible account changes (sign-out,
 * account switch, forced invalidation after a 401). Protected content is
 * keyed on `userId:epoch` so stale content is remounted, never reused.
 * Requests are bound to the same `userId:epoch` pair, so a response that
 * belongs to a previous session can be discarded instead of acted on.
 */

export type SessionStatus = "loading" | "signedIn" | "signedOut" | "unavailable";

export type AuthSignOutScope = "local" | "global";

export interface SessionDenied {
  code: string;
  message: string;
}

export interface SessionState {
  status: SessionStatus;
  userId: string | null;
  epoch: number;
  /** True when the initial lookup timed out or failed and may be retried. */
  initializationFailed: boolean;
  /**
   * Access token of the session as last established. A later token refresh
   * updates `token` for API calls but leaves this alone, so a callback can
   * still be matched against the token the link itself delivered.
   */
  establishedToken: string | null;
  /** Set when the backend rejected this account's workspace membership. */
  denied: SessionDenied | null;
}

/** The account + generation a request was started under. */
export interface SessionBinding {
  userId: string | null;
  epoch: number;
}

export interface AuthSessionLike {
  user: { id: string } | null;
  access_token?: string;
}

export type AuthEventName =
  | "INITIAL_SESSION"
  | "PASSWORD_RECOVERY"
  | "SIGNED_IN"
  | "SIGNED_OUT"
  | "TOKEN_REFRESHED"
  | "USER_UPDATED";

export interface AuthAdapter {
  getInitialSession(): Promise<AuthSessionLike | null>;
  onAuthChange(
    listener: (event: AuthEventName, session: AuthSessionLike | null) => void,
  ): () => void;
  /** `global` revokes every device; `local` only clears this browser. */
  signOut(scope: AuthSignOutScope): Promise<void>;
}

export interface SessionStore {
  getSessionState(): SessionState;
  getSessionBinding(): SessionBinding;
  getAccessToken(): Promise<string | null>;
  subscribe(listener: () => void): () => void;
  start(): void;
  /** Start a fresh bounded initial lookup after a timeout or transient failure. */
  retryInitialization(): void;
  /** Forced sign-out. Pass the binding to ignore a stale 401. */
  invalidate(binding?: SessionBinding): void;
  /** Purge workspace content for an account the backend rejected. */
  denyAccess(binding: SessionBinding, code: string, message: string): void;
  signOut(): Promise<void>;
}

export const INITIAL_SESSION_TIMEOUT_MS = 15_000;
export const TOKEN_LOOKUP_TIMEOUT_MS = 10_000;

/** The application stopped waiting for the auth SDK. The SDK may still finish. */
export class SessionWaitError extends Error {
  code = "auth_timeout" as const;

  constructor(message = "Checking your session took too long.") {
    super(message);
    this.name = "SessionWaitError";
  }
}

export interface SessionStoreOptions {
  initialTimeoutMs?: number;
  tokenTimeoutMs?: number;
}

function waitWithTimeout<T>(
  promise: Promise<T>,
  timeoutMs: number,
  timeoutError: () => Error,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      reject(timeoutError());
    }, timeoutMs);
    promise.then(
      (value) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        reject(error);
      },
    );
  });
}

export function gateDecision(
  status: SessionStatus,
): "loading" | "render" | "login" | "unavailable" {
  if (status === "signedIn") return "render";
  if (status === "signedOut") return "login";
  if (status === "unavailable") return "unavailable";
  return "loading";
}

function sameBinding(a: SessionBinding, b: SessionBinding): boolean {
  return a.userId === b.userId && a.epoch === b.epoch;
}

/** True while the store still holds a session a lookup is allowed to answer. */
function hasLiveSession(state: SessionState): boolean {
  return state.status === "signedIn" || state.status === "loading";
}

export function createSessionStore(
  adapter: AuthAdapter | null,
  options: SessionStoreOptions = {},
): SessionStore {
  const initialTimeoutMs = options.initialTimeoutMs ?? INITIAL_SESSION_TIMEOUT_MS;
  const tokenTimeoutMs = options.tokenTimeoutMs ?? TOKEN_LOOKUP_TIMEOUT_MS;
  const empty: SessionState = {
    status: adapter ? "loading" : "unavailable",
    userId: null,
    epoch: 0,
    initializationFailed: false,
    establishedToken: null,
    denied: null,
  };
  let state: SessionState = empty;
  let token: string | null = null;
  let started = false;
  let initializationAttempt = 0;
  const listeners = new Set<() => void>();

  function commit(next: SessionState): void {
    if (
      next.status === state.status &&
      next.userId === state.userId &&
      next.epoch === state.epoch &&
      next.initializationFailed === state.initializationFailed &&
      next.establishedToken === state.establishedToken &&
      next.denied === state.denied
    ) {
      return;
    }
    state = next;
    for (const listener of listeners) listener();
  }

  function applyEvent(event: AuthEventName, session: AuthSessionLike | null): void {
    if (!adapter) return;
    // INITIAL_SESSION reports only the first load. Once a newer state exists,
    // a late initial payload must not replace an account or undo logout,
    // whether that payload is null or non-null.
    if (event === "INITIAL_SESSION" && state.status !== "loading") return;

    if (session === null || session.user?.id == null) {
      if (state.status === "signedOut" && token === null) return;
      token = null;
      commit({
        status: "signedOut",
        userId: null,
        epoch: state.userId !== null ? state.epoch + 1 : state.epoch,
        initializationFailed: false,
        establishedToken: null,
        denied: null,
      });
      return;
    }

    const userId = session.user.id;
    token = session.access_token ?? token;
    const establishedToken =
      event === "TOKEN_REFRESHED"
        ? state.establishedToken
        : (session.access_token ?? state.establishedToken);
    const switched = state.userId !== null && state.userId !== userId;
    commit({
      status: "signedIn",
      userId,
      epoch: switched ? state.epoch + 1 : state.epoch,
      initializationFailed: false,
      establishedToken,
      denied: switched ? null : state.denied,
    });
  }

  function initialize(): void {
    if (!adapter || state.status !== "loading") return;
    const attempt = ++initializationAttempt;
    commit({ ...state, initializationFailed: false });
    let lookup: Promise<AuthSessionLike | null>;
    try {
      lookup = Promise.resolve(adapter.getInitialSession());
    } catch {
      lookup = Promise.reject(new Error("initial session lookup failed"));
    }
    waitWithTimeout(lookup, initialTimeoutMs, () => new SessionWaitError()).then(
      (session) => {
        if (attempt !== initializationAttempt) return;
        if (state.status === "loading") applyEvent("INITIAL_SESSION", session);
      },
      () => {
        if (attempt !== initializationAttempt) return;
        if (state.status === "loading") {
          commit({ ...state, status: "loading", initializationFailed: true });
        }
      },
    );
  }

  return {
    getSessionState: () => state,

    getSessionBinding: () => ({ userId: state.userId, epoch: state.epoch }),

    async getAccessToken(): Promise<string | null> {
      if (!adapter) return null;
      if (!hasLiveSession(state)) return null;

      // The lookup can outlive a logout or an account switch. Everything it
      // learns belongs to this account, so it may neither answer a later
      // session nor overwrite the token that session already holds.
      const wanted: SessionBinding = { userId: state.userId, epoch: state.epoch };

      let resolved: AuthSessionLike | null | undefined;
      try {
        let lookup: Promise<AuthSessionLike | null>;
        try {
          lookup = Promise.resolve(adapter.getInitialSession());
        } catch {
          lookup = Promise.reject(new Error("access token lookup failed"));
        }
        resolved = await waitWithTimeout(
          lookup,
          tokenTimeoutMs,
          () => new SessionWaitError("Getting your session token took too long."),
        );
      } catch (error) {
        if (error instanceof SessionWaitError) {
          if (!hasLiveSession(state)) return null;
          if (state.userId !== wanted.userId || state.epoch !== wanted.epoch) return token;
          throw error;
        }
        resolved = undefined; // transient failure: fall back to the cached token
      }

      // Re-read the account before touching `token`: a sign-out landed while
      // this lookup was in flight, so nothing it carries may survive.
      if (!hasLiveSession(state)) return null;
      if (state.userId !== wanted.userId || state.epoch !== wanted.epoch) {
        return token; // current session's cached token, never this stale answer
      }
      if (resolved === undefined) return token;
      if (resolved === null) return null;
      if (wanted.userId !== null && resolved.user?.id !== wanted.userId) {
        return token; // a foreign account's session must not be adopted
      }
      token = resolved.access_token ?? token;
      return token;
    },

    subscribe(listener: () => void): () => void {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },

    start(): void {
      if (started || !adapter) return;
      started = true;
      adapter.onAuthChange(applyEvent);
      initialize();
    },

    retryInitialization(): void {
      if (!adapter || state.status !== "loading") return;
      initialize();
    },

    invalidate(binding?: SessionBinding): void {
      if (!adapter) return;
      // A 401 raised under an older account must not sign the current one out.
      if (binding && !sameBinding(binding, state)) return;
      // Local scope only: forced invalidation drops THIS browser's Supabase
      // session (so INITIAL_SESSION/TOKEN_REFRESHED cannot resurrect it and
      // bounce workspace <-> /login) without revoking other devices.
      void adapter.signOut("local").catch(() => {
        // Local state is cleared below regardless of network outcome.
      });
      applyEvent("SIGNED_OUT", null);
    },

    denyAccess(binding: SessionBinding, code: string, message: string): void {
      if (state.status !== "signedIn") return;
      if (!sameBinding(binding, state)) return;
      if (state.denied?.code === code) return;
      commit({ ...state, denied: { code, message } });
    },

    async signOut(): Promise<void> {
      if (!adapter) return;
      try {
        await adapter.signOut("global");
      } catch {
        // Local session is cleared below regardless of network outcome.
      }
      applyEvent("SIGNED_OUT", null);
    },
  };
}
