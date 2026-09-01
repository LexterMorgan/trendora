/**
 * Presentation-only formatting helpers.
 *
 * Number/date formatting is UI presentation, never an analytics computation.
 * The underlying values are never changed.
 */

const compactFormatter = new Intl.NumberFormat("en", {
  notation: "compact",
  maximumFractionDigits: 1,
});

export function formatCount(value: number): string {
  return compactFormatter.format(value);
}

/** Null (missing) is distinct from zero and renders as an em dash. */
export function formatMetric(value: number | null): string {
  if (value === null || value === undefined) return "—";
  return formatCount(value);
}

export function formatDate(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString("en", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export function sourceLabel(sourceCode: string): string {
  if (sourceCode === "youtube") return "YouTube";
  return sourceCode;
}
