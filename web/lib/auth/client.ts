/**
 * Supabase-backed auth adapter and singleton session store.
 *
 * Reads only the public `NEXT_PUBLIC_SUPABASE_*` variables (anon/publishable
 * key). Never touch service-role credentials here: everything in this file
 * runs in the browser.
 *
 * Flow choice: implicit. Supabase's own guidance makes implicit the default
 * for client-only JavaScript, and `admin.inviteUserByEmail` links only work
 * with it (PKCE cannot accept an invitation in a different browser).
 */

import { createClient, type AuthError, type SupabaseClient } from "@supabase/supabase-js";

import {
  createSessionStore,
  type AuthAdapter,
  type AuthEventName,
  type AuthSessionLike,
  type AuthSignOutScope,
  type SessionStore,
} from "./session.ts";

export interface PublicAuthConfig {
  url: string;
  anonKey: string;
}

// Literal member access so Next.js inlines these at build time.
const ENV_URL = process.env.NEXT_PUBLIC_SUPABASE_URL;
const ENV_ANON_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

export function readPublicConfig(
  env?: { url?: string; anonKey?: string },
): PublicAuthConfig | null {
  const source =
    env === undefined ? { url: ENV_URL, anonKey: ENV_ANON_KEY } : env;
  const url = source.url?.trim();
  const anonKey = source.anonKey?.trim();
  if (!url || !anonKey) return null;
  return { url, anonKey };
}

export function hasPublicAuthConfig(): boolean {
  return readPublicConfig() !== null;
}

let supabase: SupabaseClient | null = null;
let supabaseFailed = false;

function getSupabase(): SupabaseClient | null {
  if (supabase) return supabase;
  if (supabaseFailed) return null;
  const config = readPublicConfig();
  if (!config) return null;
  try {
    supabase = createClient(config.url, config.anonKey, {
      auth: {
        flowType: "implicit",
        detectSessionInUrl: true,
        persistSession: true,
        autoRefreshToken: true,
      },
    });
  } catch {
    supabaseFailed = true;
    return null;
  }
  return supabase;
}

function toAdapter(client: SupabaseClient): AuthAdapter {
  return {
    async getInitialSession(): Promise<AuthSessionLike | null> {
      const { data, error } = await client.auth.getSession();
      if (error) throw error;
      return data.session as AuthSessionLike | null;
    },
    onAuthChange(listener): () => void {
      const { data } = client.auth.onAuthStateChange((event, session) => {
        listener(event as AuthEventName, session as AuthSessionLike | null);
      });
      return () => data.subscription.unsubscribe();
    },
    async signOut(scope: AuthSignOutScope): Promise<void> {
      // Explicit: supabase-js defaults to `global`, which would revoke the
      // user's other devices on every forced invalidation.
      await client.auth.signOut({ scope });
    },
  };
}

let store: SessionStore | null = null;

export function getSessionStore(): SessionStore {
  if (!store) {
    const client = getSupabase();
    store = createSessionStore(client ? toAdapter(client) : null);
  }
  return store;
}

/** Narrow view of the SDK: only the call that reports the URL verdict. */
export type CallbackSource = {
  auth: { initialize(): Promise<{ error: { message: string } | null }> };
};

/**
 * Whether Supabase accepted the auth result carried by the current URL.
 *
 * `initialize()` runs URL processing once and caches its verdict, so this
 * never re-runs a callback. `false` means the SDK rejected the link
 * (incomplete, expired, already used) or public auth is not configured.
 * The SDK's own verdict, never a hand-rolled JWT check.
 */
export async function resolveCallbackAcceptance(
  client: CallbackSource | null = getSupabase(),
): Promise<boolean> {
  if (!client) return false;
  try {
    const { error } = await client.auth.initialize();
    return error === null;
  } catch {
    return false;
  }
}

/**
 * Maps Supabase auth failures to copy that never reveals whether an account
 * exists. Unknown messages pass through (Supabase messages are already
 * user-facing, e.g. password length requirements).
 */
function mapAuthError(error: AuthError): string {
  const message = error.message;
  const lower = message.toLowerCase();
  if (lower.includes("invalid login credentials")) {
    return "Email or password is incorrect.";
  }
  if (lower.includes("email not confirmed")) {
    return "Confirm your email address before signing in.";
  }
  if (
    error.name === "TypeError" ||
    lower.includes("failed to fetch") ||
    lower.includes("network")
  ) {
    return "Couldn't reach the sign-in service. Try again.";
  }
  return message;
}

export async function signInWithPassword(
  email: string,
  password: string,
): Promise<string | null> {
  const client = getSupabase();
  if (!client) return "Sign-in is unavailable on this deployment.";
  const { error } = await client.auth.signInWithPassword({ email, password });
  return error ? mapAuthError(error) : null;
}

export async function sendPasswordResetEmail(
  email: string,
): Promise<string | null> {
  const client = getSupabase();
  if (!client) return "Sign-in is unavailable on this deployment.";
  const { error } = await client.auth.resetPasswordForEmail(email, {
    // Without this the link opens the dashboard Site URL (usually "/") and
    // the user signs in without ever setting a new password.
    redirectTo: `${window.location.origin}/reset-password`,
  });
  return error ? mapAuthError(error) : null;
}

export async function updatePassword(
  password: string,
): Promise<string | null> {
  const client = getSupabase();
  if (!client) return "Sign-in is unavailable on this deployment.";
  const { error } = await client.auth.updateUser({ password });
  return error ? mapAuthError(error) : null;
}
