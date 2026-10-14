import type { EmploymentType, SelectionStatus, TriggerRequest } from "./types";

export interface Draft {
  candidate_id: string;
  candidate_name: string;
  candidate_email: string;
  candidate_phone: string;
  role_title: string;
  department: string;
  hiring_manager_email: string;
  selection_status: SelectionStatus;
  employment_type: EmploymentType;
  start_date: string;
  end_date: string;

  // ── Posting details, carried onto both letters ──────────────────────────
  designation: string;
  work_state: string;      // 2-letter Indian state/UT code
  work_city: string;
  reporting_manager: string;
  probation_period_months: string;
  notice_period_days: string;
  offer_conditions: string;

  // ── Indian compensation: one CTC figure, engine derives the breakup ─────
  total_ctc: string;
  tax_regime: "NEW" | "OLD";
}

export const emptyDraft = (): Draft => ({
  candidate_id: "",
  candidate_name: "",
  candidate_email: "",
  candidate_phone: "",
  role_title: "",
  department: "",
  hiring_manager_email: "",
  selection_status: "PENDING",
  employment_type: "FULL_TIME",
  start_date: "",
  end_date: "",
  designation: "",
  work_state: "TS",
  work_city: "Hyderabad",
  reporting_manager: "",
  probation_period_months: "6",
  notice_period_days: "60",
  offer_conditions: "",
  total_ctc: "",
  tax_regime: "NEW",
});

/**
 * States and cities are NOT hard-coded here. They are fetched from
 * GET /meta/locations so the dropdowns can never drift from the masters the
 * backend validates against — an invalid pairing would be rejected at the
 * edge anyway, but the user should never be offered one.
 */
export interface StateOption {
  code: string;
  name: string;
  kind: "STATE" | "UT";
  levies_professional_tax: boolean;
  cities: string[];
}

export const TAX_REGIMES = [
  { value: "NEW", label: "New Tax Regime (default)" },
  { value: "OLD", label: "Old Tax Regime" },
];

export const EMPLOYMENT_TYPES = [
  { value: "FULL_TIME", label: "Full-Time (Permanent)" },
  { value: "PROBATIONARY", label: "Full-Time (On Probation)" },
  { value: "CONTRACT", label: "Fixed-Term Contract" },
  { value: "INTERN", label: "Internship" },
  { value: "CONSULTANT", label: "Consultant (Professional Services)" },
];

export type Errors = Partial<Record<keyof Draft, string>>;

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/**
 * Mirrors core.voice_state.normalize_phone. The server normalises and is
 * authoritative; this only spares HR a round-trip on an obvious typo, so it is
 * deliberately permissive about spacing and separators.
 */
export function isValidPhone(raw: string): boolean {
  const s = raw.replace(/[\s\-().\/]/g, "").replace(/^00/, "+");
  if (/^\+91[6-9]\d{9}$/.test(s)) return true;
  if (/^[6-9]\d{9}$/.test(s)) return true;
  if (/^0[6-9]\d{9}$/.test(s)) return true;
  if (/^91[6-9]\d{9}$/.test(s)) return true;
  return /^\+[1-9]\d{7,14}$/.test(s);
}
const ISO_DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Client-side mirror of the Pydantic constraints in api/main.py. The backend
 * re-validates everything — this exists so the user sees the problem beside
 * the field instead of as a 422 after submitting.
 */
