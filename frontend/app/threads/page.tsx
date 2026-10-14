import { AuthGate } from "@/components/auth/AuthGate";
import { ThreadsView } from "@/components/console/ThreadsView";

export const metadata = { title: "Candidates" };

export default function ThreadsPage() {
  return (
    <AuthGate>
      <ThreadsView />
    </AuthGate>
  );
}
