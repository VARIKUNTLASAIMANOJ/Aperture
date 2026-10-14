"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { LogoMark } from "@/components/brand/Logo";
import { GlassPanel } from "@/components/ui/GlassPanel";
import {
  IconAlert, IconArrowRight, IconCheck, IconLayers, IconMail,
  IconPlus, IconRefresh, IconShield, IconSpinner,
} from "@/components/ui/Icons";
import { NetworkError, api } from "@/lib/api";
import { clearSession, getSession } from "@/lib/session";
import {
  approvalQueue, attentionQueue, computeStats, mailLog, recentActivity, relativeTime,
} from "@/lib/dashboardData";
import type { AuditEntry, Candidate } from "@/lib/types";
import { useReducedMotion } from "@/lib/useReducedMotion";
import { ActivityFeed } from "./ActivityFeed";
import { NotificationPanel } from "./NotificationPanel";
import { MailLog } from "./MailLog";
import { StatTile } from "./StatTile";
import { VoicePanel } from "./VoicePanel";
import { WorkQueue } from "./WorkQueue";

const POLL_MS = 15_000;
/** Past this age the readout is labelled stale rather than presented as live. */
const STALE_AFTER_MS = 45_000;

export function DashboardView() {
  const reduced = useReducedMotion();
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [loadedAt, setLoadedAt] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const alive = useRef(true);

  const load = useCallback(async (manual = false) => {
    if (manual) setRefreshing(true);
    try {
      const [c, a] = await Promise.all([api.candidates(), api.allAudit()]);
      if (!alive.current) return;
      setCandidates(c);
      setAudit(a.audit_log);
      setLoadedAt(Date.now());
      setError(null);
    } catch (e) {
      if (!alive.current) return;
      setError(
        e instanceof NetworkError
          ? e.message
          : e instanceof Error
            ? e.message
            : "Could not load dashboard data.",
      );
    } finally {
      if (alive.current) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    void load();
    const poll = setInterval(() => void load(), POLL_MS);
    // Drives the "updated Xs ago" label and the stale flip without refetching.
    const tick = setInterval(() => setNow(Date.now()), 5_000);
    return () => {
      alive.current = false;
      clearInterval(poll);
      clearInterval(tick);
    };
  }, [load]);

  const stats = useMemo(() => computeStats(candidates), [candidates]);
  const approvals = useMemo(() => approvalQueue(candidates), [candidates]);
  const attention = useMemo(() => attentionQueue(candidates), [candidates]);
  const activity = useMemo(() => recentActivity(audit), [audit]);
  // Dates come from the audit trail — queue items carry no timestamp of their
  // own — so the full log is passed in, not the truncated activity slice.
  const mail = useMemo(() => mailLog(candidates, audit), [candidates, audit]);

  const stale = loadedAt !== null && now - loadedAt > STALE_AFTER_MS;
  const live = loadedAt !== null && !stale && !error;

  return (
    <div className="mx-auto w-full max-w-[1240px] px-4 py-5 sm:px-6 sm:py-7">
      {/* ── Masthead ─────────────────────────────────────────────────────── */}
      <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-3">
        {/* The mark is decorative (aria-hidden); this h1 carries the page's
            accessible name. */}
        <div className="flex min-w-0 items-center gap-2.5">
          <LogoMark className="h-8 w-8 shrink-0 text-fg" interactive={false} />
          <div className="min-w-0 leading-tight">
            <h1 className="truncate text-[15px] font-semibold tracking-[-0.01em] text-fg">
              Aperture
            </h1>
            <p className="whitespace-nowrap text-[10px] uppercase tracking-[0.16em] text-fg-faint">
              Onboarding Control
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Telemetry honesty: "live" only while data is fresh AND the last
              fetch succeeded; otherwise the age is shown and labelled stale. */}
          <span
            className="hidden items-center gap-1.5 rounded-full border border-line bg-fill px-2.5 py-1.5 sm:flex"
            title={loadedAt ? new Date(loadedAt).toLocaleTimeString() : undefined}
          >
            <span
              aria-hidden="true"
              className={`h-1.5 w-1.5 rounded-full ${
                error ? "bg-alarm" : stale ? "bg-hold" : "bg-settled"
              } ${live && !reduced ? "animate-pulse" : ""}`}
            />
            <span
              role="status"
              className={`text-[10px] font-medium uppercase tracking-[0.12em] ${
                error ? "text-alarm" : stale ? "text-hold" : "text-fg-muted"
              }`}
            >
              {error
                ? "Offline"
                : loadedAt === null
                  ? "Connecting"
                  : stale
                    ? `Stale · ${relativeTime(new Date(loadedAt).toISOString(), now)}`
                    : `Live · ${relativeTime(new Date(loadedAt).toISOString(), now)}`}
            </span>
          </span>

          <button
            type="button"
            onClick={() => void load(true)}
            disabled={refreshing}
            aria-label="Refresh dashboard data"
            className="flex h-11 w-11 cursor-pointer items-center justify-center rounded-xl border border-line bg-fill text-fg-muted transition-colors duration-[--t-hover] hover:border-line-strong hover:bg-fill-strong hover:text-fg disabled:cursor-not-allowed disabled:opacity-45"
          >
            {refreshing ? (
              <IconSpinner className="h-4 w-4 animate-spin" />
            ) : (
              <IconRefresh className="h-4 w-4" />
            )}
          </button>

          {/* Sign out. Clearing the session is what actually ends it — the
              server call is for the audit trail, so a failure there must not
              leave the operator still signed in. */}
          <button
            type="button"
            onClick={() => { void api.logout().catch(() => {}); clearSession(); }}
            title={getSession()?.username ? `Signed in as ${getSession()?.username}` : undefined}
            className="hidden h-11 cursor-pointer items-center rounded-xl border border-line bg-fill px-3 text-[12px] font-medium text-fg-muted transition-colors duration-[--t-hover] hover:border-line-strong hover:text-fg sm:inline-flex"
          >
            Sign out
          </button>

          {/* Primary CTA. A real <Link> so browser history and back behave
              normally (ux-guidelines "Back Button": don't use location.replace). */}
          <Link
            href="/onboard"
            className="group inline-flex min-h-[44px] cursor-pointer items-center gap-1.5 rounded-xl bg-signal px-4 text-sm font-semibold text-on-primary shadow-[0_0_0_1px_rgba(34,211,238,0.4),0_8px_30px_-8px_rgba(34,211,238,0.55)] transition-all duration-[--t-hover] ease-swift hover:bg-signal/90 active:scale-[0.98]"
          >
            <IconPlus className="h-4 w-4" />
            Onboard
          </Link>
        </div>
      </header>

      {error && (
        <div
          role="alert"
          className="mt-5 flex items-start gap-2.5 rounded-xl border border-alarm/35 bg-alarm/[0.08] p-4"
        >
          <IconAlert className="mt-0.5 h-4 w-4 shrink-0 text-alarm" />
          <div className="min-w-0 space-y-1">
            <p className="text-[13px] font-medium text-fg">
              Dashboard data unavailable
            </p>
            <p className="break-words text-[13px] leading-relaxed text-fg-muted">
              {error}
            </p>
          </div>
        </div>
      )}

      {/* ── Metrics ──────────────────────────────────────────────────────── */}
      <section aria-label="Key metrics" className="mt-5">
        {loading ? (
          // Reserved height matches the tiles, so arriving data does not shift
          // the page (CLS).
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {[0, 1, 2, 3].map((i) => (
              <div
                key={i}
                className="glass min-h-[112px] animate-pulse rounded-xl"
              />
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatTile
              index={0}
              label="Mails sent"
              value={stats.mailsSent}
              caption="Accepted by Resend — acceptance, not proof of delivery"
              tone="settled"
              icon={<IconMail className="h-4 w-4" />}
            />
            <StatTile
              index={1}
              label="Awaiting approval"
              value={stats.awaitingApproval}
              caption="Paused at the gate — nothing sends without a decision"
              tone={stats.awaitingApproval > 0 ? "hold" : "neutral"}
              icon={<IconShield className="h-4 w-4" />}
            />
            <StatTile
              index={2}
              label="Dispatch failed"
              value={stats.dispatchFailed}
              caption={
                stats.sendSuccessRate === null
                  ? "No sends attempted yet"
                  : `${Math.round(stats.sendSuccessRate * 100)}% send success rate`
              }
              tone={stats.dispatchFailed > 0 ? "alarm" : "neutral"}
              icon={<IconAlert className="h-4 w-4" />}
            />
            <StatTile
              index={3}
              label="Workflows"
              value={stats.totalWorkflows}
              caption={`${stats.inFlight} running · ${stats.halted} halted`}
              tone="signal"
              icon={<IconLayers className="h-4 w-4" />}
            />
          </div>
        )}
      </section>

      {/* ── Breakdown strip ──────────────────────────────────────────────── */}
      {!loading && stats.totalWorkflows > 0 && (
        <GlassPanel className="mt-3 flex flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          {[
            { k: "Offers extended", v: stats.offersExtended },
            { k: "Declines", v: stats.declines },
            { k: "In flight", v: stats.inFlight },
            { k: "Halted", v: stats.halted },
          ].map((m) => (
            <span key={m.k} className="text-[12px] text-fg-muted">
              {m.k}{" "}
              <span className="ml-0.5 font-mono font-semibold tabular-nums text-fg">
                {m.v}
              </span>
            </span>
          ))}
        </GlassPanel>
      )}

      {/* ── §3 Appointment Letter Ready ──────────────────────────────────── */}
      <div className="mt-3">
        <NotificationPanel />
      </div>

      {/* ── Queues + activity ────────────────────────────────────────────── */}
      <div className="mt-3 grid gap-3 lg:grid-cols-3">
        <WorkQueue
          title="Awaiting approval"
          hint="Each of these is a paused graph. Open the thread to approve or reject dispatch."
          items={approvals}
          kind="approval"
          emptyLabel="Nothing waiting on you."
        />
        <WorkQueue
          title="Needs attention"
          hint="Runs that halted or failed to dispatch. The candidate was not contacted."
          items={attention}
          kind="attention"
          emptyLabel="No failures or halted runs."
        />
        <ActivityFeed entries={activity} />
      </div>

      {/* ── Correspondence log ───────────────────────────────────────────── */}
      <MailLog rows={mail} loading={loading} />

      {/* ── Voice follow-up ──────────────────────────────────────────────── */}
      <VoicePanel />

      {/* ── First-run empty state ────────────────────────────────────────── */}
      {!loading && !error && stats.totalWorkflows === 0 && (
        <GlassPanel className="mt-3 flex flex-col items-center gap-3 px-6 py-10 text-center">
          <span className="flex h-11 w-11 items-center justify-center rounded-xl border border-signal/25 bg-signal/[0.08] text-signal">
            <IconCheck className="h-5 w-5" />
          </span>
          <div className="space-y-1">
            <p className="text-[15px] font-semibold text-fg">No workflows yet</p>
            <p className="max-w-[46ch] text-[13px] leading-relaxed text-fg-muted">
              Start one and the agent will compute payroll, draft the agreement,
              and pause here for your approval before anything reaches the
              candidate.
            </p>
          </div>
          <Link
            href="/onboard"
            className="mt-1 inline-flex min-h-[44px] cursor-pointer items-center gap-1.5 rounded-xl bg-signal px-4 text-sm font-semibold text-on-primary transition-colors duration-[--t-hover] hover:bg-signal/90"
          >
            Onboard your first candidate
            <IconArrowRight className="h-4 w-4" />
          </Link>
        </GlassPanel>
      )}
    </div>
  );
}
