"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { SelectField, TextField } from "@/components/ui/Field";
import { ApiError, api } from "@/lib/api";
import {
  TAX_REGIMES, inr, lpa, type Draft, type Errors,
} from "@/lib/form";
import type { SalaryBreakup, StateOptionApi } from "@/lib/types";

interface Props {
  draft: Draft;
  errors: Errors;
  set: <K extends keyof Draft>(k: K, v: Draft[K]) => void;
}

/**
 * Indian compensation. HR quotes ONE annual CTC figure; the backend derives
 * Basic / HRA / PF / gratuity and the statutory deductions.
 *
 * The breakup shown here is fetched from POST /meta/ctc-preview rather than
 * recomputed in the browser: a second implementation of Indian payroll would
 * inevitably disagree with the one that actually writes the offer letter.
 */
export function CompensationStep({ draft, errors, set }: Props) {
  const [states, setStates] = useState<StateOptionApi[]>([]);
  const [preview, setPreview] = useState<SalaryBreakup | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Locations come from the backend masters, so the dropdowns can never offer
  // a pairing the API would reject.
  useEffect(() => {
    let alive = true;
    api.metaLocations()
      .then((d) => alive && setStates(d.states ?? []))
      .catch(() => alive && setStates([]));
    return () => { alive = false; };
  }, []);

  const cities = useMemo(
    () => states.find((s) => s.code === draft.work_state)?.cities ?? [],
    [states, draft.work_state],
  );

  const ctc = Number(draft.total_ctc);
  const canPreview = Number.isFinite(ctc) && ctc > 0 && !!draft.work_state && !!draft.work_city;

  useEffect(() => {
    if (!canPreview) { setPreview(null); setPreviewError(null); return; }
    if (debounce.current) clearTimeout(debounce.current);
    debounce.current = setTimeout(async () => {
      setLoading(true);
      try {
        setPreview(await api.ctcPreview({
          total_ctc: ctc,
          state_code: draft.work_state,
          city: draft.work_city,
          tax_regime: draft.tax_regime,
          employment_type: draft.employment_type,
        }));
        setPreviewError(null);
      } catch (e) {
        setPreview(null);
        setPreviewError(
          e instanceof ApiError ? e.message : "Could not reach the salary engine.",
        );
      } finally {
        setLoading(false);
      }
    }, 350);
    return () => { if (debounce.current) clearTimeout(debounce.current); };
  }, [ctc, draft.work_state, draft.work_city, draft.tax_regime, draft.employment_type, canPreview]);

  const stateOptions = useMemo(() => {
    const st = states.filter((s) => s.kind === "STATE").map((s) => ({ value: s.code, label: s.name }));
    const ut = states.filter((s) => s.kind === "UT").map((s) => ({ value: s.code, label: `${s.name} (UT)` }));
    return [...st, ...ut];
  }, [states]);

  const selectedState = states.find((s) => s.code === draft.work_state);

  const Row = ({ label, value, strong = false, muted = false }: {
    label: string; value: string; strong?: boolean; muted?: boolean;
  }) => (
    <div className={`flex items-baseline justify-between gap-4 py-1.5 ${strong ? "border-t border-line-strong pt-2 mt-1" : ""}`}>
      <span className={`text-[12px] ${muted ? "text-fg-faint" : "text-fg-muted"}`}>{label}</span>
      <span className={`font-mono tabular-nums ${strong ? "text-[14px] font-semibold text-fg" : "text-[12px] text-fg"}`}>
        {value}
      </span>
    </div>
  );

  return (
    <div className="space-y-5">
      <div className="grid gap-5 sm:grid-cols-2">
        <TextField
          label="Annual CTC (₹)" required
          type="number" inputMode="numeric" min={0} step="10000"
          value={draft.total_ctc}
          onChange={(v) => set("total_ctc", v)}
          error={errors.total_ctc}
          placeholder="1800000"
          hint={ctc > 0 ? `${inr(ctc)} · ${lpa(ctc)}` : "Total Cost to Company, per annum."}
        />
        <SelectField
          label="Tax regime" required
          value={draft.tax_regime}
          onChange={(v) => set("tax_regime", v as Draft["tax_regime"])}
          options={TAX_REGIMES}
          hint="Determines the TDS slabs applied to this offer."
        />
      </div>

      <div className="grid gap-5 sm:grid-cols-2">
        <SelectField
          label="Work state / UT" required
          value={draft.work_state}
          onChange={(v) => {
            set("work_state", v);
            // Clear the city: it belongs to the previous state and would be
            // an invalid pairing the API rejects.
            const next = states.find((s) => s.code === v)?.cities ?? [];
            set("work_city", next[0] ?? "");
          }}
          options={stateOptions.length ? stateOptions : [{ value: draft.work_state, label: "Loading…" }]}
          error={errors.work_state}
          hint={selectedState
            ? selectedState.levies_professional_tax
              ? "Professional Tax applies in this state."
              : "This state does not levy Professional Tax."
            : undefined}
        />
        <SelectField
          label="Work location" required
          value={draft.work_city}
          onChange={(v) => set("work_city", v)}
          options={cities.length
            ? cities.map((c) => ({ value: c, label: c }))
            : [{ value: "", label: "Select a state first" }]}
          error={errors.work_city}
          hint="Metro cities attract 50% HRA; others 40%."
        />
      </div>

      {/* ── Live breakup, computed by the same engine that writes the letter ── */}
      <div className="rounded-xl border border-line bg-fill px-4 py-3">
        <div className="flex items-baseline justify-between">
          <p className="text-base font-medium text-fg">
            Salary breakup
          </p>
          {preview && (
            <span className="font-mono text-[11px] text-fg-faint">
              {preview.financial_year} · {preview.tax_regime} regime
            </span>
          )}
        </div>

        {previewError ? (
          <p role="alert" className="mt-2 text-[13px] text-alarm">{previewError}</p>
        ) : !preview ? (
          <p className="mt-2 text-[13px] text-fg-faint">
            {loading ? "Computing…" : "Enter a CTC and work location to see the breakup."}
          </p>
        ) : (
          <div aria-live="polite" className="mt-2">
            <Row label="Basic Salary" value={inr(preview.basic)} />
            <Row label="House Rent Allowance (HRA)" value={inr(preview.hra)} />
            {preview.conveyance > 0 && <Row label="Conveyance Allowance" value={inr(preview.conveyance)} />}
            {preview.medical > 0 && <Row label="Medical Allowance" value={inr(preview.medical)} />}
            <Row label="Special Allowance" value={inr(preview.special_allowance)} />
            <Row label="Gross Salary" value={inr(preview.gross_salary)} strong />

            <Row label="Employer PF" value={inr(preview.employer_pf)} muted />
            {preview.employer_esi > 0 && <Row label="Employer ESI" value={inr(preview.employer_esi)} muted />}
            <Row label="Gratuity accrual" value={inr(preview.gratuity_accrual)} muted />
            <Row label="Total CTC" value={inr(preview.total_ctc)} strong />

            <div className="mt-3 rounded-lg bg-fill px-3 py-2">
              <Row label="Employee PF" value={`− ${inr(preview.employee_pf)}`} muted />
              {preview.employee_esi > 0 && <Row label="Employee ESI" value={`− ${inr(preview.employee_esi)}`} muted />}
              {preview.professional_tax > 0 && (
                <Row label="Professional Tax" value={`− ${inr(preview.professional_tax)}`} muted />
              )}
              <Row label={`Income Tax (TDS)`} value={`− ${inr(preview.income_tax_tds)}`} muted />
              <Row label="Net take-home (per month)" value={inr(preview.monthly_net)} strong />
            </div>

            <p className="mt-2 text-[11px] leading-snug text-fg-faint">
              CTC is not take-home. {preview.esi_applicable ? "ESI applies at this salary. " : ""}
              Effective tax rate {(preview.effective_tax_rate * 100).toFixed(1)}%.
            </p>

            {preview.warnings?.map((w, i) => (
              <p key={i} className="mt-1.5 text-[11px] leading-snug text-hold">{w}</p>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
