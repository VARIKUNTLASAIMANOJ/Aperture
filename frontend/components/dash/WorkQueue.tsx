"use client";

import Link from "next/link";

import { GlassPanel } from "@/components/ui/GlassPanel";
import {
  IconAlert, IconCheck, IconChevronRight, IconShield,
} from "@/components/ui/Icons";
import { hasFailedDispatch, stageLabel } from "@/lib/dashboardData";
import type { Candidate } from "@/lib/types";

interface WorkQueueProps {
  title: string;
  hint: string;
  items: Candidate[];
  kind: "approval" | "attention";
  /** Shown when the list is empty — never a blank panel. */
  emptyLabel: string;
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  return (parts[0][0] + (parts[1]?.[0] ?? "")).toUpperCase();
}

/**
 * ux-guidelines "Empty States" (Do: "Show helpful message and action"): an
 * empty queue is the *good* outcome here, so it reads as a cleared state
 * rather than missing data.
 */
export function WorkQueue({ title, hint, items, kind, emptyLabel }: WorkQueueProps) {
  const accent = kind === "approval" ? "text-hold" : "text-alarm";
  const ring = kind === "approval" ? "border-hold/25" : "border-alarm/25";

  return (
    <GlassPanel className="flex min-h-[236px] flex-col overflow-hidden">
      <header className="flex items-baseline justify-between gap-3 border-b border-line-soft px-4 py-3">
        <h2 className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-fg">
          <span className={accent}>
            {kind === "approval" ? (
              <IconShield className="h-3.5 w-3.5" />
            ) : (
              <IconAlert className="h-3.5 w-3.5" />
            )}
          </span>
          {title}
        </h2>
        <span className="font-mono text-[11px] tabular-nums text-fg-muted">
          {items.length}
        </span>
      </header>

      <p className="px-4 pt-2.5 text-[11px] leading-snug text-fg-faint">{hint}</p>

      {items.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 px-4 py-8 text-center">
          <span className="flex h-9 w-9 items-center justify-center rounded-full border border-settled/25 bg-settled/[0.08] text-settled">
            <IconCheck className="h-4 w-4" />
          </span>
          <p className="text-[13px] text-fg-muted">{emptyLabel}</p>
        </div>
      ) : (
        <ul className="thin-scroll mt-1 max-h-[240px] flex-1 space-y-px overflow-y-auto px-2 pb-2">
          {items.map((c) => (
            <li key={c.thread_id}>
              {/* A real link, so the row is deep-linkable, middle-clickable and
                  back-button friendly. Approval deliberately happens on the
                  thread page rather than inline here: sending a binding offer
                  should not be a one-click action taken from a list, without
                  sight of the recipient, figures and audit trail. */}
              <Link
                href={`/thread/${encodeURIComponent(c.thread_id)}`}
                className="group block min-h-[44px] rounded-lg px-2 py-2 transition-colors duration-[--t-hover] hover:bg-fill-strong"
              >
              <div className="flex items-center gap-2.5">
                <span
                  className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border ${ring} bg-fill font-mono text-[10px] font-semibold text-fg`}
                  aria-hidden="true"
                >
                  {initials(c.candidate_name)}
                </span>

                <div className="min-w-0 flex-1">
                  <p className="truncate text-[13px] font-medium text-fg">
                    {c.candidate_name || "Unnamed"}
                  </p>
                  <p className="truncate text-[11px] text-fg-muted">
                    {c.role_title || "—"}
                    {c.department ? ` · ${c.department}` : ""}
                  </p>
                </div>

                <span
                  className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.1em] ${
                    kind === "approval"
                      ? "border-hold/30 bg-hold/10 text-hold"
                      : "border-alarm/30 bg-alarm/10 text-alarm"
                  }`}
                >
                  {stageLabel(c)}
                </span>

                <IconChevronRight
                  className="h-3.5 w-3.5 shrink-0 text-fg-faint transition-transform duration-[--t-hover] group-hover:translate-x-0.5 group-hover:text-fg-muted"
                />
              </div>

              {kind === "attention" && hasFailedDispatch(c) && (
                <p className="mt-1 pl-[38px] text-[11px] leading-snug text-fg-faint">
                  {c.email_queue_summary.find((e) => e.status === "FAILED")
                    ?.message_id ?? "Dispatch failed."}
                </p>
              )}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </GlassPanel>
  );
}
