/**
 * Typed client for the Trendora research API.
 *
 * Types mirror the public M15 contract (docs/17_RESEARCH_API.md). No business
 * logic lives here: it submits a structured request and parses success/error
 * responses. The request goes to the same-origin Next.js proxy
 * (`/api/research`), which forwards it to the FastAPI backend.
 */

export interface ResearchRequest {
  topic: string;
  market?: string;
  markets: string[];
  date_from?: string;
  date_to?: string;
  sources: string[];
  result_limit: number;
  facebook_page_id?: string;
  include_content_tools?: boolean;
}

export interface ResearchQueryResponse {
  topic: string;
  markets: string[];
  market: string | null;
  date_from: string;
  date_to: string;
  sources: string[];
  result_limit: number;
  facebook_page_id: string | null;
}

export interface SourceCoverageResponse {
  source_code: string;
  capability: string;
  status: string;
  reason: string | null;
}

export interface ResearchCoverageResponse {
  completeness: string;
  sources: SourceCoverageResponse[];
}

export interface ResearchMetricsResponse {
  view_count: number | null;
  like_count: number | null;
  comment_count: number | null;
  reaction_count: number | null;
  share_count: number | null;
}

export interface ResearchReferenceResponse {
  source_code: string;
  content_external_id: string;
  url: string | null;
  title: string | null;
  description: string | null;
  published_at: string | null;
  channel_external_id: string | null;
  channel_title: string | null;
  market_contexts: string[];
  market_context: string | null;
  market_basis: string | null;
  source_rank: number | null;
  metrics: ResearchMetricsResponse;
  collected_at: string;
}

export interface ResearchResponse {
  query: ResearchQueryResponse;
  coverage: ResearchCoverageResponse;
  executed_sources: string[];
  status: string;
  references: ResearchReferenceResponse[];
}

export interface ReportSummaryResponse {
  id: string;
  created_at: string;
  status: string;
  topic: string;
  markets: string[];
  source_codes: string[];
  date_from: string;
  date_to: string;
}

export { ResearchApiError } from "./api.ts";
export type { ApiErrorKind } from "./api.ts";
import { requestJson } from "./api.ts";

export async function submitResearch(
  request: ResearchRequest,
): Promise<ResearchResponse> {
  return requestJson<ResearchResponse>("/api/research", {
    method: "POST",
    body: request,
  });
}

export async function listReports(
  params?: {
    limit?: number;
    offset?: number;
  },
  options?: { signal?: AbortSignal },
): Promise<ReportSummaryResponse[]> {
  const query = new URLSearchParams();
  if (params?.limit !== undefined) query.append("limit", String(params.limit));
  if (params?.offset !== undefined) query.append("offset", String(params.offset));
  const suffix = query.size > 0 ? `?${query.toString()}` : "";

  return requestJson<ReportSummaryResponse[]>(`/api/reports${suffix}`, {
    signal: options?.signal,
  });
}
