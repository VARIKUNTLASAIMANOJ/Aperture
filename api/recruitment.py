"""
Two-stage recruitment API (§1–§5, §10).

Split out of api/main.py deliberately: the offer/appointment lifecycle is a
coherent subsystem with its own rules, and folding ~10 more endpoints into an
already 600-line module would bury them.

Every state-changing endpoint consults core.lifecycle for its precondition, so
the rules live in exactly one place and the HTTP layer only translates a
RuleCheck into a status code.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, EmailStr, Field

from core.india.compensation import (
    available_financial_years, default_financial_year, format_inr, fy_config, to_lpa,
)
from core.india.locations import CITIES, STATES, cities_for, is_valid_city, is_valid_state
from core.lifecycle import (
    can_release_appointment, can_release_offer, can_respond_to_offer,
    candidate_can_view_appointment, candidate_can_view_offer,
    appointment_status, hr_notifications, is_offer_expired, offer_status,
    onboarding_stage, stage_summary,
)
from core.state import AppointmentLetterStatus, OfferLetterStatus
from core.voice_flow import cancel
from utils.audit import emit_audit
from utils.tokens import PURPOSE_OFFER, TokenError, verify_token

#: HR-side endpoints. Mounted behind `require_operator` in api.main — these
#: release employment documents and must never be reachable unauthenticated.
router = APIRouter()

#: Candidate-side endpoints. Deliberately a SEPARATE router with no operator
#: auth: a candidate has no account. Every one of these is guarded instead by
#: the signed per-thread token (`_guard_token`), which is what makes Rule 5 an
#: access control. Keeping them in their own router means the HR router can be
#: blanket-protected without accidentally locking the candidate out.
candidate_router = APIRouter()

# Injected by main.py so this module does not import the app and create a cycle.
_get_graph: Callable[[], Any] | None = None
_list_threads: Callable[[], Any] | None = None


def bind(get_graph: Callable[[], Any], list_threads: Callable[[], Any]) -> None:
    global _get_graph, _list_threads
    _get_graph, _list_threads = get_graph, list_threads


def _graph():
    if _get_graph is None or _get_graph() is None:
        raise HTTPException(status_code=503, detail="Graph not initialised yet.")
    return _get_graph()


async def _load(thread_id: str) -> dict:
    snapshot = await _graph().aget_state({"configurable": {"thread_id": thread_id}})
    if not snapshot or not snapshot.values:
        raise HTTPException(status_code=404, detail=f"No candidate found for {thread_id}")
    return dict(snapshot.values)


def _enforce(check, *, status_code: int = 409) -> None:
    """Turn a RuleCheck into an HTTP error carrying the rule that blocked it."""
    if not check:
        raise HTTPException(
            status_code=status_code,
            detail={"message": check.reason, "rule": check.rule or None},
        )


def _guard_token(token: str, thread_id: str) -> None:
    try:
        verify_token(token, thread_id, PURPOSE_OFFER)
    except TokenError as exc:
        # 403, not 404: the thread exists, this caller may not read it.
        raise HTTPException(status_code=403, detail=str(exc)) from None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ═══════════════════════════════════════════════════════════════════════════
# Reference data — drives every dropdown so the UI cannot invent locations
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/meta/locations")
async def get_locations():
    return {
        "states": [
            {"code": s.code, "name": s.name, "kind": s.kind,
             "levies_professional_tax": s.levies_pt,
             "cities": list(cities_for(s.code))}
            for s in STATES
        ],
        "total_states": sum(1 for s in STATES if s.kind == "STATE"),
        "total_union_territories": sum(1 for s in STATES if s.kind == "UT"),
        "total_cities": sum(len(c) for c in CITIES.values()),
    }


@router.get("/meta/statutory")
async def get_statutory(financial_year: Optional[str] = None):
    """Surfaces `verified_on` so a stale configuration is visible, not silent."""
    fy = financial_year or default_financial_year()
    cfg = fy_config(fy)
    return {
        "financial_year": fy,
        "label": cfg.get("label"),
        "verified_on": cfg.get("verified_on"),
        "source_note": cfg.get("source"),
        "available_financial_years": available_financial_years(),
        "epf": cfg["epf"], "esi": cfg["esi"], "gratuity": cfg["gratuity"],
        "professional_tax": cfg["professional_tax"],
        "regimes": {
            "NEW": cfg["income_tax"]["new_regime"],
            "OLD": cfg["income_tax"]["old_regime"],
        },
    }


class CtcPreviewRequest(BaseModel):
    total_ctc: float = Field(gt=0)
    state_code: str
    city: str
    tax_regime: str = "NEW"
    financial_year: Optional[str] = None
    employment_type: str = "FULL_TIME"
    basic_pct: Optional[float] = None
    performance_bonus: float = 0.0


@router.post("/meta/ctc-preview")
async def ctc_preview(req: CtcPreviewRequest):
    """Live salary breakup for the HR form, before any workflow is started."""
    from dataclasses import asdict

    from core.india.compensation import build_salary_breakup

    if not is_valid_state(req.state_code):
        raise HTTPException(status_code=422, detail=f"Unknown state code '{req.state_code}'.")
    if req.city and not is_valid_city(req.state_code, req.city):
        raise HTTPException(
            status_code=422,
            detail=f"{req.city} is not a valid work location in {req.state_code}.",
        )
    try:
        b = build_salary_breakup(
            total_ctc=req.total_ctc, state_code=req.state_code, city=req.city,
            tax_regime=req.tax_regime, financial_year=req.financial_year,
            basic_pct=req.basic_pct, performance_bonus=req.performance_bonus,
            employment_type=req.employment_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    data = asdict(b)
    data["formatted"] = {k: format_inr(v) for k, v in data.items() if isinstance(v, (int, float))}
    data["ctc_lpa"] = to_lpa(b.total_ctc)
    return data


# ═══════════════════════════════════════════════════════════════════════════
# HR — Offer Letter (§1)
# ═══════════════════════════════════════════════════════════════════════════

class ReleaseRequest(BaseModel):
    released_by: str
    notes: Optional[str] = None


@router.post("/onboarding/{thread_id}/offer/release")
async def release_offer(thread_id: str, req: ReleaseRequest):
    """
    Rule 1 / Rule 2. The Offer Letter is already drafted by offer_node; this
    approves its dispatch and resumes the graph through email_node.

    The RELEASED transition itself belongs to email_node, which owns the moment
    the mail actually leaves. Writing it here first meant a failed dispatch
    still left the letter marked RELEASED — HR saw "Released", the candidate
    got nothing, and the thread had already routed to END. So this endpoint
    records the approval, resumes, and then reports whatever actually happened.
    """
    state = await _load(thread_id)
    _enforce(can_release_offer(state))

    cfg = {"configurable": {"thread_id": thread_id}}
    doc_no = (state.get("offer_letter") or {}).get("document_number")

    await _graph().aupdate_state(cfg, {
        "approval_status": "APPROVED",
        "approver_email": req.released_by,
        "approver_notes": req.notes,
        "audit_log": emit_audit(
            node="offer_release", event="OFFER_RELEASE_APPROVED",
            payload_summary=(
                f"Offer Letter {doc_no} approved for release to "
                f"{state.get('candidate_name')} by {req.released_by}."
            ),
            actor=f"HR_{req.released_by}",
        ),
    })
    await _graph().ainvoke(None, config=cfg)

    after = await _load(thread_id)
    status = offer_status(after)

    if status in (OfferLetterStatus.NOT_CREATED.value, OfferLetterStatus.DRAFT.value):
        # Dispatch failed. Resend records the reason on the queue item.
        reason = next(
            (i.get("message_id") for i in after.get("email_queue", [])
             if i.get("template_name") == "offer_letter_email"
             and i.get("status") == "FAILED"),
            "the email provider rejected the message",
        )
        raise HTTPException(status_code=502, detail={
            "message": f"The Offer Letter was not sent, so it stays unreleased — {reason}",
            "rule": None,
        })

    return {
        "thread_id": thread_id,
        "offer_status": status,
        "document_number": doc_no,
        "message": "Offer Letter released to the candidate.",
    }


# ═══════════════════════════════════════════════════════════════════════════
# HR — Appointment Letter (§2)
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/onboarding/{thread_id}/appointment/release")
async def release_appointment(thread_id: str, req: ReleaseRequest):
    """Rules 2, 3, 4, 6 — the gate the whole specification turns on."""
    state = await _load(thread_id)
    _enforce(can_release_appointment(state))

    cfg = {"configurable": {"thread_id": thread_id}}
    appt = dict(state.get("appointment_letter") or {})
    appt.update({
        "status": AppointmentLetterStatus.RELEASED.value,
        "released_at": _now(),
        "released_by": req.released_by,
    })

    await _graph().aupdate_state(cfg, {
        "appointment_letter": appt,
        "audit_log": emit_audit(
            node="appointment_release", event="APPOINTMENT_LETTER_RELEASED",
            payload_summary=(
                f"Appointment Letter {appt.get('document_number')} released to "
                f"{state.get('candidate_name')} by {req.released_by}."
            ),
            actor=f"HR_{req.released_by}",
        ),
    })
    # Resumes appointment_dispatch → onboarding_node.
    await _graph().ainvoke(None, config=cfg)

    return {
        "thread_id": thread_id,
        "appointment_status": AppointmentLetterStatus.RELEASED.value,
        "document_number": appt.get("document_number"),
        "message": "Appointment Letter released. Onboarding can begin.",
    }


# ═══════════════════════════════════════════════════════════════════════════
# HR — recovering a failed dispatch
# ═══════════════════════════════════════════════════════════════════════════

class RetryDispatchRequest(BaseModel):
    retried_by: str
    #: Most dispatch failures are a bad address ("Invalid `to` field"), so the
    #: retry is useless without the ability to correct it. Changing it here
    #: updates the candidate record too, not just this one queued email —
    #: otherwise the next letter would bounce the same way.
    corrected_email: Optional[EmailStr] = None


@router.post("/onboarding/{thread_id}/dispatch/retry")
async def retry_dispatch(thread_id: str, req: RetryDispatchRequest):
    """
    Re-attempt a dispatch that failed, optionally against a corrected address.

    The thread is parked at its dispatch gate (email_node or
    appointment_dispatch) because route_after_dispatch sends failures back
    there rather than to END. This resets the failed items to PENDING and
    resumes, so the retry travels the identical send path as the original —
    there is no second dispatch implementation to drift.
    """
    state = await _load(thread_id)
    queue = list(state.get("email_queue") or [])

    failed = [i for i, e in enumerate(queue) if e.get("status") == "FAILED"]
    if not failed:
        raise HTTPException(
            status_code=409,
            detail={"message": "Nothing to retry — this thread has no failed email.",
                    "rule": None},
        )

    new_email = str(req.corrected_email) if req.corrected_email else None
    patch: dict[str, Any] = {}

    for i in failed:
        item = dict(queue[i])
        item.update({
            "status": "PENDING",
            # Clear the provider's error so a second failure cannot be mistaken
            # for the first one still being displayed.
            "message_id": None,
            "sent_at": None,
            "dispatch_mode": "MANUAL",
        })
        if new_email:
            item["recipient_email"] = new_email
        queue[i] = item

    patch["email_queue"] = queue
    patch["approval_status"] = "APPROVED"
    patch["approver_email"] = req.retried_by

    if new_email:
        patch["candidate_email"] = new_email

    old_email = state.get("candidate_email")
    patch["audit_log"] = emit_audit(
        node="dispatch_retry", event="DISPATCH_RETRIED",
        payload_summary=(
            f"{req.retried_by} retried {len(failed)} failed email(s)"
            + (f"; recipient corrected from {old_email} to {new_email}."
               if new_email and new_email != old_email else ".")
        ),
        actor=f"HR_{req.retried_by}",
    )

    cfg = {"configurable": {"thread_id": thread_id}}
    await _graph().aupdate_state(cfg, patch)
    await _graph().ainvoke(None, config=cfg)

    after = await _load(thread_id)
    sent = [e for e in after.get("email_queue", []) if e.get("status") == "SENT"]
    still_failed = [e for e in after.get("email_queue", []) if e.get("status") == "FAILED"]

    if still_failed and not sent:
        # Report the provider's reason rather than a generic failure — the
        # operator needs to know whether to fix the address again or give up.
        raise HTTPException(status_code=502, detail={
            "message": (
                "The retry failed again: "
                f"{still_failed[-1].get('message_id') or 'the provider rejected it'}"
            ),
            "rule": None,
        })

    return {
        "thread_id": thread_id,
        "retried": len(failed),
        "offer_status": offer_status(after),
        "appointment_status": appointment_status(after),
        "message": f"{len(failed)} email(s) re-sent successfully.",
    }


# ═══════════════════════════════════════════════════════════════════════════
# HR — dashboard projections (§3, §4)
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/onboarding/{thread_id}/stages")
async def get_stages(thread_id: str):
    state = await _load(thread_id)
    return {
        "thread_id": thread_id,
        "candidate_name": state.get("candidate_name"),
        "designation": state.get("designation") or state.get("role_title"),
        "stages": stage_summary(state),
        "offer_status": offer_status(state),
        "appointment_status": appointment_status(state),
        "onboarding_stage": onboarding_stage(state),
    }


@router.get("/onboarding/notifications")
async def get_notifications():
    """§3 — derived from state, so it can never fire early or go stale."""
    items: list[dict] = []
    for tid in await _list_threads():
        try:
            snapshot = await _graph().aget_state({"configurable": {"thread_id": tid}})
            if snapshot and snapshot.values:
                items.extend(hr_notifications(dict(snapshot.values), tid))
        except Exception:
            continue
    return {"notifications": items, "unread_count": len(items)}


# ═══════════════════════════════════════════════════════════════════════════
# Candidate — token-guarded (§5, Rule 5)
# ═══════════════════════════════════════════════════════════════════════════

@candidate_router.get("/candidate/{thread_id}/status")
async def candidate_status(thread_id: str, token: str = Query(...)):
    """The candidate's own progression view. Never leaks an unreleased letter."""
    _guard_token(token, thread_id)
    state = await _load(thread_id)

    o_status = offer_status(state)
    if o_status in (OfferLetterStatus.RELEASED.value, OfferLetterStatus.VIEWED.value) \
            and is_offer_expired(state):
        o_status = OfferLetterStatus.EXPIRED.value

    a_released = appointment_status(state) == AppointmentLetterStatus.RELEASED.value
    breakup = state.get("salary_breakup") or {}
    offer = state.get("offer_letter") or {}

    return {
        "candidate_name": state.get("candidate_name"),
        "designation": state.get("designation") or state.get("role_title"),
        "department": state.get("department"),
        "work_location": {
            "city": state.get("work_location_city"),
            "state": state.get("work_location_state"),
        },
        "joining_date": state.get("start_date"),
        "ctc": {
            "annual": breakup.get("total_ctc"),
            "formatted": format_inr(float(breakup.get("total_ctc") or 0)),
            "lpa": to_lpa(float(breakup.get("total_ctc") or 0)),
        } if breakup else None,
        "application_status": state.get("selection_status"),
        "offer": {
            "status": o_status,
            "document_number": offer.get("document_number"),
            "released_at": offer.get("released_at"),
            "expires_at": offer.get("expires_at"),
            "responded_at": offer.get("responded_at"),
            "can_respond": bool(can_respond_to_offer(state)),
        },
        # Only the STATUS of the appointment letter is exposed while it is
        # unreleased — never its number, date or body (Rule 5).
        "appointment": {
            "status": "RELEASED" if a_released else "PENDING_FROM_HR",
            "document_number": (state.get("appointment_letter") or {}).get("document_number")
                               if a_released else None,
            "released_at": (state.get("appointment_letter") or {}).get("released_at")
                           if a_released else None,
        },
        "onboarding": {"status": onboarding_stage(state)},
    }


