/**
 * Mirrors the FastAPI/Pydantic contract in api/main.py and core/state.py.
 * Keep field names byte-identical to the backend — they are sent raw.
 */

export type SelectionStatus = "PENDING" | "SELECTED" | "REJECTED";
export type EmploymentType =
  | "FULL_TIME" | "PROBATIONARY" | "CONTRACT" | "INTERN" | "CONSULTANT"
  // legacy values retained so pre-existing threads still deserialise
  | "CONTRACTOR_W2" | "CONTRACTOR_1099";
export type ApprovalStatus = "NEEDS_APPROVAL" | "APPROVED" | "REJECTED";
export type NodeStatus =
  | "IDLE"
  | "RUNNING"
  | "COMPLETE"
  | "WAITING_HITL"
  | "ERROR";
export type KanbanColumn =
  | "PENDING"
  | "IN_PROGRESS"
  | "AWAITING_APPROVAL"
  | "COMPLETED";
export type PayFrequency = "hourly" | "monthly" | "annual";

/** Matches CompensationInputSchema (India). */
export interface CompensationInput {
  total_ctc: number;          // annual CTC in INR
  currency?: string;          // "INR"
  tax_regime?: "NEW" | "OLD";
  financial_year?: string | null;
  work_state: string;         // 2-letter Indian state/UT code
  work_city: string;
  basic_pct?: number | null;
  performance_bonus?: number;
  pf_on_actual_basic?: boolean;
}

/** Matches OnboardingTriggerRequest. */
export interface TriggerRequest {
  candidate_id: string;
  candidate_name: string;
  candidate_email: string;
  /** E.164, normalised server-side. Null means this candidate is never called. */
  candidate_phone?: string | null;
  role_title: string;
  department: string;
  hiring_manager_email: string;
  selection_status: SelectionStatus;
  employment_type?: EmploymentType | null;
  start_date?: string | null;
  end_date?: string | null;
  compensation?: CompensationInput | null;

  // Posting details carried onto both letters
  designation?: string | null;
  work_location_city?: string | null;
  work_location_state?: string | null;
  reporting_manager?: string | null;
  working_hours?: string | null;
  probation_period_months?: number | null;
  notice_period_days?: number | null;
  offer_conditions?: string | null;
}

export interface TriggerResponse {
  thread_id: string;
  candidate_id: string;
  status: string;
  message: string;
}

export interface CalculatedFinancials {
  annual_gross?: number;
  monthly_gross?: number;
  federal_tax_annual?: number;
  state_tax_annual?: number;
  health_deduction_annual?: number;
  retirement_401k_annual?: number;
  total_deductions_annual?: number;
  annual_net?: number;
  monthly_net?: number;
  employer_fica_annual?: number;
  effective_tax_rate?: number;
}

export interface LeaveAllocations {
  pto_days?: number;
  sick_days?: number;
  parental_leave_days?: number;
  prorated?: boolean;
  proration_factor?: number;
}

export interface EmailQueueSummary {
  template: string | null;
  recipient: string | null;
  /** PENDING | SCHEDULED | SENT | FAILED | CANCELLED */
  status: string | null;
  message_id: string | null;
  /** Set while status is SCHEDULED — when the auto-send should fire. */
  scheduled_for?: string | null;
  /** MANUAL | AUTO — how it went out, independent of whether it succeeded. */
  dispatch_mode?: string | null;
  /** Recorded by email_node at the moment of dispatch. */
  sent_at?: string | null;
}

/** Matches StateResponse. */
export interface OnboardingStateResponse {
  thread_id: string;
  candidate_id: string;
  current_node: string | null;
  node_status: NodeStatus | null;
  approval_status: ApprovalStatus | null;
  selection_status: SelectionStatus | null;
  calculated_financials: CalculatedFinancials | null;
  leave_allocations: LeaveAllocations | null;
  email_queue_summary: EmailQueueSummary[];
  error_message: string | null;
}

/** Matches CandidateResponse. */
export interface Candidate {
  candidate_id: string;
  thread_id: string;
  candidate_name: string;
  candidate_email: string;
  role_title: string;
  department: string;
  hiring_manager_email: string;
  employment_type: EmploymentType | null;
  selection_status: SelectionStatus | null;
  start_date: string | null;
  end_date: string | null;
  current_node: string | null;
  node_status: NodeStatus | null;
  approval_status: ApprovalStatus | null;
  calculated_financials: CalculatedFinancials | null;
  leave_allocations: LeaveAllocations | null;
  raw_compensation: Record<string, unknown> | null;
  email_queue_summary: EmailQueueSummary[];
  kanban_column: KanbanColumn;
  offer_letter_html: string | null;
}

/** One rendered outbound email. Matches GET /onboarding/{id}/messages. */
export interface MailMessage {
  index: number;
  template: string | null;
  recipient: string | null;
  recipient_name: string | null;
  status: string | null;
  message_id: string | null;
  subject: string;
  /** Fully-rendered HTML, exactly as handed to Resend. Null if it failed to render. */
  html: string | null;
  render_error: string | null;
}

export interface MailMessagesResponse {
  thread_id: string;
  candidate_id: string | null;
  candidate_name: string | null;
  messages: MailMessage[];
}

export interface AuditEntry {
  timestamp: string;
  node: string;
  event: string;
  actor: string;
  payload_summary: string;
  thread_id?: string;
  candidate_name?: string;
}

/**
 * Emitted by GET /onboarding/{id}/stream.
 * The endpoint is a read-only checkpoint poller — it reports state, it does
 * not drive it. `pending_nodes` empty means the graph reached END.
 */
