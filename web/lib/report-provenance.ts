/**
 * Citation/provenance resolution over an M23A report. Builds lookup maps from
 * returned data only; never infers missing links. Unresolvable links are
 * surfaced explicitly.
 */

import type { ResearchReferenceResponse } from "@/lib/trendora-api";
import type {
  CitationJson,
  ContentBriefJson,
  ContentGapJson,
  ContentIdeaJson,
  EvidenceAnalysisJson,
  InterpretationItemJson,
  OpportunityJson,
  PatternAggregateJson,
  ReferenceIdJson,
  ResearchReportResponse,
} from "@/lib/report-api";

export function referenceKey(reference: ReferenceIdJson): string {
  return `${reference.source_code}:${reference.content_external_id}`;
}

export interface ProvenanceMaps {
  referenceById: Map<string, ResearchReferenceResponse>;
  analysisById: Map<string, EvidenceAnalysisJson>;
  patternByType: Map<string, PatternAggregateJson>;
}

export function buildProvenanceMaps(report: ResearchReportResponse): ProvenanceMaps {
  const referenceById = new Map<string, ResearchReferenceResponse>();
  for (const reference of report.research.references) {
    referenceById.set(
      referenceKey({ source_code: reference.source_code, content_external_id: reference.content_external_id }),
      reference,
    );
  }
  const analysisById = new Map<string, EvidenceAnalysisJson>();
  if (report.evidence) {
    for (const analysis of report.evidence.analyses) {
      analysisById.set(referenceKey(analysis.reference_id), analysis);
    }
  }
  const patternByType = new Map<string, PatternAggregateJson>();
  if (report.evidence) {
    for (const pattern of report.evidence.patterns) {
      patternByType.set(pattern.observation_type, pattern);
    }
  }
  return { referenceById, analysisById, patternByType };
}

export interface ResolvedReference {
  referenceId: ReferenceIdJson;
  reference: ResearchReferenceResponse;
  title: string | null;
  source: string;
  url: string | null;
}

export interface ResolvedCitation {
  citation: CitationJson;
  kind: string;
  targetId: string;
  resolved: boolean;
  references: ResolvedReference[];
  unresolvedIdentifiers: string[];
  detail: string;
}

export function resolveCitation(citation: CitationJson, maps: ProvenanceMaps): ResolvedCitation {
  if (citation.kind === "pattern") {
    const pattern = maps.patternByType.get(citation.observation_type);
    if (!pattern) {
      return {
        citation,
        kind: "pattern",
        targetId: citation.observation_type,
        resolved: false,
        references: [],
        unresolvedIdentifiers: [citation.observation_type],
        detail: "Unresolved provenance",
      };
    }
    const supporting = [
      ...pattern.matching_reference_ids,
      ...pattern.non_matching_reference_ids,
    ];
    const resolved = resolveReferences(supporting, maps);
    return {
      citation,
      kind: "pattern",
      targetId: citation.observation_type,
      resolved: true,
      references: resolved.references,
      unresolvedIdentifiers: resolved.unresolvedIdentifiers,
      detail: `Pattern ${citation.observation_type}: ${pattern.matching_count}/${pattern.analyzed_count} matching`,
    };
  }

  const referenceId = citation.reference;
  const analysis = maps.analysisById.get(referenceKey(referenceId)) ?? null;

  if (citation.kind === "fact") {
    const fact = analysis?.facts.find((item) => item.field === citation.field) ?? null;
    const resolved = resolveReferences([referenceId], maps);
    return {
      citation,
      kind: "fact",
      targetId: citation.field,
      resolved: fact !== undefined,
      references: resolved.references,
      unresolvedIdentifiers: resolved.unresolvedIdentifiers,
      detail: fact
        ? `Fact ${citation.field} on ${referenceKey(referenceId)}`
        : `Unresolved provenance: fact ${citation.field} on ${referenceKey(referenceId)}`,
    };
  }

  const observation = analysis?.observations.find(
    (item) => item.observation_type === citation.observation_type,
  );
  const resolved = resolveReferences([referenceId], maps);
  return {
    citation,
    kind: "observation",
    targetId: citation.observation_type,
    resolved: observation !== undefined,
    references: resolved.references,
    unresolvedIdentifiers: resolved.unresolvedIdentifiers,
    detail: observation
      ? `Observation ${citation.observation_type} on ${referenceKey(referenceId)}`
      : `Unresolved provenance: observation ${citation.observation_type} on ${referenceKey(referenceId)}`,
  };
}

