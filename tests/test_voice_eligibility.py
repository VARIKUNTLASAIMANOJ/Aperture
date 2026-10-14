"""
§20 — eligibility, timing, duplicate protection and the state machine.

These run with no LiveKit, no Deepgram and no telephony: every rule that
decides whether a human gets phoned is a pure function over state, and that is
exactly the part that must be right before a single real call is placed.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("VOICE_AGENT_ENABLED", "true")
os.environ.setdefault("CANDIDATE_TOKEN_SECRET", "test-secret-for-unit-tests")

from core.lifecycle import can_call_candidate  # noqa: E402
from core.voice_flow import advance, arm_initial, call_type_for, cancel, is_due  # noqa: E402
from core.voice_state import (  # noqa: E402
    CallOutcome, CallType, CandidateIntent, FollowupState, PhoneError,
    mask_phone, normalize_phone, within_calling_hours,
)

# 14:00 IST — inside the default 10:00–19:00 calling window.
NOON_IST = datetime(2026, 10, 8, 8, 30, tzinfo=timezone.utc)


def state(**over):
    """A thread whose offer was released and genuinely dispatched."""
    base = {
        "candidate_id": "CAND-1",
        "candidate_name": "Manoj",
        "candidate_phone": "+919876543210",
        "selection_status": "SELECTED",
        "offer_letter": {
            "status": "RELEASED",
            "document_number": "OFR/2026/CAND-1",
            "expires_at": "2026-12-31T00:00:00+00:00",
        },
        "email_queue": [
            {"template_name": "offer_letter_email", "status": "SENT"},
        ],
        "offer_followup": {
            "state": FollowupState.WAITING_FOR_INITIAL_CALL.value,
            "attempts": 0,
            "do_not_contact": False,
        },
    }
    base.update(over)
    return base


# ── Phone normalisation (§3) ────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("+919876543210", "+919876543210"),
    ("9876543210", "+919876543210"),
    ("09876543210", "+919876543210"),
    ("98765 43210", "+919876543210"),
    ("+91 98765-43210", "+919876543210"),
    ("919876543210", "+919876543210"),
    ("0091 9876543210", "+919876543210"),
])
def test_phone_normalises_to_one_canonical_form(raw, expected):
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize("raw", [
    "", "   ", "12345", "+91 1234567890",      # Indian mobiles cannot start with 1
    "abcdefghij", "+91987654321",              # nine digits
])
def test_unusable_phone_is_refused_not_guessed(raw):
    with pytest.raises(PhoneError):
        normalize_phone(raw)


def test_mask_phone_hides_the_middle():
    masked = mask_phone("+919876543210")
    assert masked.startswith("+91") and masked.endswith("210")
    assert "9876543" not in masked


# ── Eligibility (§19) ───────────────────────────────────────────────────────

def test_offered_candidate_may_be_called():
    assert can_call_candidate(state(), now=NOON_IST)


def test_rejected_candidate_is_never_called():
    chk = can_call_candidate(state(selection_status="REJECTED"), now=NOON_IST)
    assert not chk and "SELECTED" in chk.reason


def test_already_accepted_blocks_the_call():
    s = state()
    s["offer_letter"] = {**s["offer_letter"], "status": "ACCEPTED"}
    chk = can_call_candidate(s, now=NOON_IST)
    assert not chk and "already accepted" in chk.reason.lower()


def test_declined_blocks_the_call():
    s = state()
    s["offer_letter"] = {**s["offer_letter"], "status": "DECLINED"}
    assert not can_call_candidate(s, now=NOON_IST)


def test_unreleased_offer_blocks_the_call():
    s = state()
    s["offer_letter"] = {**s["offer_letter"], "status": "DRAFT"}
    assert not can_call_candidate(s, now=NOON_IST)


def test_missing_phone_blocks_the_call():
    chk = can_call_candidate(state(candidate_phone=None), now=NOON_IST)
    assert not chk and "phone" in chk.reason.lower()


def test_failed_dispatch_blocks_the_call():
    """The offer never reached the candidate — calling about it would be a lie."""
    s = state(email_queue=[{"template_name": "offer_letter_email", "status": "FAILED"}])
    chk = can_call_candidate(s, now=NOON_IST)
    assert not chk and "dispatch" in chk.reason.lower()


def test_expired_offer_blocks_the_call():
    s = state()
    s["offer_letter"] = {**s["offer_letter"], "expires_at": "2026-01-01T00:00:00+00:00"}
    assert not can_call_candidate(s, now=NOON_IST)


def test_do_not_contact_is_permanent():
    s = state()
    s["offer_followup"] = {**s["offer_followup"], "do_not_contact": True}
    for call_type in (CallType.INITIAL.value, CallType.FINAL.value):
        assert not can_call_candidate(s, call_type, now=NOON_IST)


def test_call_in_progress_blocks_a_second_call():
    s = state()
    s["offer_followup"] = {**s["offer_followup"],
                           "state": FollowupState.INITIAL_CALL_IN_PROGRESS.value}
    chk = can_call_candidate(s, now=NOON_IST)
    assert not chk and "in progress" in chk.reason.lower()


def test_exhausted_attempts_block_the_call():
    s = state()
    s["offer_followup"] = {**s["offer_followup"], "attempts": 99}
    assert not can_call_candidate(s, now=NOON_IST)


def test_disabled_flag_blocks_everything(monkeypatch):
    monkeypatch.setenv("VOICE_AGENT_ENABLED", "false")
    assert not can_call_candidate(state(), now=NOON_IST)


# ── Calling hours ───────────────────────────────────────────────────────────

def test_night_calls_are_deferred():
    three_am_ist = datetime(2026, 10, 8, 21, 30, tzinfo=timezone.utc)
    assert not within_calling_hours(three_am_ist)
    chk = can_call_candidate(state(), now=three_am_ist)
    assert not chk and "deferred" in chk.reason.lower()


def test_daytime_is_inside_the_window():
    assert within_calling_hours(NOON_IST)


# ── Timing (§5, §6) ─────────────────────────────────────────────────────────

def test_arming_sets_a_future_due_time():
    fu = arm_initial(NOON_IST, delay_minutes=3)
    assert fu["state"] == FollowupState.WAITING_FOR_INITIAL_CALL.value
    assert datetime.fromisoformat(fu["due_at"]) >= NOON_IST + timedelta(minutes=3)
    assert fu["attempts"] == 0


def test_not_due_before_the_delay_elapses():
    fu = arm_initial(NOON_IST, delay_minutes=3)
    assert not is_due(fu, NOON_IST + timedelta(minutes=1))
    assert is_due(fu, NOON_IST + timedelta(minutes=4))


def test_delay_is_configurable_to_production_length():
    """2–5 minutes → 3 days must be a config change, not a code change."""
    fu = arm_initial(NOON_IST, delay_minutes=4320)
    due = datetime.fromisoformat(fu["due_at"])
    assert timedelta(days=2, hours=23) < due - NOON_IST < timedelta(days=3, hours=20)


def test_acceptance_during_the_window_cancels_the_call():
    fu = cancel(arm_initial(NOON_IST, 3), "Accepted in the portal.", now=NOON_IST)
    assert fu["state"] == FollowupState.CLOSED.value
    assert not is_due(fu, NOON_IST + timedelta(days=1))


# ── State machine (§10, §11, §9) ────────────────────────────────────────────

def test_acceptance_intent_closes_without_further_calls():
    fu = advance({}, call_type=CallType.INITIAL.value,
                 outcome=CallOutcome.COMPLETED.value,
                 intent=CandidateIntent.ACCEPTED_INTENT.value, now=NOON_IST)
    assert fu["state"] == FollowupState.CLOSED.value
    assert not is_due(fu, NOON_IST + timedelta(days=30))


def test_decline_closes():
    fu = advance({}, call_type=CallType.INITIAL.value,
                 outcome=CallOutcome.COMPLETED.value,
                 intent=CandidateIntent.DECLINED.value, now=NOON_IST)
    assert fu["state"] == FollowupState.CLOSED.value


def test_needs_time_schedules_the_final_call_when_asked():
    fu = advance({}, call_type=CallType.INITIAL.value,
                 outcome=CallOutcome.COMPLETED.value,
                 intent=CandidateIntent.NEEDS_TIME.value,
                 requested_followup_date="3 days", now=NOON_IST)
    assert fu["state"] == FollowupState.FINAL_CALL_PENDING.value
    assert call_type_for(fu) == CallType.FINAL.value
    assert datetime.fromisoformat(fu["due_at"]) > NOON_IST + timedelta(days=2)


def test_no_answer_retries_without_inventing_a_decision():
    fu = advance({"attempts": 1}, call_type=CallType.INITIAL.value,
                 outcome=CallOutcome.NO_ANSWER.value, now=NOON_IST)
    assert fu["state"] == FollowupState.WAITING_FOR_INITIAL_CALL.value
    assert fu.get("last_intent") is None       # silence is not a decline


def test_exhausted_retries_escalate_to_the_final_call():
    fu = advance({"attempts": 3}, call_type=CallType.INITIAL.value,
                 outcome=CallOutcome.NO_ANSWER.value, now=NOON_IST)
    assert fu["state"] == FollowupState.FINAL_CALL_PENDING.value
    assert fu["attempts"] == 0                 # fresh budget for the final call


def test_invalid_number_closes_rather_than_retrying():
    fu = advance({}, call_type=CallType.INITIAL.value,
                 outcome=CallOutcome.INVALID_NUMBER.value, now=NOON_IST)
    assert fu["state"] == FollowupState.CLOSED.value


def test_do_not_contact_request_closes_and_suppresses():
    fu = advance({}, call_type=CallType.INITIAL.value,
                 outcome=CallOutcome.DECLINED_CONTACT.value, now=NOON_IST)
    assert fu["state"] == FollowupState.CLOSED.value
    assert fu["do_not_contact"] is True


@pytest.mark.parametrize("intent", [
    CandidateIntent.FINAL_ACCEPTANCE_INTENT.value,
    CandidateIntent.FINAL_DECLINE.value,
    CandidateIntent.FINAL_UNDECIDED.value,
])
def test_final_call_never_schedules_another(intent):
    """§9 — not even FINAL_UNDECIDED may re-open the loop."""
    fu = advance({"attempts": 1}, call_type=CallType.FINAL.value,
                 outcome=CallOutcome.COMPLETED.value, intent=intent, now=NOON_IST)
    assert fu["state"] == FollowupState.CLOSED.value
    assert fu.get("due_at") is None
    assert not is_due(fu, NOON_IST + timedelta(days=365))


def test_final_call_undecided_does_not_record_an_acceptance():
    fu = advance({}, call_type=CallType.FINAL.value,
                 outcome=CallOutcome.COMPLETED.value,
                 intent=CandidateIntent.FINAL_UNDECIDED.value, now=NOON_IST)
    assert fu["last_intent"] == CandidateIntent.FINAL_UNDECIDED.value


def test_outcome_applied_twice_is_idempotent():
    once = advance({"attempts": 1}, call_type=CallType.INITIAL.value,
                   outcome=CallOutcome.COMPLETED.value,
                   intent=CandidateIntent.DECLINED.value, now=NOON_IST)
    twice = advance(once, call_type=CallType.INITIAL.value,
                    outcome=CallOutcome.COMPLETED.value,
                    intent=CandidateIntent.DECLINED.value, now=NOON_IST)
    assert once["state"] == twice["state"] == FollowupState.CLOSED.value
