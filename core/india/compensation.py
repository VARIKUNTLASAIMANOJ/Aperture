"""
Indian CTC / salary engine.

Replaces the US model (federal brackets, FICA, Social Security cap, 401k)
wholesale. Nothing here is guessed at runtime: every rate is read from
statutory_config.json, keyed by Financial Year, so a Budget change is a config
edit, not a code change (§6.2).

The central idea an Indian HR system must get right, and which the previous
US model had no concept of:

    CTC  ≠  Gross  ≠  Net (take-home)

    CTC    = Gross + employer PF + gratuity accrual + employer ESI
    Gross  = Basic + HRA + Special + Conveyance + Medical + Bonus
    Net    = Gross − employee PF − employee ESI − Professional Tax − TDS

Deterministic Python throughout — no LLM touches any figure.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from core.india.locations import is_hra_metro, levies_professional_tax

_CONFIG_PATH = Path(__file__).with_name("statutory_config.json")


@lru_cache(maxsize=1)
def _load_config() -> dict[str, Any]:
    return json.loads(_CONFIG_PATH.read_text())


def available_financial_years() -> list[str]:
    return sorted(_load_config()["financial_years"].keys())


def default_financial_year() -> str:
    return _load_config()["default_financial_year"]


def fy_config(financial_year: str | None = None) -> dict[str, Any]:
    cfg = _load_config()
    fy = financial_year or cfg["default_financial_year"]
    try:
        return cfg["financial_years"][fy]
    except KeyError:
        raise ValueError(
            f"No statutory configuration for {fy}. "
            f"Configured years: {', '.join(sorted(cfg['financial_years']))}"
        ) from None


# ── Salary structure defaults ───────────────────────────────────────────────
# Percentages of CTC used to derive a breakup when the employer has not
# supplied one. These are conventional Indian structures, deliberately
# overridable per offer.
DEFAULT_STRUCTURE = {
    "basic_pct_of_ctc": 0.40,      # Basic is usually 40–50% of CTC
    "hra_pct_of_basic": 0.50,      # 50% of Basic (metro convention)
    "conveyance_annual": 19200,    # ₹1,600/month, the long-standing figure
    "medical_annual": 15000,
}


@dataclass
class SalaryBreakup:
    """Every figure annual INR unless the name says monthly."""
    financial_year: str
    tax_regime: str

    # Earnings
    basic: float = 0.0
    hra: float = 0.0
    conveyance: float = 0.0
    medical: float = 0.0
    special_allowance: float = 0.0
    performance_bonus: float = 0.0
    gross_salary: float = 0.0

    # Employer contributions (part of CTC, never paid to the employee)
    employer_pf: float = 0.0
    employer_esi: float = 0.0
    gratuity_accrual: float = 0.0

    total_ctc: float = 0.0

    # Employee deductions
    employee_pf: float = 0.0
    employee_esi: float = 0.0
    professional_tax: float = 0.0
    income_tax_tds: float = 0.0
    total_deductions: float = 0.0

    net_annual: float = 0.0
    monthly_net: float = 0.0
    monthly_gross: float = 0.0

    esi_applicable: bool = False
    effective_tax_rate: float = 0.0
    config_verified_on: str = ""
    warnings: list[str] = field(default_factory=list)


def _round(v: float) -> float:
    return round(v + 0.0, 2)


def _slab_tax(taxable: float, slabs: list[dict]) -> float:
    """Progressive slab tax. `upto: null` marks the final open-ended slab."""
    tax = 0.0
    lower = 0.0
    for slab in slabs:
        upper = slab["upto"]
        if upper is None:
            if taxable > lower:
                tax += (taxable - lower) * slab["rate"]
            break
        if taxable > lower:
            tax += (min(taxable, upper) - lower) * slab["rate"]
        lower = upper
        if taxable <= lower:
            break
    return tax


def compute_income_tax(
    gross_salary: float,
    regime: str,
    financial_year: str | None = None,
    exemptions: float = 0.0,
) -> tuple[float, dict[str, float]]:
    """
    Annual income tax including surcharge and cess.

    `exemptions` covers old-regime deductions (80C, HRA exemption, etc.). The
    new regime allows almost none, which is why the caller passes 0 for it —
    applying 80C under the new regime is a classic miscalculation.
    """
    cfg = fy_config(financial_year)["income_tax"]
    key = "new_regime" if regime.upper() == "NEW" else "old_regime"
    regime_cfg = cfg[key]

    taxable = max(0.0, gross_salary - regime_cfg["standard_deduction"] - exemptions)
    base_tax = _slab_tax(taxable, regime_cfg["slabs"])

    # Section 87A rebate — wipes out liability under the threshold entirely.
    rebate_cfg = regime_cfg.get("rebate_87a") or {}
    rebate = 0.0
    if rebate_cfg and taxable <= rebate_cfg["taxable_income_upto"]:
        rebate = min(base_tax, float(rebate_cfg["max_rebate"]))
    after_rebate = max(0.0, base_tax - rebate)

    surcharge = 0.0
    for band in sorted(cfg.get("surcharge_slabs", []), key=lambda b: b["above"]):
        if taxable > band["above"]:
            surcharge = after_rebate * band["rate"]

    cess = (after_rebate + surcharge) * cfg["cess_rate"]
    total = after_rebate + surcharge + cess

    return _round(total), {
        "taxable_income": _round(taxable),
        "standard_deduction": float(regime_cfg["standard_deduction"]),
        "exemptions_applied": _round(exemptions),
        "slab_tax": _round(base_tax),
        "rebate_87a": _round(rebate),
        "surcharge": _round(surcharge),
        "cess": _round(cess),
    }


def build_salary_breakup(
    *,
    total_ctc: float,
    state_code: str,
    city: str,
    tax_regime: str = "NEW",
    financial_year: str | None = None,
    basic_pct: float | None = None,
    performance_bonus: float = 0.0,
    pf_on_actual_basic: bool = False,
    employment_type: str = "FULL_TIME",
) -> SalaryBreakup:
    """
    Derive a full Indian salary breakup from a CTC figure.

    Works backwards from CTC the way an employer actually does: fix Basic as a
    share of CTC, derive HRA and the statutory contributions from it, then let
    Special Allowance absorb the remainder so the components sum exactly to CTC.
    """
    fy = financial_year or default_financial_year()
    cfg = fy_config(fy)
    out = SalaryBreakup(financial_year=fy, tax_regime=tax_regime.upper())
    out.config_verified_on = cfg.get("verified_on", "")

    if total_ctc <= 0:
        raise ValueError("total_ctc must be greater than zero")

    basic_share = basic_pct if basic_pct is not None else DEFAULT_STRUCTURE["basic_pct_of_ctc"]
    if not 0.2 <= basic_share <= 0.6:
        raise ValueError("Basic must be between 20% and 60% of CTC")

    basic = total_ctc * basic_share
    hra_rate = cfg["hra_exemption"]["metro_rate_of_basic"] if is_hra_metro(city) \
        else cfg["hra_exemption"]["non_metro_rate_of_basic"]
    hra = basic * hra_rate

    # ── Employer-side statutory (inside CTC, never paid out) ────────────────
    epf = cfg["epf"]
    ceiling_annual = epf["statutory_wage_ceiling_monthly"] * 12
    pf_wage = basic if pf_on_actual_basic else min(basic, ceiling_annual)

    contractors_exempt = employment_type in ("CONTRACTOR_1099", "CONSULTANT")
    employer_pf = 0.0 if contractors_exempt else pf_wage * epf["employer_rate"]
    employee_pf = 0.0 if contractors_exempt else pf_wage * epf["employee_rate"]

    gratuity = 0.0 if contractors_exempt else basic * cfg["gratuity"]["accrual_rate_of_basic"]

    conveyance = float(DEFAULT_STRUCTURE["conveyance_annual"])
    medical = float(DEFAULT_STRUCTURE["medical_annual"])

    # Special allowance is the balancing figure.
    fixed = basic + hra + conveyance + medical + performance_bonus
    special = total_ctc - fixed - employer_pf - gratuity

    if special < 0:
        # CTC too small to carry the conventional structure — collapse the
        # optional allowances rather than emit a negative component.
        out.warnings.append(
            "CTC is too low for the standard structure; conveyance and medical "
            "allowances were reduced to keep components non-negative."
        )
        conveyance = medical = 0.0
        fixed = basic + hra + performance_bonus
        special = max(0.0, total_ctc - fixed - employer_pf - gratuity)

    gross = basic + hra + conveyance + medical + special + performance_bonus

    # ── ESI — eligibility is on monthly GROSS, not CTC ──────────────────────
    esi_cfg = cfg["esi"]
    monthly_gross = gross / 12
    esi_applicable = (not contractors_exempt) and monthly_gross <= esi_cfg["gross_wage_ceiling_monthly"]
    employee_esi = gross * esi_cfg["employee_rate"] if esi_applicable else 0.0
    employer_esi = gross * esi_cfg["employer_rate"] if esi_applicable else 0.0

    # ── Professional Tax — state-levied ─────────────────────────────────────
    pt = 0.0
    if levies_professional_tax(state_code):
        pt = float(cfg["professional_tax"]["by_state"].get(state_code.upper(), 0.0))

    # ── Income tax ──────────────────────────────────────────────────────────
    # Old regime permits HRA exemption + the standard 80C assumption; the new
    # regime permits neither, so exemptions are only passed for OLD.
    exemptions = 0.0
    if tax_regime.upper() == "OLD":
        hra_exempt = min(hra, basic * cfg["hra_exemption"]["metro_rate_of_basic"]
                         if is_hra_metro(city)
                         else basic * cfg["hra_exemption"]["non_metro_rate_of_basic"])
        exemptions = hra_exempt + min(employee_pf, 150000)  # 80C via EPF
    tds, tax_detail = compute_income_tax(gross, tax_regime, fy, exemptions)

    total_deductions = employee_pf + employee_esi + pt + tds
    net_annual = gross - total_deductions

    out.basic = _round(basic)
    out.hra = _round(hra)
    out.conveyance = _round(conveyance)
    out.medical = _round(medical)
    out.special_allowance = _round(special)
    out.performance_bonus = _round(performance_bonus)
    out.gross_salary = _round(gross)
    out.employer_pf = _round(employer_pf)
    out.employer_esi = _round(employer_esi)
    out.gratuity_accrual = _round(gratuity)
    out.total_ctc = _round(gross + employer_pf + employer_esi + gratuity)
    out.employee_pf = _round(employee_pf)
    out.employee_esi = _round(employee_esi)
    out.professional_tax = _round(pt)
    out.income_tax_tds = _round(tds)
    out.total_deductions = _round(total_deductions)
    out.net_annual = _round(net_annual)
    out.monthly_net = _round(net_annual / 12)
    out.monthly_gross = _round(gross / 12)
    out.esi_applicable = esi_applicable
    out.effective_tax_rate = _round(tds / gross) if gross else 0.0

    # ESI adds employer cost, so recomputing CTC above can drift from the
    # requested figure. Surface it rather than silently quoting a different CTC.
    drift = abs(out.total_ctc - total_ctc)
    if drift > 1.0:
        out.warnings.append(
            f"Derived CTC ₹{out.total_ctc:,.0f} differs from the requested "
            f"₹{total_ctc:,.0f} by ₹{drift:,.0f} because employer ESI applies "
            f"at this salary level."
        )

    out_dict_detail = tax_detail  # kept for callers that want the breakdown
    setattr(out, "tax_detail", out_dict_detail)
    return out


# ── Indian formatting ───────────────────────────────────────────────────────

def format_inr(amount: float, *, paise: bool = False) -> str:
    """
    Indian digit grouping: ₹6,00,000 — last three digits, then pairs.
    `Intl`-style Western grouping (₹600,000) is wrong for Indian documents.
    """
    neg = amount < 0
    whole = abs(int(round(amount if not paise else amount * 100)))
    if paise:
        rupees, p = divmod(whole, 100)
    else:
        rupees, p = whole, 0

    s = str(rupees)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail

    out = f"₹{s}"
    if paise:
        out += f".{p:02d}"
    return ("-" + out) if neg else out


def to_lpa(annual_ctc: float) -> str:
    """Candidate-facing shorthand: 850000 → '8.5 LPA'."""
    lakhs = annual_ctc / 100_000
    text = f"{lakhs:.2f}".rstrip("0").rstrip(".")
    return f"{text} LPA"