export function validateStep(step: string, d: Draft): Errors {
  const e: Errors = {};

  if (step === "identity") {
    if (!d.candidate_id.trim()) e.candidate_id = "Required.";
    if (!d.candidate_name.trim()) e.candidate_name = "Required.";
    if (!d.candidate_email.trim()) e.candidate_email = "Required.";
    else if (!EMAIL_RE.test(d.candidate_email))
      e.candidate_email = "Must be a valid email address.";
    if (d.candidate_phone.trim() && !isValidPhone(d.candidate_phone))
      e.candidate_phone =
        "Use an Indian mobile (10 digits starting 6-9) or full +country format.";
    if (!d.role_title.trim()) e.role_title = "Required.";
    if (!d.department.trim()) e.department = "Required.";
    if (!d.hiring_manager_email.trim()) e.hiring_manager_email = "Required.";
    else if (!EMAIL_RE.test(d.hiring_manager_email))
      e.hiring_manager_email = "Must be a valid email address.";
  }

  if (step === "decision") {
    if (d.selection_status === "PENDING")
      e.selection_status = "Choose an outcome to continue.";
  }

  if (step === "engagement") {
    if (!d.start_date) e.start_date = "Required — drives leave proration.";
    else if (!ISO_DATE_RE.test(d.start_date))
      e.start_date = "Use YYYY-MM-DD.";
    if (d.end_date) {
      if (!ISO_DATE_RE.test(d.end_date)) e.end_date = "Use YYYY-MM-DD.";
      else if (d.start_date && d.end_date <= d.start_date)
        e.end_date = "End date must fall after the start date.";
    }
    if (d.employment_type === "FULL_TIME" && d.end_date)
      e.end_date = "Full-time employees have no end date.";
  }

  if (step === "compensation") {
    const ctc = Number(d.total_ctc);
    if (!d.total_ctc.trim()) e.total_ctc = "Annual CTC is required.";
    else if (!Number.isFinite(ctc) || ctc <= 0)
      e.total_ctc = "Must be a positive amount in rupees.";
    else if (ctc < 100000)
      e.total_ctc = "CTC looks too low — enter the annual figure, not monthly.";

    if (!d.work_state) e.work_state = "Select a state or union territory.";
    if (!d.work_city) e.work_city = "Select a work location.";
  }

  return e;
}

/** Serialises the draft into the exact TriggerRequest shape the API expects. */
export function toTriggerRequest(d: Draft): TriggerRequest {
  const rejected = d.selection_status === "REJECTED";

  return {
    candidate_id: d.candidate_id.trim(),
    candidate_name: d.candidate_name.trim(),
    candidate_email: d.candidate_email.trim(),
    candidate_phone: d.candidate_phone.trim() || null,
    role_title: d.role_title.trim(),
    department: d.department.trim(),
    hiring_manager_email: d.hiring_manager_email.trim(),
    selection_status: d.selection_status,
    // A rejected candidate never reaches the salary or offer nodes, so
    // sending compensation or posting details would be dead payload.
    employment_type: rejected ? null : d.employment_type,
    start_date: rejected ? null : d.start_date || null,
    end_date: rejected || !d.end_date ? null : d.end_date,

    designation: rejected ? null : (d.designation.trim() || d.role_title.trim()),
    work_location_city: rejected ? null : d.work_city,
    work_location_state: rejected ? null : d.work_state,
    reporting_manager: rejected ? null : (d.reporting_manager.trim() || null),
    probation_period_months: rejected ? null : Number(d.probation_period_months || 6),
    notice_period_days: rejected ? null : Number(d.notice_period_days || 60),
    offer_conditions: rejected ? null : (d.offer_conditions.trim() || null),

    compensation: rejected
      ? null
      : {
          total_ctc: Number(d.total_ctc),
          currency: "INR",
          tax_regime: d.tax_regime,
          work_state: d.work_state,
          work_city: d.work_city,
        },
  };
}

/** Indian digit grouping — ₹6,00,000, not the Western ₹600,000. */
export const inr = (n: number | undefined | null) =>
  n == null
    ? "—"
    : new Intl.NumberFormat("en-IN", {
        style: "currency",
        currency: "INR",
        maximumFractionDigits: 0,
      }).format(n);

/** 850000 → "8.5 LPA" */
export const lpa = (n: number | undefined | null) => {
  if (n == null) return "—";
  const l = n / 100000;
  return `${(+l.toFixed(2)).toString()} LPA`;
};

/** @deprecated Use `inr`. Retained so existing imports keep compiling. */
export const money = inr;

export const pct = (n: number | undefined | null) =>
  n == null ? "—" : `${(n * 100).toFixed(1)}%`;
