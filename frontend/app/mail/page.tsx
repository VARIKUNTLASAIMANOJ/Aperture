import { AuthGate } from "@/components/auth/AuthGate";
import { MailView } from "@/components/console/MailView";

export const metadata = { title: "Correspondence" };

export default function MailPage() {
  return (
    <AuthGate>
      <MailView />
    </AuthGate>
  );
}