export interface StreamEvent {
  event:
    | "state_update"
    | "done"
    | "error"
    | "not_found"
    | "stream_timeout";
  thread_id?: string;
  checkpoint_id?: string | null;
  timestamp?: string;
  current_node?: string | null;
  node_status?: NodeStatus | null;
  approval_status?: ApprovalStatus | null;
  pending_nodes?: string[];
  kanban_column?: KanbanColumn;
  error_message?: string | null;
  message?: string;
}


// ── Two-stage documentation (§1, §2) ────────────────────────────────────────

export type OfferLetterStatus =
  | "NOT_CREATED" | "DRAFT" | "RELEASED" | "VIEWED"
  | "ACCEPTED" | "DECLINED" | "EXPIRED";

export type AppointmentLetterStatus =
  | "NOT_ELIGIBLE" | "ELIGIBLE" | "DRAFT" | "RELEASED" | "VIEWED";

export interface StageRow {
  stage: string;
  status: string;
  actions: string[];
  blocked_reason: string;
}

export interface StagesResponse {
  thread_id: string;
  candidate_name: string | null;
  designation: string | null;
  stages: StageRow[];
  offer_status: OfferLetterStatus;
  appointment_status: AppointmentLetterStatus;
  onboarding_stage: string;
}

export interface HrNotification {
  id: string;
  kind: string;
  title: string;
  body: string;
  thread_id: string;
  candidate_name: string;
  role_title: string;
  action_label: string;
  action_href: string;
  created_at: string | null;
}

export interface StateOptionApi {
  code: string;
  name: string;
  kind: "STATE" | "UT";
  levies_professional_tax: boolean;
  cities: string[];
}

export interface SalaryBreakup {
  total_ctc: number; gross_salary: number; net_annual: number;
  monthly_net: number; monthly_gross: number;
  basic: number; hra: number; conveyance: number; medical: number;
  special_allowance: number; employer_pf: number; employee_pf: number;
  employer_esi: number; employee_esi: number; gratuity_accrual: number;
  professional_tax: number; income_tax_tds: number; total_deductions: number;
  esi_applicable: boolean; effective_tax_rate: number;
  financial_year: string; tax_regime: string;
  config_verified_on: string; warnings: string[];
  formatted?: Record<string, string>;
  ctc_lpa?: string;
}


/** GET /candidate/{id}/status — deliberately omits any unreleased document. */
export interface CandidateStatus {
  candidate_name: string | null;
  designation: string | null;
  department: string | null;
  work_location: { city: string | null; state: string | null };
  joining_date: string | null;
  ctc: { annual: number; formatted: string; lpa: string } | null;
  application_status: string | null;
  offer: {
    status: OfferLetterStatus;
    document_number: string | null;
    released_at: string | null;
    expires_at: string | null;
    responded_at: string | null;
    can_respond: boolean;
  };
  appointment: {
    /** RELEASED | PENDING_FROM_HR — never leaks a draft's existence. */
    status: "RELEASED" | "PENDING_FROM_HR";
    document_number: string | null;
    released_at: string | null;
  };
  onboarding: { status: string };
}

export interface CandidateDocument {
  document_type: "OFFER_LETTER" | "APPOINTMENT_LETTER";
  document_number: string | null;
  status: string | null;
  html: string | null;
  expires_at?: string | null;
}

/** One turn of a recorded call. */
export interface TranscriptTurn {
  role: string;
  text: string;
}

/** Matches api/voice.py _present(). The phone arrives already masked. */
export interface VoiceCall {
  call_id: number;
  thread_id: string;
  candidate_id: string | null;
  candidate_name: string | null;
  designation: string | null;
  document_number: string | null;
  call_type: "INITIAL" | "FINAL";
  phone_masked: string;
  call_status: string | null;
  call_outcome: string | null;
  candidate_intent: string | null;
  summary: string | null;
  reason_if_declined: string | null;
  transcript: TranscriptTurn[];
  recording_url: string | null;
  attempt: number | null;
  error_detail: string | null;
  started_at: string | null;
  ended_at: string | null;
  duration_s: number | null;
}

export interface VoiceCallsResponse {
  calls: VoiceCall[];
  totals: {
    total: number;
    completed: number;
    failed: number;
    in_progress: number;
    accepted_intent: number;
    declined: number;
    needs_time: number;
    unreachable: number;
  };
}

export interface VoiceStatus {
  voice_agent_enabled: boolean;
  telephony_configured: boolean;
  telephony_problem?: string | null;
  deepgram_configured: boolean;
  initial_call_enabled: boolean;
  final_call_enabled: boolean;
  initial_delay_minutes: number;
  max_attempts: number;
  recording_enabled: boolean;
}

/** Matches api/reports.py. Rates are null when there is no sample. */
export interface ReportMetrics {
  generated_at: string;
  funnel: {
    workflows: number; offers_extended: number; awaiting_response: number;
    accepted: number; declined: number; expired: number;
    appointments_released: number; onboarding_in_progress: number;
    onboarding_completed: number;
  };
  rates: {
    acceptance_rate: number | null;
    response_rate: number | null;
    email_success_rate: number | null;
  };
  time_to_decision_hours: {
    median: number | null; fastest: number | null; slowest: number | null; sample: number;
  };
  compensation: {
    median_ctc: number | null; min_ctc: number | null; max_ctc: number | null; sample: number;
  };
  by_department: Record<string, number>;
  by_city: Record<string, number>;
  decline_reasons: { candidate: string; reason: string }[];
}
