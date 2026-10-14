"use client";

import { GlassPanel } from "@/components/ui/GlassPanel";
import { IconPulse } from "@/components/ui/Icons";
import { relativeTime } from "@/lib/dashboardData";
import type { AuditEntry } from "@/lib/types";

/** Event name → tone. Anything unmapped stays neutral rather than guessing. */
const EVENT_TONE: Record<string, string> = {
  CANDIDATE_SELECTED_ROUTED: "text-signal",
  FINANCIALS_CALCULATED: "text-signal",
  OFFER_LETTER_GENERATED: "text-signal",
  REJECTION_EMAIL_QUEUED: "text-hold",
  EMAILS_DISPATCHED: "text-settled",
  DISPATCH_REJECTED: "text-fg-muted",
  CONTRACT_GENERATION_ERROR: "text-alarm",
  CALCULATION_ERROR: "text-alarm",
  VALIDATION_ERROR: "text-alarm",
};

export function ActivityFeed({ entries }: { entries: AuditEntry[] }) {
  return (
    <GlassPanel className="flex min-h-[236px] flex-col overflow-hidden">
      <header className="flex items-baseline justify-between gap-3 border-b border-line-soft px-4 py-3">
        <h2 className="flex items-center gap-2 text-lead font-semibold text-fg">
          <IconPulse className="h-3.5 w-3.5 text-signal" />
          Activity
        </h2>
        <span className="text-micro text-fg-faint">
          Audit trail
        </span>
      </header>

      {entries.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-1.5 px-4 py-8 text-center">
          <p className="text-[13px] text-fg-muted">No activity recorded yet.</p>
          <p className="text-[11px] text-fg-faint">
            Onboard a candidate to start the trail.
          </p>
        </div>
      ) : (
        <ol className="thin-scroll max-h-[300px] flex-1 space-y-px overflow-y-auto p-2">
          {entries.map((e, i) => (
            <li
              key={`${e.timestamp}-${i}`}
              className="relative rounded-lg py-1.5 pl-6 pr-2 transition-colors duration-[--t-hover] hover:bg-fill"
            >
              {/* Rail + node. Decorative; the text carries all meaning. */}
              <span
                aria-hidden="true"
                className="absolute bottom-0 left-[9px] top-0 w-px bg-fill-strong"
              />
              <span
                aria-hidden="true"
                className={`absolute left-[6px] top-[13px] h-[7px] w-[7px] rounded-full border border-void ${
                  (EVENT_TONE[e.event] ?? "text-fg-muted").replace("text-", "bg-")
                }`}
              />

              <div className="flex flex-wrap items-baseline gap-x-2">
                <span
                  className={`font-mono text-[10px] font-semibold uppercase tracking-wider ${
                    EVENT_TONE[e.event] ?? "text-fg-muted"
                  }`}
                >
                  {e.event.replace(/_/g, " ")}
                </span>
                <span
                  className="font-mono text-[10px] tabular-nums text-fg-faint"
                  title={new Date(e.timestamp).toLocaleString()}
                >
                  {relativeTime(e.timestamp)}
                </span>
              </div>

              {e.candidate_name && (
                <p className="mt-0.5 truncate text-[12px] font-medium text-fg">
                  {e.candidate_name}
                </p>
              )}
              <p className="mt-0.5 text-[11px] leading-snug text-fg-muted">
                {e.payload_summary}
              </p>
            </li>
          ))}
        </ol>
      )}
    </GlassPanel>
  );
}
