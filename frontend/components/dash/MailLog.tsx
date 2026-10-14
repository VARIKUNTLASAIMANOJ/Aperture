"use client";

import { useState } from "react";

import { GlassPanel } from "@/components/ui/GlassPanel";
import {
  IconChevronRight, IconMail, IconSearch,
} from "@/components/ui/Icons";
import {
  TIMESTAMP_VERB, formatMailDate, mailKind, mailStatusLabel, type MailRow,
} from "@/lib/dashboardData";
import { LetterViewer } from "./LetterViewer";

interface MailLogProps {
  rows: MailRow[];
  loading?: boolean;
  /**
   * True when this panel IS the page rather than a card on the dashboard.
   * Drops its own title and the stacking margin, because the route header
   * already names it — two "Correspondence" headings one above the other
   * reads as a bug.
   */
  standalone?: boolean;
}

const STATUS_STYLE: Record<string, string> = {
  SENT: "border-settled/30 bg-settled/10 text-settled",
  PENDING: "border-hold/30 bg-hold/10 text-hold",
  // Violet separates a machine timer from the amber "a human must act" state —
  // both are unsent, but only one is waiting on a person.
  SCHEDULED: "border-violet/35 bg-violet/10 text-violet",
  FAILED: "border-alarm/30 bg-alarm/10 text-alarm",
  CANCELLED: "border-line-strong bg-fill-strong text-fg-muted",
};

const KIND_STYLE: Record<string, string> = {
  Offer: "text-signal",
  Rejection: "text-fg-muted",
  Notice: "text-fg-muted",
};

type Filter = "ALL" | "SENT" | "SCHEDULED" | "PENDING" | "FAILED";

const FILTERS: { id: Filter; label: string }[] = [
  { id: "ALL", label: "All" },
  { id: "SENT", label: "Sent" },
  { id: "SCHEDULED", label: "Scheduled" },
  { id: "PENDING", label: "Awaiting" },
  { id: "FAILED", label: "Failed" },
];

/**
 * Every outbound letter across all workflows, in one scrollable log.
 *
 * Kind (Offer / Rejection) and status (Sent / Awaiting / Failed / Cancelled)
 * are shown as two separate chips on purpose — a rejection that was sent and
 * an offer that is still awaiting approval are completely different things,
 * and collapsing them into one badge would blur exactly the distinction an
 * operator is scanning for.
 */