@candidate_router.get("/candidate/{thread_id}/offer/document")
async def candidate_offer_document(thread_id: str, token: str = Query(...)):
    _guard_token(token, thread_id)
    state = await _load(thread_id)
    _enforce(candidate_can_view_offer(state), status_code=403)

    offer = dict(state.get("offer_letter") or {})
    # First open flips RELEASED → VIEWED, giving HR read-receipt visibility.
    if offer.get("status") == OfferLetterStatus.RELEASED.value:
        offer.update({"status": OfferLetterStatus.VIEWED.value, "viewed_at": _now()})
        await _graph().aupdate_state({"configurable": {"thread_id": thread_id}}, {
            "offer_letter": offer,
            "audit_log": emit_audit(
                node="candidate", event="OFFER_LETTER_VIEWED",
                payload_summary=f"{state.get('candidate_name')} opened the Offer Letter.",
                actor="CANDIDATE",
            ),
        })

    return {
        "document_type": "OFFER_LETTER",
        "document_number": offer.get("document_number"),
        "status": offer.get("status"),
        "html": offer.get("html"),
        "expires_at": offer.get("expires_at"),
    }


@candidate_router.get("/candidate/{thread_id}/appointment/document")
async def candidate_appointment_document(thread_id: str, token: str = Query(...)):
    """Scenario D — must refuse until HR releases it."""
    _guard_token(token, thread_id)
    state = await _load(thread_id)
    _enforce(candidate_can_view_appointment(state), status_code=403)

    appt = dict(state.get("appointment_letter") or {})
    if appt.get("status") == AppointmentLetterStatus.RELEASED.value and not appt.get("viewed_at"):
        appt["viewed_at"] = _now()
        await _graph().aupdate_state({"configurable": {"thread_id": thread_id}}, {
            "appointment_letter": appt,
            "audit_log": emit_audit(
                node="candidate", event="APPOINTMENT_LETTER_VIEWED",
                payload_summary=f"{state.get('candidate_name')} opened the Appointment Letter.",
                actor="CANDIDATE",
            ),
        })

    return {
        "document_type": "APPOINTMENT_LETTER",
        "document_number": appt.get("document_number"),
        "status": appt.get("status"),
        "html": appt.get("html"),
    }


