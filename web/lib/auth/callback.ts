/**
 * Pure parsing of Supabase auth callback URLs (implicit flow).
 *
 * Invite and recovery links land on a page with the auth result in the URL
 * hash, e.g. `#access_token=...&type=invite` or
 * `#error=access_denied&error_code=otp_expired&type=recovery`.
 *
 * No JWT decoding happens here. A callback counts as processed only when
 * Supabase's own URL processing accepted it (`accepted`, read from the SDK's
 * `initialize()` verdict) and the token it adopted matches the session
 * store's established token. Equality alone is not enough: an already-signed-in
 * account whose stored token merely repeats in the hash would otherwise pass.
 */

export type AuthCallbackType = "invite" | "recovery";

export interface AuthCallbackState {
  type: AuthCallbackType | null;
  error: string | null;
  errorCode: string | null;
  /** Access token the link itself carries; null when absent or empty. */
  accessToken: string | null;
}

export type AuthCallbackPhase = "checking" | "form" | "invalid";

// Captured at module evaluation: the earliest client moment, before auth-js
// can rewrite the URL. Empty string when server-rendered.
const INITIAL_HASH: string =
  typeof window === "undefined" ? "" : window.location.hash;

export function getInitialAuthHash(): string {
  return INITIAL_HASH;
}

export function parseAuthCallback(source: string): AuthCallbackState {
  const trimmed = source.startsWith("#") || source.startsWith("?")
    ? source.slice(1)
    : source;
  const params = new URLSearchParams(trimmed);
  const rawType = params.get("type");
  const accessToken = params.get("access_token");
  return {
    type: rawType === "invite" || rawType === "recovery" ? rawType : null,
    error: params.get("error") || null,
    errorCode: params.get("error_code") || null,
    accessToken: accessToken || null,
  };
}

export function deriveCallbackPhase(
  parsed: AuthCallbackState,
  expected: AuthCallbackType,
  status: "loading" | "signedIn" | "signedOut" | "unavailable",
  establishedToken: string | null,
  /**
   * The SDK's verdict on the URL: `true` accepted, `false` rejected, `null`
   * still pending. Read from `resolveCallbackAcceptance()`.
   */
  accepted: boolean | null,
): AuthCallbackPhase {
  if (parsed.error) return "invalid";
  if (parsed.type !== expected) return "invalid";
  if (status === "loading") return "checking";
  if (status !== "signedIn") return "invalid";
  // The form may only change the password of the session this exact link
  // established: equality ties the link's token to the current account.
  if (!parsed.accessToken || parsed.accessToken !== establishedToken) {
    return "invalid";
  }
  // Equality proves identity, not adoption. An incomplete hash that merely
  // repeats this account's own token is rejected by the SDK, so wait for
  // its verdict instead of opening the form.
  if (accepted === null) return "checking";
  return accepted ? "form" : "invalid";
}
