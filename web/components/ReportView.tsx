"use client";

import { useState } from "react";

import type { ResearchReportResponse } from "@/lib/report-api";
import type { ChainLink, ResolvedCitation } from "@/lib/report-provenance";
import {
  buildProvenanceMaps,
  resolveCitation,
  resolveUpstreamChain,
} from "@/lib/report-provenance";
import { briefMarkdown, copyToClipboard, downloadReportJson, ideaMarkdown } from "@/lib/report-actions";
import { sourceLabel } from "@/lib/format";
import { CitationDrawer } from "./CitationDrawer";
import { CoveragePanel } from "./CoveragePanel";
import { MarketCaveat } from "./MarketCaveat";
import { ReferenceList } from "./ReferenceList";
import { EmptyState } from "./EmptyState";

interface DrawerSelection {
  targetLabel: string;
  title: string;
  citations: ResolvedCitation[];
  chain: ChainLink[];
}

interface ReportViewProps {
  report: ResearchReportResponse;
}

function citationsButton(
  targetLabel: string,
  title: string,
  citations: ResolvedCitation[],
  chain: ChainLink[],
  onOpen: (selection: DrawerSelection) => void,
) {
  return (
    <button
      type="button"
      className="citation-toggle"
      onClick={() => onOpen({ targetLabel, title, citations, chain })}
    >
      Trace {citations.length} {citations.length === 1 ? "citation" : "citations"}
    </button>
  );
}

function ClaimKind({ kind }: { kind: "deterministic" | "ai" | "recommendation" }) {
  const label =
    kind === "deterministic"
      ? "Deterministic evidence"
      : kind === "ai"
        ? "AI interpretation"
        : "Recommendation";
  return <span className={`claim-kind claim-kind-${kind}`}>{label}</span>;
}

/** Presentation-only: `description_has_url` → "Description has URL". The raw
 * observation_type is kept everywhere else (keys, citations, provenance). */
