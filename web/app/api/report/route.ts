import { NextRequest, NextResponse } from "next/server";

import { REPORT_BODY_LIMIT, proxyError, readBoundedBody } from "../../../lib/report-proxy.ts";

/**
 * Thin same-origin proxy for the Trendora research report API.
 *
 * Browser → this route → Trendora FastAPI `POST /api/v1/research/report`.
 *
 * Forwards the exact request body and preserves backend status/JSON error
 * body. Performs no report logic and never exposes backend credentials.
 */

const API_BASE_URL = process.env.TRENDORA_API_BASE_URL;
const REPORT_TIMEOUT_MS = 180_000;

export async function POST(request: NextRequest) {
  if (!API_BASE_URL) {
    return NextResponse.json(
      {
        error: {
          code: "backend_not_configured",
          message:
            "Trendora backend is not configured (TRENDORA_API_BASE_URL is missing).",
        },
      },
      { status: 500 },
    );
  }

  const body = await readBoundedBody(request, REPORT_BODY_LIMIT, "report_request_too_large");
  if (body instanceof Response) return body;
  try {
    JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(body));
  } catch {
    return proxyError(422, "invalid_request", "Request body must be valid JSON.");
  }

  const deadline = AbortSignal.timeout(REPORT_TIMEOUT_MS);
  const signal = AbortSignal.any([request.signal, deadline]);
  try {
    signal.throwIfAborted();
    const headers: Record<string, string> = {
      "content-type": "application/json",
    };
    const authorization = request.headers.get("authorization");
    if (authorization) headers.authorization = authorization;
    const upstream = await fetch(`${API_BASE_URL}/api/v1/research/report`, {
      method: "POST",
      headers,
      body,
      cache: "no-store",
      redirect: "error",
      signal,
    });
    const text = await upstream.text();
    signal.throwIfAborted();
    const contentType = upstream.headers.get("content-type") ?? "application/json";
    return new NextResponse(text, {
      status: upstream.status,
      headers: {
        "content-type": contentType,
        "cache-control": "private, no-store",
      },
    });
  } catch {
    if (deadline.aborted && !request.signal.aborted) {
      return proxyError(504, "report_timeout", "Research took too long. Try a smaller scope or timeframe.");
    }
    return proxyError(502, "backend_unreachable", "Trendora backend could not be reached.");
  }
}
