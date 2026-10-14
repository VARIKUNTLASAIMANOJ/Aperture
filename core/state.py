"""
OnboardingState: Shared LangGraph state schema for the multi-agent onboarding system.
All fields are typed. PII fields (ssn, bank_details) are encrypted at-rest via AES-256.
"""

from __future__ import annotations

import operator
from enum import Enum
from typing import Any, Optional

from typing_extensions import Annotated, TypedDict

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SelectionStatus(str, Enum):
    PENDING = "PENDING"
    SELECTED = "SELECTED"
    REJECTED = "REJECTED"


class EmploymentType(str, Enum):
    """Indian employment conventions. The legacy US values are retained so
    threads created before localisation still deserialise."""
    FULL_TIME = "FULL_TIME"
    PROBATIONARY = "PROBATIONARY"
    CONTRACT = "CONTRACT"
    INTERN = "INTERN"
    CONSULTANT = "CONSULTANT"
    # Legacy — do not offer in new forms.
    CONTRACTOR_W2 = "CONTRACTOR_W2"
    CONTRACTOR_1099 = "CONTRACTOR_1099"


class OfferLetterStatus(str, Enum):
    """§1 — the Offer Letter's own lifecycle, independent of the Appointment."""
    NOT_CREATED = "NOT_CREATED"
    DRAFT = "DRAFT"
    RELEASED = "RELEASED"
    VIEWED = "VIEWED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class AppointmentLetterStatus(str, Enum):
    """§2 — kept deliberately separate from the offer (Rule 7)."""
    NOT_ELIGIBLE = "NOT_ELIGIBLE"   # offer not yet accepted
    ELIGIBLE = "ELIGIBLE"           # accepted — HR may now release
    DRAFT = "DRAFT"
    RELEASED = "RELEASED"
    VIEWED = "VIEWED"


