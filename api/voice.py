"""
Voice-call endpoints (§12, §14, §21).

The agent process reports here rather than writing state itself, so every
transition still passes through core.voice_flow and core.lifecycle. That is
what makes the conversational layer untrusted-by-design: the worst a confused
model can do is report a wrong outcome, never place a call it should not have
placed or mark an offer accepted.

THE INVARIANT THAT MATTERS MOST
-------------------------------
No endpoint here writes offer_letter.status. A verbal "yes" produces
ACCEPTED_INTENT and an HR notification — the binding acceptance stays the
token-guarded portal click (§8 Scenario A).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from core.voice_flow import advance
from core.voice_state import (
    CallOutcome, CandidateIntent, FollowupState, mask_phone,
)
from db import voice_calls
from utils.audit import emit_audit
from utils.tokens import PURPOSE_OFFER, TokenError, verify_token

#: HR-side: the dashboard's call history and configuration readout.
router = APIRouter(prefix="/voice", tags=["voice"])

#: The agent worker reporting a call outcome. Authenticated by the same signed
#: thread token the candidate portal uses, not by an operator session — the
#: worker is a machine with no login.
agent_router = APIRouter(prefix="/voice", tags=["voice"])

_get_graph: Callable[[], Any] | None = None


def bind(get_graph: Callable[[], Any]) -> None:
    global _get_graph
    _get_graph = get_graph


def _graph():
    if _get_graph is None or _get_graph() is None:
        raise HTTPException(status_code=503, detail="Graph not initialised yet.")
    return _get_graph()


def _guard(token: str, thread_id: str) -> None:
    try:
        verify_token(token, thread_id, PURPOSE_OFFER)
    except TokenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None


class CallOutcomeRequest(BaseModel):
    outcome: str
    intent: Optional[str] = None
    summary: Optional[str] = None
    reason_if_declined: Optional[str] = None
    requested_followup_date: Optional[str] = None
    transcript: Optional[list[dict]] = None


@agent_router.post("/calls/{call_id}/outcome")
async def record_outcome(call_id: int, req: CallOutcomeRequest, token: str = Query(...)):
    """
    Called once by the agent when a call ends.

    Idempotent (§15): a duplicate report on an already-finished call is
    acknowledged and discarded rather than advancing the state machine twice —
    a retried webhook must not turn one NO_ANSWER into two spent attempts.
    """
    call = await voice_calls.get_call(call_id)
    if not call:
        raise HTTPException(status_code=404, detail=f"No call {call_id}.")

    thread_id = call["thread_id"]
    _guard(token, thread_id)

    if call.get("call_status") in ("COMPLETED", "FAILED"):
        return {
            "call_id": call_id,
            "status": call["call_status"],
            "message": "Already recorded; no state change.",
            "duplicate": True,
        }

    valid_outcomes = {o.value for o in CallOutcome}
    if req.outcome not in valid_outcomes:
        raise HTTPException(
            status_code=422,
            detail=f"outcome must be one of {sorted(valid_outcomes)}.",
        )
    if req.intent and req.intent not in {i.value for i in CandidateIntent}:
        raise HTTPException(status_code=422, detail=f"Unknown intent '{req.intent}'.")

    now = datetime.now(timezone.utc)
    started = call.get("call_started_at")
    duration = int((now - started).total_seconds()) if started else None

    await voice_calls.update_call(
        call_id,
        call_status="COMPLETED" if req.outcome == CallOutcome.COMPLETED.value else "FAILED",
        call_outcome=req.outcome,
        candidate_intent=req.intent,
        summary=req.summary,
        reason_if_declined=req.reason_if_declined,
        transcript=req.transcript,
        call_ended_at=now,
        call_duration_s=duration,
    )

    cfg = {"configurable": {"thread_id": thread_id}}
    snapshot = await _graph().aget_state(cfg)
    state = dict(snapshot.values) if snapshot and snapshot.values else {}

    followup = advance(
        state.get("offer_followup"),
        call_type=call["call_type"],
        outcome=req.outcome,
        intent=req.intent,
        requested_followup_date=req.requested_followup_date,
        now=now,
    )

    # A call that never reached anyone releases its claim so a retry can
    # proceed; one that produced a conversation keeps it, permanently.
    if followup.get("state") in (
        FollowupState.WAITING_FOR_INITIAL_CALL.value,
        FollowupState.FINAL_CALL_PENDING.value,
    ) and req.outcome != CallOutcome.COMPLETED.value:
        await voice_calls.release_claim(call_id)

    await _graph().aupdate_state(cfg, {
        "offer_followup": followup,
        "audit_log": emit_audit(
            node="voice_agent",
            event="VOICE_CALL_COMPLETED",
            payload_summary=(
                f"{call['call_type']} call to "
                f"{mask_phone(call.get('phone_number'))}: {req.outcome}"
                + (f" / {req.intent}" if req.intent else "")
                + (f" — {req.summary}" if req.summary else "")
            ),
            actor="VOICE_AGENT",
        ),
    })

    return {
        "call_id": call_id,
        "thread_id": thread_id,
        "outcome": req.outcome,
        "intent": req.intent,
        "followup_state": followup.get("state"),
        "next_call_due": followup.get("due_at"),
        # Said explicitly in the response so no caller can mistake a verbal yes
        # for a completed acceptance.
        "offer_status_changed": False,
    }


def _present(row: dict) -> dict:
    """
    One call, shaped for the HR console.

    The phone number is masked here rather than in the component: a raw number
    must not reach the browser at all, or it ends up in logs, screenshots and
    anything that scrapes the response.
    """
    return {
        "call_id": row["id"],
        "thread_id": row["thread_id"],
        "candidate_id": row.get("candidate_id"),
        "candidate_name": row.get("candidate_name"),
        "designation": row.get("designation"),
        "document_number": row.get("document_number"),
        "call_type": row["call_type"],
        "phone_masked": mask_phone(row.get("phone_number")),
        "call_status": row.get("call_status"),
        "call_outcome": row.get("call_outcome"),
        "candidate_intent": row.get("candidate_intent"),
        "summary": row.get("summary"),
        "reason_if_declined": row.get("reason_if_declined"),
        "transcript": row.get("transcript") or [],
        "recording_url": row.get("recording_url"),
        "attempt": row.get("attempt"),
        "error_detail": row.get("error_detail"),
        "started_at": (row.get("call_started_at") or row.get("created_at")).isoformat()
                      if (row.get("call_started_at") or row.get("created_at")) else None,
        "ended_at": row["call_ended_at"].isoformat() if row.get("call_ended_at") else None,
        "duration_s": row.get("call_duration_s"),
    }


@router.get("/calls")
async def all_calls(limit: int = Query(100, ge=1, le=500)):
    """
    Every call, newest first — the dashboard's voice panel.

    Returns counts alongside the rows so the panel's header does not have to
    re-derive them from a truncated list and quietly under-report.
    """
    rows = await voice_calls.recent_calls(limit)
    calls = [_present(r) for r in rows]

    def count(**match) -> int:
        return sum(1 for c in calls
                   if all(c.get(k) == v for k, v in match.items()))

    return {
        "calls": calls,
        "totals": {
            "total": len(calls),
            "completed": count(call_status="COMPLETED"),
            "failed": count(call_status="FAILED"),
            "in_progress": count(call_status="IN_PROGRESS"),
            "accepted_intent": sum(
                1 for c in calls
                if c["candidate_intent"] in
                ("ACCEPTED_INTENT", "FINAL_ACCEPTANCE_INTENT")),
            "declined": sum(
                1 for c in calls
                if c["candidate_intent"] in ("DECLINED", "FINAL_DECLINE")),
            "needs_time": count(candidate_intent="NEEDS_TIME"),
            "unreachable": sum(
                1 for c in calls
                if c["call_outcome"] in ("NO_ANSWER", "BUSY", "INVALID_NUMBER")),
        },
    }


@router.get("/calls/{thread_id}")
async def calls_for_thread(thread_id: str):
    """Call history for the HR console. Transcripts are included; numbers are masked."""
    rows = await voice_calls.calls_for_thread(thread_id)
    return {"thread_id": thread_id, "calls": [_present(r) for r in rows]}


@router.get("/status")
async def voice_status():
    """Is voice actually wired up? Surfaces misconfiguration instead of silence."""
    from core.voice_state import (
        final_call_enabled, initial_call_enabled, initial_delay_minutes,
        max_attempts, recording_enabled, voice_enabled,
    )
    from voice.dispatch import telephony_configured, trunk_id_problem

    import os
    return {
        "voice_agent_enabled": voice_enabled(),
        "telephony_configured": telephony_configured(),
        # The specific reason, so the dashboard can say what is wrong instead
        # of "not configured" — which sent the last debugging session to the
        # wrong place entirely.
        "telephony_problem": trunk_id_problem() if not telephony_configured() else None,
        "deepgram_configured": bool(os.environ.get("DEEPGRAM_API_KEY")),
        "initial_call_enabled": initial_call_enabled(),
        "final_call_enabled": final_call_enabled(),
        "initial_delay_minutes": initial_delay_minutes(),
        "max_attempts": max_attempts(),
        "recording_enabled": recording_enabled(),
    }
