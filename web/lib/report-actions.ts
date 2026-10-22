/**
 * Report output actions: full Markdown copy/export, browser print, idea/brief
 * Markdown, and exact JSON download. Uses returned content only; no invented
 * text, and provenance caveats are never dropped to make an export look neater.
 */

import type {
  ContentBriefJson,
  ContentIdeaJson,
  ResearchReportResponse,
} from "./report-api.ts";
import {
  buildProvenanceMaps,
  citationPublicationScope,
  classifyFindingSupport,
  hasSourceBackedSummaries,
  publicationScope,
  publicationScopeLabel,
  resolveCitation,
  type ResolvedCitation,
} from "./report-provenance.ts";
import { sourceLabel } from "./format.ts";

export function ideaMarkdown(idea: ContentIdeaJson): string {
  const lines = [
    `## ${idea.title}`,
    "",
    `**Angle:** ${idea.angle}`,
    "",
    `**Opportunity indexes:** ${idea.opportunity_indexes.join(", ") || "Unknown"}`,
    "",
    `**Citations:** ${idea.citations.length}`,
  ];
  return lines.join("\n");
}

export function briefMarkdown(brief: ContentBriefJson): string {
  const lines = [
    "## Content Brief",
    "",
    `**Idea index:** ${brief.idea_index}`,
    "",
    `**Objective:** ${brief.objective}`,
    "",
    `**Format:** ${brief.format}`,
    "",
    `**Hook:** ${brief.hook}`,
    "",
    "**Outline:**",
    ...brief.outline.map((item) => `- ${item}`),
  ];
  return lines.join("\n");
}

export async function copyToClipboard(text: string): Promise<void> {
  if (!navigator.clipboard || !navigator.clipboard.writeText) {
    throw new Error("Clipboard is not available in this browser.");
  }
  await navigator.clipboard.writeText(text);
}