class OnboardingStage(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class TaxRegime(str, Enum):
    NEW = "NEW"
    OLD = "OLD"


class ApprovalStatus(str, Enum):
    NEEDS_APPROVAL = "NEEDS_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class NodeStatus(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    WAITING_HITL = "WAITING_HITL"
    ERROR = "ERROR"


# ---------------------------------------------------------------------------
# Nested typed dicts
# ---------------------------------------------------------------------------

class RawCompensationInput(TypedDict, total=False):
    """
    Raw input from HR before deterministic calculation.

    Indian model: HR quotes a single annual CTC and the engine derives the
    component breakup. The US fields below are retained only so pre-existing
    checkpoints still load — new offers must not populate them.
    """
    # ── Indian ──────────────────────────────────────────────────────────────
    total_ctc: float                   # annual CTC in INR
    currency: str                      # "INR"
    tax_regime: str                    # "NEW" | "OLD"
    financial_year: str                # e.g. "FY2025-26"
    work_state: str                    # 2-letter code from core.india.locations
    work_city: str
    basic_pct: Optional[float]         # override the default 40% of CTC
    performance_bonus: Optional[float]
    pf_on_actual_basic: Optional[bool]

    # ── Legacy US (do not use for new offers) ───────────────────────────────
    base_pay: float
    pay_frequency: str
    hourly_estimated_hours_per_week: Optional[float]
    bonus_annual: Optional[float]
    health_deduction_monthly: Optional[float]
    retirement_401k_pct: Optional[float]
    tax_state: str


class IndianSalaryBreakup(TypedDict, total=False):
    """Mirrors core.india.compensation.SalaryBreakup."""
    financial_year: str
    tax_regime: str
    basic: float
    hra: float
    conveyance: float
    medical: float
    special_allowance: float
    performance_bonus: float
    gross_salary: float
    employer_pf: float
    employer_esi: float
    gratuity_accrual: float
    total_ctc: float
    employee_pf: float
    employee_esi: float
    professional_tax: float
    income_tax_tds: float
    total_deductions: float
    net_annual: float
    monthly_net: float
    monthly_gross: float
    esi_applicable: bool
    effective_tax_rate: float
    config_verified_on: str
    warnings: list[str]


class EmployeeDetails(TypedDict, total=False):
    """
    §7 — Indian employee record, populated at onboarding.

    PAN / Aadhaar / bank details are PII. They are stored via
    utils.encryption.encrypt_pii and the API never returns them in plaintext;
    only masked forms (e.g. XXXXX1234F) leave the server.
    """
    employee_id: str
    full_name: str
    date_of_birth: str
    personal_email: str
    official_email: str
    phone: str
    pan_encrypted: Optional[str]
    aadhaar_encrypted: Optional[str]
    uan: Optional[str]
    bank_name: Optional[str]
    bank_account_encrypted: Optional[str]
    ifsc_code: Optional[str]
    emergency_contact_name: Optional[str]
    emergency_contact_phone: Optional[str]
    current_address: Optional[str]
    permanent_address: Optional[str]
    state: Optional[str]
    city: Optional[str]
    pincode: Optional[str]


class LetterRecord(TypedDict, total=False):
    """
    One generated document. Offer and Appointment each get their own record
    (Rule 7) — they never share a status or a document body.
    """
    document_type: str                 # "OFFER_LETTER" | "APPOINTMENT_LETTER"
    status: str
    html: Optional[str]
    generated_at: Optional[str]
    released_at: Optional[str]
    viewed_at: Optional[str]
    responded_at: Optional[str]        # accepted / declined
    expires_at: Optional[str]
    released_by: Optional[str]
    decline_reason: Optional[str]
    document_number: Optional[str]     # e.g. OFR/2026/0007


class CalculatedFinancials(TypedDict, total=False):
    annual_gross: float
    monthly_gross: float
    federal_tax_annual: float
    state_tax_annual: float
    health_deduction_annual: float
    retirement_401k_annual: float
    total_deductions_annual: float
    annual_net: float
    monthly_net: float
    employer_fica_annual: float
    effective_tax_rate: float


class LeaveAllocations(TypedDict, total=False):
    pto_days: float
    sick_days: float
    parental_leave_days: int
    prorated: bool
    proration_factor: float            # e.g. 0.75 if 9 months remaining


class EmailQueueItem(TypedDict, total=False):
    template_name: str                 # e.g. "offer_letter" | "rejection_notice"
    recipient_email: str
    recipient_name: str
    variables: dict[str, Any]
    # "PENDING"   — approved, dispatches on the next email_node run
    # "SCHEDULED" — approved for a future time; the scheduler releases it
    # "SENT" | "FAILED" | "CANCELLED"
    status: str
    message_id: Optional[str]

    # ── Scheduled dispatch ──────────────────────────────────────────────────
    # total=False above: these keys are absent on items created before this
    # feature existed, so every read must tolerate them missing.
    scheduled_for: Optional[str]       # ISO-8601 UTC — when it should go out
    dispatch_mode: Optional[str]       # "MANUAL" | "AUTO"
    sent_at: Optional[str]             # ISO-8601 UTC — when it actually went


class AuditEntry(TypedDict):
    timestamp: str                     # ISO-8601
    node: str
    event: str
    actor: str                         # "SYSTEM" | "HR_<user_id>"
    payload_summary: str               # NO raw PII — summarized


# ---------------------------------------------------------------------------
# Primary Graph State
# ---------------------------------------------------------------------------

class OnboardingState(TypedDict, total=False):
    # ── Candidate identity ──────────────────────────────────────────────────
    candidate_id: str
    candidate_email: str               # PII – stored encrypted
    candidate_name: str
    # §3 — captured at trigger time and never looked up again. The voice agent
    # reads the number from THIS record, the same dict that carries the offer,
    # so a call can never be placed to a number resolved by name or email.
    # E.164, normalised by core.voice_state.normalize_phone.
    candidate_phone: Optional[str]
    role_title: str
    department: str
    hiring_manager_email: str

    # ── Decision & employment ───────────────────────────────────────────────
    selection_status: SelectionStatus
    employment_type: EmploymentType
    start_date: str                    # ISO-8601 date
    end_date: Optional[str]            # contractors only

    # ── Encrypted PII (encrypted blob stored, raw never logged) ────────────
    ssn_encrypted: Optional[str]
    bank_details_encrypted: Optional[str]

    # ── Financial pipeline ──────────────────────────────────────────────────
    raw_compensation_input: RawCompensationInput
    calculated_financials: CalculatedFinancials

    # ── Leave ───────────────────────────────────────────────────────────────
    leave_allocations: LeaveAllocations

    # ── Contract / documents ────────────────────────────────────────────────
    contract_document_url: Optional[str]
    # Retained for backward compatibility with pre-existing threads and the
    # correspondence log. New code should read offer_letter["html"].
    offer_letter_html: Optional[str]

    # ── Two-stage documentation (§1, §2) ────────────────────────────────────
    # Two independent records with independent statuses — Rule 7. Merging them
    # into one document/status is explicitly forbidden.
    offer_letter: LetterRecord
    appointment_letter: LetterRecord

    # ── Voice follow-up (§10) ───────────────────────────────────────────────
    # Armed by email_node when the Offer Letter is actually dispatched, so a
    # thread whose offer never reached the candidate is never called.
    # core.voice_state.OfferFollowup; typed as dict here to avoid a circular
    # import (voice_state imports nothing from this module, and must not).
    offer_followup: dict[str, Any]

    # Position / posting details that appear on both documents
    designation: Optional[str]
    work_location_city: Optional[str]
    work_location_state: Optional[str]
    reporting_manager: Optional[str]
    working_hours: Optional[str]
    probation_period_months: Optional[int]
    notice_period_days: Optional[int]
    offer_conditions: Optional[str]

    # ── Indian compensation ─────────────────────────────────────────────────
    salary_breakup: IndianSalaryBreakup

    # ── Employee record + onboarding (§7) ───────────────────────────────────
    employee_details: EmployeeDetails
    onboarding_stage: Optional[str]

    # Candidate-facing access. HMAC-signed, carried in the emailed link; the
    # server re-derives and compares rather than trusting the URL.
    candidate_access_token: Optional[str]

    # ── Email workflow ──────────────────────────────────────────────────────
    # NOT an append reducer: email_node rewrites item statuses (PENDING → SENT),
    # so it must be able to replace the list. Nodes that enqueue concatenate
    # explicitly onto the existing queue.
    email_queue: list[EmailQueueItem]

    # ── Human-in-the-loop ───────────────────────────────────────────────────
    approval_status: ApprovalStatus
    approver_email: Optional[str]
    approver_notes: Optional[str]

    # ── Agent observability ─────────────────────────────────────────────────
    current_node: str
    node_status: NodeStatus
    error_message: Optional[str]

    # ── Immutable audit trail (append-only via Annotated reducer) ───────────
    audit_log: Annotated[list[AuditEntry], operator.add]