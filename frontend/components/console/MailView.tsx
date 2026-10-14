"use client";

import { useMemo } from "react";

import { MailLog } from "@/components/dash/MailLog";
import { AppShell } from "@/components/shell/AppShell";
import { Freshness } from "@/components/shell/Freshness";
import { mailLog } from "@/lib/dashboardData";
import { useConsoleData } from "@/lib/useConsoleData";

export function MailView() {
  const d = useConsoleData();
  // Dates come from the audit trail — queue items carry no timestamp of their
  // own — so the full log is passed in, not a truncated slice.
  const rows = useMemo(() => mailLog(d.candidates, d.audit), [d.candidates, d.audit]);

  return (
    <AppShell
      title="Correspondence"
      actions={
        <Freshness
          loadedAt={d.loadedAt} now={d.now} stale={d.stale} error={d.error}
          refreshing={d.refreshing} onRefresh={() => void d.reload(true)}
        />
      }
    >
      <MailLog rows={rows} loading={d.loading} standalone />
    </AppShell>
  );
}
