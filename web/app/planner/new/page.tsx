import { Protected } from "@/components/Protected";
import { PlannerWorkspace } from "@/components/PlannerWorkspace";

export default function NewPlannerPostPage() {
  return <Protected><PlannerWorkspace /></Protected>;
}
