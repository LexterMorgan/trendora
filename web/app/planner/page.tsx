import { Protected } from "@/components/Protected";
import { PlannerInbox } from "@/components/PlannerInbox";

export default function PlannerPage() {
  return <Protected><PlannerInbox /></Protected>;
}
