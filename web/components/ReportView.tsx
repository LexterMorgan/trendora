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

export function ReportView({ report }: ReportViewProps) {
  const [drawer, setDrawer] = useState<DrawerSelection | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const maps = buildProvenanceMaps(report);
  const isCompleted = report.status === "completed";

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

  const provenance = [
    `Report status: ${report.status}`,
    `Executed sources: ${report.research.executed_sources.map(sourceLabel).join(", ") || "none"}`,
    `Requested sources: ${report.research.query.sources.map(sourceLabel).join(", ") || "none"}`,
    `References: ${report.research.references.length}`,
  ];

  return (
    <div className="report">
      <div className="result-header report-top">
        <h3 className="section-title">Truth &amp; provenance</h3>
        <ul className="provenance-list">
          {provenance.map((item, index) => (
            <li key={index}>{item}</li>
          ))}
        </ul>
        <p className="drawer-muted">
          Coverage reflects capability truth; executed sources reflect what was
          actually searched. Structural grounding is not proof of semantic
          entailment.
        </p>
        <MarketCaveat market={report.research.query.market} />
        <button type="button" className="secondary-button" onClick={() => downloadReportJson(report)}>
          Download report JSON
        </button>
      </div>

      <details className="report-section" open>
        <summary>Research execution and coverage</summary>
        <CoveragePanel
          coverage={report.research.coverage}
          executedSources={report.research.executed_sources}
        />
      </details>

      {isCompleted ? (
        <>
          <details className="report-section">
            <summary>Evidence and references ({report.research.references.length})</summary>
            {report.research.references.length > 0 ? (
              <ReferenceList references={report.research.references} />
            ) : (
              <EmptyState />
            )}
          </details>

          {report.interpretation && (
            <details className="report-section">
              <summary>AI interpretations ({report.interpretation.interpretations.length})</summary>
              {report.interpretation.interpretations.map((item, index) => {
                const citations = item.citations.map((citation) => resolveCitation(citation, maps));
                const chain = resolveUpstreamChain(report, { kind: "interpretation", item });
                return (
                  <article key={index} className="report-item">
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
            <details className="report-section">
              <summary>
                Content gaps ({report.strategy.content_gaps.length}) &amp; opportunities (
                {report.strategy.opportunities.length})
              </summary>
              <h4 className="drawer-subheading">Gaps</h4>
              {report.strategy.content_gaps.map((gap, index) => {
                const citations = gap.citations.map((citation) => resolveCitation(citation, maps));
                const chain = resolveUpstreamChain(report, { kind: "gap", item: gap });
                return (
                  <article key={index} className="report-item">
                    <p className="report-statement">{gap.statement}</p>
                    <p className="drawer-muted">
                      Supporting interpretations: {gap.supporting_interpretation_indexes.join(", ")}
                    </p>
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
                    <p className="report-statement">{opportunity.statement}</p>
                    <p className="drawer-muted">Gap indexes: {opportunity.gap_indexes.join(", ")}</p>
                    {citationsButton(`Opportunity #${index}`, opportunity.statement, citations, chain, setDrawer)}
                  </article>
                );
              })}
            </details>
          )}

          {report.ideation && (
            <details className="report-section">
              <summary>
                Content ideas ({report.ideation.content_ideas.length}) &amp; briefs (
                {report.ideation.content_briefs.length})
              </summary>
              <h4 className="drawer-subheading">Ideas</h4>
              {report.ideation.content_ideas.map((idea, index) => {
                const citations = idea.citations.map((citation) => resolveCitation(citation, maps));
                const chain = resolveUpstreamChain(report, { kind: "idea", item: idea });
                return (
                  <article key={index} className="report-item">
                    <h5 className="idea-title">{idea.title}</h5>
                    <p className="report-statement">Angle: {idea.angle}</p>
                    <p className="drawer-muted">Opportunity indexes: {idea.opportunity_indexes.join(", ")}</p>
                    {citationsButton(`Idea #${index}`, idea.title, citations, chain, setDrawer)}
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
                  </article>
                );
              })}
              <h4 className="drawer-subheading">Briefs</h4>
              {report.ideation.content_briefs.map((brief, index) => {
                const citations = brief.citations.map((citation) => resolveCitation(citation, maps));
                const chain = resolveUpstreamChain(report, { kind: "brief", item: brief });
                return (
                  <article key={index} className="report-item">
                    <h5 className="idea-title">Brief for idea #{brief.idea_index}</h5>
                    <p className="report-statement">
                      {brief.objective} · {brief.format}
                    </p>
                    <p className="report-statement">Hook: {brief.hook}</p>
                    <ul className="outline-list">
                      {brief.outline.map((line, lineIndex) => (
                        <li key={lineIndex}>{line}</li>
                      ))}
                    </ul>
                    {citationsButton(`Brief #${index}`, `idea ${brief.idea_index}`, citations, chain, setDrawer)}
                    <button type="button" className="secondary-button" onClick={() => copyBrief(index)}>
                      Copy brief as Markdown
                    </button>
                    {copied === `brief-${index}` && (
                      <span className="copy-feedback" role="status">
                        Copied
                      </span>
                    )}
                    {copied === `failed-${index}` && (
                      <span className="copy-feedback copy-failed" role="status">
                        Clipboard unavailable
                      </span>
                    )}
                  </article>
                );
              })}
            </details>
          )}
        </>
      ) : (
        <div className="empty-state">
          <h3 className="section-title">No evidence</h3>
          <p>
            Retrieval completed but returned no usable references. No
            interpretations, gaps, opportunities, ideas, or briefs were
            generated for this request.
          </p>
          {report.research.references.length > 0 && (
            <p className="drawer-muted">
              References: {report.research.references.length}
            </p>
          )}
        </div>
      )}

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
