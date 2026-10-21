import { NextRequest, NextResponse } from "next/server";

/**
 * Thin same-origin proxy for asking a saved report a grounded question.
 *
 * Browser → this route → Trendora FastAPI
 * `POST /api/v1/research/reports/{id}/ask`.
 * The question body and the backend status/JSON body pass through unchanged.
 */

const API_BASE_URL = process.env.TRENDORA_API_BASE_URL;

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
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

  const { id } = await params;
  const headers: Record<string, string> = { "content-type": "application/json" };
  const authorization = request.headers.get("authorization");
  if (authorization) headers.authorization = authorization;

  let upstream: Response;
  try {
    upstream = await fetch(
      `${API_BASE_URL}/api/v1/research/reports/${encodeURIComponent(id)}/ask`,
      { method: "POST", headers, body: await request.text(), cache: "no-store" },
    );
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
