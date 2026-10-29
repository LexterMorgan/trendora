import { Protected } from "@/components/Protected";
import { PlannerInbox } from "@/components/PlannerInbox";
import { AppShell } from "@/components/research/AppShell";

export default function PlannerPage() {
  return (
    <Protected>
      <AppShell view="planner" section="Shared planner">
        <PlannerInbox />
      </AppShell>
    </Protected>
  );
}
