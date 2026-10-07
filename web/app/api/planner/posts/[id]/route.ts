import { proxyPlanner } from "../../../../../lib/planner-proxy.ts";

type Context = { params: Promise<{ id: string }> };

export async function GET(request: Request, { params }: Context) {
  return proxyPlanner(request, "posts", (await params).id);
}

export async function PUT(request: Request, { params }: Context) {
  return proxyPlanner(request, "posts", (await params).id);
}
