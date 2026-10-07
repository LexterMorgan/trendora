import { proxyPlanner } from "../../../../../../lib/planner-proxy.ts";

type Context = { params: Promise<{ id: string }> };

/** Same-origin proxy for a post's immutable research origin. */
export async function GET(request: Request, { params }: Context) {
  return proxyPlanner(request, "posts", (await params).id, "origin");
}
