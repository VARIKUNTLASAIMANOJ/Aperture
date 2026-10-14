"""
§10 state-machine transitions, as pure functions.

Same discipline as core.lifecycle: the scheduler, the API and the tests all
call these, so "what happens after a NO_ANSWER" has exactly one answer. A call
outcome arriving twice must produce the same state as it arriving once.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from core.voice_state import (
    CallOutcome,
    CallType,
    CandidateIntent,
    FollowupState,
    OfferFollowup,
    RETRYABLE_OUTCOMES,
    TERMINAL_INTENTS,
    final_delay_minutes,
    max_attempts,
    next_calling_slot,
    retry_delay_minutes,
)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def arm_initial(now: datetime, delay_minutes: int) -> OfferFollowup:
    """The state email_node writes when the Offer Letter is dispatched."""
    return {
        "state": FollowupState.WAITING_FOR_INITIAL_CALL.value,
        "due_at": _iso(next_calling_slot(now + timedelta(minutes=delay_minutes))),
        "attempts": 0,
        "do_not_contact": False,
        "armed_at": _iso(now),
    }


def is_due(followup: dict[str, Any] | None, now: datetime) -> bool:
    """Whether the scheduler should act on this thread right now."""
    fu = followup or {}
    if fu.get("state") not in (
        FollowupState.WAITING_FOR_INITIAL_CALL.value,
        FollowupState.FOLLOW_UP_PENDING.value,
        FollowupState.FINAL_CALL_PENDING.value,
        FollowupState.INITIAL_CALL_PENDING.value,
    ):
        return False
    due_at = fu.get("due_at")
    if not due_at:
        return False
    try:
        when = datetime.fromisoformat(due_at)
    except ValueError:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return now >= when


def call_type_for(followup: dict[str, Any] | None) -> str:
    """Which call is owed next."""
    state = (followup or {}).get("state")
    if state in (FollowupState.FOLLOW_UP_PENDING.value,
                 FollowupState.FINAL_CALL_PENDING.value,
                 FollowupState.FINAL_CALL_IN_PROGRESS.value):
        return CallType.FINAL.value
    return CallType.INITIAL.value


def mark_in_progress(followup: dict[str, Any] | None, call_type: str,
                     now: datetime) -> OfferFollowup:
    fu = dict(followup or {})
    fu.update({
        "state": (FollowupState.FINAL_CALL_IN_PROGRESS.value
                  if call_type == CallType.FINAL.value
                  else FollowupState.INITIAL_CALL_IN_PROGRESS.value),
        "attempts": int(fu.get("attempts") or 0) + 1,
        "last_call_type": call_type,
        "due_at": None,
    })
    return fu  # type: ignore[return-value]


def advance(
    followup: dict[str, Any] | None,
    *,
    call_type: str,
    outcome: str,
    intent: Optional[str] = None,
    requested_followup_date: Optional[str] = None,
    now: Optional[datetime] = None,
) -> OfferFollowup:
    """
    Compute the next follow-up state from how a call ended.

    Two rules shape everything here:

    §9 — a FINAL call never schedules another one. Whatever the candidate says,
    including "I still need time", the workflow closes. Allowing another
    extension is how a follow-up loop becomes harassment.

    §11 — "nobody answered" is not "the candidate said no". Retryable outcomes
    keep their state and re-arm; only a real conversation produces an intent.
    """
    now = now or datetime.now(timezone.utc)
    fu = dict(followup or {})
    fu["last_call_type"] = call_type
    fu["last_outcome"] = outcome
    if intent:
        fu["last_intent"] = intent

    def close(reason: str) -> OfferFollowup:
        fu.update({
            "state": FollowupState.CLOSED.value,
            "due_at": None,
            "closed_at": _iso(now),
            "closed_reason": reason,
        })
        return fu  # type: ignore[return-value]

    # ── Outcomes that end things regardless of what was said ────────────────
    if outcome == CallOutcome.DECLINED_CONTACT.value:
        fu["do_not_contact"] = True
        return close("The candidate asked not to be contacted again.")

    if outcome == CallOutcome.INVALID_NUMBER.value:
        # Retrying an invalid number just burns attempts; HR must fix the record.
        return close("The phone number on the candidate record is not reachable.")

    # ── The candidate was never actually reached ────────────────────────────
    if outcome in {o.value for o in RETRYABLE_OUTCOMES}:
        attempts = int(fu.get("attempts") or 0)
        if attempts < max_attempts():
            fu.update({
                "state": (FollowupState.FINAL_CALL_PENDING.value
                          if call_type == CallType.FINAL.value
                          else FollowupState.WAITING_FOR_INITIAL_CALL.value),
                "due_at": _iso(next_calling_slot(
                    now + timedelta(minutes=retry_delay_minutes()))),
            })
            return fu  # type: ignore[return-value]

        if call_type == CallType.FINAL.value:
            return close(f"Unreachable after {attempts} attempts on the final call.")
        # Out of initial attempts — escalate to the final call with a fresh budget.
        fu.update({
            "state": FollowupState.FINAL_CALL_PENDING.value,
            "attempts": 0,
            "due_at": _iso(next_calling_slot(
                now + timedelta(minutes=final_delay_minutes()))),
        })
        return fu  # type: ignore[return-value]

    # ── A real conversation happened ────────────────────────────────────────
    if call_type == CallType.FINAL.value:
        # §9 — terminal in every branch, including FINAL_UNDECIDED.
        return close(f"Final call completed: {intent or CandidateIntent.NO_RESPONSE.value}.")

    if intent in {i.value for i in TERMINAL_INTENTS}:
        return close(f"Candidate response recorded: {intent}.")

    if intent == CandidateIntent.NEEDS_TIME.value:
        due = _parse_requested_date(requested_followup_date, now)
        fu.update({
            "state": FollowupState.FINAL_CALL_PENDING.value,
            "attempts": 0,
            "requested_followup_date": requested_followup_date,
            "due_at": _iso(next_calling_slot(due)),
        })
        return fu  # type: ignore[return-value]

    # Connected, but nothing usable was said — treat as one spent attempt and
    # let the final call be the decisive one.
    fu.update({
        "state": FollowupState.FINAL_CALL_PENDING.value,
        "attempts": 0,
        "due_at": _iso(next_calling_slot(
            now + timedelta(minutes=final_delay_minutes()))),
    })
    return fu  # type: ignore[return-value]


def cancel(followup: dict[str, Any] | None, reason: str,
           now: Optional[datetime] = None) -> OfferFollowup:
    """
    Close the workflow because the candidate acted outside the call — the §6
    Case 3 path, when an acceptance lands during the delay window.
    """
    now = now or datetime.now(timezone.utc)
    fu = dict(followup or {})
    fu.update({
        "state": FollowupState.CLOSED.value,
        "due_at": None,
        "closed_at": _iso(now),
        "closed_reason": reason,
    })
    return fu  # type: ignore[return-value]


_RELATIVE = re.compile(r"(\d+)\s*(day|days|week|weeks|hour|hours)", re.I)


def _parse_requested_date(raw: Optional[str], now: datetime) -> datetime:
    """
    Turn what the candidate said into a datetime.

    Accepts an ISO date (the agent is asked to emit one) and falls back to
    loose phrasing like "3 days". Anything unparseable becomes the configured
    default rather than an error — a follow-up at a slightly wrong time beats
    no follow-up, and the raw text is stored alongside for HR to read.
    """
    default = now + timedelta(minutes=final_delay_minutes())
    if not raw:
        return default

    try:
        parsed = datetime.fromisoformat(raw.strip())
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed if parsed > now else default
    except ValueError:
        pass

    match = _RELATIVE.search(raw)
    if match:
        n, unit = int(match.group(1)), match.group(2).lower()
        if unit.startswith("day"):
            return now + timedelta(days=n)
        if unit.startswith("week"):
            return now + timedelta(weeks=n)
        if unit.startswith("hour"):
            return now + timedelta(hours=n)
    return default
