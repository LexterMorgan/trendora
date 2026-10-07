import { proxyPlanner } from "../../../../../lib/planner-proxy.ts";

/** Same-origin proxy for research-to-planner import. */
export async function POST(request: Request) {
  return proxyPlanner(request, "posts", undefined, "import");
}
