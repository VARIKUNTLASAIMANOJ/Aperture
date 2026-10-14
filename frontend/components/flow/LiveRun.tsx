"use client";

import { AnimatePresence, motion } from "framer-motion";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/Button";
import {
  IconAlert, IconArrowLeft, IconCheck, IconClock, IconLock,
  IconPulse, IconShield, IconX,
} from "@/components/ui/Icons";
import { api } from "@/lib/api";
import { money, pct } from "@/lib/form";
import { T } from "@/lib/motion";
import type {
  AuditEntry, OnboardingStateResponse, StreamEvent,
} from "@/lib/types";
import { useOnboardingStream } from "@/lib/useOnboardingStream";
import { useReducedMotion } from "@/lib/useReducedMotion";

interface LiveRunProps {
  threadId: string;
  candidateName: string;
  /**
   * Only the onboarding flow needs this — it drives the 3D agent's mood.
   * Optional so the same component can render a thread opened from the
   * dashboard, where there is no agent to drive.
   */
  onStateChange?: (s: OnboardingStateResponse | null, ev: StreamEvent | null) => void;
  onRestart: () => void;
  /** Label for the secondary action; differs by entry point. */
  restartLabel?: string;
  /**
   * Hold the exit control closed until the run is terminal.
   *
   * Right after launching a run this is a useful speed bump. When the thread
   * was *opened* from the dashboard queue it is not: the operator arrived to
   * review, may legitimately leave without deciding, and already has a
   * breadcrumb above — a locked button under a working link just contradicts
   * itself.
   */
  lockExitUntilTerminal?: boolean;
}

const NODE_LABEL: Record<string, string> = {
  INIT: "Initialising",
  triage_node: "Triage",
  financial_node: "Payroll calculation",
  contract_node: "Contract drafting",
  email_node: "Dispatch",
  error_handler: "Halted",
};

const PIPELINE = ["triage_node", "financial_node", "contract_node", "email_node"];

