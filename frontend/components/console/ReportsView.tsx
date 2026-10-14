"use client";

import { useCallback, useEffect, useState } from "react";

import { AppShell } from "@/components/shell/AppShell";
import { Button } from "@/components/ui/Button";
import { IconAlert, IconSpinner } from "@/components/ui/Icons";
import { NetworkError, api } from "@/lib/api";
import { inr, lpa } from "@/lib/form";
import { saveBlob } from "@/lib/download";
import type { ReportMetrics } from "@/lib/types";

/**
 * The questions a head of HR actually asks.
 *
 * Everything is derived server-side from the audit trail at request time, so
 * there is no second set of counters to drift from what happened.
 */

/** A rate of null means "no sample", which is not the same as 0%. */
function pct(v: number | null): string {
  return v === null ? "—" : `${Math.round(v * 100)}%`;
}

function hours(v: number | null): string {
  if (v === null) return "—";
  if (v < 1) return `${Math.round(v * 60)} min`;
  if (v < 48) return `${v} h`;
  return `${(v / 24).toFixed(1)} days`;
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="min-w-0 border-line-soft p-4 [&:not(:last-child)]:border-r">
      <p className="text-micro text-fg-muted">{label}</p>
      <p className="mt-1 font-mono text-display tabular-nums text-fg">{value}</p>
      {hint && <p className="mt-0.5 truncate text-micro text-fg-faint">{hint}</p>}
    </div>
  );
}

function Bars({ title, data }: { title: string; data: Record<string, number> }) {
  const entries = Object.entries(data).slice(0, 8);
  const max = Math.max(1, ...entries.map(([, n]) => n));
  return (
    <section className="surface rounded-card p-4">
      <h2 className="text-lead font-semibold text-fg">{title}</h2>
      {entries.length === 0 ? (
        <p className="mt-2 text-body text-fg-muted">Nothing to show yet.</p>
      ) : (
        <ul className="mt-3 space-y-2">
          {entries.map(([label, n]) => (
            <li key={label} className="flex items-center gap-3">
              <span className="w-[108px] shrink-0 truncate text-body text-fg-muted">
                {label}
              </span>
              <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-fill-strong">
                <span
                  className="block h-full rounded-full bg-signal/70"
                  style={{ width: `${(n / max) * 100}%` }}
                />
              </span>
              <span className="w-8 shrink-0 text-right font-mono text-micro tabular-nums text-fg">
                {n}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function ReportsView() {
  const [m, setM] = useState<ReportMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  const load = useCallback(async () => {
    try {
      setM(await api.metrics());
      setError(null);
    } catch (e) {
      setError(e instanceof NetworkError || e instanceof Error
        ? e.message : "Could not load the report.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const exportCsv = async () => {
    setExporting(true);
    try {
      const { blob, filename } = await api.candidatesCsv();
      saveBlob(blob, filename);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not export.");
    } finally {
      setExporting(false);
    }
  };

  return (
    <AppShell
      title="Reports"
      actions={
        <Button
          variant="ghost"
          className="!min-h-[36px]"
          loading={exporting}
          disabled={exporting}
          onClick={exportCsv}
        >
          Export CSV
        </Button>
      }
    >
      {loading ? (
        <div className="surface flex items-center justify-center gap-2 rounded-card py-16 text-fg-muted">
          <IconSpinner className="h-4 w-4 animate-spin" />
          <span className="text-body">Computing…</span>
        </div>
      ) : error ? (
        <div role="alert" className="flex items-start gap-2.5 rounded-xl border border-alarm/35 bg-alarm/[0.07] p-4">
          <IconAlert className="mt-0.5 h-4 w-4 shrink-0 text-alarm" />
          <p className="text-body text-fg-muted">{error}</p>
        </div>
      ) : m && (
        <div className="space-y-4">
          <section className="surface grid grid-cols-2 overflow-hidden rounded-card sm:grid-cols-4">
            <Stat label="Offers extended" value={String(m.funnel.offers_extended)}
                  hint={`of ${m.funnel.workflows} workflows`} />
            <Stat label="Acceptance rate" value={pct(m.rates.acceptance_rate)}
                  hint={`${m.funnel.accepted} accepted · ${m.funnel.declined} declined`} />
            <Stat label="Median decision" value={hours(m.time_to_decision_hours.median)}
                  hint={`${m.time_to_decision_hours.sample} responses`} />
            {/* LPA, not the rupee figure: ₹24,00,000 overflows a quarter-width
                tile and was clipped mid-number, which reads worse than
                rounding. LPA is the unit Indian HR quotes anyway; the exact
                figure moves to the hint, where there is room for it. */}
            <Stat label="Median CTC"
                  value={m.compensation.median_ctc ? lpa(m.compensation.median_ctc) : "—"}
                  hint={m.compensation.median_ctc
                    ? `${inr(m.compensation.median_ctc)} · ${m.compensation.sample} offers`
                    : "no offers yet"} />
          </section>

          <section className="surface rounded-card p-4">
            <h2 className="text-lead font-semibold text-fg">Funnel</h2>
            <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
              {[
                ["Offers extended", m.funnel.offers_extended],
                ["Awaiting a reply", m.funnel.awaiting_response],
                ["Accepted", m.funnel.accepted],
                ["Declined", m.funnel.declined],
                ["Expired", m.funnel.expired],
                ["Appointments released", m.funnel.appointments_released],
                ["Onboarding in progress", m.funnel.onboarding_in_progress],
                ["Onboarding complete", m.funnel.onboarding_completed],
              ].map(([label, n]) => (
                <div key={label as string}>
                  <dt className="text-micro text-fg-faint">{label}</dt>
                  <dd className="mt-0.5 font-mono text-title tabular-nums text-fg">{n}</dd>
                </div>
              ))}
            </dl>
            <p className="mt-3 text-body leading-relaxed text-fg-muted">
              Response rate {pct(m.rates.response_rate)} · email delivery{" "}
              {pct(m.rates.email_success_rate)}. Decisions land between{" "}
              {hours(m.time_to_decision_hours.fastest)} and{" "}
              {hours(m.time_to_decision_hours.slowest)}.
            </p>
          </section>

          <div className="grid gap-4 lg:grid-cols-2">
            <Bars title="By department" data={m.by_department} />
            <Bars title="By location" data={m.by_city} />
          </div>

          {m.decline_reasons.length > 0 && (
            <section className="surface rounded-card p-4">
              <h2 className="text-lead font-semibold text-fg">Why candidates declined</h2>
              <ul className="mt-2 space-y-2">
                {m.decline_reasons.map((d, i) => (
                  <li key={i} className="text-body text-fg-muted">
                    <span className="font-medium text-fg">{d.candidate}</span> — {d.reason}
                  </li>
                ))}
              </ul>
            </section>
          )}

          <p className="text-micro text-fg-muted">
            Computed from the audit trail at {new Date(m.generated_at).toLocaleString()}.
          </p>
        </div>
      )}
    </AppShell>
  );
}
