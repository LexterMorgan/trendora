/**
 * Typed client for the Trendora research report API (M23A).
 *
 * Types mirror the exact public M23A JSON contract. No business logic; the
 * request goes through the same-origin Next.js proxy (`/api/report`).
 */

import { ResearchApiError, type ResearchRequest, type ResearchResponse } from "@/lib/trendora-api";

export type { ResearchRequest };

export interface ReferenceIdJson {
  source_code: string;
  content_external_id: string;
}

export type CitationJson =
  | {
      kind: "fact";
      reference: ReferenceIdJson;
      field: string;
    }
  | {
      kind: "observation";
      reference: ReferenceIdJson;
      observation_type: string;
    }
  | {
      kind: "pattern";
      observation_type: string;
    };

export interface ModelProvenanceJson {
  provider: string;
  model: string;
}

export interface EvidenceFactJson {
  field: string;
  value: unknown;
}

export interface ContentObservationJson {
  observation_type: string;
  value: unknown;
  evidence_fields: string[];
  analysis_basis: string;
}

export interface EvidenceAnalysisJson {
  reference_id: ReferenceIdJson;
  facts: EvidenceFactJson[];
  observations: ContentObservationJson[];
}

export interface PatternAggregateJson {
  observation_type: string;
  analyzed_count: number;
  matching_count: number;
  non_matching_count: number;
  ratio: number;
  matching_reference_ids: ReferenceIdJson[];
  non_matching_reference_ids: ReferenceIdJson[];
}

export interface EvidencePackJson {
  analyses: EvidenceAnalysisJson[];
  patterns: PatternAggregateJson[];
}

export interface InterpretationItemJson {
  statement: string;
  citations: CitationJson[];
}

export interface InterpretationResultJson {
  model_provenance: ModelProvenanceJson;
  interpretations: InterpretationItemJson[];
}

export interface ContentGapJson {
  statement: string;
  supporting_interpretation_indexes: number[];
  citations: CitationJson[];
}

export interface OpportunityJson {
  statement: string;
  gap_indexes: number[];
  citations: CitationJson[];
}

export interface StrategicResultJson {
  model_provenance: ModelProvenanceJson;
  content_gaps: ContentGapJson[];
  opportunities: OpportunityJson[];
}

export interface ContentIdeaJson {
  title: string;
  angle: string;
  opportunity_indexes: number[];
  citations: CitationJson[];
}

export interface ContentBriefJson {
  idea_index: number;
  objective: string;
  format: string;
  hook: string;
  outline: string[];
  citations: CitationJson[];
}

export interface IdeationResultJson {
  model_provenance: ModelProvenanceJson;
  content_ideas: ContentIdeaJson[];
  content_briefs: ContentBriefJson[];
}

export interface ResearchReportResponse {
  status: string;
  research: ResearchResponse;
  evidence: EvidencePackJson | null;
  interpretation: InterpretationResultJson | null;
  strategy: StrategicResultJson | null;
  ideation: IdeationResultJson | null;
}

export function isResearchReport(value: unknown): value is ResearchReportResponse {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Partial<ResearchReportResponse>;
  return (
    typeof candidate.status === "string" &&
    typeof candidate.research === "object" &&
    candidate.research !== null &&
    candidate.research !== undefined
  );
}

export async function submitReport(
  request: ResearchRequest,
): Promise<ResearchReportResponse> {
  let response: Response;
  try {
    response = await fetch("/api/report", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(request),
    });
  } catch {
    throw new ResearchApiError(
      "backend_unreachable",
      "The Trendora backend could not be reached.",
    );
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new ResearchApiError(
      "invalid_response",
      "Trendora returned an unreadable response.",
    );
  }

  if (!response.ok) {
    const err = payload as { error?: { code?: string; message?: string } };
    throw new ResearchApiError(
      err.error?.code ?? "unknown_error",
      err.error?.message ?? "Report request failed.",
    );
  }

  if (!isResearchReport(payload)) {
    throw new ResearchApiError(
      "invalid_response",
      "Trendora returned an unexpected report shape.",
    );
  }
  return payload;
}
