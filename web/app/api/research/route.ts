import { NextRequest, NextResponse } from "next/server";

/**
 * Thin same-origin proxy for the Trendora research API.
 *
 * Browser → this route → Trendora FastAPI `POST /api/v1/research`.
 *
 * This route only forwards the structured request body and passes through the
 * backend response status/body. It performs no research logic, interprets no
 * YouTube data, changes no metrics, ranks nothing, invents no coverage, and
 * never exposes backend credentials.
 */

const API_BASE_URL = process.env.TRENDORA_API_BASE_URL;

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

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      { error: { code: "invalid_request", message: "Request body must be valid JSON." } },
      { status: 422 },
    );
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${API_BASE_URL}/api/v1/research`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
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
