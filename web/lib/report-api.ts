/**
 * Typed client for the Trendora research report API (M23A).
 *
 * Types mirror the exact public M23A JSON contract. No business logic; the
 * request goes through the same-origin Next.js proxy (`/api/report`).
 */

import { requestJson, type RequestOptions } from "./api.ts";
import { ResearchApiError, type ResearchRequest, type ResearchResponse } from "./trendora-api.ts";

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

export interface PersistenceOutcomeJson {
  status: "saved" | "failed" | "unknown";
  request_id: string | null;
  report_id: string | null;
  snapshot_origin: "server_generated" | "client_supplied" | "legacy_unclassified";
  error_code: string | null;
  recovery_receipt?: string | null;
}

export interface ResearchReportResponse {
  status: string;
  research: ResearchResponse;
  evidence: EvidencePackJson | null;
  interpretation: InterpretationResultJson | null;
  strategy: StrategicResultJson | null;
  ideation: IdeationResultJson | null;
  persistence?: PersistenceOutcomeJson | null;
}

export const SNAPSHOT_FIELDS = [
  "status",
  "research",
  "evidence",
  "interpretation",
  "strategy",
  "ideation",
] as const;

export const SAVE_BODY_LIMIT_BYTES = 8_388_608;

export type SnapshotJson = Pick<
  ResearchReportResponse,
  "status" | "research" | "evidence" | "interpretation" | "strategy" | "ideation"
>;

/** The immutable six-field snapshot, excluding persistence metadata. */
export function snapshotOf(report: ResearchReportResponse): SnapshotJson {
  return {
    status: report.status,
    research: report.research,
    evidence: report.evidence,
    interpretation: report.interpretation,
    strategy: report.strategy,
    ideation: report.ideation,
  };
}

export interface SaveReportResult {
  persistence: PersistenceOutcomeJson;
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
  const payload = await requestJson<ResearchReportResponse>("/api/report", {
    method: "POST",
    body: request,
  });
  if (!isResearchReport(payload)) {
    throw new ResearchApiError(
      "invalid_response",
      "Trendora returned an unexpected report shape.",
    );
  }
  return payload;
}

export async function getSingleReport(
  reportId: string,
  options?: { signal?: AbortSignal },
): Promise<ResearchReportResponse> {
  try {
    const payload = await requestJson<ResearchReportResponse>(
      `/api/reports/${encodeURIComponent(reportId)}`,
      { signal: options?.signal },
    );
    if (!isResearchReport(payload)) {
      throw new ResearchApiError(
        "invalid_response",
        "Trendora returned an unexpected report shape.",
      );
    }
    return payload;
  } catch (err) {
    if (err instanceof ResearchApiError && err.kind === "not_found") {
      throw new ResearchApiError("not_found", "Report not found.", "not_found", 404);
    }
    throw err;
  }
}

/**
 * Save or recover one report snapshot under a frozen request key.
 *
 * The caller measures the serialized envelope before calling this, so an
 * oversized snapshot never leaves the browser. No research or AI runs here.
 */
export async function saveReportSnapshot(
  requestId: string,
  report: ResearchReportResponse,
  options?: { signal?: AbortSignal; runtime?: RequestOptions["runtime"]; recoveryReceipt?: string | null },
): Promise<SaveReportResult> {
  const snapshot = snapshotOf(report);
  const receipt = options?.recoveryReceipt === undefined ? report.persistence?.recovery_receipt : options.recoveryReceipt;
  const body = { schema_version: 1, request_id: requestId, snapshot, ...(receipt == null ? {} : { recovery_receipt: receipt }) };
  const encoded = new TextEncoder().encode(JSON.stringify(body));
  if (encoded.byteLength > SAVE_BODY_LIMIT_BYTES) {
    throw new ResearchApiError(
      "snapshot_too_large",
      "This report is too large to save for later recovery.",
      "invalid_request",
      413,
    );
  }
  const payload = await requestJson<SaveReportResult>("/api/reports/save", {
    method: "POST",
    body,
    signal: options?.signal,
  });
  if (!payload || typeof payload.persistence !== "object" || payload.persistence === null) {
    throw new ResearchApiError(
      "invalid_response",
      "Trendora returned an unexpected save response.",
    );
  }
  return payload;
}
