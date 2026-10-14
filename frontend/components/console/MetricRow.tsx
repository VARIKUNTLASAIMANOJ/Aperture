"use client";

import Link from "next/link";

import { IconArrowRight } from "@/components/ui/Icons";

/**
 * The headline numbers, as separate cards rather than one bordered strip.
 *
 * Four equal cells divided by hairlines read as a table of numbers; four
 * cards with their own elevation read as the summary of a system. The figure
 * that needs action still carries the only colour — if all four were tinted,
 * none of them would mean anything.
 */

export interface Metric {
  label: string;
  value: number | string;
  hint?: string;
  tone?: "neutral" | "alarm" | "hold" | "settled";
  href?: string;
  icon?: React.ReactNode;
}

const TONE: Record<NonNullable<Metric["tone"]>, { value: string; chip: string }> = {
  neutral: { value: "text-fg", chip: "bg-fill text-fg-muted" },
  alarm:   { value: "text-alarm", chip: "bg-alarm/10 text-alarm" },
  hold:    { value: "text-hold", chip: "bg-hold/10 text-hold" },
  settled: { value: "text-settled", chip: "bg-settled/10 text-settled" },
};

export function MetricRow({ metrics, loading }: { metrics: Metric[]; loading?: boolean }) {
  if (loading) {
    return (
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="surface min-h-[104px] animate-pulse rounded-card" />
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {metrics.map((m) => {
        const tone = TONE[m.tone ?? "neutral"];
        const body = (
          <>
            <div className="flex items-start justify-between gap-2">
              <p className="text-micro text-fg-muted">{m.label}</p>
              {m.icon && (
                <span
                  aria-hidden="true"
                  className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${tone.chip}`}
                >
                  {m.icon}
                </span>
              )}
            </div>
            <p className={`mt-2 font-mono text-display tabular-nums ${tone.value}`}>
              {m.value}
            </p>
            {m.hint && (
              <p className="mt-1 flex items-center gap-1 truncate text-micro text-fg-faint">
                {m.hint}
                {m.href && (
                  <IconArrowRight
                    aria-hidden="true"
                    className="h-3 w-3 shrink-0 opacity-0 transition-opacity duration-[--t-hover] group-hover:opacity-100"
                  />
                )}
              </p>
            )}
          </>
        );

        const shared = "surface group block min-h-[104px] rounded-card p-4";

        return m.href ? (
          <Link
            key={m.label}
            href={m.href}
            className={`${shared} transition-shadow duration-[--t-hover] hover:shadow-lift`}
          >
            {body}
          </Link>
        ) : (
          <div key={m.label} className={shared}>{body}</div>
        );
      })}
    </div>
  );
}
