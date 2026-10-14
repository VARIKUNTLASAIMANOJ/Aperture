"""
Compensation & Statutory Calculator Node (India)
────────────────────────────────────────────────
Calls the deterministic Indian CTC engine and the leave allocator.
NO LLM is involved in any numeric computation.

Replaces the previous US model (federal brackets, FICA, 401k, US state tax)
entirely. Rates are read from core/india/statutory_config.json by financial
year, so a Budget change never requires touching this file.
"""

from __future__ import annotations

from dataclasses import asdict

from langchain_core.runnables import RunnableConfig

from core.india.compensation import build_salary_breakup, default_financial_year
from core.india.locations import is_valid_city, is_valid_state, state_name
from core.leave_allocator import allocate_leave
from core.state import NodeStatus, OnboardingState
from utils.audit import emit_audit


async def financial_node(state: OnboardingState, config: RunnableConfig) -> dict:
    candidate_id = state.get("candidate_id", "UNKNOWN")
    employment_type = state.get("employment_type") or "FULL_TIME"
    comp = dict(state.get("raw_compensation_input") or {})
    start_date = state.get("start_date")

    try:
        state_code = (state.get("work_location_state") or comp.get("work_state") or "").upper()
        city = state.get("work_location_city") or comp.get("work_city") or ""

        # Location is validated here, not just at the API edge, because these
        # values drive HRA metro classification and Professional Tax — a bad
        # pairing would silently produce a wrong salary rather than an error.
        if not is_valid_state(state_code):
            raise ValueError(f"'{state_code}' is not a valid Indian state or union territory code.")
        if city and not is_valid_city(state_code, city):
            raise ValueError(f"{city} is not a recognised work location in {state_name(state_code)}.")

        total_ctc = float(comp.get("total_ctc") or 0)
        if total_ctc <= 0:
            raise ValueError("Annual CTC is required and must be greater than zero.")

        breakup = build_salary_breakup(
            total_ctc=total_ctc,
            state_code=state_code,
            city=city,
            tax_regime=(comp.get("tax_regime") or "NEW"),
            financial_year=comp.get("financial_year") or default_financial_year(),
            basic_pct=comp.get("basic_pct"),
            performance_bonus=float(comp.get("performance_bonus") or 0),
            pf_on_actual_basic=bool(comp.get("pf_on_actual_basic")),
            employment_type=employment_type,
        )

        leave = allocate_leave(employment_type, start_date)
        payload = asdict(breakup)

        return {
            "current_node": "financial_node",
            "node_status": NodeStatus.COMPLETE,
            "salary_breakup": payload,
            "leave_allocations": leave,
            "error_message": None,
            "audit_log": emit_audit(
                node="financial_node",
                event="FINANCIALS_CALCULATED",
                payload_summary=(
                    f"{candidate_id}: CTC ₹{breakup.total_ctc:,.0f}, "
                    f"gross ₹{breakup.gross_salary:,.0f}, "
                    f"net ₹{breakup.net_annual:,.0f}/yr "
                    f"(₹{breakup.monthly_net:,.0f}/mo). "
                    f"TDS ₹{breakup.income_tax_tds:,.0f} under {breakup.tax_regime} regime, "
                    f"{breakup.financial_year}. PT ₹{breakup.professional_tax:,.0f}, "
                    f"ESI {'applicable' if breakup.esi_applicable else 'not applicable'}."
                ),
            ),
        }

    except Exception as exc:
        return {
            "current_node": "financial_node",
            "node_status": NodeStatus.ERROR,
            "error_message": str(exc),
            "audit_log": emit_audit(
                node="financial_node",
                event="CALCULATION_ERROR",
                payload_summary=f"{candidate_id}: salary calculation failed — {exc}",
            ),
        }


def route_after_financial(state: OnboardingState) -> str:
    if state.get("node_status") == NodeStatus.ERROR:
        return "error_handler"
    return "offer_node"
