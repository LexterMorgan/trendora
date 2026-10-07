/**
 * Frozen save/import attempts and their UI state.
 *
 * One attempt holds a request key and payload fixed for its whole lifetime, so
 * a retry can never create a second row. Attempts are plain in-memory state:
 * they are never written to browser storage, and the component that owns them
 * is remounted by `Protected` on any account switch, which discards them.
 */

export type SaveStatus = "idle" | "saving" | "saved" | "failed" | "uncertain";

export interface SaveAttempt {
  requestId: string | null;
  reportId: string | null;
  status: SaveStatus;
  errorCode: string | null;
  origin: string | null;
  recoveryReceipt?: string | null;
}

export interface ImportAttempt {
  requestId: string;
  reportId: string;
  itemKind: "idea" | "brief";
  itemIndex: number;
  status: "idle" | "saving" | "saved" | "failed";
  postId: string | null;
  errorCode: string | null;
}

export const REQUEST_ID_ERROR_MESSAGE =
  "Secure randomness is unavailable. This action was not sent. Use a browser with Web Crypto enabled.";

export function newRequestId(): string {
  try {
    const secure = globalThis.crypto;
    if (typeof secure?.randomUUID === "function") return secure.randomUUID();
    if (typeof secure?.getRandomValues !== "function") throw new Error();
    const bytes = secure.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  } catch {
    throw new Error(REQUEST_ID_ERROR_MESSAGE);
  }
}

export function saveStatusFromOutcome(outcome: {
  status: string;
  report_id: string | null;
  snapshot_origin: string;
}): SaveStatus {
  if (outcome.status === "saved") return "saved";
  if (outcome.status === "failed") return "failed";
  return "uncertain";
}

/** Codes where retrying the same frozen payload cannot succeed. */
export const TERMINAL_SAVE_CODES: readonly string[] = [
  "report_request_too_large",
  "snapshot_too_large",
  "invalid_report_snapshot",
  "report_save_conflict",
  "report_expired",
];

export const TERMINAL_SAVE_MESSAGES: Record<string, string> = {
  report_request_too_large:
    "This report is too large to save for later recovery. It stays visible here and can be copied; saving cannot be retried.",
  snapshot_too_large:
    "This report is too large to save for later recovery. It stays visible here and can be copied; saving cannot be retried.",
  invalid_report_snapshot:
    "This report could not be verified for saving. It stays visible here and can be copied; saving cannot be retried.",
  report_save_conflict:
    "This report conflicts with an earlier save under the same key. It stays visible here; saving is not retried automatically.",
  report_expired:
    "This report’s source data has expired. It cannot be saved again.",
};

export function isTerminalSaveCode(code: string | null | undefined): boolean {
  return typeof code === "string" && TERMINAL_SAVE_CODES.includes(code);
}

export function terminalSaveMessage(code: string | null | undefined): string | null {
  if (!isTerminalSaveCode(code)) return null;
  return TERMINAL_SAVE_MESSAGES[code as string] ?? "This report could not be saved.";
}

export function saveStatusForErrorCode(code: string | null | undefined): SaveStatus {
  return isTerminalSaveCode(code) ? "failed" : "uncertain";
}
