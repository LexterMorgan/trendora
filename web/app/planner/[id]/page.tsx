import { Protected } from "@/components/Protected";
import { PlannerWorkspace } from "@/components/PlannerWorkspace";

export default async function PlannerPostPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <Protected><PlannerWorkspace key={id} id={id} /></Protected>;
}
