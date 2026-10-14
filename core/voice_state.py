"""
Voice follow-up state machine (§10) and phone-number handling (§3).

Kept in its own module rather than bolted onto core.state so the employment
lifecycle and the call lifecycle stay separable: a candidate's offer status is
a contractual fact, a call outcome is an operational one, and conflating them
is how a missed phone call would end up looking like a declined offer.

    OFFER_RELEASED
          ↓  email_node arms the follow-up on dispatch
    WAITING_FOR_INITIAL_CALL
          ↓  delay elapses, eligibility re-checked
    INITIAL_CALL_PENDING → INITIAL_CALL_IN_PROGRESS
          ↓
          ├── ACCEPTED_INTENT ─── terminal (official acceptance is NOT implied)
          ├── DECLINED ────────── terminal
          ├── NEEDS_TIME ──────── FOLLOW_UP_PENDING → FINAL_CALL_PENDING
          ├── NO_ANSWER / BUSY ── retry, then FINAL_CALL_PENDING
          └── CALL_FAILED ─────── retry or terminal
                    ↓
          FINAL_CALL_IN_PROGRESS
                    ↓
          ├── FINAL_ACCEPTANCE_INTENT
          ├── FINAL_DECLINE
          └── FINAL_UNDECIDED      (no further "how many days?" — §9)
"""

from __future__ import annotations

import os
import re
from datetime import datetime, time, timedelta, timezone
from enum import Enum
from typing import Optional

from typing_extensions import TypedDict


class FollowupState(str, Enum):
    """Where a thread sits in the call workflow."""
    NOT_APPLICABLE = "NOT_APPLICABLE"
    WAITING_FOR_INITIAL_CALL = "WAITING_FOR_INITIAL_CALL"
    INITIAL_CALL_PENDING = "INITIAL_CALL_PENDING"
    INITIAL_CALL_IN_PROGRESS = "INITIAL_CALL_IN_PROGRESS"
    FOLLOW_UP_PENDING = "FOLLOW_UP_PENDING"
    FINAL_CALL_PENDING = "FINAL_CALL_PENDING"
    FINAL_CALL_IN_PROGRESS = "FINAL_CALL_IN_PROGRESS"
    CLOSED = "CLOSED"


class CallType(str, Enum):
    INITIAL = "INITIAL"
    FINAL = "FINAL"


class CallOutcome(str, Enum):
    """
    §11 — how the call ended, kept distinct from what the candidate said.

    'The candidate did not answer' and 'the number was invalid' demand
    different operational responses, so they must never collapse into a single
    FAILED bucket.
    """
    COMPLETED = "COMPLETED"
    NO_ANSWER = "NO_ANSWER"
    BUSY = "BUSY"
    CALL_FAILED = "CALL_FAILED"
    INVALID_NUMBER = "INVALID_NUMBER"
    DECLINED_CONTACT = "DECLINED_CONTACT"


class CandidateIntent(str, Enum):
    """
    What the candidate actually said.

    ACCEPTED_INTENT is deliberately NOT OfferLetterStatus.ACCEPTED. A verbal
    yes on an unauthenticated phone call must never become a binding
    acceptance — that transition belongs to the token-guarded portal endpoint
    and nothing else (§8 Scenario A).
    """
    ACCEPTED_INTENT = "ACCEPTED_INTENT"
    DECLINED = "DECLINED"
    NEEDS_TIME = "NEEDS_TIME"
    NO_RESPONSE = "NO_RESPONSE"
    FINAL_ACCEPTANCE_INTENT = "FINAL_ACCEPTANCE_INTENT"
    FINAL_DECLINE = "FINAL_DECLINE"
    FINAL_UNDECIDED = "FINAL_UNDECIDED"


#: Intents that close the workflow — no further calls, ever.
TERMINAL_INTENTS = frozenset({
    CandidateIntent.ACCEPTED_INTENT,
    CandidateIntent.DECLINED,
    CandidateIntent.FINAL_ACCEPTANCE_INTENT,
    CandidateIntent.FINAL_DECLINE,
    CandidateIntent.FINAL_UNDECIDED,
})

#: Outcomes worth retrying — the candidate was never actually reached.
RETRYABLE_OUTCOMES = frozenset({
    CallOutcome.NO_ANSWER,
    CallOutcome.BUSY,
    CallOutcome.CALL_FAILED,
})


class OfferFollowup(TypedDict, total=False):
    """
    The call workflow's slice of graph state. Deliberately small: transcripts
    and per-call metadata live in the voice_calls table, because LangGraph
    rewrites the whole checkpoint on every super-step and a transcript would be
    copied on each one.
    """
    state: str                              # FollowupState
    due_at: Optional[str]                   # ISO-8601 UTC — when to act next
    attempts: int                           # dial attempts for the current call type
    last_call_type: Optional[str]           # CallType
    last_outcome: Optional[str]             # CallOutcome
    last_intent: Optional[str]              # CandidateIntent
    requested_followup_date: Optional[str]  # what the candidate asked for
    do_not_contact: bool                    # §11 — permanent suppression
    armed_at: Optional[str]
    closed_at: Optional[str]
    closed_reason: Optional[str]


