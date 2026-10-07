"use client";

import { useState } from "react";

import type { ResearchReportResponse } from "@/lib/report-api";
import type { ChainLink, ResolvedCitation } from "@/lib/report-provenance";
import {
  buildProvenanceMaps,
  hasSourceBackedSummaries,
  citationPublicationScope,
  publicationScopeLabel,
  resolveCitation,
  resolveUpstreamChain,
} from "@/lib/report-provenance";
import { briefMarkdown, copyToClipboard, downloadReportJson, ideaMarkdown } from "@/lib/report-actions";
import { formatDate, sourceLabel } from "@/lib/format";
import { CitationDrawer } from "./CitationDrawer";
import { CoveragePanel } from "./CoveragePanel";
import { MarketCaveat } from "./MarketCaveat";
import { ReferenceList } from "./ReferenceList";
import { ReportPersistencePanel } from "./ReportPersistencePanel";
import { SaveToPlanner } from "./SaveToPlanner";

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
  // The canonical report id is shared here so a successful recovery reaches
  // every import button. It starts from the generation outcome and is updated
  // once by the persistence panel after a confirmed save.
  const [reportId, setReportId] = useState<string | null>(
    report.persistence?.report_id ?? null,
  );
  const maps = buildProvenanceMaps(report);
  const sourceBacked = hasSourceBackedSummaries(report);
  const references = report.research.references ?? [];

  async function copyIdea(index: number) {
    const idea = report.ideation?.content_ideas?.[index];
    if (!idea) return;
    try {
      await copyToClipboard(ideaMarkdown(idea));
      setCopied(`idea-${index}`);
    } catch {
      setCopied(`failed-${index}`);
    }
  }

  async function copyBrief(index: number) {
    const brief = report.ideation?.content_briefs?.[index];
    if (!brief) return;
    try {
      await copyToClipboard(briefMarkdown(brief));
      setCopied(`brief-${index}`);
    } catch {
      setCopied(`failed-${index}`);
    }
  }

  if (report.status === "no_evidence") {
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

  const contentIdeas = (
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
                <SaveToPlanner
                  reportId={reportId}
                  itemKind="idea"
                  itemIndex={index}
                />
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
                        <SaveToPlanner
                          reportId={reportId}
                          itemKind="brief"
                          itemIndex={briefIndex}
                        />
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
  );

  const interpretations = report.interpretation?.interpretations ?? [];
  const findings = interpretations.map((item, index) => {
    const citations = (item.citations ?? []).map((citation) => resolveCitation(citation, maps));
    return { item, index, citations, scope: citationPublicationScope(citations, report.research.query) };
  });

  function finding({ item, index, citations, scope }: (typeof findings)[number]) {
    const chain = resolveUpstreamChain(report, { kind: "interpretation", item });
    return (
      <article key={index} className="report-item" data-finding-scope={scope}>
        {sourceBacked ? <span className="claim-kind claim-kind-ai">Source-attributed excerpt</span> : <ClaimKind kind="ai" />}
        <p className="report-statement">{sourceBacked ? `“${item.statement}”` : item.statement}</p>
        {citationsButton(sourceBacked ? `Source-backed summary #${index}` : `Interpretation #${index}`, item.statement, citations, chain, setDrawer)}
      </article>
    );
  }

  return (
    <div className="report">
      <ReportPersistencePanel report={report} onResolved={setReportId} />
      <section className="report-primary-section" aria-labelledby="findings-title">
        <h3 className="section-title" id="findings-title">Research findings</h3>
        <p className="section-note">
          {sourceBacked
            ? "These are source-attributed excerpts, not synthesized findings. A source’s statement and publication date do not independently verify an event or its date. Event dates are unavailable."
            : "AI synthesis of the collected material. Citations show supporting evidence, but do not independently verify a claim or its significance. Publication dates do not establish event dates. Event dates are unavailable."}
        </p>
        {report.status === "research_unavailable" && (
          <p className="drawer-muted">Sourced summaries are unavailable. Collected sources and evidence remain available below.</p>
        )}
        {report.status === "insufficient_evidence" && (
          <p className="drawer-muted">Insufficient source text for a sourced summary. No development claim is inferred from dates or counts.</p>
        )}
        {findings.length === 0 ? (
          <p className="drawer-muted">No research findings are available in this report.</p>
        ) : (["in_window", "outside_window", "undated", "unknown_window"] as const).map((scope) => {
          const group = findings.filter((entry) => entry.scope === scope);
          return group.length ? <section key={scope} aria-label={publicationScopeLabel(scope)}>
            <h4 className="drawer-subheading">{publicationScopeLabel(scope)}</h4>
            {group.map(finding)}
          </section> : null;
        })}
      </section>

      <ReportScope report={report} />

      <section className="report-primary-section" aria-labelledby="sources-title">
        <h3 className="section-title" id="sources-title">Sources and evidence ({references.length})</h3>
        <p className="section-note">
          Titles and descriptions are source material, not verified event summaries.
          No measured trend evidence is available in this report.
        </p>
        {references.length > 0 ? (
          <ReferenceList references={references} window={report.research.query} />
        ) : (
          <p className="drawer-muted">No source references are available in this report.</p>
        )}
      </section>

      {(report.evidence?.patterns?.length ?? 0) > 0 && (
        <details className="report-section report-secondary-details">
          <summary>Evidence patterns ({report.evidence?.patterns.length})</summary>
          <p className="section-note">
            Sample prevalence among the analyzed references, not evidence of
            growing attention. Trace a pattern to inspect its supporting sources.
          </p>
          {report.evidence?.patterns?.map((pattern) => {
            const citation = resolveCitation(
              { kind: "pattern", observation_type: pattern.observation_type },
              maps,
            );
            const chain: ChainLink[] = [
              {
                label: "Pattern",
                value: `${pattern.observation_type}: ${pattern.matching_count}/${pattern.analyzed_count} matching`,
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

      <details className="report-section report-secondary-details">
        <summary>Content tools (optional)</summary>
        {report.status === "content_unavailable" ? (
          <p className="drawer-muted">Content generation is unavailable. Your research is preserved and can be saved.</p>
        ) : !report.strategy && !report.ideation && (
          <p className="drawer-muted">Content tools were not generated for this report.</p>
        )}
        {contentIdeas}
      {report.strategy && (
        <details className="report-section report-secondary-details">
          <summary>Gaps and opportunities</summary>
          <h4 className="drawer-subheading">Gaps</h4>
          {(report.strategy.content_gaps ?? []).map((gap, index) => {
            const citations = (gap.citations ?? []).map((citation) => resolveCitation(citation, maps));
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
          {(report.strategy.opportunities ?? []).map((opportunity, index) => {
            const citations = (opportunity.citations ?? []).map((citation) =>
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

      </details>

      <button type="button" className="secondary-button" onClick={() => downloadReportJson(report)}>
        Download report JSON
      </button>

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

function ReportScope({ report }: { report: ResearchReportResponse }) {
  const research = report.research;
  const query = research.query;
  const references = research.references ?? [];
  const collectedDates = [...new Set(references.map((reference) => formatDate(reference.collected_at)))];
  const knownDates = collectedDates.filter((date) => date !== "—");
  const hasPublicWeb = research.executed_sources?.includes("public_web") ||
    references.some((reference) => reference.source_code === "public_web");
  return (
    <section className="report-primary-section" aria-label="Research scope">
      <h3 className="section-title">Research scope</h3>
      <ul className="provenance-list">
        <li>Topic: {query?.topic || "Unavailable"}</li>
        <li>Requested timeframe: {query?.date_from || "Unknown"} to {query?.date_to || "Unknown"}</li>
        <li>Requested sources: {query?.sources?.map(sourceLabel).join(", ") || "Unavailable"}</li>
        <li>Sources searched: {research.executed_sources?.map(sourceLabel).join(", ") || (research.executed_sources ? "None" : "Unavailable")}</li>
        <li>References: {research.references ? references.length : "Unavailable"}</li>
        <li>
          Collection dates: {knownDates.join(", ") || "Unknown"}
          {knownDates.length > 0 && collectedDates.includes("—") && "; some collection dates unknown"}
        </li>
      </ul>
      <p className="section-note">
        Timeframe coverage is unverified. Publication dates are source metadata;
        collection dates do not establish when a development happened.
      </p>
      {hasPublicWeb && (
        <p className="section-note">Public-web results were not verified against the requested timeframe.</p>
      )}
      <CoveragePanel coverage={research.coverage} executedSources={research.executed_sources} />
      <MarketCaveat markets={query?.markets ?? []} executedSources={research.executed_sources ?? []} />
    </section>
  );
}

function NoEvidenceView({ report }: { report: ResearchReportResponse }) {
  return (
    <div className="report">
      <ReportPersistencePanel report={report} />
      <div className="empty-state">
        <h3 className="section-title">Research findings</h3>
        <p>No research findings are available in this report.</p>
        <p className="drawer-muted">Report status: {report.status}</p>
      </div>
      <ReportScope report={report} />
      {(report.research.references?.length ?? 0) > 0 && (
        <ReferenceList references={report.research.references} window={report.research.query} />
      )}
      <button type="button" className="secondary-button" onClick={() => downloadReportJson(report)}>
        Download report JSON
      </button>
    </div>
  );
}
