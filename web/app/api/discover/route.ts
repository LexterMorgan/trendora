import { NextRequest, NextResponse } from "next/server";

import { proxyError } from "../../../lib/report-proxy.ts";

/**
 * Thin same-origin proxy for public-web discovery.
 *
 * Browser → this route → Trendora FastAPI `GET /api/v1/discover`.
 * Forwards only `q` and `limit` plus the authorization header.
 *
 * The 65 second deadline covers the complete upstream exchange. The search
 * gateways allow at most two 30 second attempts (Serper) or a 25 second batch
 * (SearXNG), so this leaves a small bounded margin without changing provider
 * budgets.
 */

const API_BASE_URL = process.env.TRENDORA_API_BASE_URL;
const DISCOVER_TIMEOUT_MS = 65_000;

export async function GET(request: NextRequest) {
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

  const upstreamParams = new URLSearchParams();
  for (const key of ["q", "limit"]) {
    const value = request.nextUrl.searchParams.get(key);
    if (value !== null) upstreamParams.set(key, value);
  }
  const search = upstreamParams.size > 0 ? `?${upstreamParams.toString()}` : "";

  const deadline = AbortSignal.timeout(DISCOVER_TIMEOUT_MS);
  const signal = AbortSignal.any([request.signal, deadline]);
  try {
    signal.throwIfAborted();
    const headers: Record<string, string> = {};
    const authorization = request.headers.get("authorization");
    if (authorization) headers.authorization = authorization;
    const upstream = await fetch(`${API_BASE_URL}/api/v1/discover${search}`, {
      headers,
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
      return proxyError(
        504,
        "discover_timeout",
        "Search took too long. Try a narrower query.",
      );
    }
    return proxyError(
      502,
      "backend_unreachable",
      "Trendora backend could not be reached.",
    );
  }
}
