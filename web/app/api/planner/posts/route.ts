import { proxyPlanner } from "../../../../lib/planner-proxy.ts";

export async function GET(request: Request) {
  return proxyPlanner(request, "posts");
}

export async function POST(request: Request) {
  return proxyPlanner(request, "posts");
}
