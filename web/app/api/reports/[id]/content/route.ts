import { NextRequest, NextResponse } from "next/server";

import { proxyError } from "../../../../../lib/report-proxy.ts";

const API_BASE_URL = process.env.TRENDORA_API_BASE_URL;
const CONTENT_TIMEOUT_MS = 180_000;

/** Thin same-origin proxy for on-demand content generation on one saved report. */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  if (!API_BASE_URL) {
    return proxyError(500, "backend_not_configured", "Trendora backend is not configured.");
  }
  const { id } = await params;
  const headers: Record<string, string> = {};
  const authorization = request.headers.get("authorization");
  if (authorization) headers.authorization = authorization;
  const deadline = AbortSignal.timeout(CONTENT_TIMEOUT_MS);
  const signal = AbortSignal.any([request.signal, deadline]);
  try {
    const upstream = await fetch(
      `${API_BASE_URL}/api/v1/research/reports/${encodeURIComponent(id)}/content`,
      { method: "POST", headers, cache: "no-store", redirect: "error", signal },
    );
    const text = await upstream.text();
    return new NextResponse(text, {
      status: upstream.status,
      headers: {
        "content-type": upstream.headers.get("content-type") ?? "application/json",
        "cache-control": "private, no-store",
      },
    });
  } catch {
    if (deadline.aborted && !request.signal.aborted) {
      return proxyError(504, "content_timeout", "Content generation took too long.");
    }
    return proxyError(502, "backend_unreachable", "Trendora backend could not be reached.");
  }
}
