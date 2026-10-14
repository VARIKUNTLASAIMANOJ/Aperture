import { AuthGate } from "@/components/auth/AuthGate";
import { OverviewView } from "@/components/console/OverviewView";

export const metadata = {
  title: "Onboarding Control",
  description:
    "Operations view for the human-gated onboarding agent: dispatch counts, approval queue, and audit trail.",
};

export default function OverviewPage() {
  return (
    <AuthGate>
      <OverviewView />
    </AuthGate>
  );
}
