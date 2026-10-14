"use client";

import { IconAlert } from "@/components/ui/Icons";
import { EMPLOYMENT_TYPES, inr, lpa, type Draft } from "@/lib/form";

interface Props {
  draft: Draft;
  submitError: string | null;
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-6 border-b border-line-soft py-2.5 last:border-0">
      <dt className="shrink-0 text-[13px] text-fg-muted">{label}</dt>
      <dd className="min-w-0 truncate text-right text-[13px] font-medium text-fg">
        {value || "—"}
      </dd>
    </div>
  );
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-1">
      <h3 className="text-base font-semibold text-signal">
        {title}
      </h3>
      <dl>{children}</dl>
    </section>
  );
}

export function ReviewStep({ draft, submitError }: Props) {
  const rejected = draft.selection_status === "REJECTED";
  const empLabel =
    EMPLOYMENT_TYPES.find((e) => e.value === draft.employment_type)?.label ?? "";
  const ctc = Number(draft.total_ctc);

  return (
    <div className="space-y-6">
      <div
        className={`flex gap-3 rounded-xl border p-4 ${
          rejected
            ? "border-line bg-fill"
            : "border-settled/25 bg-settled/[0.06]"
        }`}
      >
        <span
          className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${
            rejected ? "bg-fg-muted" : "bg-settled"
          }`}
          aria-hidden="true"
        />
        <p className="text-[13px] leading-relaxed text-fg-muted">
          {rejected ? (
            <>
              <span className="font-medium text-fg">Rejection path.</span> The
              agent drafts a notice and stops at the approval gate. Nothing
              reaches {draft.candidate_name || "the candidate"} until you
              approve it.
            </>
          ) : (
            <>
              <span className="font-medium text-fg">Offer path.</span> Payroll
              is computed deterministically, the agreement is drafted, then the
              run pauses at the approval gate. No email is sent without your
              sign-off.
            </>
          )}
        </p>
      </div>

      <div className="grid gap-x-10 gap-y-6 sm:grid-cols-2">
        <Group title="Candidate">
          <Row label="Name" value={draft.candidate_name} />
          <Row label="Email" value={draft.candidate_email} />
          <Row label="Reference" value={draft.candidate_id} />
        </Group>

        <Group title="Position">
          <Row label="Role" value={draft.role_title} />
          <Row label="Department" value={draft.department} />
          <Row label="Hiring manager" value={draft.hiring_manager_email} />
        </Group>

        {!rejected && (
          <>
            <Group title="Engagement">
              <Row label="Type" value={empLabel} />
              <Row label="Start date" value={draft.start_date} />
              <Row label="End date" value={draft.end_date || "Open-ended"} />
            </Group>

            <Group title="Compensation">
              <Row label="Annual CTC" value={ctc > 0 ? `${inr(ctc)} · ${lpa(ctc)}` : ""} />
              <Row label="Tax regime" value={draft.tax_regime === "NEW" ? "New Tax Regime" : "Old Tax Regime"} />
              <Row label="Work location" value={draft.work_city ? `${draft.work_city}, ${draft.work_state}` : ""} />
              <Row label="Reporting manager" value={draft.reporting_manager} />
            </Group>

            <Group title="Terms">
              <Row label="Designation" value={draft.designation || draft.role_title} />
              <Row label="Probation" value={`${draft.probation_period_months || 6} months`} />
              <Row label="Notice period" value={`${draft.notice_period_days || 60} days`} />
              <Row label="Conditions" value={draft.offer_conditions || "None"} />
            </Group>
          </>
        )}
      </div>

      {/* ux-guidelines "Submit Feedback": a failed submit must say so, near
          the action, not vanish silently. */}
      {submitError && (
        <div
          role="alert"
          className="flex items-start gap-2.5 rounded-xl border border-alarm/35 bg-alarm/[0.08] p-4"
        >
          <IconAlert className="mt-0.5 h-4 w-4 shrink-0 text-alarm" />
          <div className="min-w-0 space-y-1">
            <p className="text-[13px] font-medium text-fg">
              Could not start the workflow
            </p>
            <p className="break-words text-[13px] leading-relaxed text-fg-muted">
              {submitError}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
