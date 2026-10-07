/**
 * Shared bounded-body logic for the research report proxies.
 *
 * The save route accepts a full report snapshot envelope, so it needs the
 * same streaming cap discipline as the planner proxy (Content-Length is not
 * trusted). The generation route only carries the small request body.
 */

export const SAVE_BODY_LIMIT = 8_388_608;
export const REPORT_BODY_LIMIT = 65_536;

const PRIVATE = { "cache-control": "private, no-store" };

export function proxyError(status: number, code: string, message: string): Response {
  return Response.json({ error: { code, message } }, { status, headers: PRIVATE });
}

export async function readBoundedBody(
  request: Request,
  limit: number,
  tooLargeCode: string,
): Promise<ArrayBuffer | Response> {
  if (!request.body) return new ArrayBuffer(0);
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > limit) {
        await reader.cancel().catch(() => {});
        return proxyError(413, tooLargeCode, "Request body is too large.");
      }
      chunks.push(value);
    }
  } catch {
    return proxyError(422, "invalid_request", "Request body could not be read.");
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