def _letter_pdf(record: dict, fallback: str) -> Response:
    """Turn a stored letter into a downloadable PDF response."""
    from core.india.pdf import PdfError, html_to_pdf, pdf_filename

    html = (record or {}).get("html")
    if not html:
        raise HTTPException(status_code=404, detail="This document has no body to render.")
    try:
        data = html_to_pdf(html)
    except PdfError as exc:
        # 500, not a corrupt download: a truncated PDF attached to an offer
        # letter is worse than an error the operator can act on.
        raise HTTPException(status_code=500, detail=str(exc)) from None

    name = pdf_filename(record.get("document_number"), fallback)
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/onboarding/{thread_id}/offer/document.pdf")
async def hr_offer_pdf(thread_id: str):
    """HR's own copy. Operator-authenticated via the router dependency."""
    state = await _load(thread_id)
    _enforce(candidate_can_view_offer(state), status_code=404)
    return _letter_pdf(state.get("offer_letter") or {}, "offer-letter")


@router.get("/onboarding/{thread_id}/appointment/document.pdf")
async def hr_appointment_pdf(thread_id: str):
    state = await _load(thread_id)
    appt = state.get("appointment_letter") or {}
    # HR may read the DRAFT — that is the point of the review step — so this
    # deliberately does NOT use candidate_can_view_appointment (Rule 5), which
    # exists to keep the draft from the candidate.
    if not appt.get("html"):
        raise HTTPException(status_code=404, detail="No Appointment Letter has been drafted yet.")
    return _letter_pdf(appt, "appointment-letter")


