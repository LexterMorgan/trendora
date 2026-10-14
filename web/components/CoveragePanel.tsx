import type { ResearchCoverageResponse } from "@/lib/trendora-api";
import { sourceLabel } from "@/lib/format";

interface CoveragePanelProps {
  coverage?: ResearchCoverageResponse | null;
  executedSources?: string[];
}

/** Friendly text for the machine-readable coverage reason codes. */
export const COVERAGE_REASON_TEXT: Record<string, string> = {
  search_partial:
    "Public social discovery was partial: some platform queries failed or the shared time budget expired. Results shown are the ones that completed.",
};

/**
 * Shows capability coverage and execution truth separately. Capability
 * availability never implies a source was actually searched; that comes only
 * from `executed_sources`.
 */
export function CoveragePanel({ coverage, executedSources }: CoveragePanelProps) {
  // The backend "completeness" is static capability coverage: a source can be
  // "available" yet not executed at runtime (e.g. public web is unconfigured).
  // Surface that honestly instead of claiming "complete" when a requested
  // source was skipped.
  const requested = coverage?.sources ?? [];
  const skipped = executedSources
    ? requested.filter((source) => !executedSources.includes(source.source_code))
    : [];
  const capability = coverage?.completeness || "Unavailable";
  const label = skipped.length
    ? `${capability} (partial execution: ${skipped.map((s) => sourceLabel(s.source_code)).join(", ")} not searched)`
    : capability;
  return (
    <section className="coverage-panel" aria-label="Source coverage">
      <h2 className="section-title">Source coverage</h2>
      <p className="coverage-completeness">Capability coverage: {label}</p>
      <p className="section-note">
        Coverage describes the listed sources and bounded sample, not the whole internet.
      </p>
      {!coverage?.sources?.length && <p className="drawer-muted">Source capability details unavailable.</p>}
      <ul className="coverage-sources">
        {(coverage?.sources ?? []).map((source) => {
          const executed = executedSources?.includes(source.source_code);
          return (
            <li key={source.source_code} className="coverage-source">
              <span className="source-badge">{sourceLabel(source.source_code)}</span>
              <span className="coverage-capability">Capability: {source.status || "Unavailable"}</span>
              <span
                className="coverage-execution"
                data-searched={executed === undefined ? "unknown" : executed ? "true" : "false"}
              >
                Execution: {executed === undefined ? "Unavailable" : executed ? "Searched" : "Not searched"}
              </span>
              {source.reason && <p className="drawer-muted coverage-reason">{COVERAGE_REASON_TEXT[source.reason] ?? source.reason}</p>}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
