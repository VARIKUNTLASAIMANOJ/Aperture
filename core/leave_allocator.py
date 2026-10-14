"""
Leave Entitlement Allocator — deterministic, no LLM.

Policy (from 03_business_rules.md):
  - FULL_TIME: 15 days PTO, 10 days Sick Leave, prorated to remaining calendar year.
  - CONTRACTOR_W2 / CONTRACTOR_1099: 0 PTO, 0 Sick Leave (unless custom terms).
  - Parental leave: 90 days for FULL_TIME, 0 for contractors.
"""

from __future__ import annotations

from datetime import date

from core.state import EmploymentType, LeaveAllocations

# ---------------------------------------------------------------------------
# Policy constants
# ---------------------------------------------------------------------------

FULL_TIME_PTO_DAYS      = 15
FULL_TIME_SICK_DAYS     = 10
FULL_TIME_PARENTAL_DAYS = 90   # ~12 weeks

CONTRACTOR_PTO_DAYS     = 0
CONTRACTOR_SICK_DAYS    = 0
CONTRACTOR_PARENTAL_DAYS = 0


def _proration_factor(start: date) -> float:
    """
    Fraction of calendar year remaining from start_date (inclusive).
    Jan 1 → 1.0,  Dec 1 → 1/12 ≈ 0.083
    """
    year_end   = date(start.year, 12, 31)
    total_days = (year_end - date(start.year, 1, 1)).days + 1
    remaining  = (year_end - start).days + 1
    return round(remaining / total_days, 4)


def allocate_leave(
    employment_type: EmploymentType,
    start_date_iso: str,
    custom_pto_days: float | None = None,
) -> LeaveAllocations:
    """
    Returns prorated leave allocation.
    `custom_pto_days` overrides contractor default (for special contract terms).
    """
    start = date.fromisoformat(start_date_iso)
    factor = _proration_factor(start)

    if employment_type == EmploymentType.FULL_TIME:
        raw_pto    = custom_pto_days if custom_pto_days is not None else FULL_TIME_PTO_DAYS
        raw_sick   = FULL_TIME_SICK_DAYS
        raw_parent = FULL_TIME_PARENTAL_DAYS
    else:
        # Contractors — 0 unless custom terms override PTO
        raw_pto    = custom_pto_days if custom_pto_days is not None else CONTRACTOR_PTO_DAYS
        raw_sick   = CONTRACTOR_SICK_DAYS
        raw_parent = CONTRACTOR_PARENTAL_DAYS

    # Prorate PTO and sick leave; parental leave is always full entitlement
    prorated_pto  = round(raw_pto  * factor, 1)
    prorated_sick = round(raw_sick * factor, 1)

    return LeaveAllocations(
        pto_days         = prorated_pto,
        sick_days        = prorated_sick,
        parental_leave_days = raw_parent,
        prorated         = True,
        proration_factor = factor,
    )