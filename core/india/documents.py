"""
Offer / Appointment letter rendering.

Both documents are rendered deterministically from state. The previous design
had an LLM generate the entire offer HTML, which meant a legal document
carrying salary figures depended on a model call succeeding and could vary
between runs. Numbers now come only from core.india.compensation, and prose
comes only from the Jinja templates.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from core.india.compensation import format_inr, fy_config, to_lpa
from core.india.locations import state_name

_env = Environment(
    loader=FileSystemLoader("templates"),
    autoescape=select_autoescape(["html", "j2"]),
)
_env.filters["inr"] = format_inr
_env.filters["lpa"] = to_lpa


EMPLOYMENT_TYPE_LABELS = {
    "FULL_TIME": "Full-Time (Permanent)",
    "PROBATIONARY": "Full-Time (On Probation)",
    "CONTRACT": "Fixed-Term Contract",
    "INTERN": "Internship",
    "CONSULTANT": "Consultant (Professional Services)",
    # legacy
    "CONTRACTOR_W2": "Fixed-Term Contract",
    "CONTRACTOR_1099": "Consultant (Professional Services)",
}

REGIME_LABELS = {"NEW": "New Tax Regime", "OLD": "Old Tax Regime"}

# Statutory / conventional Indian leave. Interns and consultants accrue none.
LEAVE_BY_TYPE = {
    "FULL_TIME":     {"earned": 18, "casual": 8, "sick": 12, "maternity": 182, "paternity": 15},
    "PROBATIONARY":  {"earned": 12, "casual": 6, "sick": 8,  "maternity": 182, "paternity": 15},
    "CONTRACT":      {"earned": 12, "casual": 6, "sick": 6,  "maternity": 0,   "paternity": 0},
    "INTERN":        {"earned": 0,  "casual": 6, "sick": 6,  "maternity": 0,   "paternity": 0},
    "CONSULTANT":    {"earned": 0,  "casual": 0, "sick": 0,  "maternity": 0,   "paternity": 0},
}


def company_profile() -> dict[str, str]:
    """Branding is configuration, not code — every document reads from here."""
    return {
        "company_name": os.environ.get("COMPANY_NAME", "Aperture Technologies Private Limited"),
        "company_address": os.environ.get(
            "COMPANY_ADDRESS", "Plot 42, HITEC City, Hyderabad, Telangana 500081"
        ),
        "company_cin": os.environ.get("COMPANY_CIN", "U72200TS2019PTC134521"),
        "hr_signatory_name": os.environ.get("HR_SIGNATORY_NAME", "Priya Raghavan"),
        "hr_signatory_designation": os.environ.get("HR_SIGNATORY_DESIGNATION", "Head — Human Resources"),
    }


def _fmt_date(value: str | None) -> str:
    """Indian convention: 01 September 2026."""
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(str(value)).strftime("%d %B %Y")
    except ValueError:
        return str(value)


def document_number(prefix: str, candidate_id: str, when: date | None = None) -> str:
    """e.g. OFR/2026/CAND-2041 — a human-quotable reference."""
    year = (when or date.today()).year
    return f"{prefix}/{year}/{candidate_id}"


def _amount_maps(breakup: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    """Annual and monthly INR-formatted views of every salary component."""
    annual_keys = (
        "basic", "hra", "conveyance", "medical", "special_allowance",
        "performance_bonus", "gross_salary", "employer_pf", "employer_esi",
        "gratuity_accrual", "total_ctc", "employee_pf", "employee_esi",
        "professional_tax", "income_tax_tds", "total_deductions", "net_annual",
    )
    annual = {k: format_inr(float(breakup.get(k) or 0)) for k in annual_keys}
    monthly = {k: format_inr(float(breakup.get(k) or 0) / 12) for k in annual_keys}
    monthly["net"] = format_inr(float(breakup.get("monthly_net") or 0))
    annual["net"] = annual["net_annual"]
    return annual, monthly


def _common_context(state: dict[str, Any]) -> dict[str, Any]:
    breakup = state.get("salary_breakup") or {}
    annual, monthly = _amount_maps(breakup)
    fy = breakup.get("financial_year") or ""
    regime = (breakup.get("tax_regime") or "NEW").upper()
    emp_type = state.get("employment_type") or "FULL_TIME"
    comp = state.get("raw_compensation_input") or {}
    state_code = state.get("work_location_state") or comp.get("work_state") or ""

    ctx = {
        **company_profile(),
        "candidate_name": state.get("candidate_name", ""),
        "designation": state.get("designation") or state.get("role_title") or "",
        "department": state.get("department", ""),
        "employment_type_label": EMPLOYMENT_TYPE_LABELS.get(emp_type, emp_type),
        "joining_date": _fmt_date(state.get("start_date")),
        "work_city": state.get("work_location_city") or comp.get("work_city") or "",
        "work_state": state_name(state_code) if state_code else "",
        "reporting_manager": state.get("reporting_manager")
                             or state.get("hiring_manager_email", ""),
        "breakup": breakup,
        "f": annual,
        "m": monthly,
        "ctc_inr": format_inr(float(breakup.get("total_ctc") or 0)),
        "ctc_lpa": to_lpa(float(breakup.get("total_ctc") or 0)),
        "regime_label": REGIME_LABELS.get(regime, regime),
        "financial_year_label": (fy_config(fy).get("label") if fy else "the current financial year"),
        "document_date": date.today().strftime("%d %B %Y"),
    }
    return ctx


def render_offer_letter(state: dict[str, Any], *, validity_days: int = 7) -> tuple[str, str, str]:
    """Returns (html, document_number, expires_at_iso)."""
    ctx = _common_context(state)
    doc_no = document_number("OFR", state.get("candidate_id", "CAND"))
    expires = datetime.now(timezone.utc) + timedelta(days=validity_days)

    ctx.update({
        "document_number": doc_no,
        "offer_expiry_date": expires.strftime("%d %B %Y"),
        "offer_conditions": state.get("offer_conditions") or "",
    })
    html = _env.get_template("offer_letter_in.html.j2").render(**ctx)
    return html, doc_no, expires.isoformat()


def render_appointment_letter(state: dict[str, Any]) -> tuple[str, str]:
    """Returns (html, document_number). Assumes the offer was accepted."""
    ctx = _common_context(state)
    emp_type = state.get("employment_type") or "FULL_TIME"
    offer = state.get("offer_letter") or {}
    employee = state.get("employee_details") or {}
    doc_no = document_number("APT", state.get("candidate_id", "CAND"))
    probation = int(state.get("probation_period_months") or 6)

    ctx.update({
        "document_number": doc_no,
        "employee_id": employee.get("employee_id") or _derive_employee_id(state),
        "working_hours": state.get("working_hours") or "09:30 to 18:30, Monday to Friday",
        "probation_months": probation,
        "probation_notice_days": 15 if probation else 30,
        "notice_period_days": int(state.get("notice_period_days") or 60),
        "pay_frequency_label": "monthly",
        "leave": LEAVE_BY_TYPE.get(emp_type, LEAVE_BY_TYPE["FULL_TIME"]),
        "gratuity_years": 5,
        "offer_reference": offer.get("document_number"),
        "offer_accepted_date": _fmt_date(offer.get("responded_at")),
    })
    html = _env.get_template("appointment_letter.html.j2").render(**ctx)
    return html, doc_no


def _derive_employee_id(state: dict[str, Any]) -> str:
    """Stable placeholder until HR assigns one during onboarding."""
    cid = (state.get("candidate_id") or "0000").replace("CAND-", "")
    return f"EMP{date.today().year}{cid[-4:].zfill(4)}"