export function downloadReportJson(report: ResearchReportResponse): void {
  const blob = new Blob([JSON.stringify(report, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "trendora-report.json";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

/** Source text is escaped for Markdown so returned HTML-looking strings stay
 * literal text, not markup, in the copied document. */
function mdText(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/([\\[\]`])/g, "\\$1");
}

function mdDate(value: string | null | undefined): string {
  return value ? mdText(value) : "Unknown";
}

/** Only http(s) source URLs become links; anything else is stated as unsafe. */
function sourceLink(url: string | null): string {
  if (!url || !/^https?:\/\/[^\s<>]+$/i.test(url)) {
    return "Original URL unavailable or not a safe web link.";
  }
  return `<${url}>`;
}

interface SourceAnchor {
  index: number;
  label: string;
  title: string;
}

function sourceAnchors(report: ResearchReportResponse): Map<string, SourceAnchor> {
  const anchors = new Map<string, SourceAnchor>();
  (report.research.references ?? []).forEach((reference, index) => {
    const key = `${reference.source_code}:${reference.content_external_id}`;
    anchors.set(key, {
      index: index + 1,
      label: `source-${index + 1}`,
      title: reference.title || "Untitled source",
    });
  });
  return anchors;
}

function citedBy(citation: ResolvedCitation, anchors: Map<string, SourceAnchor>): string {
  const links = citation.references.map((entry) => {
    const key = `${entry.referenceId.source_code}:${entry.referenceId.content_external_id}`;
    const anchor = anchors.get(key);
    return anchor ? `[Source ${anchor.index}](#${anchor.label})` : `Unresolved source ${key}`;
  });
  if (links.length === 0 && citation.unresolvedIdentifiers.length > 0) {
    links.push(`Unresolved provenance: ${citation.unresolvedIdentifiers.join(", ")}`);
  }
  return links.length ? links.join(", ") : "No resolved source";
}

/** The exact cited fact value from the evidence map, or its unavailable reason. */
function citedEvidence(citation: ResolvedCitation): string {
  if (!citation.textEvidence) return "";
  if (citation.textEvidence.value !== null) {
    return `> Cited ${mdText(citation.targetId)}: ${mdText(citation.textEvidence.value)}`;
  }
  return `> ${mdText(citation.textEvidence.unavailableReason ?? "Cited text unavailable.")}`;
}

function citationBlock(citation: ResolvedCitation, anchors: Map<string, SourceAnchor>): string[] {
  return [
    `- ${mdText(citation.kind)}: ${mdText(citation.detail)}`,
    ...(citation.textEvidence ? [`  ${citedEvidence(citation)}`] : []),
    `  Sources: ${citedBy(citation, anchors)}`,
  ];
}

function modelLine(label: string, provenance?: { provider: string; model: string } | null): string {
  return provenance
    ? `- ${label} model: ${mdText(provenance.provider)} / ${mdText(provenance.model)}`
    : `- ${label} model: unavailable`;
}

function marketCaveats(report: ResearchReportResponse): string[] {
  const executed = report.research.executed_sources ?? [];
  const markets = report.research.query?.markets ?? [];
  const lines: string[] = [];
  if (executed.includes("youtube")) {
    lines.push(
      markets.length
        ? `- YouTube market context: ${mdText(markets.join(", "))} reflects regional availability/viewability and does not establish creator nationality or content origin.`
        : "- Global search: no country restriction was applied. YouTube availability does not establish creator nationality or content origin.",
    );
  }
  if (executed.includes("facebook")) {
    lines.push(
      `- Facebook market context: ${mdText(markets.join(", ") || "Global")}: collection used the explicit Facebook Page and date range; topic and market did not filter the collected Page posts.`,
    );
  }
  return lines;
}

/**
 * A complete report as Markdown. Every claim keeps its citation, every source
 * keeps its identity and link (when safe), and the report's own coverage,
 * date-uncertainty, excess-metrics, and diagnostics caveats travel with it.
 */
export function reportMarkdown(report: ResearchReportResponse): string {
  const maps = buildProvenanceMaps(report);
  const anchors = sourceAnchors(report);
  const references = report.research.references ?? [];
  const query = report.research.query;
  const executed = report.research.executed_sources;
  const sourceBacked = hasSourceBackedSummaries(report);
  const lines: string[] = [];
  const push = (...items: string[]) => lines.push(...items);

  push(`# Research report: ${mdText(query?.topic || "Untitled topic")}`, "");

  push("## Research scope", "");
  push(`- Requested timeframe: ${mdDate(query?.date_from)} to ${mdDate(query?.date_to)}`);
  push(`- Scope: ${query?.markets?.length ? mdText(query.markets.join(", ")) : "Global (no country restriction)"}`);
  push(`- Requested sources: ${query?.sources?.length ? query.sources.map(sourceLabel).join(", ") : "Unavailable"}`);
  push(`- Sources searched: ${executed ? executed.map(sourceLabel).join(", ") || "None" : "Unavailable"}`);
  push(`- References: ${references.length}`);
  push("- Coverage: describes the listed sources and bounded sample, not the whole internet.");
  if (!executed) {
    push("- Execution details are unavailable in this report. This does not prove a search ran.");
  } else {
    const notSearched = (query?.sources ?? []).filter((code) => !executed.includes(code));
    if (notSearched.length) push(`- Requested but not searched: ${notSearched.map(sourceLabel).join(", ")}.`);
  }
  if (executed?.includes("public_web")) {
    push("- Public web search did not enforce the requested timeframe.");
  }
  push(...marketCaveats(report));
  push("- Timeframe coverage is unverified. Publication dates are source metadata; collection dates do not establish when a development happened.");
  push("- Counts observed at collection, not a measure of growth. Missing values are unknown.", "");

  const coverage = report.research.coverage;
  if (coverage) {
    push("### Source coverage", "");
    push(`- Capability completeness: ${mdText(coverage.completeness)}`);
    for (const source of coverage.sources ?? []) {
      push(`- ${mdText(source.source_code)}: capability ${mdText(source.capability)}, status ${mdText(source.status)}, reason ${mdText(source.reason ?? "None")}`);
    }
    push("");
  }

  push(modelLine("Interpretation", report.interpretation?.model_provenance), "");

  const interpretations = report.interpretation?.interpretations ?? [];
  const findings = interpretations.map((item, index) => {
    const citations = (item.citations ?? []).map((citation) => resolveCitation(citation, maps));
    return {
      item,
      index,
      citations,
      scope: citationPublicationScope(citations, query),
      bucket: classifyFindingSupport(maps, citations),
    };
  });
  const primaryFindings = findings.filter((entry) => entry.bucket === "finding");
  const observationFindings = findings.filter((entry) => entry.bucket === "observation");
  const limitedFindings = findings.filter((entry) => entry.bucket === "limited");

  const findingBlock = (entry: (typeof findings)[number], label: string) => {
    push(`### ${label} ${entry.index + 1}`, "");
    const statement = mdText(entry.item.statement);
    push(sourceBacked && entry.bucket === "finding" ? `> ${statement}` : statement, "");
    push(`Publication scope: ${publicationScopeLabel(entry.scope)}.`, "");
    for (const citation of entry.citations) push(...citationBlock(citation, anchors));
    push("");
  };

  if (primaryFindings.length > 0) {
    push("## Research findings", "");
    if (sourceBacked) {
      push("These are source-attributed excerpts, not synthesized findings. A source's statement and publication date do not independently verify an event or its date.", "");
    } else {
      push("AI synthesis of the collected material. Citations show supporting evidence, but do not independently verify a claim or its significance.", "");
    }
    push("Publication dates do not establish event dates. Event dates are unavailable.", "");
    for (const entry of primaryFindings) findingBlock(entry, "Finding");
  }

  if (observationFindings.length > 0) {
    push("## AI observations about the sample", "");
    push("These interpretations concern patterns, formatting, or metrics in the collected sample. They do not establish developments or growing attention.", "");
    for (const entry of observationFindings) findingBlock(entry, "AI observation");
  }

  if (limitedFindings.length > 0) {
    push("## Interpretations with limited evidence", "");
    push("The cited evidence is missing, incomplete, or insufficient to support a research finding. These interpretations are retained for reference.", "");
    for (const entry of limitedFindings) findingBlock(entry, "Interpretation");
  }

  if (findings.length === 0) {
    push("No interpretations are available in this report.", "");
  }

  const patterns = report.evidence?.patterns ?? [];
  if (patterns.length) {
    push("## Evidence patterns", "");
    push("Sample prevalence among the analyzed references, not evidence of growing attention.", "");
    for (const pattern of patterns) {
      push(`- ${mdText(pattern.observation_type)}: ${pattern.matching_count}/${pattern.analyzed_count} matching (${pattern.non_matching_count} not matching).`);
    }
    push("");
  }

  push("## Sources", "");
  if (references.length === 0) {
    push("No source references are available in this report.", "");
  }
  references.forEach((reference, index) => {
    const anchor = `source-${index + 1}`;
    const scope = publicationScope(reference.published_at, query);
    push(`### <a id="${anchor}"></a>Source ${index + 1}: ${mdText(reference.title || "Untitled source")}`);
    push("");
    push(`- Identity: ${mdText(reference.source_code)}:${mdText(reference.content_external_id)}`);
    push(`- Link: ${sourceLink(reference.url)}`);
    push(`- Published: ${mdDate(reference.published_at)}`);
    push(`- Collection date: ${mdDate(reference.collected_at)}`);
    push(`- ${publicationScopeLabel(scope)}.`);
    if (reference.source_code === "public_web") {
      push("- Timeframe coverage is unverified for this public-web result.");
    }
    if ((reference.market_contexts?.length ?? 0) > 0) {
      push(`- Regional availability/viewability: ${mdText(reference.market_contexts.join(" · "))}.`);
    }
    const metrics = reference.metrics;
    if (metrics && (reference.source_code === "youtube" || reference.source_code === "facebook")) {
      push(`- Counts observed at collection, not a measure of growth: views ${metrics.view_count ?? "unknown"}, likes ${metrics.like_count ?? "unknown"}, comments ${metrics.comment_count ?? "unknown"}, reactions ${metrics.reaction_count ?? "unknown"}, shares ${metrics.share_count ?? "unknown"}.`);
    }
    if (reference.description) push(`- Description (source material): ${mdText(reference.description)}`);
    push("");
  });

  const strategy = report.strategy;
  if (strategy) {
    push("## Gaps and opportunities", "");
    push(modelLine("Strategy", strategy.model_provenance), "");
    strategy.content_gaps?.forEach((gap, index) => {
      push(`### Gap ${index + 1}`, "");
      push(`> ${mdText(gap.statement)}`, "");
      for (const citation of gap.citations ?? []) push(...citationBlock(resolveCitation(citation, maps), anchors));
      push("");
    });
    strategy.opportunities?.forEach((opportunity, index) => {
      push(`### Opportunity ${index + 1}`, "");
      push(`> ${mdText(opportunity.statement)}`, "");
      for (const citation of opportunity.citations ?? []) push(...citationBlock(resolveCitation(citation, maps), anchors));
      push("");
    });
  }

  const ideation = report.ideation;
  if (ideation) {
    push("## Content ideas", "");
    push(modelLine("Ideation", ideation.model_provenance), "");
    ideation.content_ideas?.forEach((idea, index) => {
      push(`### Idea ${index + 1}: ${mdText(idea.title)}`, "");
      push(`- Angle: ${mdText(idea.angle)}`);
      push(`- Opportunity indexes: ${idea.opportunity_indexes.join(", ") || "Unknown"}`);
      for (const citation of idea.citations ?? []) push(...citationBlock(resolveCitation(citation, maps), anchors));
      push("");
    });
    push("## Content briefs", "");
    ideation.content_briefs?.forEach((brief, index) => {
      push(`### Brief ${index + 1}`, "");
      push(`- Idea index: ${brief.idea_index}`);
      push(`- Objective: ${mdText(brief.objective)}`);
      push(`- Format: ${mdText(brief.format)}`);
      push(`- Hook: ${mdText(brief.hook)}`);
      push("- Outline:");
      for (const line of brief.outline ?? []) push(`  - ${mdText(line)}`);
      for (const citation of brief.citations ?? []) push(...citationBlock(resolveCitation(citation, maps), anchors));
      push("");
    });
  }

  push("## Run diagnostics", "");
  const runDetails = report.run_details;
  if (runDetails) {
    push("```json", JSON.stringify(runDetails, null, 2) ?? "null", "```", "");
    push("Stage durations and AI request timings are measurements for this response only. Serialized request bytes are not tokens or billing. Provider-reported token usage may be missing or not add up; missing usage is unknown, not zero.", "");
  } else {
    push("Run diagnostics unavailable for this report. Measurements were not recorded when this report was saved.", "");
    push("Missing diagnostics do not imply zero elapsed time, zero retries, or zero AI requests. Saved reports do not retain fresh-run measurements.", "");
  }

  if (report.persistence) {
    push("## Save provenance", "");
    push(`- Persistence: ${mdText(report.persistence.status)}`);
    push(`- Snapshot origin: ${mdText(report.persistence.snapshot_origin)}`);
    if (report.persistence.report_id) push(`- Report ID: ${mdText(report.persistence.report_id)}`);
    push("");
  }

  return lines.join("\n");
}

/**
 * Open every disclosure in the report, print through the browser (including
 * Save as PDF), then restore the previous disclosure state even when the
 * native print call throws. Print-only markup stays hidden on screen.
 */
export function printReport(root: HTMLElement = document.body): void {
  const details = Array.from(root.querySelectorAll("details"));
  const previous = details.map((detail) => detail.open);
  details.forEach((detail) => {
    detail.open = true;
  });
  root.setAttribute("data-print-open", "");
  try {
    const view = root.ownerDocument?.defaultView ?? window;
    view.print();
  } finally {
    details.forEach((detail, index) => {
      detail.open = previous[index];
    });
    root.removeAttribute("data-print-open");
  }
}
