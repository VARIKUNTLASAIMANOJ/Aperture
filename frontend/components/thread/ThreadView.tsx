"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { StageTable } from "@/components/dash/StageTable";
import { LiveRun } from "@/components/flow/LiveRun";
import { AppShell } from "@/components/shell/AppShell";
import { RetryDispatch } from "@/components/thread/RetryDispatch";
import { IconAlert, IconSpinner } from "@/components/ui/Icons";
import { NetworkError, api } from "@/lib/api";
import { stageLabel } from "@/lib/dashboardData";
import type { Candidate } from "@/lib/types";

/**
 * One workflow, opened for action.
 *
 * Without this route the approval gate lived only inside the session that
 * started the run: closing that tab stranded the thread permanently, because
 * nothing else in the app could resume it.
 *
 * LiveRun is reused verbatim rather than reimplemented — it already fetches
 * state and audit by thread id, renders the gate, and calls approve/reject —
 * so there is exactly one implementation of the approval path.
 */

const STAGE_TONE: Record<string, string> = {
  "Awaiting approval": "border-hold/35 bg-hold/10 text-hold",
  Halted: "border-alarm/35 bg-alarm/10 text-alarm",
  Declined: "border-alarm/35 bg-alarm/10 text-alarm",
  Completed: "border-settled/35 bg-settled/10 text-settled",
  Accepted: "border-settled/35 bg-settled/10 text-settled",
};

export function ThreadView({ threadId }: { threadId: string }) {
  const router = useRouter();
  const [candidate, setCandidate] = useState<Candidate | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // /state has no candidate_name; the roster endpoint is the only place the
  // display fields live.
  const fetchCandidate = useCallback(async () => {
    const all = await api.candidates();
    return all.find((c) => c.thread_id === threadId) ?? null;
  }, [threadId]);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const found = await fetchCandidate();
        if (!alive) return;
        setCandidate(found);
        setError(found ? null : "No workflow found for this thread.");
      } catch (e) {
        if (!alive) return;
        setError(
          e instanceof NetworkError || e instanceof Error
            ? e.message
            : "Could not load this workflow.",
        );
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [fetchCandidate]);

  const reload = useCallback(() => {
    void fetchCandidate().then(setCandidate).catch(() => {});
  }, [fetchCandidate]);

  const goToOnboard = useCallback(() => router.push("/onboard"), [router]);

  // A bounced letter is the one state HR cannot act on from anywhere else:
  // the thread parks at the dispatch gate with nothing in the stage table to
  // click, because no document was released.
  const failed = candidate?.email_queue_summary?.find((e) => e.status === "FAILED");
  const stage = candidate ? stageLabel(candidate) : null;

  return (
    <AppShell
      title={loading ? "Loading…" : candidate?.candidate_name || "Workflow"}
      subtitle={
        candidate
          ? [candidate.role_title, candidate.department, candidate.candidate_email]
              .filter(Boolean).join(" · ")
          : undefined
      }
      back={{ href: "/threads", label: "Candidates" }}
      actions={
        stage ? (
          <span
            className={`shrink-0 rounded-lg border px-2.5 py-1 text-micro font-medium ${
              STAGE_TONE[stage] ?? "border-line bg-fill text-fg-muted"
            }`}
          >
            {stage}
          </span>
        ) : undefined
      }
    >
      {loading ? (
        <div className="surface flex items-center justify-center gap-2 rounded-card py-16 text-fg-muted">
          <IconSpinner className="h-4 w-4 animate-spin" />
          <span className="text-body">Loading workflow…</span>
        </div>
      ) : error ? (
        <div
          role="alert"
          className="flex items-start gap-2.5 rounded-xl border border-alarm/35 bg-alarm/[0.07] p-4"
        >
          <IconAlert className="mt-0.5 h-4 w-4 shrink-0 text-alarm" />
          <div className="min-w-0 space-y-2">
            <p className="text-base font-medium text-fg">
              Could not open this workflow
            </p>
            <p className="break-words text-body leading-relaxed text-fg-muted">
              {error}
            </p>
            <Link
              href="/threads"
              className="inline-flex min-h-[40px] items-center text-body font-medium text-signal hover:underline"
            >
              Back to candidates
            </Link>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          {failed && (
            <RetryDispatch
              threadId={threadId}
              currentEmail={candidate?.candidate_email}
              failureReason={failed.message_id}
              onRetried={reload}
            />
          )}

          {/* §4 — employment progression, with the gated Release actions.
              Above the run detail because it is what HR acts on. */}
          <StageTable threadId={threadId} />

          <section>
            <h2 className="mb-2 text-lead font-semibold text-fg">Run detail</h2>
            <div className="surface rounded-card p-5 sm:p-6">
              <LiveRun
                threadId={threadId}
                candidateName={candidate?.candidate_name ?? ""}
                onRestart={goToOnboard}
                restartLabel="Onboard a new candidate"
                lockExitUntilTerminal={false}
              />
            </div>
          </section>
        </div>
      )}
    </AppShell>
  );
}
