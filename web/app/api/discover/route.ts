import { NextRequest, NextResponse } from "next/server";

/**
 * Thin same-origin proxy for public-web discovery.
 *
 * Browser → this route → Trendora FastAPI `GET /api/v1/discover`.
 * Forwards only `q` and `limit` plus the authorization header.
 */

const API_BASE_URL = process.env.TRENDORA_API_BASE_URL;

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

  const headers: Record<string, string> = {};
  const authorization = request.headers.get("authorization");
  if (authorization) headers.authorization = authorization;
  let upstream: Response;
  try {
    upstream = await fetch(`${API_BASE_URL}/api/v1/discover${search}`, {
      headers,
      cache: "no-store",
    });
  } catch {
    return NextResponse.json(
      {
        error: {
          code: "backend_unreachable",
          message: "Trendora backend could not be reached.",
        },
      },
      { status: 502 },
    );
  }

  const text = await upstream.text();
  const contentType = upstream.headers.get("content-type") ?? "application/json";
  return new NextResponse(text, {
    status: upstream.status,
    headers: {
      "content-type": contentType,
      "cache-control": "private, no-store",
    },
  });
}
