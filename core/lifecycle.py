"""
Two-stage documentation lifecycle and its business rules (§10).

Every rule lives here as a pure function over state, so the API, the graph
nodes and the UI all consult ONE implementation. Scattering these checks across
endpoints is how a system ends up letting an Appointment Letter out for a
candidate who declined.

    Candidate selected
          ↓
    Offer Letter released      (Rule 2 — must precede appointment)
          ↓
    Candidate accepts          (Rule 3 — decline blocks, Rule 4)
          ↓
    Appointment Letter released (Rule 6 — never automatic)
          ↓
    Onboarding
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from core.state import (
    AppointmentLetterStatus,
    OfferLetterStatus,
    OnboardingStage,
    SelectionStatus,
)


@dataclass(frozen=True)
class RuleCheck:
    allowed: bool
    reason: str = ""
    rule: str = ""

    def __bool__(self) -> bool:      # so callers can `if check:`
        return self.allowed


def _offer(state: dict[str, Any]) -> dict[str, Any]:
    return state.get("offer_letter") or {}


def _appointment(state: dict[str, Any]) -> dict[str, Any]:
    return state.get("appointment_letter") or {}


def offer_status(state: dict[str, Any]) -> str:
    return _offer(state).get("status") or OfferLetterStatus.NOT_CREATED.value


def appointment_status(state: dict[str, Any]) -> str:
    """
    Derives ELIGIBLE the moment the offer is accepted, even before any
    appointment record exists. Without this the dashboard reported
    "NOT_ELIGIBLE" while simultaneously offering the Release action — §4
    expects that cell to read "Ready to Release".
    """
    recorded = _appointment(state).get("status")
    accepted = offer_status(state) == OfferLetterStatus.ACCEPTED.value

    # NOT_ELIGIBLE is also the value seeded at trigger time, so a recorded
    # NOT_ELIGIBLE is indistinguishable from "never set". Once the offer is
    # accepted it is stale either way — without this the dashboard showed
    # "Pending" beside an enabled Release button.
    if recorded and recorded != AppointmentLetterStatus.NOT_ELIGIBLE.value:
        return recorded
    if accepted:
        return AppointmentLetterStatus.ELIGIBLE.value
    return AppointmentLetterStatus.NOT_ELIGIBLE.value


def onboarding_stage(state: dict[str, Any]) -> str:
    return state.get("onboarding_stage") or OnboardingStage.NOT_STARTED.value


# ── Rule 1 / 2: releasing the Offer Letter ──────────────────────────────────

def can_release_offer(state: dict[str, Any]) -> RuleCheck:
    if state.get("selection_status") != SelectionStatus.SELECTED.value:
        return RuleCheck(False, "Only a SELECTED candidate can be issued an Offer Letter.", "Rule 1")
    status = offer_status(state)
    if status in (OfferLetterStatus.RELEASED.value, OfferLetterStatus.VIEWED.value):
        return RuleCheck(False, "The Offer Letter has already been released.", "Rule 7")
    if status == OfferLetterStatus.ACCEPTED.value:
        return RuleCheck(False, "This offer has already been accepted.", "Rule 7")
    if status == OfferLetterStatus.DECLINED.value:
        return RuleCheck(False, "This offer was declined and cannot be re-released.", "Rule 4")

    # An auto-send already holds this dispatch. Releasing manually would resume
    # the graph past a queue email_node deliberately skips, sending nothing and
    # routing the thread to END — silently cancelling the scheduled send.
    scheduled = next(
        (e for e in state.get("email_queue", [])
         if e.get("template_name") == "offer_letter_email"
         and e.get("status") == "SCHEDULED"),
        None,
    )
    if scheduled:
        when = (scheduled.get("scheduled_for") or "").replace("T", " ")[:16]
        return RuleCheck(
            False,
            f"Auto-send is already scheduled{' for ' + when if when else ''}.",
            "Rule 7",
        )

    return RuleCheck(True)


# ── Candidate responses ─────────────────────────────────────────────────────

def can_respond_to_offer(state: dict[str, Any]) -> RuleCheck:
    """Accept/decline is only meaningful on a live, released offer."""
    status = offer_status(state)
    if status in (OfferLetterStatus.NOT_CREATED.value, OfferLetterStatus.DRAFT.value):
        return RuleCheck(False, "This offer has not been released yet.", "Rule 2")
    if status == OfferLetterStatus.ACCEPTED.value:
        return RuleCheck(False, "You have already accepted this offer.")
    if status == OfferLetterStatus.DECLINED.value:
        return RuleCheck(False, "You have already declined this offer.")
    if status == OfferLetterStatus.EXPIRED.value:
        return RuleCheck(False, "This offer has expired. Please contact HR.")
    return RuleCheck(True)


def is_offer_expired(state: dict[str, Any], now: datetime | None = None) -> bool:
    expires = _offer(state).get("expires_at")
    if not expires:
        return False
    try:
        deadline = datetime.fromisoformat(expires)
    except ValueError:
        return False
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    return (now or datetime.now(timezone.utc)) > deadline


# ── Rules 2, 3, 4, 6: releasing the Appointment Letter ──────────────────────

def can_release_appointment(state: dict[str, Any]) -> RuleCheck:
    """
    The gate the whole spec turns on. Checked in dependency order so the
    message names the earliest unmet prerequisite rather than a later symptom.
    """
    if state.get("selection_status") != SelectionStatus.SELECTED.value:
        return RuleCheck(False, "Only a SELECTED candidate can be appointed.", "Rule 1")

    status = offer_status(state)

    if status in (OfferLetterStatus.NOT_CREATED.value, OfferLetterStatus.DRAFT.value):
        return RuleCheck(
            False,
            "An Offer Letter must be released before an Appointment Letter.",
            "Rule 2",
        )
    if status == OfferLetterStatus.DECLINED.value:
        return RuleCheck(
            False,
            "The candidate declined the offer, so no Appointment Letter can be issued.",
            "Rule 4",
        )
    if status == OfferLetterStatus.EXPIRED.value:
        return RuleCheck(False, "The Offer Letter expired before it was accepted.", "Rule 4")
    if status in (OfferLetterStatus.RELEASED.value, OfferLetterStatus.VIEWED.value):
        return RuleCheck(
            False,
            "Waiting for the candidate to accept the Offer Letter.",
            "Rule 3",
        )
    if status != OfferLetterStatus.ACCEPTED.value:
        return RuleCheck(False, f"Unexpected offer status: {status}", "Rule 3")

    if appointment_status(state) == AppointmentLetterStatus.RELEASED.value:
        return RuleCheck(False, "The Appointment Letter has already been released.", "Rule 7")

    return RuleCheck(True)


# ── Rule 5: candidate visibility ────────────────────────────────────────────

def candidate_can_view_offer(state: dict[str, Any]) -> RuleCheck:
    if offer_status(state) in (OfferLetterStatus.NOT_CREATED.value, OfferLetterStatus.DRAFT.value):
        return RuleCheck(False, "This document is not available.", "Rule 5")
    return RuleCheck(True)


def candidate_can_view_appointment(state: dict[str, Any]) -> RuleCheck:
    """
    A DRAFT appointment letter exists on the server the moment the offer is
    accepted, so HR can review it. It must stay invisible to the candidate
    until RELEASED — this check is the only thing standing between the two.
    """
    if appointment_status(state) != AppointmentLetterStatus.RELEASED.value:
        return RuleCheck(
            False,
            "Your Appointment Letter has not been released yet.",
            "Rule 5",
        )
    return RuleCheck(True)


# ── §19: may we place a voice follow-up call? ───────────────────────────────

def can_call_candidate(
    state: dict[str, Any],
    call_type: str = "INITIAL",
    now: datetime | None = None,
) -> RuleCheck:
    """
    Every precondition from §19, in dependency order, as one pure function.

    This is re-evaluated immediately before the dial, not only when the call
    was scheduled — the whole point of the delay is that the candidate may act
    during it, and §6 Case 3 requires that an acceptance mid-window cancels the
    call rather than racing it.

    Deliberately checks the OFFER EMAIL, not just the offer status: a thread
    whose dispatch failed never reached the candidate, so calling to ask about
    "the offer letter we sent you" would be a lie.
    """
    from core.voice_state import (
        CallType, FollowupState, final_call_enabled, initial_call_enabled,
        max_attempts, voice_enabled, within_calling_hours,
    )

    if not voice_enabled():
        return RuleCheck(False, "Voice follow-up is disabled.", "Config")

    fu = state.get("offer_followup") or {}

    if fu.get("do_not_contact"):
        return RuleCheck(
            False, "The candidate asked not to be contacted again.", "§11")

    if state.get("selection_status") != SelectionStatus.SELECTED.value:
        return RuleCheck(
            False, "Only a SELECTED candidate is called — never a rejection.", "§4")

    status = offer_status(state)
    if status in (OfferLetterStatus.NOT_CREATED.value, OfferLetterStatus.DRAFT.value):
        return RuleCheck(False, "The Offer Letter has not been released.", "§4")
    if status == OfferLetterStatus.ACCEPTED.value:
        return RuleCheck(False, "The candidate has already accepted the offer.", "§6 Case 3")
    if status == OfferLetterStatus.DECLINED.value:
        return RuleCheck(False, "The candidate has already declined the offer.", "§6")
    if status == OfferLetterStatus.EXPIRED.value or is_offer_expired(state, now):
        # Calling about a dead offer invites a promise we cannot keep.
        return RuleCheck(False, "The Offer Letter has expired.", "§19")

    offer_reached_candidate = any(
        e.get("template_name") == "offer_letter_email" and e.get("status") == "SENT"
        for e in state.get("email_queue", [])
    )
    if not offer_reached_candidate:
        return RuleCheck(
            False, "The Offer Letter email was never successfully dispatched.", "§19")

    # §3 — the number must come from this candidate's own record.
    if not state.get("candidate_phone"):
        return RuleCheck(
            False, "No phone number was captured for this candidate.", "§3")

    if call_type == CallType.INITIAL.value and not initial_call_enabled():
        return RuleCheck(False, "Initial calls are disabled.", "Config")
    if call_type == CallType.FINAL.value and not final_call_enabled():
        return RuleCheck(False, "Final calls are disabled.", "Config")

    if fu.get("state") in (
        FollowupState.INITIAL_CALL_IN_PROGRESS.value,
        FollowupState.FINAL_CALL_IN_PROGRESS.value,
    ):
        return RuleCheck(False, "A call to this candidate is already in progress.", "§15")
    if fu.get("state") == FollowupState.CLOSED.value:
        return RuleCheck(False, "The follow-up workflow is already closed.", "§10")

    if int(fu.get("attempts") or 0) >= max_attempts():
        return RuleCheck(
            False,
            f"All {max_attempts()} dial attempts for this call have been used.",
            "§11",
        )

    if not within_calling_hours(now):
        return RuleCheck(
            False, "Outside permitted calling hours — deferred, not cancelled.",
            "Calling hours")

    return RuleCheck(True)


def can_start_onboarding(state: dict[str, Any]) -> RuleCheck:
    if appointment_status(state) != AppointmentLetterStatus.RELEASED.value:
        return RuleCheck(False, "Release the Appointment Letter before onboarding begins.", "Rule 2")
    if onboarding_stage(state) == OnboardingStage.COMPLETED.value:
        return RuleCheck(False, "Onboarding is already complete.")
    return RuleCheck(True)


# ── Dashboard projection (§4) ───────────────────────────────────────────────

def stage_summary(state: dict[str, Any]) -> list[dict[str, Any]]:
    """
    The four-row Stage / Status / Action table from §4, derived in one place so
    the HR console and the candidate view can never disagree about progress.
    """
    # Checkpoints may hold either the enum or its value depending on how the
    # state was written; normalise so the dashboard never shows
    # "SelectionStatus.SELECTED".
    raw_sel = state.get("selection_status") or SelectionStatus.PENDING
    sel = raw_sel.value if isinstance(raw_sel, SelectionStatus) else str(raw_sel)
    o_status = offer_status(state)
    a_status = appointment_status(state)
    ob = onboarding_stage(state)

    offer_actions: list[str] = []
    if can_release_offer(state):
        offer_actions.append("RELEASE_OFFER")
    if o_status not in (OfferLetterStatus.NOT_CREATED.value, OfferLetterStatus.DRAFT.value):
        offer_actions += ["VIEW_OFFER", "DOWNLOAD_OFFER"]

    appt_actions: list[str] = []
    if can_release_appointment(state):
        appt_actions.append("RELEASE_APPOINTMENT")
    if a_status == AppointmentLetterStatus.RELEASED.value:
        appt_actions += ["VIEW_APPOINTMENT", "DOWNLOAD_APPOINTMENT"]

    onboarding_actions = ["START_ONBOARDING"] if can_start_onboarding(state) else []

    return [
        {
            "stage": "Selection",
            "status": sel,
            "actions": [],
            "blocked_reason": "",
        },
        {
            "stage": "Offer Letter",
            "status": o_status,
            "actions": offer_actions,
            "blocked_reason": "" if offer_actions else can_release_offer(state).reason,
        },
        {
            "stage": "Appointment Letter",
            "status": a_status,
            "actions": appt_actions,
            "blocked_reason": "" if appt_actions else can_release_appointment(state).reason,
        },
        {
            "stage": "Onboarding",
            "status": ob,
            "actions": onboarding_actions,
            "blocked_reason": "" if onboarding_actions else can_start_onboarding(state).reason,
        },
    ]


def hr_notifications(state: dict[str, Any], thread_id: str) -> list[dict[str, Any]]:
    """
    §3 — HR is notified only once the offer is ACCEPTED, never on release.
    Derived from state rather than stored, so it cannot go stale or fire twice.
    """
    name = state.get("candidate_name", "The candidate")
    role = state.get("designation") or state.get("role_title") or "the role"

    # A verbal yes is not an acceptance (§8 Scenario A), so it cannot advance
    # the lifecycle — but HR must still learn about it, or the intent dies in a
    # call record nobody reads while the candidate waits for someone to act.
    fu = state.get("offer_followup") or {}
    verbal = fu.get("last_intent") in (
        "ACCEPTED_INTENT", "FINAL_ACCEPTANCE_INTENT",
    )
    if verbal and offer_status(state) not in (
        OfferLetterStatus.ACCEPTED.value, OfferLetterStatus.DECLINED.value,
    ):
        return [{
            "id": f"{thread_id}:verbal_acceptance",
            "kind": "VERBAL_ACCEPTANCE",
            "title": "Verbal acceptance — not yet confirmed",
            "body": (
                f"{name} said on the follow-up call that they intend to accept "
                f"the offer for {role}, but has not yet confirmed through the "
                f"portal. The offer is not accepted until they do."
            ),
            "thread_id": thread_id,
            "candidate_name": name,
            "role_title": role,
            "action_label": "Open workflow",
            "action_href": f"/thread/{thread_id}",
            "created_at": fu.get("closed_at"),
        }]

    if offer_status(state) != OfferLetterStatus.ACCEPTED.value:
        return []
    if appointment_status(state) == AppointmentLetterStatus.RELEASED.value:
        return []

    return [{
        "id": f"{thread_id}:appointment_ready",
        "kind": "APPOINTMENT_LETTER_READY",
        "title": "Appointment Letter Ready",
        "body": (
            f"{name} has accepted the Offer Letter for the position of {role}. "
            f"You can now review and release the Appointment Letter."
        ),
        "thread_id": thread_id,
        "candidate_name": name,
        "role_title": role,
        "action_label": "Open Appointment Letter",
        "action_href": f"/thread/{thread_id}?stage=appointment",
        "created_at": _appointment(state).get("generated_at")
                      or _offer(state).get("responded_at"),
    }]
