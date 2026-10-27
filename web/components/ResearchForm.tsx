/**
 * Shared research-form helpers and types. The simplified global request no
 * longer offers country, source, or depth selection, so those constants were
 * removed; the values interface and date helpers remain the single contract
 * shared by the form, the turn view, and the workspace.
 */

export const EXAMPLE_QUERIES = [
  "Skincare",
  "FPS games",
  "Electric cars",
  "Coffee",
  "Streetwear",
  "AI tools",
];

export const DATE_PRESETS = [
  { value: "last_7d", label: "Last 7 days" },
  { value: "last_30d", label: "Last 30 days" },
  { value: "last_90d", label: "Last 90 days" },
  { value: "last_12m", label: "Last 12 months" },
  { value: "custom", label: "Custom" },
];

/** Fixed global discovery budget. Reuses the existing default result limit. */
export const DEFAULT_RESULT_LIMIT = 50;

/** Global discovery runs the two configured topic-search sources. */
export const GLOBAL_SOURCE_CODES = ["youtube", "public_web"] as const;

export const GLOBAL_COVERAGE_NOTE =
  "Searches YouTube and the public web globally, with no country restriction. This is not comprehensive worldwide coverage. Public-web results are indexed titles and snippets; the timeframe is not enforced and publication dates are unverified, so undated results remain context.";

export interface ResearchDraft {
  topic?: string;
  date_from?: string;
  date_to?: string;
  preset?: string;
  include_content_tools?: boolean;
}

export interface ResearchFormValues {
  topic: string;
  markets: string[];
  date_from?: string;
  date_to?: string;
  sources: string[];
  result_limit: number;
  facebook_page_id?: string;
  include_content_tools?: boolean;
}

/* Local-calendar date helpers. Never UTC, never hardcoded years. */

function todayLocal(): Date {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), now.getDate());
}

export function toISODate(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function todayISODate(): string {
  return toISODate(todayLocal());
}

function daysAgoLocal(today: Date, offset: number): Date {
  return new Date(today.getFullYear(), today.getMonth(), today.getDate() - offset);
}

function oneYearEarlier(value: Date): Date {
  const year = value.getFullYear() - 1;
  const month = value.getMonth();
  const day = value.getDate();
  const shifted = new Date(year, month, day);
  if (shifted.getDate() !== day) {
    // e.g. Feb 29 in a leap year, year before is not leap: clamp to Feb 28.
    return new Date(year, month + 1, 0);
  }
  return shifted;
}

export function presetRange(
  preset: string,
  today: Date,
): { from: Date; to: Date } | null {
  switch (preset) {
    case "last_7d":
      return { from: daysAgoLocal(today, 6), to: today };
    case "last_30d":
      return { from: daysAgoLocal(today, 29), to: today };
    case "last_90d":
      return { from: daysAgoLocal(today, 89), to: today };
    case "last_12m":
      return { from: oneYearEarlier(today), to: today };
    default:
      return null;
  }
}
