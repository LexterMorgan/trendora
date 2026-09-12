import { NextRequest, NextResponse } from "next/server";

/**
 * Thin same-origin proxy for the Trendora report history API.
 *
 * Browser → this route → Trendora FastAPI `GET /api/v1/research/reports`.
 * Forwards pagination params and preserves backend status/JSON body.
 * Performs no report logic and never exposes backend credentials.
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

  const search = request.nextUrl.search;
  let upstream: Response;
  try {
    upstream = await fetch(`${API_BASE_URL}/api/v1/research/reports${search}`, {
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
    headers: { "content-type": contentType },
  });
}
