import { NextRequest } from "next/server";

import { SAVE_BODY_LIMIT, proxyError, readBoundedBody } from "../../../../lib/report-proxy.ts";

/**
 * Same-origin proxy for report save/recovery.
 *
 * Browser → this route → Trendora FastAPI `POST /api/v1/research/reports/save`.
 * Forwards the exact request body under an 8 MiB streaming cap and preserves
 * backend status/JSON. Performs no report logic and never exposes credentials.
 */

const API_BASE_URL = process.env.TRENDORA_API_BASE_URL;

export async function POST(request: NextRequest) {
  if (!API_BASE_URL) {
    return proxyError(
      500,
      "backend_not_configured",
      "Trendora backend is not configured (TRENDORA_API_BASE_URL is missing).",
    );
  }

  const body = await readBoundedBody(request, SAVE_BODY_LIMIT, "report_request_too_large");
  if (body instanceof Response) return body;

  const headers = new Headers({ "content-type": "application/json" });
  const authorization = request.headers.get("authorization");
  if (authorization) headers.set("authorization", authorization);

  try {
    const upstream = await fetch(`${API_BASE_URL}/api/v1/research/reports/save`, {
      method: "POST",
      headers,
      body,
      cache: "no-store",
      redirect: "error",
    });
    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        "cache-control": "private, no-store",
        "content-type": upstream.headers.get("content-type") ?? "application/json",
      },
    });
  } catch {
    return proxyError(502, "backend_unreachable", "Trendora backend could not be reached.");
  }
}
