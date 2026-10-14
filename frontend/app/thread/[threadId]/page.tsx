import { AuthGate } from "@/components/auth/AuthGate";
import { ThreadView } from "@/components/thread/ThreadView";

export const metadata = {
  title: "Workflow",
};

/**
 * Deep-linkable view of a single workflow — this is where an operator
 * approves or rejects a dispatch that was started in some other session.
 *
 * No <main> or backdrop here: AppShell owns both, and nesting a second <main>
 * gave the page two skip-link targets.
 *
 * Next 16 passes route params as a Promise.
 */
export default async function ThreadPage({
  params,
}: {
  params: Promise<{ threadId: string }>;
}) {
  const { threadId } = await params;

  return (
    <AuthGate>
      <ThreadView threadId={threadId} />
    </AuthGate>
  );
}
