"""
Placing the outbound call (§17).

LiveKit does NOT provide PSTN connectivity on its own. Reaching a real phone
needs a SIP trunk registered with LiveKit Cloud (Twilio, Plivo or — for Indian
numbers, where TRAI/DLT registration applies — Exotel). `LIVEKIT_SIP_TRUNK_ID`
is that trunk; without it this module refuses rather than pretending to dial.

Flow:
    scheduler claims the call  →  place_call()
        creates a LiveKit room
        dispatches an agent job carrying the thread metadata
        asks LiveKit SIP to dial the candidate into that room
    voice/agent.py picks the job up and runs the conversation
    agent POSTs the outcome back to /voice/calls/{id}/outcome

The agent is handed a thread_id and a short-lived HMAC token, never the
candidate's PII — it fetches what it needs through the API, so the rules layer
stays the single enforcement point.
"""

from __future__ import annotations

import json
import os
from typing import Any

from core.voice_state import mask_phone, recording_enabled

ROOM_PREFIX = "offer-followup"


class TelephonyNotConfigured(RuntimeError):
    """Raised instead of silently no-oping, so a misconfiguration is loud."""


#: Substrings identifying a failure that never reached the carrier: our network
#: dropped, DNS failed, LiveKit was unreachable. Matched on the message because
#: the SDK wraps transport errors in its own exception types.
_INFRASTRUCTURE_MARKERS = (
    "could not contact dns",
    "cannot connect to host",
    "temporary failure in name resolution",
    "connection reset",
    "connection refused",
    "timeout",
    "timed out",
)


def is_infrastructure_failure(exc: BaseException) -> bool:
    """
    True when the dial failed on OUR side, before the carrier saw it.

    These must not count against the candidate's retry budget. A laptop losing
    wifi for thirty seconds burned three attempts on several threads and closed
    them permanently — the candidate was never called and never will be, because
    of a network blip they had nothing to do with. A misconfiguration is the
    same: the operator must fix it, and the candidate should not pay for it.
    """
    if isinstance(exc, TelephonyNotConfigured):
        return True
    text = str(exc).lower()
    return any(marker in text for marker in _INFRASTRUCTURE_MARKERS)


def _require(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise TelephonyNotConfigured(
            f"{name} is not set. Outbound calling needs LIVEKIT_URL, "
            f"LIVEKIT_API_KEY, LIVEKIT_API_SECRET and LIVEKIT_SIP_TRUNK_ID "
            f"(a SIP trunk registered with LiveKit — LiveKit alone cannot "
            f"reach the PSTN)."
        )
    return value


#: LiveKit trunk ids are always `ST_` followed by an opaque suffix.
TRUNK_ID_PREFIX = "ST_"


def trunk_id_problem() -> str | None:
    """
    Why the configured trunk cannot work, in words, or None if it looks sane.

    Checked by shape before any API call because the server's own answer is an
    unhelpful `twirp error unknown: object cannot be found` 404 — raised only
    after an agent session has already been dispatched and started talking to
    an empty room. Catching the common paste mistake here turns a confusing
    mid-call failure into a sentence.
    """
    value = os.environ.get("LIVEKIT_SIP_TRUNK_ID", "").strip()
    if not value:
        return "LIVEKIT_SIP_TRUNK_ID is empty."
    if value.startswith(TRUNK_ID_PREFIX):
        return None
    if value.startswith("sip:") or ".livekit.cloud" in value or value.startswith("wss://"):
        return (
            f"LIVEKIT_SIP_TRUNK_ID is set to {value!r}, which is a SIP endpoint "
            f"address, not a trunk id. A trunk id starts with 'ST_' and is "
            f"created when you register a telephony provider's trunk "
            f"(Twilio / Plivo / Exotel) with LiveKit — the SIP hostname alone "
            f"does not provide outbound calling."
        )
    return (
        f"LIVEKIT_SIP_TRUNK_ID is set to {value!r}, which is not a LiveKit "
        f"trunk id — those start with '{TRUNK_ID_PREFIX}'."
    )


def telephony_configured() -> bool:
    if not all(os.environ.get(k) for k in (
        "LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET",
    )):
        return False
    return trunk_id_problem() is None


def room_name(thread_id: str, call_id: int) -> str:
    return f"{ROOM_PREFIX}-{thread_id[:8]}-{call_id}"


async def place_call(
    *,
    thread_id: str,
    call_id: int,
    call_type: str,
    phone_number: str,
    state: dict[str, Any],
) -> str:
    """
    Dial the candidate and hand the session to the agent worker.

    Returns the LiveKit SIP participant id. Raises TelephonyNotConfigured when
    credentials are absent, and lets provider errors propagate so the scheduler
    can release the claim and retry.
    """
    from livekit import api

    url = _require("LIVEKIT_URL")
    key = _require("LIVEKIT_API_KEY")
    secret = _require("LIVEKIT_API_SECRET")
    trunk = _require("LIVEKIT_SIP_TRUNK_ID")

    # Before dispatching an agent — otherwise a bad trunk burns a LiveKit
    # session with the agent greeting an empty room, and surfaces only as a
    # 404 from a later call.
    problem = trunk_id_problem()
    if problem:
        raise TelephonyNotConfigured(problem)

    from db import voice_calls
    from utils.tokens import PURPOSE_OFFER, issue_token

    room = room_name(thread_id, call_id)
    # The agent authenticates back to the API with this, exactly like the
    # candidate portal does — no second auth scheme.
    token = state.get("candidate_access_token") or issue_token(thread_id, PURPOSE_OFFER)

    metadata = json.dumps({
        "thread_id": thread_id,
        "call_id": call_id,
        "call_type": call_type,
        "token": token,
        "candidate_name": state.get("candidate_name", ""),
        "api_base": os.environ.get("INTERNAL_API_BASE", "http://127.0.0.1:8000"),
        "record": recording_enabled(),
    })

    lk = api.LiveKitAPI(url=url, api_key=key, api_secret=secret)
    try:
        await lk.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(
                agent_name=os.environ.get("VOICE_AGENT_NAME", "offer-followup-agent"),
                room=room,
                metadata=metadata,
            )
        )

        participant = await lk.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                sip_trunk_id=trunk,
                sip_call_to=phone_number,
                room_name=room,
                participant_identity=f"candidate-{call_id}",
                participant_name=state.get("candidate_name", "Candidate"),
                # Block until the call is actually answered so a NO_ANSWER
                # surfaces here as an error rather than as a silent room that
                # the agent sits in alone.
                wait_until_answered=True,
            )
        )
    finally:
        await lk.aclose()

    await voice_calls.update_call(
        call_id,
        room_name=room,
        provider_call_id=getattr(participant, "participant_id", None),
        call_status="IN_PROGRESS",
        call_started_at=voice_calls.utcnow(),
    )

    print(
        f"[voice] dialing {mask_phone(phone_number)} for thread {thread_id} "
        f"({call_type}, room={room})"
    )
    return getattr(participant, "participant_id", "")
