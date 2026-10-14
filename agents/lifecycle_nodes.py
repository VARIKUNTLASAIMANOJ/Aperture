"""
Post-offer lifecycle nodes (§2, §11).

    email_node (offer sent)
        ↓  interrupt — thread parks here for days
    offer_gate            ← resumed when the candidate accepts or declines
        ↓  ACCEPTED
    appointment_node      ← drafts the Appointment Letter for HR review
        ↓  interrupt — HR's "Release Appointment Letter" resumes it
    appointment_dispatch  ← the same email_node function, second registration
        ↓
    onboarding_node
        ↓
    END

The gate is a real graph node behind `interrupt_before`, which is what lets a
thread wait indefinitely for an external human event without a polling loop —
the same mechanism the HR approval gate already uses.
"""

from __future__ import annotations

from datetime import datetime, timezone

from langchain_core.runnables import RunnableConfig

from core.india.documents import render_appointment_letter
from core.lifecycle import can_release_appointment, offer_status
from core.state import (
    AppointmentLetterStatus,
    ApprovalStatus,
    EmailQueueItem,
    NodeStatus,
    OfferLetterStatus,
    OnboardingStage,
    OnboardingState,
)
from utils.audit import emit_audit


def _queue_status(state: OnboardingState, template: str) -> set[str]:
    return {
        e.get("status") for e in state.get("email_queue", [])
        if e.get("template_name") == template
    }


def route_after_dispatch(state: OnboardingState) -> str:
    """
    Where the workflow goes once email_node has run.

    Three outcomes, and the middle one is the reason this function changed:

    * SENT      → offer_gate, to await the candidate's decision.
    * FAILED    → back to email_node. Because email_node sits behind
                  `interrupt_before`, routing here PARKS the thread at the gate
                  instead of re-running it, so HR can correct the address and
                  retry. Previously this returned "__end__": a bounced offer
                  left the workflow at a terminal node with no way back in, and
                  every Resend rejection permanently stranded a candidate.
    * neither   → "__end__". A rejection notice, or a thread with no offer
                  email at all, is genuinely finished. Parking it at offer_gate
                  would leave it waiting for a decision that cannot come.
    """
    # HR rejected the dispatch: the queue was cancelled on purpose and there is
    # nothing to retry. Checked before node_status, which is COMPLETE here.
    if state.get("approval_status") == ApprovalStatus.REJECTED:
        return "__end__"

    statuses = _queue_status(state, "offer_letter_email")
    if "SENT" in statuses:
        return "offer_gate"

    # Anything still awaiting dispatch keeps the thread AT the gate.
    # PENDING matters as much as FAILED: `aupdate_state` re-evaluates this
    # router, so the retry endpoint resetting FAILED → PENDING would otherwise
    # route the thread straight to END and undo the resume it was setting up.
    if statuses & {"FAILED", "PENDING", "SCHEDULED"}:
        return "email_node"
    return "__end__"


def route_after_appointment_dispatch(state: OnboardingState) -> str:
    """
    Same reasoning for the Appointment Letter.

    A failed appointment dispatch used to fall through to onboarding_node,
    which recorded ONBOARDING_DEFERRED and ended — leaving an accepted
    candidate with no letter and no route to one.
    """
    if state.get("approval_status") == ApprovalStatus.REJECTED:
        return "onboarding_node"

    statuses = _queue_status(state, "appointment_letter_email")
    if "SENT" not in statuses and statuses & {"FAILED", "PENDING", "SCHEDULED"}:
        return "appointment_dispatch"
    return "onboarding_node"


async def offer_gate(state: OnboardingState, config: RunnableConfig) -> dict:
    """
    Records the candidate's decision. Reached only after the API has already
    written the ACCEPTED/DECLINED status, so this node reports rather than
    decides — keeping the authoritative transition in one place (the API,
    which validates the token) instead of two.
    """
    status = offer_status(dict(state))
    accepted = status == OfferLetterStatus.ACCEPTED.value

    return {
        "current_node": "offer_gate",
        "node_status": NodeStatus.COMPLETE,
        # Rule 6: acceptance makes the appointment ELIGIBLE, never RELEASED.
        "appointment_letter": {
            "document_type": "APPOINTMENT_LETTER",
            "status": (AppointmentLetterStatus.ELIGIBLE.value if accepted
                       else AppointmentLetterStatus.NOT_ELIGIBLE.value),
        },
        "audit_log": emit_audit(
            node="offer_gate",
            event="OFFER_RESPONSE_RECORDED",
            payload_summary=(
                f"Candidate {state.get('candidate_id')} {status.lower()} the Offer Letter."
                + (" Appointment Letter is now eligible for release."
                   if accepted else " No Appointment Letter will be issued.")
            ),
            actor="CANDIDATE",
        ),
    }