/** `YYYY-MM-DDTHH:mm` in LOCAL time, the only format datetime-local accepts. */
function localDateTimeValue(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}`
  );
}

export function LiveRun({
  threadId, candidateName, onStateChange, onRestart,
  restartLabel = "Onboard another candidate",
  lockExitUntilTerminal = true,
}: LiveRunProps) {
  const reduced = useReducedMotion();
  const stream = useOnboardingStream(threadId);
  const [snapshot, setSnapshot] = useState<OnboardingStateResponse | null>(null);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [decided, setDecided] = useState<"APPROVED" | "REJECTED" | null>(null);
  const [scheduleOn, setScheduleOn] = useState(false);
  const [scheduleAt, setScheduleAt] = useState("");
  const [scheduledFor, setScheduledFor] = useState<string | null>(null);
  const logRef = useRef<HTMLOListElement>(null);

  const refresh = useCallback(async () => {
    try {
      const [s, a] = await Promise.all([
        api.getState(threadId),
        api.audit(threadId),
      ]);
      setSnapshot(s);
      setAudit(a.audit_log);
      return s;
    } catch {
      return null;
    }
  }, [threadId]);

  // Initial fetch, then re-fetch whenever the stream reports a new checkpoint.
  // The stream carries status only; the full financials come from /state.
  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    if (stream.latest?.checkpoint_id) void refresh();
  }, [stream.latest?.checkpoint_id, refresh]);

  useEffect(() => {
    onStateChange?.(snapshot, stream.latest);
  }, [snapshot, stream.latest, onStateChange]);

  const approvalStatus = snapshot?.approval_status ?? null;
  const nodeStatus = snapshot?.node_status ?? null;
  const pending = stream.latest?.pending_nodes;
  const awaiting =
    approvalStatus === "NEEDS_APPROVAL" &&
    (snapshot?.email_queue_summary?.some((e) => e.status === "PENDING") ?? false) &&
    !decided;

  // A scheduled item is approved-but-unsent: the gate closes, yet the run is
  // not finished, so neither the gate nor the terminal block should claim it.
  const scheduledItem =
    snapshot?.email_queue_summary?.find((e) => e.status === "SCHEDULED") ?? null;

  const act = async (kind: "approve" | "reject") => {
    setBusy(kind);
    setActionError(null);
    try {
      if (kind === "approve") {
        // `datetime-local` yields wall-clock with no zone. Constructing a Date
        // from it interprets it in the operator's timezone — which is what they
        // meant — and toISOString then converts to the UTC the API stores.
        let sendAt: string | null = null;
        if (scheduleOn) {
          if (!scheduleAt) {
            setActionError("Pick a date and time, or switch back to sending now.");
            setBusy(null);
            return;
          }
          const local = new Date(scheduleAt);
          if (Number.isNaN(local.getTime())) {
            setActionError("That date and time could not be read.");
            setBusy(null);
            return;
          }
          if (local.getTime() < Date.now()) {
            setActionError("Pick a time in the future.");
            setBusy(null);
            return;
          }
          sendAt = local.toISOString();
        }

        const res = await api.approve(
          threadId,
          "hr-console@company.com",
          scheduleOn ? "Scheduled from console" : "Approved from console",
          sendAt,
        );
        if (sendAt) {
          setScheduledFor(res.scheduled_for ?? sendAt);
          // Deliberately NOT `decided`: the workflow is not finished, it is
          // waiting on a timer, and the run view should keep saying so.
          await refresh();
          setBusy(null);
          return;
        }
        setDecided("APPROVED");
      } else {
        await api.rejectApproval(
          threadId, "hr-console@company.com", "Rejected from console",
        );
        setDecided("REJECTED");
      }
      await refresh();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Action failed.");
    } finally {
      setBusy(null);
    }
  };

  const fin = snapshot?.calculated_financials;
  const leave = snapshot?.leave_allocations;
  const activeIdx = PIPELINE.indexOf(snapshot?.current_node ?? "");

  /**
   * What actually happened to the mail, read off the queue rather than
   * inferred from the approve call's HTTP status.
   *
   * email_node marks each item SENT / FAILED / CANCELLED individually and
   * stores the provider's error text in message_id on failure, so a partial
   * failure (some sent, some not) stays visible instead of collapsing into a
   * single success message.
   */
  const outcome = useMemo(() => {
    const queue = snapshot?.email_queue_summary ?? [];
    const sent = queue.filter((e) => e.status === "SENT");
    const failed = queue.filter((e) => e.status === "FAILED");
    const cancelled = queue.filter((e) => e.status === "CANCELLED");
    const auto = sent.some((e) => e.dispatch_mode === "AUTO")
      || failed.some((e) => e.dispatch_mode === "AUTO");

    let label: string;
    let tone: "ok" | "neutral" | "bad";

    if (failed.length > 0) {
      tone = "bad";
      label = sent.length
        ? `Partial dispatch — ${sent.length} sent, ${failed.length} failed.`
        : auto
          ? "Automatic send failed. Nothing was delivered."
          : "Dispatch failed. Nothing was delivered.";
    } else if (sent.length > 0) {
      tone = "ok";
      label = auto
        ? `Sent automatically — ${sent.length} email${sent.length > 1 ? "s" : ""} delivered on schedule.`
        : `Approved. ${sent.length} email${sent.length > 1 ? "s" : ""} dispatched via Resend.`;
    } else if (cancelled.length > 0) {
      tone = "neutral";
      label = "Dispatch rejected. Queued mail was cancelled — nothing was sent.";
    } else if (snapshot?.node_status === "ERROR") {
      tone = "bad";
      label = "Workflow halted before dispatch.";
    } else {
      tone = "neutral";
      label = "Workflow finished.";
    }
    return { label, tone, sent, failed, cancelled };
  }, [snapshot]);

  /**
   * The run is over — dispatched, cancelled, or halted. This gates the "go
   * back" control: while the graph is still computing, or parked waiting on a
   * decision only this screen can take, leaving would abandon the operator's
   * only view of it. The masthead logo stays a live link throughout, so this
   * is a deliberate speed bump on the primary path, never a keyboard trap.
   */
  // A scheduled send is explicitly NOT terminal: contract_node leaves
  // node_status COMPLETE, which would otherwise make the run look finished
  // while a letter is still queued to go out hours later.
  const terminal =
    !awaiting &&
    !scheduledItem &&
    (decided !== null ||
      stream.finished ||
      nodeStatus === "COMPLETE" ||
      nodeStatus === "ERROR");

  // Scheduled runs unlock the exit: the decision is made and the send is
  // unattended by design, so there is nothing left for the operator to watch.
  const exitUnlocked = terminal || !!scheduledItem;

  const lockReason = awaiting
    ? "Approve or reject dispatch to finish this run."
    : "Unlocks once the agent finishes this run.";

  return (
    <div className="space-y-6">
      {/* ── Pipeline ───────────────────────────────────────────────────── */}
      <section aria-label="Agent pipeline">
        <div className="flex items-center gap-2">
          {PIPELINE.map((node, i) => {
            const done = activeIdx > i || (activeIdx === i && nodeStatus === "COMPLETE");
            const active = snapshot?.current_node === node;
            const halted = nodeStatus === "ERROR" && active;
            return (
              <div key={node} className="flex min-w-0 flex-1 flex-col gap-1.5">
                <span className="relative block h-[3px] overflow-hidden rounded-full bg-fill-strong">
                  <motion.span
                    className={`absolute inset-y-0 left-0 rounded-full ${
                      halted ? "bg-alarm" : done ? "bg-settled" : "bg-signal"
                    }`}
                    initial={false}
                    animate={{ width: done ? "100%" : active ? "60%" : "0%" }}
                    transition={reduced ? { duration: 0.05 } : T.panel}
                  />
                  {active && !reduced && !halted && (
                    <span className="absolute inset-y-0 left-0 w-full animate-pulse bg-signal/20" />
                  )}
                </span>
                <span
                  className={`truncate text-[10px] font-medium uppercase tracking-[0.12em] ${
                    active ? "text-fg" : done ? "text-fg-muted" : "text-fg-faint"
                  }`}
                >
                  {NODE_LABEL[node]}
                </span>
              </div>
            );
          })}
        </div>

        <p className="sr-only" aria-live="polite">
          {snapshot
            ? `${NODE_LABEL[snapshot.current_node ?? ""] ?? "Running"}, status ${snapshot.node_status}`
            : "Connecting to agent"}
        </p>
      </section>

      {/* ── Approval gate ──────────────────────────────────────────────── */}
      <AnimatePresence mode="wait">
        {awaiting && (
          <motion.section
            key="gate"
            initial={reduced ? { opacity: 0 } : { opacity: 0, y: 14, scale: 0.985 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={reduced ? { opacity: 0 } : { opacity: 0, y: -10 }}
            transition={T.panel}
            className="relative overflow-hidden rounded-2xl border border-hold/30 bg-hold/[0.07] p-5"
            aria-labelledby="gate-title"
          >
            <span
              aria-hidden="true"
              className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-hold to-transparent"
            />
            <div className="flex items-start gap-3">
              <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-hold/35 bg-hold/10 text-hold">
                <IconShield className="h-[18px] w-[18px]" />
              </span>
              <div className="min-w-0 flex-1 space-y-3">
                <div className="space-y-1">
                  <h3 id="gate-title" className="text-[15px] font-semibold text-fg">
                    Human approval required
                  </h3>
                  <p className="text-[13px] leading-relaxed text-fg-muted">
                    The graph is paused before dispatch.{" "}
                    {scheduleOn ? "Scheduling queues" : "Approving sends"}{" "}
                    {snapshot?.email_queue_summary?.length ?? 1} email to{" "}
                    <span className="font-medium text-fg">
                      {snapshot?.email_queue_summary?.[0]?.recipient ?? candidateName}
                    </span>
                    {scheduleOn
                      ? " for automatic delivery at the time you pick."
                      : ". This cannot be undone."}
                  </p>
                </div>

                {/* ── Schedule ───────────────────────────────────────────── */}
                <div className="rounded-xl border border-line bg-fill p-3">
                  <label className="flex min-h-[44px] cursor-pointer items-center gap-2.5">
                    <input
                      type="checkbox"
                      checked={scheduleOn}
                      onChange={(e) => setScheduleOn(e.target.checked)}
                      className="h-4 w-4 shrink-0 cursor-pointer accent-[rgb(var(--c-violet))]"
                    />
                    <span className="text-[13px] font-medium text-fg">
                      Send later instead
                    </span>
                    <IconClock className="h-3.5 w-3.5 text-fg-muted" />
                  </label>

                  {scheduleOn && (
                    <div className="mt-1 space-y-1.5">
                      {/* Visible label, not placeholder-only, and a real
                          datetime-local so the OS picker does the work. */}
                      <label
                        htmlFor="send-at"
                        className="block text-micro font-medium text-fg-muted"
                      >
                        Send date and time
                      </label>
                      <input
                        id="send-at"
                        type="datetime-local"
                        value={scheduleAt}
                        // Must be LOCAL wall-clock: datetime-local compares
                        // `min` against what the user sees, so toISOString()
                        // here would offset the floor by the timezone —
                        // permissive east of UTC, and wrongly blocking west of it.
                        min={localDateTimeValue(new Date(Date.now() + 60_000))}
                        onChange={(e) => setScheduleAt(e.target.value)}
                        aria-describedby="send-at-hint"
                        className="w-full cursor-pointer rounded-lg border border-line bg-fill px-3 py-2.5 text-[14px] text-fg [color-scheme:dark] focus:border-violet/60"
                      />
                      <p id="send-at-hint" className="text-[11px] leading-snug text-fg-faint">
                        Your local time. The letter stays unsent until then —
                        nothing is dispatched now.
                      </p>
                    </div>
                  )}
                </div>

                {actionError && (
                  <p role="alert" className="flex items-center gap-1.5 text-xs font-medium text-alarm">
                    <IconAlert className="h-3.5 w-3.5 shrink-0" />
                    {actionError}
                  </p>
                )}

                <div className="flex flex-wrap gap-2.5">
                  <Button
                    variant="hold"
                    loading={busy === "approve"}
                    disabled={busy !== null}
                    onClick={() => act("approve")}
                  >
                    {busy !== "approve" && <IconCheck className="h-4 w-4" />}
                    {scheduleOn ? "Approve and schedule" : "Approve and send"}
                  </Button>
                  <Button
                    variant="danger"
                    loading={busy === "reject"}
                    disabled={busy !== null}
                    onClick={() => act("reject")}
                  >
                    {busy !== "reject" && <IconX className="h-4 w-4" />}
                    Reject dispatch
                  </Button>
                </div>
              </div>
            </div>
          </motion.section>
        )}
      </AnimatePresence>

      {/* ── Scheduled auto-send ────────────────────────────────────────── */}
      {scheduledItem && (
        <motion.section
          initial={reduced ? { opacity: 0 } : { opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={T.panel}
          className="relative overflow-hidden rounded-2xl border border-violet/30 bg-violet/[0.07] p-5"
          aria-labelledby="scheduled-title"
        >
          <span
            aria-hidden="true"
            className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-violet to-transparent"
          />
          <div className="flex items-start gap-3">
            <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-violet/35 bg-violet/10 text-violet">
              <IconClock className="h-[18px] w-[18px]" />
            </span>
            <div className="min-w-0 space-y-1">
              <h3 id="scheduled-title" className="text-[15px] font-semibold text-fg">
                Scheduled for automatic send
              </h3>
              <p className="text-[13px] leading-relaxed text-fg-muted">
                Approved, but nothing has been sent yet. The agent will deliver
                to{" "}
                <span className="font-medium text-fg">
                  {scheduledItem.recipient}
                </span>{" "}
                on{" "}
                <span className="font-medium text-fg">
                  {scheduledItem.scheduled_for
                    ? new Date(scheduledItem.scheduled_for).toLocaleString()
                    : "the scheduled time"}
                </span>
                . Rejecting before then cancels it.
              </p>
            </div>
          </div>
        </motion.section>
      )}

      {/* ── Results ────────────────────────────────────────────────────── */}
      {(fin?.annual_gross != null || leave?.pto_days != null) && (
        <motion.section
          initial={reduced ? { opacity: 0 } : { opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={T.panel}
          className="space-y-4"
          aria-label="Computed results"
        >
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              { k: "Annual gross", v: money(fin?.annual_gross) },
              { k: "Annual net", v: money(fin?.annual_net) },
              { k: "Monthly net", v: money(fin?.monthly_net) },
              { k: "Effective rate", v: pct(fin?.effective_tax_rate) },
            ].map((m) => (
              <div
                key={m.k}
                className="rounded-xl border border-line bg-fill px-4 py-3"
              >
                <p className="text-micro font-medium text-fg-muted">
                  {m.k}
                </p>
                <p className="mt-1 font-mono text-lg font-semibold tabular-nums text-fg">
                  {m.v}
                </p>
              </div>
            ))}
          </div>

          {leave?.pto_days != null && (
            <div className="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-xl border border-line bg-fill px-4 py-3 text-[13px]">
              <span className="text-fg-muted">
                PTO{" "}
                <span className="font-mono font-semibold tabular-nums text-fg">
                  {leave.pto_days}d
                </span>
              </span>
              <span className="text-fg-muted">
                Sick{" "}
                <span className="font-mono font-semibold tabular-nums text-fg">
                  {leave.sick_days}d
                </span>
              </span>
              <span className="text-fg-muted">
                Parental{" "}
                <span className="font-mono font-semibold tabular-nums text-fg">
                  {leave.parental_leave_days}d
                </span>
              </span>
              {leave.proration_factor != null && (
                <span className="text-fg-faint">
                  prorated ×{leave.proration_factor}
                </span>
              )}
            </div>
          )}
        </motion.section>
      )}

      {/* ── Error ──────────────────────────────────────────────────────── */}
      {snapshot?.error_message && (
        <div
          role="alert"
          className="flex items-start gap-2.5 rounded-xl border border-alarm/35 bg-alarm/[0.08] p-4"
        >
          <IconAlert className="mt-0.5 h-4 w-4 shrink-0 text-alarm" />
          <p className="break-words text-[13px] leading-relaxed text-fg-muted">
            {snapshot.error_message}
          </p>
        </div>
      )}

      {/* ── Audit trail ────────────────────────────────────────────────── */}
      <section aria-label="Audit trail" className="space-y-2">
        <header className="flex items-center justify-between">
          <h3 className="flex items-center gap-1.5 text-base font-semibold text-fg">
            <IconPulse className="h-3.5 w-3.5" />
            Audit trail
          </h3>
          <span
            className={`flex items-center gap-1.5 text-micro font-medium ${
              stream.connected ? "text-settled" : stream.finished ? "text-fg-muted" : "text-fg-faint"
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                stream.connected ? "bg-settled" : "bg-fg-faint"
              } ${stream.connected && !reduced ? "animate-pulse" : ""}`}
              aria-hidden="true"
            />
            {stream.connected ? "Live" : stream.finished ? "Closed" : "Idle"}
          </span>
        </header>

        <ol
          ref={logRef}
          className="thin-scroll max-h-52 space-y-px overflow-y-auto rounded-xl border border-line bg-black/20 p-1"
        >
          {audit.length === 0 && (
            <li className="px-3 py-4 text-[13px] text-fg-faint">
              No entries yet.
            </li>
          )}
          {audit.map((e, i) => (
            <li
              key={`${e.timestamp}-${i}`}
              className="rounded-lg px-3 py-2 transition-colors duration-[--t-hover] hover:bg-fill"
            >
              <div className="flex items-baseline gap-2">
                <IconClock className="h-3 w-3 shrink-0 translate-y-0.5 text-fg-faint" />
                <span className="font-mono text-[10px] tabular-nums text-fg-faint">
                  {new Date(e.timestamp).toLocaleTimeString()}
                </span>
                <span className="font-mono text-[10px] font-semibold uppercase tracking-wider text-signal">
                  {e.event}
                </span>
              </div>
              <p className="mt-0.5 pl-5 text-[12px] leading-relaxed text-fg-muted">
                {e.payload_summary}
              </p>
            </li>
          ))}
        </ol>
      </section>

      {/* ── Terminal state ─────────────────────────────────────────────── */}
      {terminal && (
          <div className="space-y-3 border-t border-line pt-5">
            {/* Never claim a send succeeded because /approve returned 200 — it
                returns 200 whenever the graph RESUMED, even if every message
                failed at the provider. The queue item's own status is the only
                honest source. */}
            {outcome.failed.length > 0 && (
              <div
                role="alert"
                className="flex items-start gap-2.5 rounded-xl border border-alarm/35 bg-alarm/[0.08] p-4"
              >
                <IconAlert className="mt-0.5 h-4 w-4 shrink-0 text-alarm" />
                <div className="min-w-0 space-y-1">
                  <p className="text-[13px] font-medium text-fg">
                    {outcome.failed.length} email
                    {outcome.failed.length > 1 ? "s" : ""} could not be sent
                  </p>
                  {outcome.failed.map((e, i) => (
                    <p
                      key={i}
                      className="break-words text-[13px] leading-relaxed text-fg-muted"
                    >
                      <span className="text-fg">{e.recipient}</span>
                      {e.message_id ? ` — ${e.message_id}` : ""}
                    </p>
                  ))}
                  <p className="text-[13px] leading-relaxed text-fg-muted">
                    The candidate was not contacted. Fix the cause and run the
                    workflow again.
                  </p>
                </div>
              </div>
            )}

            <p className="flex items-center gap-2 text-[13px] text-fg-muted">
              {outcome.tone === "ok" && (
                <IconCheck className="h-4 w-4 shrink-0 text-settled" />
              )}
              {outcome.tone === "neutral" && (
                <IconX className="h-4 w-4 shrink-0 text-fg-muted" />
              )}
              {outcome.tone === "bad" && (
                <IconAlert className="h-4 w-4 shrink-0 text-alarm" />
              )}
              {outcome.label}
            </p>
          </div>
        )}

      {/* ── Exit ───────────────────────────────────────────────────────────
          Rendered in both states so the control does not appear out of
          nowhere at the end — it is visibly present and visibly locked while
          the run is live, then unlocks. */}
      <div
        className={`flex flex-wrap items-center justify-between gap-3 ${
          terminal ? "" : "border-t border-line pt-5"
        }`}
      >
        {exitUnlocked || !lockExitUntilTerminal ? (
          <>
            <motion.div
              initial={reduced ? { opacity: 0 } : { opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={T.panel}
            >
              <Link
                href="/"
                className="inline-flex min-h-[44px] cursor-pointer items-center gap-2 rounded-xl bg-signal px-5 text-sm font-semibold text-on-primary shadow-[0_0_0_1px_rgba(34,211,238,0.4),0_8px_30px_-8px_rgba(34,211,238,0.5)] transition-colors duration-[--t-hover] ease-swift hover:bg-signal/90"
              >
                <IconArrowLeft className="h-4 w-4" />
                Go back to dashboard
              </Link>
            </motion.div>
            <Button variant="ghost" onClick={onRestart}>
              {restartLabel}
            </Button>
          </>
        ) : (
          <>
            <span
              // aria-disabled rather than `disabled`: the control stays
              // reachable by keyboard so screen-reader users can find it and
              // hear why it is unavailable.
              role="button"
              aria-disabled="true"
              tabIndex={0}
              aria-describedby="exit-lock-reason"
              className="inline-flex min-h-[44px] cursor-not-allowed items-center gap-2 rounded-xl border border-line bg-fill px-5 text-sm font-medium text-fg-faint"
            >
              <IconLock className="h-4 w-4" />
              Go back to dashboard
            </span>
            <p
              id="exit-lock-reason"
              className="text-[12px] leading-snug text-fg-faint"
            >
              {lockReason}
            </p>
          </>
        )}
      </div>

      <p className="font-mono text-[10px] text-fg-faint">
        thread {threadId}
      </p>
    </div>
  );
}
