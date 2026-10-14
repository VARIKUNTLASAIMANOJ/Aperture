import { AuthGate } from "@/components/auth/AuthGate";
import { ReportsView } from "@/components/console/ReportsView";

export const metadata = { title: "Reports" };

export default function ReportsPage() {
  return (
    <AuthGate>
      <ReportsView />
    </AuthGate>
  );
}
