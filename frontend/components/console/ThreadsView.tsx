"use client";

import { useMemo } from "react";

import { AppShell } from "@/components/shell/AppShell";
import { Freshness } from "@/components/shell/Freshness";
import { computeStats } from "@/lib/dashboardData";
import { useConsoleData } from "@/lib/useConsoleData";
import { CandidateTable } from "./CandidateTable";

export function ThreadsView() {
  const d = useConsoleData();
  const stats = useMemo(() => computeStats(d.candidates), [d.candidates]);

  return (
    <AppShell
      title="Candidates"
      actions={
        <Freshness
          loadedAt={d.loadedAt} now={d.now} stale={d.stale} error={d.error}
          refreshing={d.refreshing} onRefresh={() => void d.reload(true)}
        />
      }
    >
      <p className="mb-3 text-body text-fg-muted">
        {stats.totalWorkflows} workflow{stats.totalWorkflows === 1 ? "" : "s"}
        {stats.awaitingApproval > 0 && (
          <> · <span className="text-hold">{stats.awaitingApproval} waiting on you</span></>
        )}
        {stats.dispatchFailed > 0 && (
          <> · <span className="text-alarm">{stats.dispatchFailed} failed to send</span></>
        )}
      </p>
      <CandidateTable candidates={d.candidates} loading={d.loading} />
    </AppShell>
  );
}