def route_after_offer_gate(state: OnboardingState) -> str:
    """Rule 4: anything other than acceptance ends the workflow."""
    if offer_status(dict(state)) == OfferLetterStatus.ACCEPTED.value:
        return "appointment_node"
    return "__end__"


async def appointment_node(state: OnboardingState, config: RunnableConfig) -> dict:
    """
    Drafts the Appointment Letter. Runs on acceptance so HR has something to
    review, but leaves it DRAFT — the candidate cannot see it (Rule 5) and it
    is not released until HR acts (Rule 6).
    """
    candidate_id = state.get("candidate_id", "UNKNOWN")
    snapshot = dict(state)

    # Defence in depth: the API gates this too, but a graph resumed by any
    # other path must not be able to skip the prerequisite chain.
    allowed = can_release_appointment(snapshot)
    if not allowed and allowed.rule in ("Rule 1", "Rule 2", "Rule 4"):
        return {
            "current_node": "appointment_node",
            "node_status": NodeStatus.ERROR,
            "error_message": f"{allowed.rule}: {allowed.reason}",
            "audit_log": emit_audit(
                node="appointment_node",
                event="APPOINTMENT_BLOCKED",
                payload_summary=f"{candidate_id}: blocked — {allowed.reason}",
            ),
        }

    try:
        html, doc_no = render_appointment_letter(snapshot)
        now = datetime.now(timezone.utc).isoformat()

        email: EmailQueueItem = {
            "template_name": "appointment_letter_email",
            "recipient_email": state.get("candidate_email", ""),
            "recipient_name": state.get("candidate_name", ""),
            "variables": {
                "candidate_name": state.get("candidate_name", ""),
                "designation": state.get("designation") or state.get("role_title", ""),
                "appointment_letter_html": html,
                "document_number": doc_no,
                "thread_id": (config or {}).get("configurable", {}).get("thread_id", ""),
                "action_token": state.get("candidate_access_token", ""),
            },
            "status": "PENDING",
            "message_id": None,
        }

        return {
            "current_node": "appointment_node",
            "node_status": NodeStatus.COMPLETE,
            "appointment_letter": {
                **(state.get("appointment_letter") or {}),
                "document_type": "APPOINTMENT_LETTER",
                "status": AppointmentLetterStatus.DRAFT.value,
                "html": html,
                "generated_at": now,
                "document_number": doc_no,
            },
            "email_queue": [*state.get("email_queue", []), email],
            "error_message": None,
            "audit_log": emit_audit(
                node="appointment_node",
                event="APPOINTMENT_LETTER_GENERATED",
                payload_summary=(
                    f"Appointment Letter {doc_no} drafted for {candidate_id}. "
                    f"Awaiting HR release — not visible to the candidate."
                ),
            ),
        }

    except Exception as exc:
        return {
            "current_node": "appointment_node",
            "node_status": NodeStatus.ERROR,
            "error_message": str(exc),
            "audit_log": emit_audit(
                node="appointment_node",
                event="APPOINTMENT_LETTER_ERROR",
                payload_summary=f"{candidate_id}: appointment generation failed — {exc}",
            ),
        }


def route_after_appointment(state: OnboardingState) -> str:
    if state.get("node_status") == NodeStatus.ERROR:
        return "error_handler"
    return "appointment_dispatch"


async def onboarding_node(state: OnboardingState, config: RunnableConfig) -> dict:
    """Marks the Appointment Letter released and opens onboarding."""
    now = datetime.now(timezone.utc).isoformat()
    appt = dict(state.get("appointment_letter") or {})
    dispatched = any(
        e.get("template_name") == "appointment_letter_email" and e.get("status") == "SENT"
        for e in state.get("email_queue", [])
    )

    appt.update({
        "status": (AppointmentLetterStatus.RELEASED.value if dispatched
                   else appt.get("status") or AppointmentLetterStatus.DRAFT.value),
        "released_at": now if dispatched else appt.get("released_at"),
    })

    return {
        "current_node": "onboarding_node",
        "node_status": NodeStatus.COMPLETE,
        "appointment_letter": appt,
        "onboarding_stage": (OnboardingStage.IN_PROGRESS.value if dispatched
                             else OnboardingStage.NOT_STARTED.value),
        "audit_log": emit_audit(
            node="onboarding_node",
            event="ONBOARDING_STARTED" if dispatched else "ONBOARDING_DEFERRED",
            payload_summary=(
                f"Appointment Letter released to {state.get('candidate_id')}; "
                f"onboarding is now in progress."
                if dispatched else
                "Appointment Letter was not dispatched; onboarding not started."
            ),
        ),
    }