@candidate_router.get("/candidate/{thread_id}/offer/document.pdf")
async def candidate_offer_pdf(thread_id: str, token: str = Query(...)):
    _guard_token(token, thread_id)
    state = await _load(thread_id)
    _enforce(candidate_can_view_offer(state), status_code=403)
    return _letter_pdf(state.get("offer_letter") or {}, "offer-letter")


@candidate_router.get("/candidate/{thread_id}/appointment/document.pdf")
async def candidate_appointment_pdf(thread_id: str, token: str = Query(...)):
    """Rule 5 applies here exactly as it does to the HTML view."""
    _guard_token(token, thread_id)
    state = await _load(thread_id)
    _enforce(candidate_can_view_appointment(state), status_code=403)
    return _letter_pdf(state.get("appointment_letter") or {}, "appointment-letter")


class OfferResponse(BaseModel):
    reason: Optional[str] = None


@candidate_router.post("/candidate/{thread_id}/offer/accept")
async def accept_offer(thread_id: str, req: OfferResponse, token: str = Query(...)):
    """Rule 3 — acceptance is what makes the Appointment Letter eligible."""
    _guard_token(token, thread_id)
    state = await _load(thread_id)
    _enforce(can_respond_to_offer(state))

    if is_offer_expired(state):
        raise HTTPException(status_code=409, detail={
            "message": "This offer has expired. Please contact HR.", "rule": "Rule 4"})

    cfg = {"configurable": {"thread_id": thread_id}}
    offer = dict(state.get("offer_letter") or {})
    offer.update({"status": OfferLetterStatus.ACCEPTED.value, "responded_at": _now()})

    await _graph().aupdate_state(cfg, {
        "offer_letter": offer,
        # §6 Case 3 — the candidate acted during the follow-up window, so the
        # pending call is cancelled here rather than being refused later by
        # can_call_candidate. Both would prevent the call; closing it now also
        # keeps the dashboard honest about why no call happened.
        "offer_followup": cancel(
            state.get("offer_followup"),
            "The candidate accepted the offer in the portal.",
        ),
        "audit_log": emit_audit(
            node="candidate", event="OFFER_ACCEPTED",
            payload_summary=(
                f"{state.get('candidate_name')} ACCEPTED Offer Letter "
                f"{offer.get('document_number')}. Appointment Letter is now eligible."
            ),
            actor="CANDIDATE",
        ),
    })
    # Resumes offer_gate → appointment_node, which drafts (not releases) the
    # Appointment Letter and parks again for HR.
    await _graph().ainvoke(None, config=cfg)

    return {
        "thread_id": thread_id,
        "offer_status": OfferLetterStatus.ACCEPTED.value,
        "message": "Offer accepted. Your Appointment Letter will follow from HR.",
    }


