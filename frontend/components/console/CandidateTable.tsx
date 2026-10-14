"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { IconAlert, IconSearch } from "@/components/ui/Icons";
import {
  hasFailedDispatch, isAwaitingApproval, stageLabel,
} from "@/lib/dashboardData";
import type { Candidate } from "@/lib/types";

/**
 * Every workflow as one scannable table.
 *
 * Replaces the three card queues. Cards cost roughly five times the vertical
 * space per candidate and could not be sorted or searched, so forty threads
 * meant scrolling past forty boxes. A table also lets the state that needs
 * action sit in a column the eye can run down.
 */

type Filter = "ALL" | "ACTION" | "FAILED" | "RUNNING" | "DONE";

const FILTERS: { id: Filter; label: string }[] = [
  { id: "ALL", label: "All" },
  { id: "ACTION", label: "Needs you" },
  { id: "FAILED", label: "Failed" },
  { id: "RUNNING", label: "In flight" },
  { id: "DONE", label: "Settled" },
];

const STAGE_TONE: Record<string, string> = {
  "Awaiting approval": "text-hold",
  Halted: "text-alarm",
  Rejected: "text-fg-muted",
  Declined: "text-alarm",
  Completed: "text-settled",
  Accepted: "text-settled",
};

function matches(c: Candidate, f: Filter): boolean {
  switch (f) {
    case "ACTION":  return isAwaitingApproval(c);
    case "FAILED":  return hasFailedDispatch(c);
    case "RUNNING": return !isAwaitingApproval(c) && !hasFailedDispatch(c)
                        && c.kanban_column !== "COMPLETED";
    case "DONE":    return c.kanban_column === "COMPLETED" && !hasFailedDispatch(c);
    default:        return true;
  }
}

export function CandidateTable({
  candidates, loading, limit, compact = false,
}: {
  candidates: Candidate[];
  loading?: boolean;
  limit?: number;
  compact?: boolean;
}) {
  const [filter, setFilter] = useState<Filter>("ALL");
  const [query, setQuery] = useState("");

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const out = candidates.filter(
      (c) =>
        matches(c, filter) &&
        (!q ||
          c.candidate_name?.toLowerCase().includes(q) ||
          c.role_title?.toLowerCase().includes(q) ||
          c.candidate_email?.toLowerCase().includes(q)),
    );
    return limit ? out.slice(0, limit) : out;
  }, [candidates, filter, query, limit]);

  const counts = useMemo(
    () => Object.fromEntries(
      FILTERS.map((f) => [f.id, candidates.filter((c) => matches(c, f.id)).length]),
    ) as Record<Filter, number>,
    [candidates],
  );

  if (loading) {
    return (
      <div className="surface overflow-hidden rounded-card">
        {[0, 1, 2, 3, 4].map((i) => (
          <div key={i} className="h-[52px] animate-pulse border-b border-line-soft last:border-0" />
        ))}
      </div>
    );
  }

  return (
    <section className="surface overflow-hidden rounded-card">
      {!compact && (
        <header className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line-soft px-3 py-2.5">
          <div role="group" aria-label="Filter candidates" className="flex flex-wrap gap-1">
            {FILTERS.map((f) => {
              const active = filter === f.id;
              return (
                <button
                  key={f.id}
                  type="button"
                  onClick={() => setFilter(f.id)}
                  aria-pressed={active}
                  className={`inline-flex min-h-[32px] cursor-pointer items-center gap-1.5 rounded-lg px-2.5 text-body transition-colors duration-[--t-hover] ${
                    active
                      ? "bg-fill-strong font-medium text-fg"
                      : "text-fg-muted hover:bg-fill hover:text-fg"
                  }`}
                >
                  {f.label}
                  <span className="font-mono text-micro tabular-nums opacity-60">
                    {counts[f.id]}
                  </span>
                </button>
              );
            })}
          </div>

          <label className="ml-auto flex min-w-[180px] flex-1 items-center gap-2 rounded-lg border border-line-soft px-2.5 sm:max-w-[260px] sm:flex-none">
            <IconSearch className="h-3.5 w-3.5 shrink-0 text-fg-faint" />
            <span className="sr-only">Search candidates</span>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search name, role or email"
              className="min-h-[32px] w-full bg-transparent text-body text-fg outline-none placeholder:text-fg-faint"
            />
          </label>
        </header>
      )}

      {rows.length === 0 ? (
        <div className="px-4 py-12 text-center">
          <p className="text-body text-fg-muted">
            {candidates.length === 0
              ? "No workflows yet."
              : "Nothing matches that filter."}
          </p>
        </div>
      ) : (
        <div className="thin-scroll overflow-x-auto">
        <table className="w-full min-w-[520px] border-collapse text-left">
          <caption className="sr-only">Candidate workflows</caption>
          <thead>
            <tr className="border-b border-line-soft">
              {["Candidate", "Role", "Stage", "Joining"].map((h, i) => (
                <th
                  key={h}
                  scope="col"
                  className={`px-3 py-2 text-micro font-medium text-fg-faint ${
                    i > 1 ? "hidden sm:table-cell" : ""
                  }`}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => {
              const stage = stageLabel(c);
              const failed = hasFailedDispatch(c);
              return (
                <tr
                  key={c.thread_id}
                  className="border-b border-line-soft last:border-0 transition-colors duration-[--t-hover] hover:bg-surface-raised"
                >
                  <td className="px-3 py-0">
                    {/* The link fills the cell so the whole row is the target,
                        while staying a real anchor for keyboard and middle-click. */}
                    <Link
                      href={`/thread/${encodeURIComponent(c.thread_id)}`}
                      className="flex min-h-[48px] flex-col justify-center"
                    >
                      <span className="flex items-center gap-1.5 text-base font-medium text-fg">
                        {failed && (
                          <IconAlert className="h-3.5 w-3.5 shrink-0 text-alarm" />
                        )}
                        <span className="truncate">{c.candidate_name || "—"}</span>
                      </span>
                      <span className="truncate text-micro text-fg-faint">
                        {c.candidate_email}
                      </span>
                    </Link>
                  </td>
                  <td className="px-3 py-2 text-body text-fg-muted">
                    <span className="block truncate">{c.role_title}</span>
                    <span className="block truncate text-micro text-fg-faint">
                      {c.department}
                    </span>
                  </td>
                  <td className="hidden px-3 py-2 sm:table-cell">
                    <span className={`text-body ${STAGE_TONE[stage] ?? "text-fg-muted"}`}>
                      {stage}
                    </span>
                  </td>
                  <td className="hidden whitespace-nowrap px-3 py-2 font-mono text-micro tabular-nums text-fg-faint sm:table-cell">
                    {c.start_date
                      ? new Date(c.start_date).toLocaleDateString(undefined, {
                          day: "numeric", month: "short", year: "numeric" })
                      : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        </div>
      )}
    </section>
  );
}
