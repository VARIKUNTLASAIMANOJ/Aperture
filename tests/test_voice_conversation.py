"""
§20 conversation coverage, plus the single most important invariant in this
feature: a phone call can never accept an offer.

These exercise the outcome-processing path with the HTTP layer stubbed, so the
§8/§9 scenarios are verified without LiveKit, Deepgram or a telephony account.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("VOICE_AGENT_ENABLED", "true")
os.environ.setdefault("CANDIDATE_TOKEN_SECRET", "test-secret-for-unit-tests")

from core.lifecycle import hr_notifications  # noqa: E402
from core.voice_flow import advance, call_type_for, is_due  # noqa: E402
from core.voice_state import (  # noqa: E402
    CallOutcome, CallType, CandidateIntent, FollowupState,
)
from voice.prompts import build_instructions, greeting  # noqa: E402

NOW = datetime(2026, 10, 8, 8, 30, tzinfo=timezone.utc)   # 14:00 IST

STATUS = {
    "candidate_name": "Manoj",
    "designation": "Finance Executive",
    "department": "Finance",
    "work_location": {"city": "Bengaluru", "state": "KA"},
    "joining_date": "2026-12-01",
    "ctc": {"annual": 2500000},
    "offer": {"status": "RELEASED", "expires_at": "2026-10-20T00:00:00+00:00"},
}


# ── §8 scenarios ────────────────────────────────────────────────────────────

def test_scenario_a_acceptance_does_not_accept_the_offer():
    """
    The invariant the whole design protects: a verbal yes records intent and
    nothing else. Nothing in the voice path may write offer_letter.status.
    """
    fu = advance({}, call_type=CallType.INITIAL.value,
                 outcome=CallOutcome.COMPLETED.value,
                 intent=CandidateIntent.ACCEPTED_INTENT.value, now=NOW)

    assert fu["last_intent"] == CandidateIntent.ACCEPTED_INTENT.value
    assert fu["state"] == FollowupState.CLOSED.value
    # The follow-up record carries no offer status at all — by construction.
    assert "offer_letter" not in fu and "status" not in fu


def test_scenario_a_raises_an_hr_notification_instead():
    state = {
        "candidate_name": "Manoj",
        "designation": "Finance Executive",
        "offer_letter": {"status": "RELEASED"},
        "offer_followup": {
            "last_intent": CandidateIntent.ACCEPTED_INTENT.value,
            "state": FollowupState.CLOSED.value,
            "closed_at": NOW.isoformat(),
        },
    }
    notes = hr_notifications(state, "t1")
    assert len(notes) == 1
    assert notes[0]["kind"] == "VERBAL_ACCEPTANCE"
    assert "not accepted until" in notes[0]["body"]


def test_verbal_acceptance_notification_disappears_once_confirmed():
    state = {
        "candidate_name": "Manoj",
        "offer_letter": {"status": "ACCEPTED"},
        "appointment_letter": {"status": "ELIGIBLE"},
        "offer_followup": {"last_intent": CandidateIntent.ACCEPTED_INTENT.value},
    }
    notes = hr_notifications(state, "t1")
    assert [n["kind"] for n in notes] == ["APPOINTMENT_LETTER_READY"]


def test_scenario_b_decline_captures_the_reason_and_stops():
    fu = advance({}, call_type=CallType.INITIAL.value,
                 outcome=CallOutcome.COMPLETED.value,
                 intent=CandidateIntent.DECLINED.value, now=NOW)
    assert fu["state"] == FollowupState.CLOSED.value
    assert not is_due(fu, NOW + timedelta(days=365))


@pytest.mark.parametrize("phrase,min_days", [
    ("3 days", 2), ("2 weeks", 13), ("2026-10-15", 6),
])
def test_scenario_c_needs_time_honours_what_they_asked_for(phrase, min_days):
    fu = advance({}, call_type=CallType.INITIAL.value,
                 outcome=CallOutcome.COMPLETED.value,
                 intent=CandidateIntent.NEEDS_TIME.value,
                 requested_followup_date=phrase, now=NOW)
    assert fu["state"] == FollowupState.FINAL_CALL_PENDING.value
    assert fu["requested_followup_date"] == phrase
    assert datetime.fromisoformat(fu["due_at"]) - NOW >= timedelta(days=min_days)


def test_unparseable_timeframe_still_schedules_something():
    """A vague answer must not silently drop the follow-up."""
    fu = advance({}, call_type=CallType.INITIAL.value,
                 outcome=CallOutcome.COMPLETED.value,
                 intent=CandidateIntent.NEEDS_TIME.value,
                 requested_followup_date="sometime after Diwali", now=NOW)
    assert fu["state"] == FollowupState.FINAL_CALL_PENDING.value
    assert fu["due_at"]
    assert fu["requested_followup_date"] == "sometime after Diwali"


def test_no_answer_is_not_a_decline():
    fu = advance({"attempts": 1}, call_type=CallType.INITIAL.value,
                 outcome=CallOutcome.NO_ANSWER.value, now=NOW)
    assert fu.get("last_intent") is None
    assert fu["state"] == FollowupState.WAITING_FOR_INITIAL_CALL.value


def test_unrelated_question_leaves_the_call_undecided_not_declined():
    """A connected call with no decision is NO_RESPONSE, never DECLINED."""
    fu = advance({}, call_type=CallType.INITIAL.value,
                 outcome=CallOutcome.COMPLETED.value,
                 intent=CandidateIntent.NO_RESPONSE.value, now=NOW)
    assert fu["state"] == FollowupState.FINAL_CALL_PENDING.value
    assert fu["last_intent"] == CandidateIntent.NO_RESPONSE.value


def test_do_not_contact_suppresses_the_final_call_too():
    fu = advance({}, call_type=CallType.INITIAL.value,
                 outcome=CallOutcome.DECLINED_CONTACT.value, now=NOW)
    assert fu["do_not_contact"] is True
    assert not is_due(fu, NOW + timedelta(days=365))


# ── §9 final call ───────────────────────────────────────────────────────────

def test_final_call_is_reached_after_needs_time():
    fu = advance({}, call_type=CallType.INITIAL.value,
                 outcome=CallOutcome.COMPLETED.value,
                 intent=CandidateIntent.NEEDS_TIME.value,
                 requested_followup_date="2 days", now=NOW)
    assert call_type_for(fu) == CallType.FINAL.value
    assert is_due(fu, NOW + timedelta(days=3))


@pytest.mark.parametrize("intent", [
    CandidateIntent.FINAL_ACCEPTANCE_INTENT.value,
    CandidateIntent.FINAL_DECLINE.value,
    CandidateIntent.FINAL_UNDECIDED.value,
])
def test_every_final_outcome_is_terminal(intent):
    fu = advance({"attempts": 1}, call_type=CallType.FINAL.value,
                 outcome=CallOutcome.COMPLETED.value, intent=intent, now=NOW)
    assert fu["state"] == FollowupState.CLOSED.value
    assert fu.get("due_at") is None


def test_needs_time_on_a_final_call_cannot_extend_the_loop():
    """
    Even if the model emits NEEDS_TIME on a final call, the state machine must
    close. The prompt forbids it; this is the enforcement behind the prompt.
    """
    fu = advance({"attempts": 1}, call_type=CallType.FINAL.value,
                 outcome=CallOutcome.COMPLETED.value,
                 intent=CandidateIntent.NEEDS_TIME.value,
                 requested_followup_date="5 days", now=NOW)
    assert fu["state"] == FollowupState.CLOSED.value
    assert not is_due(fu, NOW + timedelta(days=30))


# ── §18 / §9 prompt construction ────────────────────────────────────────────

def test_final_prompt_forbids_asking_for_more_time():
    text = build_instructions("FINAL", STATUS)
    assert "Do NOT ask how many more days" in text
    assert "FINAL_UNDECIDED" in text


def test_initial_prompt_allows_asking_once():
    text = build_instructions("INITIAL", STATUS)
    assert "ONCE" in text
    assert "Do NOT ask how many more days" not in text


def test_prompt_speaks_only_figures_it_was_given():
    text = build_instructions("INITIAL", STATUS)
    assert "25,00,000" in text              # Indian digit grouping
    assert "Bengaluru" in text
    assert "cannot confirm that on this call" in text
    assert "never state or imply" in text.lower()


def test_prompt_survives_missing_compensation():
    """A thread without a computed breakup must not crash the call."""
    text = build_instructions("INITIAL", {**STATUS, "ctc": None})
    assert "not available on this call" in text


def test_greeting_asks_for_the_candidate_by_name():
    assert greeting("INITIAL", "Manoj") == "Hello, may I speak with Manoj?"