# ---------------------------------------------------------------------------
# Configuration (§16) — every timing knob is env-driven so the 2–5 minute
# prototype window becomes a 2–3 day production window without a code change.
# ---------------------------------------------------------------------------

def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def voice_enabled() -> bool:
    return os.environ.get("VOICE_AGENT_ENABLED", "false").lower() in ("1", "true", "yes")


def initial_call_enabled() -> bool:
    return os.environ.get("INITIAL_CALL_ENABLED", "true").lower() in ("1", "true", "yes")


def final_call_enabled() -> bool:
    return os.environ.get("FINAL_CALL_ENABLED", "true").lower() in ("1", "true", "yes")


def initial_delay_minutes() -> int:
    """OFFER_CALL_DELAY_MINUTES — 3 for testing, 4320 (3 days) for production."""
    return _int_env("OFFER_CALL_DELAY_MINUTES", 3)


def final_delay_minutes() -> int:
    """Gap before the final call when the candidate gave no specific date."""
    return _int_env("FINAL_CALL_DELAY_MINUTES", 5)


def retry_delay_minutes() -> int:
    return _int_env("CALL_RETRY_DELAY_MINUTES", 2)


def max_attempts() -> int:
    """Dial attempts per call type before giving up and moving on."""
    return _int_env("CALL_MAX_ATTEMPTS", 3)


def recording_enabled() -> bool:
    """§13 — off by default. Recording a call is a compliance decision."""
    return os.environ.get("VOICE_RECORDING_ENABLED", "false").lower() in ("1", "true", "yes")


# ── Permitted calling hours ────────────────────────────────────────────────
# Not in the original spec, but a 3-day delay scheduled in UTC will eventually
# dial an Indian candidate at 03:00 local. Calls outside the window are
# deferred to the next opening, never dropped.

IST = timezone(timedelta(hours=5, minutes=30))


def calling_window() -> tuple[time, time]:
    return (
        time(_int_env("CALL_WINDOW_START_HOUR_IST", 10), 0),
        time(_int_env("CALL_WINDOW_END_HOUR_IST", 19), 0),
    )


def within_calling_hours(now: datetime | None = None) -> bool:
    now_ist = (now or datetime.now(timezone.utc)).astimezone(IST)
    start, end = calling_window()
    return start <= now_ist.time() < end


def next_calling_slot(now: datetime | None = None) -> datetime:
    """The earliest UTC instant at or after `now` inside the calling window."""
    now = now or datetime.now(timezone.utc)
    if within_calling_hours(now):
        return now

    now_ist = now.astimezone(IST)
    start, _ = calling_window()
    candidate = now_ist.replace(
        hour=start.hour, minute=start.minute, second=0, microsecond=0
    )
    if now_ist.time() >= start:          # past today's window — open tomorrow
        candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Phone numbers (§3)
# ---------------------------------------------------------------------------

#: E.164. Indian mobiles are +91 followed by 10 digits starting 6-9.
E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")
INDIAN_MOBILE_RE = re.compile(r"^\+91[6-9]\d{9}$")


class PhoneError(ValueError):
    pass


def normalize_phone(raw: str, *, default_country: str = "+91") -> str:
    """
    Normalise HR's input to E.164, or raise.

    Accepts the shapes people actually type — "98765 43210", "098765-43210",
    "+91 98765 43210" — because rejecting those outright just means the number
    gets typed into some other field. Anything ambiguous raises rather than
    guessing: dialing a wrong number is worse than refusing to dial.
    """
    if not raw or not raw.strip():
        raise PhoneError("A phone number is required.")

    s = re.sub(r"[\s\-()./]", "", raw.strip())

    if s.startswith("00"):
        s = "+" + s[2:]
    if not s.startswith("+"):
        digits = s.lstrip("0")
        if len(digits) == 10 and default_country == "+91":
            s = default_country + digits
        elif len(digits) == 12 and digits.startswith("91"):
            s = "+" + digits
        else:
            raise PhoneError(
                f"'{raw}' is not a recognisable phone number. "
                f"Use the international format, e.g. +919876543210."
            )

    if not E164_RE.match(s):
        raise PhoneError(f"'{raw}' is not a valid E.164 phone number.")
    if s.startswith("+91") and not INDIAN_MOBILE_RE.match(s):
        raise PhoneError(
            f"'{raw}' is not a valid Indian mobile number — it must be +91 "
            f"followed by 10 digits beginning 6, 7, 8 or 9."
        )
    return s


def mask_phone(phone: str | None) -> str:
    """Logs and audit entries get the masked form only (§21)."""
    if not phone:
        return ""
    return phone[:3] + "*" * max(0, len(phone) - 6) + phone[-3:] if len(phone) > 6 else "***"
