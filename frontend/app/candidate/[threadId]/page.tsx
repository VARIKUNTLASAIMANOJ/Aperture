import { CandidateView } from "@/components/candidate/CandidateView";

export const metadata = {
  title: "Your employment status",
  // Candidate letters carry salary and personal details — keep them out of
  // search indexes even though the link is token-guarded.
  robots: { index: false, follow: false },
};

/**
 * Candidate-facing page (§5). Reached only from the emailed link, which
 * carries the signed token. Next 16 passes params and searchParams as Promises.
 */
export default async function CandidatePage({
  params,
  searchParams,
}: {
  params: Promise<{ threadId: string }>;
  searchParams: Promise<{ token?: string }>;
}) {
  const { threadId } = await params;
  const { token } = await searchParams;

  return (
    <main id="main" className="relative min-h-dvh">
      {token ? (
        <CandidateView threadId={threadId} token={token} />
      ) : (
        <div className="mx-auto mt-24 max-w-[460px] px-6 text-center">
          <h1 className="text-title font-semibold text-fg">Access link required</h1>
          <p className="mt-2 text-base leading-relaxed text-fg-muted">
            Please open your employment status using the link sent to you by
            email. It carries a secure token that identifies you.
          </p>
        </div>
      )}
    </main>
  );
}
