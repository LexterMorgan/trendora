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
  market: string;
  date_from: string;
  date_to: string;
  sources: string[];
  result_limit: number;
  facebook_page_id?: string;
}

export interface ResearchQueryResponse {
  topic: string;
  market: string;
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

export class ResearchApiError extends Error {
  code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "ResearchApiError";
    this.code = code;
  }
}

export async function submitResearch(
  request: ResearchRequest,
): Promise<ResearchResponse> {
  let response: Response;
  try {
    response = await fetch("/api/research", {
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
      err.error?.message ?? "Research request failed.",
    );
  }

  return payload as ResearchResponse;
}
