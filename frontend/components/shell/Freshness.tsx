"use client";

import { IconRefresh, IconSpinner } from "@/components/ui/Icons";
import { relativeTime } from "@/lib/dashboardData";
import { useReducedMotion } from "@/lib/useReducedMotion";

/**
 * The "is this data current" readout, for the header bar.
 *
 * Says "live" only while the last fetch succeeded AND is recent; otherwise it
 * shows the age and calls itself stale. A dashboard that looks live while
 * silently serving a forty-minute-old snapshot is worse than one that admits
 * it is offline.
 */
export function Freshness({
  loadedAt, now, stale, error, refreshing, onRefresh,
}: {
  loadedAt: number | null;
  now: number;
  stale: boolean;
  error: string | null;
  refreshing: boolean;
  onRefresh: () => void;
}) {
  const reduced = useReducedMotion();
  const live = loadedAt !== null && !stale && !error;

  return (
    <div className="flex items-center gap-1.5">
      <span
        className="hidden items-center gap-1.5 rounded-lg border border-line-soft px-2 py-1 sm:flex"
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
          className={`text-micro ${
            error ? "text-alarm" : stale ? "text-hold" : "text-fg-muted"
          }`}
        >
          {error
            ? "Offline"
            : loadedAt === null
              ? "Connecting"
              : `${stale ? "Stale" : "Live"} · ${relativeTime(new Date(loadedAt).toISOString(), now)}`}
        </span>
      </span>

      <button
        type="button"
        onClick={onRefresh}
        disabled={refreshing}
        aria-label="Refresh"
        className="flex h-9 w-9 cursor-pointer items-center justify-center rounded-lg border border-line-soft text-fg-muted transition-colors duration-[--t-hover] hover:border-line hover:text-fg disabled:cursor-not-allowed disabled:opacity-45"
      >
        {refreshing
          ? <IconSpinner className="h-3.5 w-3.5 animate-spin" />
          : <IconRefresh className="h-3.5 w-3.5" />}
      </button>
    </div>
  );
}
