/**
 * Shared HTTP helper for the browser → Next.js proxy → FastAPI path.
 *
 * Adds the Supabase bearer token when a session exists, classifies backend
 * error envelopes ({error: {code, message}}) into kinds the UI handles
 * distinctly (401 / 403 / 503 / ...), and never logs or exposes secrets.
 * Backend status and codes pass through unchanged; only the human-readable
 * message is sharpened for the auth failures.
 *
 * Every request is bound to the `userId:epoch` it started under. A logout,
 * account switch, or forced invalidation during the round trip makes the
 * binding stale: the request is never dispatched, and a response that
 * arrives afterwards is discarded along with its auth side effects, so an
 * old 401 cannot invalidate a newer session.
 */

import { getSessionStore } from "./auth/client.ts";
import type { SessionBinding } from "./auth/session.ts";

export type ApiErrorKind =
  | "unauthenticated"
  | "forbidden"
  | "unavailable"
  | "not_found"
  | "invalid_request"
  | "upstream"
  | "network"
  | "stale"
  | "unknown";

export class ResearchApiError extends Error {
  code: string;
  kind: ApiErrorKind;
  status: number;

  constructor(
    code: string,
    message: string,
    kind: ApiErrorKind = "unknown",
    status = 0,
  ) {
    super(message);
    this.name = "ResearchApiError";
    this.code = code;
    this.kind = kind;
    this.status = status;
  }
}

/** Backend codes meaning the account has no workspace access. */
const MEMBERSHIP_CODES = new Set(["auth_not_member", "auth_inactive"]);

export function classifyApiError(status: number, code: string): ApiErrorKind {
  if (status === 401) return "unauthenticated";
  if (status === 403) return "forbidden";
  if (status === 404) return "not_found";
  if (status === 422) return "invalid_request";
  if (status === 503) return "unavailable";
  if (status === 502) {
    return code === "backend_unreachable" ? "network" : "upstream";
  }
  if (status === 500 && code === "backend_not_configured") return "unavailable";
  return "unknown";
}

export function friendlyApiMessage(
  kind: ApiErrorKind,
  code: string,
  serverMessage: string,
): string {
  switch (kind) {
    case "unauthenticated":
      return "Your session has expired. Sign in again to continue.";
    case "forbidden":
      if (code === "auth_not_member") {
        return "This account isn't a member of this Trendora workspace.";
      }
      if (code === "auth_inactive") {
        return "This account's access has been turned off. Ask an administrator to restore it.";
      }
      return "You don't have access to this action.";
    case "unavailable":
      return "Trendora is temporarily unavailable. Try again in a moment.";
    case "network":
      return "Trendora could not be reached. Check your connection and try again.";
    default:
      return serverMessage;
  }
}

export interface ApiRuntime {
  getAccessToken(): Promise<string | null>;
  getSessionBinding(): SessionBinding;
  onUnauthenticated(binding: SessionBinding): void;
  onAccessDenied(binding: SessionBinding, code: string, message: string): void;
}

let sharedRuntime: ApiRuntime | null = null;

function defaultRuntime(): ApiRuntime {
  if (!sharedRuntime) {
    sharedRuntime = {
      getAccessToken: () => getSessionStore().getAccessToken(),
      getSessionBinding: () => getSessionStore().getSessionBinding(),
      onUnauthenticated: (binding) => getSessionStore().invalidate(binding),
      onAccessDenied: (binding, code, message) =>
        getSessionStore().denyAccess(binding, code, message),
    };
  }
  return sharedRuntime;
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
  cache?: RequestCache;
  runtime?: ApiRuntime;
}

function isCurrent(binding: SessionBinding, now: SessionBinding): boolean {
  return binding.userId === now.userId && binding.epoch === now.epoch;
}

function staleRequest(): ResearchApiError {
  return new ResearchApiError(
    "session_changed",
    "This request belonged to a previous session and was ignored.",
    "stale",
  );
}

export async function requestJson<T = unknown>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const runtime = options.runtime ?? defaultRuntime();
  const binding = runtime.getSessionBinding();

  // Capture the account before reading the token: a logout or account switch
  // while the token is being retrieved must stop the request going out.
  const token = await runtime.getAccessToken().catch(() => null);
  if (!isCurrent(binding, runtime.getSessionBinding())) throw staleRequest();

  const headers = new Headers();
  if (options.body !== undefined) {
    headers.set("content-type", "application/json");
  }
  if (token) {
    headers.set("authorization", `Bearer ${token}`);
  }

  let response: Response;
  try {
    response = await fetch(path, {
      method: options.method ?? "GET",
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      cache: options.cache ?? "no-store",
      signal: options.signal,
    });
  } catch (err) {
    if (err instanceof Error && err.name === "AbortError") throw err;
    throw new ResearchApiError(
      "backend_unreachable",
      "Trendora could not be reached. Check your connection and try again.",
      "network",
    );
  }

  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  // Response belongs to a session that no longer exists: drop it, including
  // the 401/403 side effects it would otherwise trigger.
  if (!isCurrent(binding, runtime.getSessionBinding())) throw staleRequest();

  if (!response.ok) {
    const envelope = (
      payload as { error?: { code?: string; message?: string } } | null
    )?.error;
    const code = envelope?.code ?? "unknown_error";
    const serverMessage =
      envelope?.message ?? `Request failed with status ${response.status}.`;
    const kind = classifyApiError(response.status, code);
    const friendly = friendlyApiMessage(kind, code, serverMessage);
    if (kind === "unauthenticated") {
      runtime.onUnauthenticated(binding);
    } else if (kind === "forbidden" && MEMBERSHIP_CODES.has(code)) {
      runtime.onAccessDenied(binding, code, friendly);
    }
    throw new ResearchApiError(code, friendly, kind, response.status);
  }

  if (payload === null) {
    throw new ResearchApiError(
      "invalid_response",
      "Trendora returned an unreadable response.",
      "unknown",
      response.status,
    );
  }
  return payload as T;
}