function humanizeObservationType(observationType: string): string {
  return observationType
    .split("_")
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export function ReportView({ report }: ReportViewProps) {
  const [drawer, setDrawer] = useState<DrawerSelection | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const maps = buildProvenanceMaps(report);
  const isCompleted = report.status === "completed";
  const research = report.research;

  async function copyIdea(index: number) {
    const idea = report.ideation?.content_ideas[index];
    if (!idea) return;
    try {
      await copyToClipboard(ideaMarkdown(idea));
      setCopied(`idea-${index}`);
    } catch {
      setCopied(`failed-${index}`);
    }
  }

  async function copyBrief(index: number) {
    const brief = report.ideation?.content_briefs[index];
    if (!brief) return;
    try {
      await copyToClipboard(briefMarkdown(brief));
      setCopied(`brief-${index}`);
    } catch {
      setCopied(`failed-${index}`);
    }
  }

  if (!isCompleted) {
    return <NoEvidenceView report={report} />;
  }

  const ideas = report.ideation?.content_ideas ?? [];
  const briefs = report.ideation?.content_briefs ?? [];

  // Group each brief visually with the idea referenced by idea_index.
  const briefsByIdea = new Map<number, { brief: (typeof briefs)[number]; index: number }[]>();
  const orphanBriefs: { brief: (typeof briefs)[number]; index: number }[] = [];
  briefs.forEach((brief, index) => {
    const entry = { brief, index };
    if (brief.idea_index >= 0 && brief.idea_index < ideas.length) {
      const group = briefsByIdea.get(brief.idea_index);
      if (group) {
        group.push(entry);
      } else {
        briefsByIdea.set(brief.idea_index, [entry]);
      }
    } else {
      orphanBriefs.push(entry);
    }
  });

  return (
    <div className="report">
      {/* Primary output — always visible and expanded */}
      <section className="report-primary-section" aria-labelledby="ideas-title">
        <h3 className="section-title" id="ideas-title">
          Content ideas
        </h3>
        {ideas.length === 0 ? (
          <p className="drawer-muted">No content ideas were generated for this report.</p>
        ) : (
          ideas.map((idea, index) => {
            const grouped = briefsByIdea.get(index) ?? [];
            return (
              <article key={index} className="report-item idea-group">
                <ClaimKind kind="recommendation" />
                <h5 className="idea-title">{idea.title}</h5>
                <p className="report-statement">Angle: {idea.angle}</p>
                <button type="button" className="secondary-button" onClick={() => copyIdea(index)}>
                  Copy idea as Markdown
                </button>
                {copied === `idea-${index}` && (
                  <span className="copy-feedback" role="status">
                    Copied
                  </span>
                )}
                {copied === `failed-${index}` && (
                  <span className="copy-feedback copy-failed" role="status">
                    Clipboard unavailable
                  </span>
                )}
                {grouped.length > 0 && (
                  <div className="brief-group">
                    <h6 className="drawer-subheading">Execution briefs</h6>
                    {grouped.map(({ brief, index: briefIndex }) => (
                      <div key={briefIndex} className="brief-card">
                        <p className="report-statement">
                          {brief.objective} · {brief.format}
                        </p>
                        <p className="report-statement">Hook: {brief.hook}</p>
                        <ul className="outline-list">
                          {brief.outline.map((line, lineIndex) => (
                            <li key={lineIndex}>{line}</li>
                          ))}
                        </ul>
                        <button
                          type="button"
                          className="secondary-button"
                          onClick={() => copyBrief(briefIndex)}
                        >
                          Copy brief as Markdown
                        </button>
                        {copied === `brief-${briefIndex}` && (
                          <span className="copy-feedback" role="status">
                            Copied
                          </span>
                        )}
                        {copied === `failed-${briefIndex}` && (
                          <span className="copy-feedback copy-failed" role="status">
                            Clipboard unavailable
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </article>
            );
          })
        )}

        <h3 className="section-title" id="briefs-title">
          Content briefs
        </h3>
        {orphanBriefs.length > 0 ? (
          <div className="brief-fallback">
            <p className="drawer-muted">
              These briefs reference an idea index not present in this report.
              They are shown here rather than discarded.
            </p>
            {orphanBriefs.map(({ brief, index }) => (
              <div key={index} className="brief-card">
                <p className="report-statement">
                  {brief.objective} · {brief.format}
                </p>
                <p className="report-statement">Hook: {brief.hook}</p>
                <ul className="outline-list">
                  {brief.outline.map((line, lineIndex) => (
                    <li key={lineIndex}>{line}</li>
                  ))}
                </ul>
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => copyBrief(index)}
                >
                  Copy brief as Markdown
                </button>
                {copied === `brief-${index}` && (
                  <span className="copy-feedback" role="status">
                    Copied
                  </span>
                )}
              </div>
            ))}
          </div>
        ) : (
          briefs.length === 0 && (
            <p className="drawer-muted">No content briefs were generated for this report.</p>
          )
        )}
      </section>

      {/* Secondary detail — collapsed by default */}
      {(report.evidence?.patterns.length ?? 0) > 0 && (
        <details className="report-section report-secondary-details">
          <summary>Evidence patterns ({report.evidence?.patterns.length})</summary>
          <p className="section-note">
            Deterministic aggregation over the collected references — not AI
            output. Trace a pattern to see every supporting reference.
          </p>
          {report.evidence?.patterns.map((pattern) => {
            const citation = resolveCitation(
              { kind: "pattern", observation_type: pattern.observation_type },
              maps,
            );
            const chain: ChainLink[] = [
              {
                label: "Pattern",
                value: `${pattern.observation_type} — ${pattern.matching_count}/${pattern.analyzed_count} matching`,
                resolved: true,
              },
            ];
            return (
              <article key={pattern.observation_type} className="report-item">
                <div className="report-item-head">
                  <ClaimKind kind="deterministic" />
                  <span className="pattern-counts">
                    {pattern.matching_count}/{pattern.analyzed_count} matching
                  </span>
                </div>
                <p className="report-statement">
                  {humanizeObservationType(pattern.observation_type)}
                </p>
                <p className="drawer-muted">
                  Based on {pattern.analyzed_count} reference
                  {pattern.analyzed_count === 1 ? "" : "s"}:{" "}
                  {pattern.matching_count} matching,{" "}
                  {pattern.non_matching_count} not matching.
                </p>
                {citationsButton(
                  `Pattern: ${pattern.observation_type}`,
                  `${pattern.matching_count}/${pattern.analyzed_count} matching`,
                  [citation],
                  chain,
                  setDrawer,
                )}
              </article>
            );
          })}
        </details>
      )}

      {report.interpretation && report.interpretation.interpretations.length > 0 && (
        <details className="report-section report-secondary-details">
          <summary>
            AI interpretations ({report.interpretation.interpretations.length})
          </summary>
          {report.interpretation.interpretations.map((item, index) => {
            const citations = item.citations.map((citation) => resolveCitation(citation, maps));
            const chain = resolveUpstreamChain(report, { kind: "interpretation", item });
            return (
              <article key={index} className="report-item">
                <ClaimKind kind="ai" />
                <p className="report-statement">{item.statement}</p>
                {citationsButton(
                  `Interpretation #${index}`,
                  item.statement,
                  citations,
                  chain,
                  setDrawer,
                )}
              </article>
            );
          })}
        </details>
      )}

      {report.strategy && (
        <details className="report-section report-secondary-details">
          <summary>Gaps and opportunities</summary>
          <h4 className="drawer-subheading">Gaps</h4>
          {report.strategy.content_gaps.map((gap, index) => {
            const citations = gap.citations.map((citation) => resolveCitation(citation, maps));
            const chain = resolveUpstreamChain(report, { kind: "gap", item: gap });
            return (
              <article key={index} className="report-item">
                <ClaimKind kind="ai" />
                <p className="report-statement">{gap.statement}</p>
                {citationsButton(`Gap #${index}`, gap.statement, citations, chain, setDrawer)}
              </article>
            );
          })}
          <h4 className="drawer-subheading">Opportunities</h4>
          {report.strategy.opportunities.map((opportunity, index) => {
            const citations = opportunity.citations.map((citation) =>
              resolveCitation(citation, maps),
            );
            const chain = resolveUpstreamChain(report, { kind: "opportunity", item: opportunity });
            return (
              <article key={index} className="report-item">
                <ClaimKind kind="recommendation" />
                <p className="report-statement">{opportunity.statement}</p>
                {citationsButton(
                  `Opportunity #${index}`,
                  opportunity.statement,
                  citations,
                  chain,
                  setDrawer,
                )}
              </article>
            );
          })}
        </details>
      )}

      {/* Sources and evidence */}
      <details className="report-section report-secondary-details">
        <summary>Sources and evidence ({research.references.length})</summary>
        {research.references.length > 0 ? (
          <ReferenceList references={research.references} />
        ) : (
          <EmptyState />
        )}
      </details>

      {/* Research scope, coverage, and provenance — progressive disclosure */}
      <details className="report-section report-secondary-details">
        <summary>Research scope, coverage, and provenance</summary>
        <CoveragePanel coverage={research.coverage} executedSources={research.executed_sources} />
        <ul className="provenance-list">
          <li>Report status: {report.status}</li>
          <li>
            Executed sources:{" "}
            {research.executed_sources.map(sourceLabel).join(", ") || "none"}
          </li>
          <li>
            Requested sources:{" "}
            {research.query.sources.map(sourceLabel).join(", ") || "none"}
          </li>
          <li>References: {research.references.length}</li>
        </ul>
        <p className="drawer-muted">
          Coverage reflects capability truth; executed sources reflect what was
          actually searched. Structural grounding is not proof of semantic
          entailment.
        </p>
        <MarketCaveat
          markets={research.query.markets}
          executedSources={research.executed_sources}
        />
        <button
          type="button"
          className="secondary-button"
          onClick={() => downloadReportJson(report)}
        >
          Download report JSON
        </button>
      </details>

      {drawer && (
        <CitationDrawer
          open
          title={drawer.title}
          targetLabel={drawer.targetLabel}
          citations={drawer.citations}
          chain={drawer.chain}
          onClose={() => setDrawer(null)}
        />
      )}
    </div>
  );
}

function NoEvidenceView({ report }: { report: ResearchReportResponse }) {
  const research = report.research;
  return (
    <div className="report">
      <div className="empty-state">
        <h3 className="section-title">No evidence</h3>
        <p>
          Retrieval completed but returned no usable references. No
          interpretations, gaps, opportunities, ideas, or briefs were
          generated for this request.
        </p>
        {research.references.length > 0 && (
          <p className="drawer-muted">
            References: {research.references.length}
          </p>
        )}
      </div>
      <details className="report-section">
        <summary>Research scope, coverage, and provenance</summary>
        <CoveragePanel coverage={research.coverage} executedSources={research.executed_sources} />
        <ul className="provenance-list">
          <li>Report status: {report.status}</li>
          <li>
            Executed sources:{" "}
            {research.executed_sources.map(sourceLabel).join(", ") || "none"}
          </li>
          <li>
            Requested sources:{" "}
            {research.query.sources.map(sourceLabel).join(", ") || "none"}
          </li>
          <li>References: {research.references.length}</li>
        </ul>
        <p className="drawer-muted">
          Coverage reflects capability truth; executed sources reflect what was
          actually searched.
        </p>
        <MarketCaveat
          markets={research.query.markets}
          executedSources={research.executed_sources}
        />
        <button type="button" className="secondary-button" onClick={() => downloadReportJson(report)}>
          Download report JSON
        </button>
      </details>
    </div>
  );
}
