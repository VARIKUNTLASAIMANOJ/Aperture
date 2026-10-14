"""
Reporting (metrics + CSV export).

Everything here is derived from the checkpoint and the audit trail at request
time — nothing is pre-aggregated and no counters are maintained. The audit log
is already the system's record of what happened, and a second source of truth
that drifts from it would be worse than no reporting at all.

The questions this answers are the ones a head of HR actually asks: how many
offers did we extend, how many came back, how long did people take to decide,
and why did the ones who said no say no.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from statistics import median
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Query, Response

from core.lifecycle import appointment_status, offer_status, onboarding_stage

router = APIRouter(prefix="/reports", tags=["reports"])

_get_graph: Callable[[], Any] | None = None
_list_threads: Callable[[], Any] | None = None


def bind(get_graph: Callable[[], Any], list_threads: Callable[[], Any]) -> None:
    global _get_graph, _list_threads
    _get_graph, _list_threads = get_graph, list_threads


def _graph():
    if _get_graph is None or _get_graph() is None:
        raise HTTPException(status_code=503, detail="Graph not initialised yet.")
    return _get_graph()


def _parse(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


async def _rows() -> list[dict[str, Any]]:
    """
    One flat record per workflow — the shape both the metrics and the CSV are
    built from, so the two can never disagree about what a "decline" is.
    """
    out: list[dict[str, Any]] = []
    for tid in await _list_threads():
        try:
            snapshot = await _graph().aget_state({"configurable": {"thread_id": tid}})
        except Exception:
            continue
        if not snapshot or not snapshot.values:
            continue

        st = dict(snapshot.values)
        offer = st.get("offer_letter") or {}
        appt = st.get("appointment_letter") or {}
        breakup = st.get("salary_breakup") or {}
        followup = st.get("offer_followup") or {}
        queue = st.get("email_queue") or []

        released = _parse(offer.get("released_at"))
        responded = _parse(offer.get("responded_at"))
        # Hours, one decimal: the headline number is "how long do candidates
        # take", and a raw timedelta is not something anyone reads.
        decision_hours = (
            round((responded - released).total_seconds() / 3600, 1)
            if released and responded and responded >= released else None
        )

        out.append({
            "thread_id": tid,
            "candidate_id": st.get("candidate_id"),
            "candidate_name": st.get("candidate_name"),
            "candidate_email": st.get("candidate_email"),
            "role_title": st.get("role_title"),
            "designation": st.get("designation"),
            "department": st.get("department"),
            "work_city": st.get("work_location_city"),
            "work_state": st.get("work_location_state"),
            "employment_type": st.get("employment_type"),
            "selection_status": st.get("selection_status"),
            "total_ctc": breakup.get("total_ctc"),
            "tax_regime": breakup.get("tax_regime"),
            "joining_date": st.get("start_date"),
            "offer_status": offer_status(st),
            "offer_number": offer.get("document_number"),
            "offer_released_at": offer.get("released_at"),
            "offer_responded_at": offer.get("responded_at"),
            "decision_hours": decision_hours,
            "decline_reason": offer.get("decline_reason"),
            "appointment_status": appointment_status(st),
            "appointment_number": appt.get("document_number"),
            "onboarding_stage": onboarding_stage(st),
            "emails_sent": sum(1 for e in queue if e.get("status") == "SENT"),
            "emails_failed": sum(1 for e in queue if e.get("status") == "FAILED"),
            "call_outcome": followup.get("last_outcome"),
            "call_intent": followup.get("last_intent"),
            "call_attempts": followup.get("attempts"),
        })
    return out


def _rate(numerator: int, denominator: int) -> Optional[float]:
    """None, not 0.0, when there is nothing to divide — 'no offers yet' and
    '0% acceptance' are different facts and must not look the same."""
    return round(numerator / denominator, 3) if denominator else None


@router.get("/metrics")
async def metrics():
    rows = await _rows()

    extended = [r for r in rows if r["offer_status"] not in ("NOT_CREATED", "DRAFT")]
    accepted = [r for r in rows if r["offer_status"] == "ACCEPTED"]
    declined = [r for r in rows if r["offer_status"] == "DECLINED"]
    expired = [r for r in rows if r["offer_status"] == "EXPIRED"]
    pending = [r for r in extended if r["offer_status"] in ("RELEASED", "VIEWED")]

    times = [r["decision_hours"] for r in rows if r["decision_hours"] is not None]
    ctcs = [float(r["total_ctc"]) for r in rows if r.get("total_ctc")]

    def group(key: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in rows:
            k = r.get(key) or "—"
            counts[k] = counts.get(k, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "funnel": {
            "workflows": len(rows),
            "offers_extended": len(extended),
            "awaiting_response": len(pending),
            "accepted": len(accepted),
            "declined": len(declined),
            "expired": len(expired),
            "appointments_released": sum(
                1 for r in rows if r["appointment_status"] == "RELEASED"),
            "onboarding_in_progress": sum(
                1 for r in rows if r["onboarding_stage"] == "IN_PROGRESS"),
            "onboarding_completed": sum(
                1 for r in rows if r["onboarding_stage"] == "COMPLETED"),
        },
        "rates": {
            # Of the offers that got a yes/no — pending ones are not failures.
            "acceptance_rate": _rate(len(accepted), len(accepted) + len(declined)),
            "response_rate": _rate(len(accepted) + len(declined), len(extended)),
            "email_success_rate": _rate(
                sum(r["emails_sent"] for r in rows),
                sum(r["emails_sent"] + r["emails_failed"] for r in rows),
            ),
        },
        "time_to_decision_hours": {
            # Median, not mean: one candidate who sat on it for three weeks
            # should not move the number everyone reads.
            "median": round(median(times), 1) if times else None,
            "fastest": min(times) if times else None,
            "slowest": max(times) if times else None,
            "sample": len(times),
        },
        "compensation": {
            "median_ctc": round(median(ctcs)) if ctcs else None,
            "min_ctc": round(min(ctcs)) if ctcs else None,
            "max_ctc": round(max(ctcs)) if ctcs else None,
            "sample": len(ctcs),
        },
        "by_department": group("department"),
        "by_city": group("work_city"),
        "decline_reasons": [
            {"candidate": r["candidate_name"], "reason": r["decline_reason"]}
            for r in declined if r.get("decline_reason")
        ],
    }


@router.get("/candidates.csv")
async def candidates_csv(
    status: Optional[str] = Query(None, description="Filter by offer status."),
):
    """
    Every workflow as a spreadsheet.

    Emitted with a UTF-8 BOM: without it Excel on Windows reads ₹ and Indian
    names as mojibake, which is where this file is most likely to be opened.
    """
    rows = await _rows()
    if status:
        wanted = status.upper()
        rows = [r for r in rows if r["offer_status"] == wanted]

    columns = list(rows[0].keys()) if rows else ["thread_id", "candidate_name"]

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return Response(
        content="﻿" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="aperture-candidates-{stamp}.csv"',
        },
    )