@candidate_router.post("/candidate/{thread_id}/offer/decline")
async def decline_offer(thread_id: str, req: OfferResponse, token: str = Query(...)):
    """Rule 4 — declining permanently blocks the Appointment Letter."""
    _guard_token(token, thread_id)
    state = await _load(thread_id)
    _enforce(can_respond_to_offer(state))

    cfg = {"configurable": {"thread_id": thread_id}}
    offer = dict(state.get("offer_letter") or {})
    offer.update({
        "status": OfferLetterStatus.DECLINED.value,
        "responded_at": _now(),
        "decline_reason": req.reason,
    })

    await _graph().aupdate_state(cfg, {
        "offer_letter": offer,
        "offer_followup": cancel(
            state.get("offer_followup"),
            "The candidate declined the offer in the portal.",
        ),
        "audit_log": emit_audit(
            node="candidate", event="OFFER_DECLINED",
            payload_summary=(
                f"{state.get('candidate_name')} DECLINED Offer Letter "
                f"{offer.get('document_number')}."
                + (f" Reason: {req.reason}" if req.reason else "")
            ),
            actor="CANDIDATE",
        ),
    })
    await _graph().ainvoke(None, config=cfg)   # offer_gate routes to END

    return {
        "thread_id": thread_id,
        "offer_status": OfferLetterStatus.DECLINED.value,
        "message": "Offer declined. No Appointment Letter will be issued.",
    }
