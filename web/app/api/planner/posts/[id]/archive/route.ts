import { proxyPlanner } from "../../../../../../lib/planner-proxy.ts";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  return proxyPlanner(request, "posts", (await params).id, "archive");
}
