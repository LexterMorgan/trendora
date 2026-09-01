import type { ResearchCoverageResponse } from "@/lib/trendora-api";
import { sourceLabel } from "@/lib/format";

interface CoveragePanelProps {
  coverage: ResearchCoverageResponse;
  executedSources: string[];
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
      <p className="coverage-completeness">Completeness: {coverage.completeness}</p>
      <ul className="coverage-sources">
        {coverage.sources.map((source) => {
          const executed = executedSources.includes(source.source_code);
          return (
            <li key={source.source_code} className="coverage-source">
              <span className="source-badge">{sourceLabel(source.source_code)}</span>
              <span className="coverage-capability">Capability: {source.status}</span>
              <span
                className="coverage-execution"
                data-searched={executed ? "true" : "false"}
              >
                Execution: {executed ? "Searched" : "Not searched"}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