function resolveReferences(
  identifiers: ReferenceIdJson[],
  maps: ProvenanceMaps,
): { references: ResolvedReference[]; unresolvedIdentifiers: string[] } {
  const references: ResolvedReference[] = [];
  const unresolvedIdentifiers: string[] = [];
  for (const identifier of identifiers) {
    const reference = maps.referenceById.get(referenceKey(identifier));
    if (!reference) {
      unresolvedIdentifiers.push(referenceKey(identifier));
      continue;
    }
    references.push({
      referenceId: identifier,
      reference,
      title: reference.title,
      source: reference.source_code,
      url: reference.url,
    });
  }
  return { references, unresolvedIdentifiers };
}

export interface ChainLink {
  label: string;
  value: string;
  resolved: boolean;
}

type StageItem =
  | { kind: "brief"; item: ContentBriefJson }
  | { kind: "idea"; item: ContentIdeaJson }
  | { kind: "opportunity"; item: OpportunityJson }
  | { kind: "gap"; item: ContentGapJson }
  | { kind: "interpretation"; item: InterpretationItemJson };

export function resolveUpstreamChain(report: ResearchReportResponse, entry: StageItem): ChainLink[] {
  const links: ChainLink[] = [];
  if (!report.ideation || !report.strategy || !report.interpretation) {
    return links;
  }

  const push = (label: string, value: string, resolved: boolean) => {
    links.push({ label, value, resolved });
  };

  if (entry.kind === "brief") {
    push("Brief", `#${entry.item.idea_index}`, true);
    const idea = report.ideation.content_ideas[entry.item.idea_index];
    if (!idea) {
      push("Idea", `#${entry.item.idea_index}`, false);
      return links;
    }
    push("Idea", idea.title, true);
    return links.concat(ideaChain(report, idea));
  }
  if (entry.kind === "idea") {
    return ideaChain(report, entry.item);
  }
  if (entry.kind === "opportunity") {
    push("Opportunity", entry.item.statement, true);
    for (const gapIndex of entry.item.gap_indexes) {
      const gap = report.strategy.content_gaps[gapIndex];
      if (!gap) {
        push("Gap", `#${gapIndex}`, false);
      } else {
        push("Gap", gap.statement, true);
        push("Interpretation", `#${gap.supporting_interpretation_indexes.join(", ")}`, true);
      }
    }
    return links;
  }
  if (entry.kind === "gap") {
    push("Gap", entry.item.statement, true);
    for (const index of entry.item.supporting_interpretation_indexes) {
      const interpretation = report.interpretation.interpretations[index];
      if (!interpretation) {
        push("Interpretation", `#${index}`, false);
      } else {
        push("Interpretation", interpretation.statement, true);
      }
    }
    return links;
  }
  push("Interpretation", entry.item.statement, true);
  return links;
}

function ideaChain(report: ResearchReportResponse, idea: ContentIdeaJson): ChainLink[] {
  const links: ChainLink[] = [];
  for (const opportunityIndex of idea.opportunity_indexes) {
    const opportunity = report.strategy?.opportunities[opportunityIndex];
    if (!opportunity) {
      links.push({ label: "Opportunity", value: `#${opportunityIndex}`, resolved: false });
      continue;
    }
    links.push({ label: "Opportunity", value: opportunity.statement, resolved: true });
    for (const gapIndex of opportunity.gap_indexes) {
      const gap = report.strategy?.content_gaps[gapIndex];
      if (!gap) {
        links.push({ label: "Gap", value: `#${gapIndex}`, resolved: false });
      } else {
        links.push({ label: "Gap", value: gap.statement, resolved: true });
      }
    }
  }
  return links;
}
