"use client";

import { SelectField, TextField } from "@/components/ui/Field";
import { EMPLOYMENT_TYPES, type Draft, type Errors } from "@/lib/form";

interface Props {
  draft: Draft;
  errors: Errors;
  set: <K extends keyof Draft>(k: K, v: Draft[K]) => void;
}

export function EngagementStep({ draft, errors, set }: Props) {
  const isContractor = draft.employment_type !== "FULL_TIME";

  return (
    <div className="space-y-5">
      <SelectField
        label="Employment type" required
        value={draft.employment_type}
        onChange={(v) => {
          set("employment_type", v as Draft["employment_type"]);
          // Full-time has no end date; clear any stale value so the payload
          // never carries a contradiction into the graph.
          if (v === "FULL_TIME") set("end_date", "");
        }}
        options={EMPLOYMENT_TYPES}
        hint={
          isContractor
            ? "Consultants and interns accrue no earned leave or statutory benefits."
            : "Full-time accrues 18 days earned leave, 8 casual and 12 sick, prorated from the date of joining."
        }
      />

      <div className="grid gap-5 sm:grid-cols-2">
        <TextField
          label="Start date" required type="date"
          value={draft.start_date}
          onChange={(v) => set("start_date", v)}
          error={errors.start_date}
          hint="Leave is prorated across the remaining calendar year."
        />

        {/* Progressive disclosure — the end-date field only exists for the
            employment types that can actually have one. */}
        {isContractor && (
          <TextField
            label="Contract end date" type="date"
            value={draft.end_date}
            onChange={(v) => set("end_date", v)}
            error={errors.end_date}
            hint="Schedules expiry alerts at T-30, T-15 and T-7."
          />
        )}
      </div>

      {/* Posting details — these appear verbatim on both letters, so they are
          collected here rather than invented at document-generation time. */}
      <div className="grid gap-5 sm:grid-cols-2">
        <TextField
          label="Designation"
          value={draft.designation}
          onChange={(v) => set("designation", v)}
          placeholder="Senior Software Engineer"
          hint="Shown on the Offer and Appointment Letters. Defaults to the role title."
        />
        <TextField
          label="Reporting manager"
          value={draft.reporting_manager}
          onChange={(v) => set("reporting_manager", v)}
          placeholder="Ananya Sharma"
        />
      </div>

      <div className="grid gap-5 sm:grid-cols-2">
        <TextField
          label="Probation period (months)"
          type="number" inputMode="numeric" min={0} step="1"
          value={draft.probation_period_months}
          onChange={(v) => set("probation_period_months", v)}
        />
        <TextField
          label="Notice period (days)"
          type="number" inputMode="numeric" min={0} step="15"
          value={draft.notice_period_days}
          onChange={(v) => set("notice_period_days", v)}
        />
      </div>

      <TextField
        label="Offer conditions"
        value={draft.offer_conditions}
        onChange={(v) => set("offer_conditions", v)}
        placeholder="Subject to background verification and relieving letter."
        hint="Appears in the Conditions section of the Offer Letter."
      />

      {draft.employment_type === "CONSULTANT" && (
        <div className="flex gap-3 rounded-xl border border-hold/25 bg-hold/[0.06] p-4">
          <span className="mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full bg-hold" aria-hidden="true" />
          <p className="text-[13px] leading-relaxed text-fg-muted">
            <span className="font-medium text-fg">Consultant engagement.</span>{" "}
            No EPF, ESI or gratuity is computed, and payments are subject to
            TDS under Section 194J rather than salary TDS under Section 192.
          </p>
        </div>
      )}
    </div>
  );
}
