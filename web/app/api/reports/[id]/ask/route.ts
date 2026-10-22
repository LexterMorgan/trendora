import { REPORT_BODY_LIMIT, proxyError, readBoundedBody } from "../../../../../lib/report-proxy.ts";

const ASK_TIMEOUT_MS = 180_000;

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const base = process.env.TRENDORA_API_BASE_URL?.replace(/\/$/, "");
  if (!base) return proxyError(500, "backend_not_configured", "Trendora backend is not configured.");

  const body = await readBoundedBody(request, REPORT_BODY_LIMIT, "ask_request_too_large");
  if (body instanceof Response) return body;
  try {
    JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(body));
  } catch {
    return proxyError(422, "invalid_request", "Request body must be valid JSON.");
  }

  const { id } = await params;
  const deadline = AbortSignal.timeout(ASK_TIMEOUT_MS);
  const signal = AbortSignal.any([request.signal, deadline]);
  const headers: Record<string, string> = { "content-type": "application/json" };
  const authorization = request.headers.get("authorization");
  if (authorization) headers.authorization = authorization;

  try {
    signal.throwIfAborted();
    const upstream = await fetch(
      `${base}/api/v1/research/reports/${encodeURIComponent(id)}/ask`,
      { method: "POST", headers, body, cache: "no-store", redirect: "error", signal },
    );
    const text = await upstream.text();
    signal.throwIfAborted();
    return new Response(text, {
      status: upstream.status,
      headers: {
        "content-type": upstream.headers.get("content-type") ?? "application/json",
        "cache-control": "private, no-store",
      },
    });
  } catch {
    if (deadline.aborted && !request.signal.aborted) {
      return proxyError(504, "ask_timeout", "The answer took too long. Try a more specific question.");
    }
    return proxyError(502, "backend_unreachable", "Trendora backend could not be reached.");
  }
}
