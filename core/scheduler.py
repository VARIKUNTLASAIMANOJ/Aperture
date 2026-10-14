"""
Auto-send scheduler
───────────────────
Releases email_queue items that HR approved for a future time.

WHY IN-PROCESS, NOT CELERY
--------------------------
`workers/celery_app.py` exists, but Celery needs a Redis broker and a running
worker. Neither is present in this deployment, so routing scheduled sends
through Celery would enqueue tasks that never execute — a scheduled offer
letter would simply never arrive, with nothing surfacing the failure. An
asyncio loop inside the API process fires with no extra infrastructure.

The schedule itself lives in the LangGraph checkpoint (Postgres), never in
memory, so a restart re-discovers every outstanding schedule. The trade-off is
that nothing fires while the API is down — handled explicitly by the grace
window below rather than silently sending a stale offer hours late.

MECHANISM
---------
A scheduled thread stays parked at `interrupt_before=["email_node"]`. When an
item comes due the scheduler flips it SCHEDULED → PENDING and resumes the
graph, so dispatch runs through the exact same `email_node` path as a manual
approval. There is no second sending code path to drift out of sync.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

import psycopg

from utils.audit import emit_audit

POLL_SECONDS = int(os.environ.get("AUTO_SEND_POLL_SECONDS", "20"))

# How late a scheduled send may fire and still be considered on time. Past this
# the item is failed instead of dispatched: an offer letter arriving hours after
# its intended moment (because the service was down) is worse than one that
# visibly did not go, which an operator can retry deliberately.
GRACE_MINUTES = int(os.environ.get("AUTO_SEND_GRACE_MINUTES", "30"))


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    # Naive values are treated as UTC; the API only ever stores UTC.
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


async def _thread_ids(db_url: str) -> list[str]:
    async with await psycopg.AsyncConnection.connect(db_url) as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT DISTINCT thread_id FROM checkpoints WHERE checkpoint_ns = ''"
            )
            return [row[0] for row in await cur.fetchall()]


async def _process_thread(graph, thread_id: str, now: datetime) -> str | None:
    """Release or fail any due items on one thread. Returns a log line if it acted."""
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = await graph.aget_state(config)
    if not snapshot or not snapshot.values:
        return None

    queue = snapshot.values.get("email_queue", [])
    if not any(e.get("status") == "SCHEDULED" for e in queue):
        return None

    cutoff = now - timedelta(minutes=GRACE_MINUTES)
    released, missed = 0, 0
    new_queue = []

    for item in queue:
        if item.get("status") != "SCHEDULED":
            new_queue.append(item)
            continue

        due_at = _parse_iso(item.get("scheduled_for"))
        if due_at is None:
            # Unparseable schedule cannot be honoured; fail it loudly rather
            # than leaving it stuck as SCHEDULED forever.
            new_queue.append({
                **item, "status": "FAILED", "dispatch_mode": "AUTO",
                "message_id": "Auto-send failed: the scheduled time was unreadable.",
                "sent_at": now.isoformat(),
            })
            missed += 1
        elif due_at > now:
            new_queue.append(item)                       # not yet due
        elif due_at < cutoff:
            new_queue.append({
                **item, "status": "FAILED", "dispatch_mode": "AUTO",
                "message_id": (
                    f"Auto-send failed: the scheduled window "
                    f"({due_at.isoformat()}) passed while the service was "
                    f"unavailable. Nothing was sent."
                ),
                "sent_at": now.isoformat(),
            })
            missed += 1
        else:
            # Due now — hand to email_node by making it look like a normal
            # approved send.
            new_queue.append({**item, "status": "PENDING", "dispatch_mode": "AUTO"})
            released += 1

    if not released and not missed:
        return None

    patch: dict = {"email_queue": new_queue}
    if missed and not released:
        patch["audit_log"] = emit_audit(
            node="scheduler",
            event="AUTO_SEND_MISSED",
            payload_summary=(
                f"{missed} scheduled email(s) missed their window by more than "
                f"{GRACE_MINUTES} minutes and were marked failed. Nothing was sent."
            ),
            actor="SCHEDULER",
        )

    await graph.aupdate_state(config, patch)

    if released:
        # Resumes into email_node, which dispatches the now-PENDING items.
        await graph.ainvoke(None, config=config)
        return f"[scheduler] thread {thread_id}: released {released}, missed {missed}"

    return f"[scheduler] thread {thread_id}: missed {missed}"


async def _process_voice_followup(graph, thread_id: str, now: datetime) -> str | None:
    """
    Place a voice follow-up call if one is due on this thread (§5, §14).

    Deliberately a second, independent pass over the same thread rather than a
    branch inside _process_thread: an email schedule and a call schedule are
    unrelated events, and a failure in one must not skip the other.

    Eligibility is re-checked HERE, immediately before the dial, not when the
    call was scheduled — §6 Case 3 requires that an acceptance during the delay
    window cancels the call rather than racing it.
    """
    from core.lifecycle import can_call_candidate
    from core.voice_flow import call_type_for, is_due, mark_in_progress
    from core.voice_state import (
        mask_phone, next_calling_slot, retry_delay_minutes, voice_enabled,
    )

    if not voice_enabled():
        return None

    config = {"configurable": {"thread_id": thread_id}}
    snapshot = await graph.aget_state(config)
    if not snapshot or not snapshot.values:
        return None

    state = dict(snapshot.values)
    followup = state.get("offer_followup") or {}

    # Cheap pre-filter before the expensive checks — most threads have no
    # follow-up armed at all.
    if not is_due(followup, now):
        return None

    call_type = call_type_for(followup)
    allowed = can_call_candidate(state, call_type, now)
    if not allowed:
        # Outside calling hours is a deferral, not a cancellation: leave the
        # due time alone and the next poll inside the window will pick it up.
        if "deferred" in allowed.reason.lower():
            return None
        from core.voice_flow import cancel
        await graph.aupdate_state(config, {
            "offer_followup": cancel(followup, allowed.reason, now),
            "audit_log": emit_audit(
                node="voice_scheduler", event="VOICE_CALL_SKIPPED",
                payload_summary=f"No call placed — {allowed.reason}",
                actor="SCHEDULER",
            ),
        })
        return f"[voice] thread {thread_id}: skipped — {allowed.reason}"

    # Claim the call in Postgres BEFORE touching graph state. The unique index
    # on (thread_id, call_type) is the only guard that survives two workers, a
    # retried job, or a restart (§15); the state machine alone would not.
    from db import voice_calls

    phone = state["candidate_phone"]
    claim_id = await voice_calls.claim_call(
        thread_id, call_type, phone,
        candidate_id=state.get("candidate_id"),
        candidate_name=state.get("candidate_name"),
        designation=state.get("designation") or state.get("role_title"),
        document_number=(state.get("offer_letter") or {}).get("document_number"),
        attempt=int(followup.get("attempts") or 0) + 1,
    )
    if claim_id is None:
        return f"[voice] thread {thread_id}: {call_type} already claimed — not dialing"

    await graph.aupdate_state(config, {
        "offer_followup": mark_in_progress(followup, call_type, now),
        "audit_log": emit_audit(
            node="voice_scheduler", event="VOICE_CALL_INITIATED",
            payload_summary=(
                f"{call_type} follow-up call placed to {mask_phone(phone)} "
                f"regarding Offer Letter "
                f"{(state.get('offer_letter') or {}).get('document_number')}."
            ),
            actor="VOICE_AGENT",
        ),
    })

    from voice import dispatch

    try:
        await dispatch.place_call(
            thread_id=thread_id, call_id=claim_id, call_type=call_type,
            phone_number=phone, state=state,
        )
        return f"[voice] thread {thread_id}: {call_type} call dialing (call_id={claim_id})"
    except Exception as exc:
        # The dial never happened, so release the claim — otherwise a transient
        # provider error would permanently consume the candidate's call slot.
        from core.voice_flow import advance
        from core.voice_state import CallOutcome

        await voice_calls.update_call(
            claim_id, call_status="FAILED",
            call_outcome=CallOutcome.CALL_FAILED.value, error_detail=str(exc)[:500],
        )
        await voice_calls.release_claim(claim_id)

        ours = dispatch.is_infrastructure_failure(exc)
        latest = dict((await graph.aget_state(config)).values.get("offer_followup") or {})

        if ours:
            # Our network or our configuration failed, not the candidate's
            # phone. Re-arm WITHOUT spending an attempt, so a wifi drop cannot
            # silently exhaust the budget and close the workflow for good.
            latest.update({
                "attempts": max(0, int(latest.get("attempts") or 1) - 1),
                "state": followup.get("state"),
                "due_at": next_calling_slot(
                    now + timedelta(minutes=retry_delay_minutes())).isoformat(),
                "last_outcome": CallOutcome.CALL_FAILED.value,
            })
            next_followup = latest
        else:
            next_followup = advance(
                latest, call_type=call_type,
                outcome=CallOutcome.CALL_FAILED.value, now=now,
            )

        await graph.aupdate_state(config, {
            "offer_followup": next_followup,
            "audit_log": emit_audit(
                node="voice_scheduler", event="VOICE_CALL_FAILED",
                payload_summary=(
                    f"Could not place the {call_type} call: {exc}"
                    + (" (our side — attempt not counted)" if ours else "")
                ),
                actor="VOICE_AGENT",
            ),
        })
        return f"[voice] thread {thread_id}: dial failed{' (not counted)' if ours else ''} — {exc}"


async def run_scheduler(get_graph, db_url: str, stop: asyncio.Event) -> None:
    """
    Poll loop. `get_graph` is a callable so the task can start before the graph
    finishes building without capturing a None reference.
    """
    print(
        f"[scheduler] auto-send poller started "
        f"(every {POLL_SECONDS}s, grace {GRACE_MINUTES}m)"
    )
    while not stop.is_set():
        try:
            graph = get_graph()
            if graph is not None:
                now = datetime.now(timezone.utc)
                for tid in await _thread_ids(db_url):
                    try:
                        line = await _process_thread(graph, tid, now)
                        if line:
                            print(line)
                    except Exception as exc:
                        # One bad thread must never kill the loop for the rest.
                        print(f"[scheduler] thread {tid} failed: {exc}")

                    # Separate try: an email-schedule failure must not skip the
                    # voice pass, and vice versa.
                    try:
                        line = await _process_voice_followup(graph, tid, now)
                        if line:
                            print(line)
                    except Exception as exc:
                        print(f"[voice] thread {tid} failed: {exc}")
        except Exception as exc:
            print(f"[scheduler] poll failed: {exc}")

        try:
            await asyncio.wait_for(stop.wait(), timeout=POLL_SECONDS)
        except asyncio.TimeoutError:
            pass

    print("[scheduler] stopped")
