import type { ResearchCoverageResponse } from "@/lib/trendora-api";
import { sourceLabel } from "@/lib/format";

interface CoveragePanelProps {
  coverage?: ResearchCoverageResponse | null;
  executedSources?: string[];
}

/**
 * Shows capability coverage and execution truth separately. Capability
 * availability never implies a source was actually searched; that comes only
 * from `executed_sources`.
 */
export function CoveragePanel({ coverage, executedSources }: CoveragePanelProps) {
  return (
    <section className="coverage-panel" aria-label="Source coverage">
      <h2 className="section-title">Source coverage</h2>
      <p className="coverage-completeness">Capability coverage: {coverage?.completeness || "Unavailable"}</p>
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
              {source.reason && <p className="drawer-muted coverage-reason">{source.reason}</p>}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
