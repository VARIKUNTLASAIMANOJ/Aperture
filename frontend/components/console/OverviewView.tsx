"use client";

import Link from "next/link";
import { useMemo } from "react";

import { ActivityFeed } from "@/components/dash/ActivityFeed";
import { NotificationPanel } from "@/components/dash/NotificationPanel";
import { AppShell } from "@/components/shell/AppShell";
import { Freshness } from "@/components/shell/Freshness";
import {
  IconAlert, IconArrowRight, IconCheck, IconLayers, IconMail, IconShield,
} from "@/components/ui/Icons";
import { computeStats, recentActivity } from "@/lib/dashboardData";
import { useConsoleData } from "@/lib/useConsoleData";
import { CandidateTable } from "./CandidateTable";
import { MetricRow } from "./MetricRow";

/**
 * The landing view: what is true right now, and what needs a human.
 *
 * Deliberately NOT everything. Correspondence and calls moved to their own
 * routes — stacking them here is what made the old dashboard a six-panel
 * scroll where nothing was primary.
 */
export function OverviewView() {
  const d = useConsoleData();
  const stats = useMemo(() => computeStats(d.candidates), [d.candidates]);
  const activity = useMemo(() => recentActivity(d.audit, 8), [d.audit]);

  return (
    <AppShell
      title="Overview"
      actions={
        <Freshness
          loadedAt={d.loadedAt} now={d.now} stale={d.stale} error={d.error}
          refreshing={d.refreshing} onRefresh={() => void d.reload(true)}
        />
      }
    >
      {d.error && (
        <div
          role="alert"
          className="mb-4 flex items-start gap-2.5 rounded-xl border border-alarm/35 bg-alarm/[0.07] p-3.5"
        >
          <IconAlert className="mt-0.5 h-4 w-4 shrink-0 text-alarm" />
          <div className="min-w-0 space-y-0.5">
            <p className="text-base font-medium text-fg">Console data unavailable</p>
            <p className="break-words text-body text-fg-muted">{d.error}</p>
          </div>
        </div>
      )}

      <MetricRow
        loading={d.loading}
        metrics={[
          { label: "Mails sent", value: stats.mailsSent,
            hint: "accepted by Resend",
            icon: <IconMail className="h-3.5 w-3.5" /> },
          { label: "Awaiting approval", value: stats.awaitingApproval,
            hint: "paused at the gate",
            tone: stats.awaitingApproval > 0 ? "hold" : "neutral",
            icon: <IconShield className="h-3.5 w-3.5" />,
            href: "/threads" },
          { label: "Dispatch failed", value: stats.dispatchFailed,
            hint: stats.sendSuccessRate === null
              ? "no sends attempted"
              : `${Math.round(stats.sendSuccessRate * 100)}% success`,
            tone: stats.dispatchFailed > 0 ? "alarm" : "neutral",
            icon: <IconAlert className="h-3.5 w-3.5" />,
            href: "/threads" },
          { label: "Workflows", value: stats.totalWorkflows,
            hint: `${stats.offersExtended} offers · ${stats.declines} declines`,
            icon: <IconLayers className="h-3.5 w-3.5" />,
            href: "/threads" },
        ]}
      />

      <div className="mt-4">
        <NotificationPanel />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[1.5fr_minmax(320px,1fr)]">
        <section>
          <header className="mb-2 flex items-baseline justify-between gap-3">
            <h2 className="text-lead font-semibold text-fg">Recent candidates</h2>
            <Link
              href="/threads"
              className="inline-flex min-h-[32px] items-center gap-1 text-body text-fg-muted transition-colors duration-[--t-hover] hover:text-fg"
            >
              View all
              <IconArrowRight className="h-3.5 w-3.5" />
            </Link>
          </header>
          <CandidateTable candidates={d.candidates} loading={d.loading} limit={8} compact />
        </section>

        <section className="min-w-0">
          <h2 className="mb-2 text-lead font-semibold text-fg">Activity</h2>
          <ActivityFeed entries={activity} />
        </section>
      </div>

      {!d.loading && !d.error && stats.totalWorkflows === 0 && (
        <div className="surface mt-4 flex flex-col items-center gap-3 rounded-card px-6 py-12 text-center">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl border border-signal/25 bg-signal/[0.08] text-signal">
            <IconCheck className="h-5 w-5" />
          </span>
          <div className="space-y-1">
            <p className="text-lead font-semibold text-fg">No workflows yet</p>
            <p className="max-w-[46ch] text-body leading-relaxed text-fg-muted">
              Start one and the agent will compute payroll, draft the letter, and
              pause here for your approval before anything reaches the candidate.
            </p>
          </div>
          <Link
            href="/onboard"
            className="mt-1 inline-flex min-h-[40px] items-center gap-1.5 rounded-lg bg-signal px-4 text-body font-semibold text-on-primary transition-colors duration-[--t-hover] hover:bg-signal/90"
          >
            Onboard your first candidate
            <IconArrowRight className="h-4 w-4" />
          </Link>
        </div>
      )}
    </AppShell>
  );
}
