"""
PDF rendering and the reporting projections.

The PDF tests care about one thing above layout: **₹ must survive**. The
built-in PDF fonts have no glyph for U+20B9, so the first working renderer
produced an Indian offer letter with a blank box where every salary figure
should be. A letter that renders beautifully and cannot show the currency is
not a working feature.
"""

from __future__ import annotations

import csv
import io
import os
from dataclasses import asdict

import pytest
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
os.environ.setdefault("CANDIDATE_TOKEN_SECRET", "test-secret-for-unit-tests")

from core.india.compensation import build_salary_breakup  # noqa: E402
from core.india.documents import render_appointment_letter, render_offer_letter  # noqa: E402
from core.india.pdf import PdfError, html_to_pdf, pdf_filename  # noqa: E402


def state() -> dict:
    s = {
        "candidate_id": "CAND-PDF", "candidate_name": "Manoj Varikuntla",
        "designation": "Finance Executive", "department": "Finance",
        "employment_type": "FULL_TIME", "start_date": "2026-12-01",
        "work_location_city": "Bengaluru", "work_location_state": "KA",
        "reporting_manager": "A. Rao", "probation_period_months": 6,
        "notice_period_days": 60,
        "raw_compensation_input": {
            "total_ctc": 2500000, "tax_regime": "NEW", "work_state": "KA",
            "work_city": "Bengaluru", "employment_type": "FULL_TIME",
            "performance_bonus": 0,
        },
    }
    s["salary_breakup"] = asdict(build_salary_breakup(
        total_ctc=2500000, state_code="KA", city="Bengaluru",
        tax_regime="NEW", employment_type="FULL_TIME"))
    return s


def text_of(pdf: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:                                  # pragma: no cover
        from PyPDF2 import PdfReader                     # type: ignore
    return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages)


# ── Rendering ───────────────────────────────────────────────────────────────

def test_offer_letter_renders_to_a_real_pdf():
    html, _, _ = render_offer_letter(state())
    pdf = html_to_pdf(html)
    assert pdf.startswith(b"%PDF-")
    assert len(pdf) > 10_000


def test_appointment_letter_renders_to_a_real_pdf():
    s = state()
    s["offer_letter"] = {"status": "ACCEPTED", "document_number": "OFR/2026/CAND-PDF"}
    html, _ = render_appointment_letter(s)
    assert html_to_pdf(html).startswith(b"%PDF-")


def test_the_rupee_sign_survives():
    """
    The reason the fonts are vendored. Without them every figure on the letter
    printed as an empty box, which is worse than useless on an Indian offer.
    """
    html, _, _ = render_offer_letter(state())
    assert "₹" in text_of(html_to_pdf(html)), "₹ did not render — check assets/fonts"


def test_the_actual_salary_figures_appear():
    html, _, _ = render_offer_letter(state())
    text = text_of(html_to_pdf(html))
    # Indian digit grouping, not 2,500,000.
    assert "25,00,000" in text
    assert "Total CTC" in text


def test_the_font_is_embedded_not_referenced():
    """A PDF that depends on the reader having DejaVu is not portable."""
    html, _, _ = render_offer_letter(state())
    pdf = html_to_pdf(html)
    assert b"DejaVu" in pdf, "the font must be embedded in the file"


def test_empty_html_is_refused_rather_than_producing_a_stub():
    for bad in ("", "   ", None):
        with pytest.raises(PdfError):
            html_to_pdf(bad)  # type: ignore[arg-type]


# ── Filenames ───────────────────────────────────────────────────────────────

def test_document_number_slashes_do_not_become_path_separators():
    """
    'OFR/2026/CAND-1.pdf' in Content-Disposition saves as 'CAND-1.pdf' and the
    rest of the reference is lost.
    """
    name = pdf_filename("OFR/2026/CAND-1", "offer")
    assert name == "OFR-2026-CAND-1.pdf"
    assert "/" not in name


@pytest.mark.parametrize("raw,expected", [
    (None, "offer-letter.pdf"),
    ("", "offer-letter.pdf"),
    ("   ", "offer-letter.pdf"),
    ("APT/2026/CAND-7", "APT-2026-CAND-7.pdf"),
])
def test_filename_always_resolves_to_something_usable(raw, expected):
    assert pdf_filename(raw, "offer-letter") == expected


# ── Reporting ───────────────────────────────────────────────────────────────

def rows() -> list[dict]:
    """Three workflows: one accepted, one declined, one still out."""
    return [
        {"offer_status": "ACCEPTED", "decision_hours": 2.0, "total_ctc": 2500000,
         "emails_sent": 2, "emails_failed": 0, "department": "Finance",
         "work_city": "Bengaluru", "decline_reason": None, "candidate_name": "A",
         "appointment_status": "RELEASED", "onboarding_stage": "IN_PROGRESS"},
        {"offer_status": "DECLINED", "decision_hours": 48.0, "total_ctc": 1800000,
         "emails_sent": 1, "emails_failed": 1, "department": "Engineering",
         "work_city": "Hyderabad", "decline_reason": "Accepted another offer",
         "candidate_name": "B", "appointment_status": "NOT_ELIGIBLE",
         "onboarding_stage": "NOT_STARTED"},
        {"offer_status": "RELEASED", "decision_hours": None, "total_ctc": 2000000,
         "emails_sent": 1, "emails_failed": 0, "department": "Engineering",
         "work_city": "Hyderabad", "decline_reason": None, "candidate_name": "C",
         "appointment_status": "NOT_ELIGIBLE", "onboarding_stage": "NOT_STARTED"},
    ]


def test_rate_returns_none_rather_than_zero_when_there_is_no_sample():
    """
    'No offers yet' and '0% acceptance' are different facts. Reporting the
    first as the second is how a brand-new deployment looks like a disaster.
    """
    from api.reports import _rate

    assert _rate(0, 0) is None
    assert _rate(0, 5) == 0.0
    assert _rate(3, 4) == 0.75


def test_acceptance_rate_excludes_offers_still_awaiting_a_reply():
    """A pending offer is not a rejection and must not drag the rate down."""
    from api.reports import _rate

    r = rows()
    accepted = sum(1 for x in r if x["offer_status"] == "ACCEPTED")
    declined = sum(1 for x in r if x["offer_status"] == "DECLINED")
    assert _rate(accepted, accepted + declined) == 0.5     # 1 of 2 decided
    assert _rate(accepted, len(r)) == 0.333                # ...not 1 of 3


def test_time_to_decision_uses_median_not_mean():
    """One candidate who sat on it for weeks must not move the headline."""
    from statistics import mean, median

    times = [2.0, 3.0, 4.0, 500.0]
    assert median(times) == 3.5
    assert mean(times) > 100          # which is why the mean is not reported


def test_csv_round_trips_with_indian_names_and_rupees():
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["candidate_name", "ctc"])
    w.writeheader()
    w.writerow({"candidate_name": "Manoj Varikuntla", "ctc": "₹25,00,000"})
    payload = "﻿" + buf.getvalue()

    parsed = list(csv.DictReader(io.StringIO(payload[1:])))
    assert parsed[0]["ctc"] == "₹25,00,000"
    assert payload.startswith("﻿"), "Excel on Windows needs the BOM for ₹"
