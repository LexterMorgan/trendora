const BODY_LIMIT = 131_072;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const PRIVATE = { "cache-control": "private, no-store" };

function error(status: number, code: string, message: string): Response {
  return Response.json({ error: { code, message } }, { status, headers: PRIVATE });
}

async function boundedBody(request: Request): Promise<ArrayBuffer | Response> {
  if (!request.body) return new ArrayBuffer(0);
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > BODY_LIMIT) {
        await reader.cancel().catch(() => {});
        return error(413, "planner_request_too_large", "Planner request body is too large.");
      }
      chunks.push(value);
    }
  } catch {
    return error(422, "invalid_request", "Request body could not be read.");
  } finally {
    reader.releaseLock();
  }
  const body = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return body.buffer;
}

export async function proxyPlanner(
  request: Request,
  endpoint: "members" | "posts",
  id?: string,
  action?: "archive" | "restore" | "import" | "origin",
): Promise<Response> {
  if (id !== undefined && !UUID.test(id) && action !== "import") {
    return error(422, "invalid_request", "Post ID must be a UUID.");
  }

  let upstreamUrl: URL;
  try {
    upstreamUrl = new URL(process.env.TRENDORA_API_BASE_URL ?? "");
    if (
      !["http:", "https:"].includes(upstreamUrl.protocol) ||
      upstreamUrl.username || upstreamUrl.password ||
      upstreamUrl.search || upstreamUrl.hash
    ) throw new Error();
  } catch {
    return error(500, "backend_not_configured", "Trendora backend is not configured.");
  }
  upstreamUrl.pathname = `${upstreamUrl.pathname.replace(/\/+$/, "")}/api/v1/planner/${endpoint}${id ? `/${id}` : ""}${action ? `/${action}` : ""}`;
  if (request.method === "GET" && endpoint === "posts" && !id) {
    const query = new URL(request.url).searchParams;
    for (const key of ["archived", "limit", "offset"]) {
      const value = query.get(key);
      if (value !== null) upstreamUrl.searchParams.set(key, value);
    }
  }

  const headers = new Headers();
  const authorization = request.headers.get("authorization");
  if (authorization) headers.set("authorization", authorization);
  let body: ArrayBuffer | undefined;
  if (request.method === "POST" || request.method === "PUT") {
    const result = await boundedBody(request);
    if (result instanceof Response) return result;
    body = result;
    headers.set("content-type", "application/json");
  }

  try {
    const upstream = await fetch(upstreamUrl.toString(), {
      method: request.method,
      headers,
      body,
      cache: "no-store",
      redirect: "error",
      signal: request.signal,
    });
    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        ...PRIVATE,
        "content-type": upstream.headers.get("content-type") ?? "application/json",
      },
    });
  } catch {
    return error(502, "backend_unreachable", "Trendora backend could not be reached.");
  }
}