export function MailLog({ rows, loading = false, standalone = false }: MailLogProps) {
  const [filter, setFilter] = useState<Filter>("ALL");
  const [open, setOpen] = useState<MailRow | null>(null);

  const visible = filter === "ALL" ? rows : rows.filter((r) => r.status === filter);
  const counts = {
    ALL: rows.length,
    SENT: rows.filter((r) => r.status === "SENT").length,
    SCHEDULED: rows.filter((r) => r.status === "SCHEDULED").length,
    PENDING: rows.filter((r) => r.status === "PENDING").length,
    FAILED: rows.filter((r) => r.status === "FAILED").length,
  };

  return (
    <>
      <GlassPanel className={`${standalone ? "" : "mt-3"} flex flex-col overflow-hidden`}>
        <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-line-soft px-4 py-3">
          {!standalone && (
            <div className="flex items-baseline gap-2">
              <h2 className="flex items-center gap-2 text-lead font-semibold text-fg">
                <IconMail className="h-3.5 w-3.5 text-signal" />
                Correspondence
              </h2>
              <span className="font-mono text-micro tabular-nums text-fg-muted">
                {counts.ALL}
              </span>
            </div>
          )}

          {/* Filter chips double as the legend for what the log contains. */}
          <div role="group" aria-label="Filter correspondence" className="flex flex-wrap gap-1.5">
            {FILTERS.map((f) => {
              const active = filter === f.id;
              return (
                <button
                  key={f.id}
                  type="button"
                  onClick={() => setFilter(f.id)}
                  aria-pressed={active}
                  // 44px hit area (priority 2, CRITICAL) with a −6px block
                  // margin, so the target is finger-sized while the chip keeps
                  // the compact rhythm the header needs.
                  className={`-my-1.5 inline-flex min-h-[44px] cursor-pointer items-center rounded-lg border px-2.5 text-[11px] font-medium transition-colors duration-[--t-hover] ease-swift
                    ${active
                      ? "border-signal/50 bg-signal/12 text-signal"
                      : "border-line bg-fill text-fg-muted hover:border-line-strong hover:text-fg"}`}
                >
                  {f.label}
                  <span className="ml-1.5 font-mono tabular-nums opacity-70">
                    {counts[f.id]}
                  </span>
                </button>
              );
            })}
          </div>
        </header>

        <p className="px-4 pt-2.5 text-[11px] leading-snug text-fg-faint">
          Every letter the agent produced. Open one to read exactly what was — or
          would be — delivered.
        </p>

        {loading ? (
          <div className="space-y-px p-2">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="h-[52px] animate-pulse rounded-lg bg-fill" />
            ))}
          </div>
        ) : visible.length === 0 ? (
          <div className="flex flex-col items-center gap-1.5 px-4 py-10 text-center">
            <IconSearch className="h-5 w-5 text-fg-faint" />
            <p className="text-[13px] text-fg-muted">
              {rows.length === 0
                ? "No letters yet."
                : `No ${mailStatusLabel(filter).toLowerCase()} letters.`}
            </p>
            {rows.length > 0 && filter !== "ALL" && (
              <button
                type="button"
                onClick={() => setFilter("ALL")}
                className="min-h-[44px] cursor-pointer text-[13px] font-medium text-signal hover:underline"
              >
                Show all {counts.ALL}
              </button>
            )}
          </div>
        ) : (
          /* Fixed max height + overflow-y makes this the scrolling box; the
             page itself never grows to accommodate the log. */
          <ul className="thin-scroll max-h-[320px] space-y-px overflow-y-auto p-2">
            {visible.map((r) => (
              <li key={`${r.threadId}-${r.index}`}>
                <button
                  type="button"
                  onClick={() => setOpen(r)}
                  className="group flex min-h-[52px] w-full cursor-pointer items-center gap-3 rounded-lg px-2 py-2 text-left transition-colors duration-[--t-hover] hover:bg-fill-strong"
                >
                  <span
                    className={`shrink-0 ${KIND_STYLE[mailKind(r.template)]}`}
                    aria-hidden="true"
                  >
                    <IconMail className="h-4 w-4" />
                  </span>

                  <span className="min-w-0 flex-1">
                    <span className="flex items-baseline gap-1.5">
                      <span className="truncate text-[13px] font-medium text-fg">
                        {r.candidateName}
                      </span>
                      <span className="shrink-0 text-[11px] text-fg-faint">
                        {mailKind(r.template)}
                      </span>
                      {/* Auto marker rides beside the kind so it survives in
                          the Sent tab, where the status chip just says Sent. */}
                      {r.dispatchMode === "AUTO" && r.status !== "SCHEDULED" && (
                        <span className="shrink-0 rounded border border-violet/30 bg-violet/10 px-1 text-[9px] font-semibold uppercase tracking-[0.08em] text-violet">
                          Auto
                        </span>
                      )}
                    </span>
                    <span className="block truncate text-[11px] text-fg-muted">
                      {r.recipient}
                    </span>
                    {/* Narrow layouts have no room for the right-hand column,
                        so the date rides along here instead of disappearing. */}
                    {r.timestamp && (
                      <span className="block truncate font-mono text-[10px] tabular-nums text-fg-faint sm:hidden">
                        {r.timestampKind ? TIMESTAMP_VERB[r.timestampKind] : ""}{" "}
                        {formatMailDate(r.timestamp)}
                      </span>
                    )}
                  </span>

                  {/* The verb is carried with the date: "Sent 16 Aug" must never
                      appear on a letter that was only queued or cancelled. */}
                  <span className="hidden shrink-0 text-right sm:block">
                    {r.timestamp ? (
                      <>
                        <span
                          className="block font-mono text-[11px] tabular-nums text-fg-muted"
                          title={new Date(r.timestamp).toLocaleString()}
                        >
                          {formatMailDate(r.timestamp)}
                        </span>
                        <span className="block text-micro text-fg-faint">
                          {r.timestampKind ? TIMESTAMP_VERB[r.timestampKind] : ""}
                        </span>
                      </>
                    ) : (
                      <span className="block text-[11px] text-fg-faint">No date</span>
                    )}
                  </span>

                  <span
                    className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.1em] ${
                      STATUS_STYLE[r.status] ?? STATUS_STYLE.CANCELLED
                    }`}
                  >
                    {mailStatusLabel(r.status, r.dispatchMode)}
                  </span>

                  <IconChevronRight className="h-3.5 w-3.5 shrink-0 text-fg-faint transition-transform duration-[--t-hover] group-hover:translate-x-0.5 group-hover:text-fg-muted" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </GlassPanel>

      <LetterViewer row={open} onClose={() => setOpen(null)} />
    </>
  );
}
