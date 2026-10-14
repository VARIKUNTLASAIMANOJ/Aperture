"""
Deterministic Financial Calculator — zero LLM involvement.
Handles FULL_TIME salaried employees and hourly/fixed CONTRACTORS (W2 & 1099).

Federal tax brackets are 2024 MFJ/Single approximations.
State tax is a flat rate lookup (extend as needed).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.state import CalculatedFinancials, EmploymentType, RawCompensationInput

# ---------------------------------------------------------------------------
# Tax tables (extend per jurisdiction)
# ---------------------------------------------------------------------------

# 2024 Federal Income Tax — Single filer brackets (inclusive lower bound)
FEDERAL_BRACKETS_SINGLE: list[tuple[float, float]] = [
    (0,        0.10),
    (11_600,   0.12),
    (47_150,   0.22),
    (100_525,  0.24),
    (191_950,  0.32),
    (243_725,  0.35),
    (609_350,  0.37),
]

# Flat state income tax rates by state code (placeholder — expand to full schedule)
STATE_TAX_RATES: dict[str, float] = {
    "CA": 0.093,  "NY": 0.0685, "TX": 0.00,  "FL": 0.00,
    "WA": 0.00,   "IL": 0.0495, "MA": 0.05,  "GA": 0.055,
    "CO": 0.044,  "NJ": 0.0637, "OH": 0.04,  "VA": 0.0575,
    "NC": 0.0499, "AZ": 0.025,  "MN": 0.0985,"OR": 0.099,
    "OTHER": 0.05,  # fallback
}

# FICA (employer + employee combined)
SOCIAL_SECURITY_RATE    = 0.062   # employee share, capped at $168,600 (2024)
SOCIAL_SECURITY_WAGE_CAP = 168_600
MEDICARE_RATE           = 0.0145  # employee share (no cap)
EMPLOYER_FICA_RATE      = 0.0765  # mirrors employee SS + Medicare

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _federal_tax(annual_income: float) -> float:
    """Progressive federal income tax calculation (single filer)."""
    tax = 0.0
    prev_limit = 0.0
    for limit, rate in FEDERAL_BRACKETS_SINGLE:
        if annual_income <= limit:
            break
        taxable_in_bracket = min(annual_income, limit) - prev_limit if limit > 0 else 0
        # handle last (open-ended) bracket
        if limit == 0:
            taxable_in_bracket = annual_income - prev_limit
        tax += taxable_in_bracket * rate
        prev_limit = limit
    # handle income above last defined bracket
    if annual_income > FEDERAL_BRACKETS_SINGLE[-1][0]:
        tax += (annual_income - FEDERAL_BRACKETS_SINGLE[-1][0]) * FEDERAL_BRACKETS_SINGLE[-1][1]
    return round(tax, 2)


def _progressive_federal_tax(annual_income: float) -> float:
    """Correct bracket iteration."""
    tax = 0.0
    brackets = FEDERAL_BRACKETS_SINGLE
    for i, (lower, rate) in enumerate(brackets):
        upper = brackets[i + 1][0] if i + 1 < len(brackets) else float("inf")
        if annual_income <= lower:
            break
        taxable = min(annual_income, upper) - lower
        tax += taxable * rate
    return round(tax, 2)


def _state_tax(annual_income: float, state: str) -> float:
    rate = STATE_TAX_RATES.get(state.upper(), STATE_TAX_RATES["OTHER"])
    return round(annual_income * rate, 2)


def _fica(annual_income: float) -> tuple[float, float]:
    """Returns (employee_ss, employee_medicare)."""
    ss_base = min(annual_income, SOCIAL_SECURITY_WAGE_CAP)
    ss = round(ss_base * SOCIAL_SECURITY_RATE, 2)
    medicare = round(annual_income * MEDICARE_RATE, 2)
    return ss, medicare


# ---------------------------------------------------------------------------
# Public calculator entry point
# ---------------------------------------------------------------------------

def calculate_financials(
    compensation: RawCompensationInput,
    employment_type: EmploymentType,
) -> CalculatedFinancials:
    """
    Deterministic calculation — never calls an LLM.
    Returns a fully populated CalculatedFinancials dict.
    """
    pay_freq  = compensation.get("pay_frequency", "annual").lower()
    base_pay  = float(compensation.get("base_pay", 0))
    state     = compensation.get("tax_state", "OTHER").upper()

    # ── Step 1: Derive annual gross ─────────────────────────────────────────
    if pay_freq == "hourly":
        hours_pw = float(compensation.get("hourly_estimated_hours_per_week", 40))
        annual_gross = base_pay * hours_pw * 4.33 * 12
    elif pay_freq == "monthly":
        annual_gross = base_pay * 12
    else:  # "annual" default
        annual_gross = base_pay

    monthly_gross = round(annual_gross / 12, 2)
    annual_gross  = round(annual_gross, 2)

    # ── Step 2: Deductions ──────────────────────────────────────────────────
    health_monthly   = float(compensation.get("health_deduction_monthly", 0))
    health_annual    = round(health_monthly * 12, 2)

    ret_pct          = float(compensation.get("retirement_401k_pct", 0))
    retirement_annual = round(annual_gross * ret_pct, 2)

    # ── Step 3: Tax calculations ────────────────────────────────────────────
    # 1099 contractors pay self-employment tax (SE) instead of FICA witholding
    if employment_type == EmploymentType.CONTRACTOR_1099:
        federal_tax   = _progressive_federal_tax(annual_gross)
        state_tax     = _state_tax(annual_gross, state)
        # Self-employment = 15.3% on 92.35% of net earnings (simplified)
        se_base       = annual_gross * 0.9235
        se_tax        = round(se_base * 0.153, 2)
        employer_fica = 0.0          # 1099 pays own SE tax
        fica_employee_total = se_tax
    else:
        # W2 employees (FULL_TIME or CONTRACTOR_W2)
        taxable = max(annual_gross - retirement_annual, 0)
        federal_tax   = _progressive_federal_tax(taxable)
        state_tax     = _state_tax(taxable, state)
        ss, med       = _fica(annual_gross)
        fica_employee_total = round(ss + med, 2)
        employer_fica = round(annual_gross * EMPLOYER_FICA_RATE, 2)

    total_deductions = round(
        federal_tax + state_tax + fica_employee_total + health_annual + retirement_annual, 2
    )
    annual_net  = round(annual_gross - total_deductions, 2)
    monthly_net = round(annual_net / 12, 2)
    eff_rate    = round((federal_tax + state_tax) / annual_gross, 4) if annual_gross else 0.0

    return CalculatedFinancials(
        annual_gross             = annual_gross,
        monthly_gross            = monthly_gross,
        federal_tax_annual       = federal_tax,
        state_tax_annual         = state_tax,
        health_deduction_annual  = health_annual,
        retirement_401k_annual   = retirement_annual,
        total_deductions_annual  = total_deductions,
        annual_net               = annual_net,
        monthly_net              = monthly_net,
        employer_fica_annual     = employer_fica,
        effective_tax_rate       = eff_rate,
    )