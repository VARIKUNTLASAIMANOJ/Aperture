import { AuthGate } from "@/components/auth/AuthGate";
import { CallsView } from "@/components/console/CallsView";

export const metadata = { title: "Voice calls" };

export default function CallsPage() {
  return (
    <AuthGate>
      <CallsView />
    </AuthGate>
  );
}
