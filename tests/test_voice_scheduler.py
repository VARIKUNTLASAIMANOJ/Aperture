"""
The scheduler branch (§5, §14, §19) end to end on the real graph.

Exercises the actual `_process_voice_followup` — real eligibility checks, real
database claim, real dispatch call — with only the outbound dial stubbed. No
email is sent and no phone rings.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
os.environ["VOICE_AGENT_ENABLED"] = "true"
os.environ["OFFER_CALL_DELAY_MINUTES"] = "3"
os.environ.setdefault("CANDIDATE_TOKEN_SECRET", "test-secret-for-unit-tests")

from langgraph.checkpoint.memory import MemorySaver  # noqa: E402

import agents.email_node as email_node_mod  # noqa: E402
import core.scheduler as scheduler  # noqa: E402
import voice.dispatch as dispatch  # noqa: E402
from core.graph import build_graph  # noqa: E402
from core.voice_state import FollowupState  # noqa: E402
from db import voice_calls  # noqa: E402

pytestmark = pytest.mark.asyncio

LATER = datetime.now(timezone.utc) + timedelta(hours=1)

SEED = dict(
    candidate_id="CAND-S1", candidate_name="Manoj",
    candidate_email="candidate@example.com", candidate_phone="+919876543210",
    role_title="Finance Executive", designation="Finance Executive",
    department="Finance", employment_type="FULL_TIME", selection_status="SELECTED",
    start_date="2026-12-01", work_location_state="KA", work_location_city="Bengaluru",
    raw_compensation_input={"total_ctc": 2500000, "tax_regime": "NEW",
                            "work_state": "KA", "work_city": "Bengaluru",
                            "employment_type": "FULL_TIME", "performance_bonus": 0},
    offer_letter={"status": "NOT_CREATED"}, appointment_letter={"status": "NOT_ELIGIBLE"},
    offer_followup={"state": "NOT_APPLICABLE", "attempts": 0, "do_not_contact": False},
    email_queue=[], audit_log=[], approval_status="NEEDS_APPROVAL",
)


@pytest.fixture(scope="module", autouse=True)
def _require_db():
    import psycopg
    try:
        with psycopg.connect(voice_calls._dsn(), connect_timeout=3) as conn:
            conn.execute("SELECT 1")
    except Exception as exc:
        pytest.skip(f"Postgres unavailable: {exc}")


@pytest_asyncio.fixture
async def armed(monkeypatch):
    """A thread whose offer was dispatched and whose follow-up is now due."""
    await voice_calls.setup()
    monkeypatch.setattr(email_node_mod, "send_email",
                        lambda to_email, subject, html_body: "msg_1")

    tid = f"test-{uuid.uuid4()}"
    graph = await build_graph(MemorySaver())
    cfg = {"configurable": {"thread_id": tid}}
    await graph.ainvoke(dict(SEED), config=cfg)
    await graph.aupdate_state(cfg, {"approval_status": "APPROVED",
                                    "approver_email": "hr@company.com"})
    await graph.ainvoke(None, config=cfg)

    # Make it due now, inside calling hours.
    fu = dict((await graph.aget_state(cfg)).values["offer_followup"])
    fu["due_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    await graph.aupdate_state(cfg, {"offer_followup": fu})

    yield graph, cfg, tid

    import psycopg
    async with await psycopg.AsyncConnection.connect(voice_calls._dsn()) as conn:
        await conn.execute("DELETE FROM voice_calls WHERE thread_id = %s", (tid,))
        await conn.commit()


async def _state(graph, cfg):
    return dict((await graph.aget_state(cfg)).values)


def _force_window(monkeypatch):
    """Pin the calling-hours check open so the suite passes at any hour."""
    monkeypatch.setattr("core.voice_state.within_calling_hours", lambda now=None: True)
    monkeypatch.setattr("core.voice_flow.next_calling_slot",
                        lambda dt: dt if isinstance(dt, datetime) else dt)


async def test_due_followup_places_a_call(armed, monkeypatch):
    graph, cfg, tid = armed
    _force_window(monkeypatch)

    placed = {}

    async def fake_place(**kw):
        placed.update(kw)
        return "sip_participant_1"

    monkeypatch.setattr(dispatch, "place_call", fake_place)

    line = await scheduler._process_voice_followup(graph, tid, datetime.now(timezone.utc))

    assert placed["phone_number"] == "+919876543210"
    assert placed["call_type"] == "INITIAL"
    assert placed["thread_id"] == tid
    assert "dialing" in (line or "")

    st = await _state(graph, cfg)
    assert st["offer_followup"]["state"] == FollowupState.INITIAL_CALL_IN_PROGRESS.value
    assert st["offer_followup"]["attempts"] == 1
    assert any(a["event"] == "VOICE_CALL_INITIATED" for a in st["audit_log"])


async def test_acceptance_during_the_window_prevents_the_call(armed, monkeypatch):
    """§6 Case 3 — eligibility is re-checked at dial time, not only at schedule time."""
    graph, cfg, tid = armed
    _force_window(monkeypatch)

    called = []
    monkeypatch.setattr(dispatch, "place_call",
                        lambda **kw: called.append(kw))

    st = await _state(graph, cfg)
    await graph.aupdate_state(cfg, {
        "offer_letter": {**st["offer_letter"], "status": "ACCEPTED"}})

    await scheduler._process_voice_followup(graph, tid, datetime.now(timezone.utc))

    assert called == [], "a candidate who accepted must never be dialed"
    st = await _state(graph, cfg)
    assert st["offer_followup"]["state"] == FollowupState.CLOSED.value
    assert "accepted" in (st["offer_followup"]["closed_reason"] or "").lower()


async def test_second_poll_does_not_place_a_second_call(armed, monkeypatch):
    """§15 — a repeated poll, retry or restart must not dial twice."""
    graph, cfg, tid = armed
    _force_window(monkeypatch)

    calls = []

    async def fake_place(**kw):
        calls.append(kw)
        return "sip_1"

    monkeypatch.setattr(dispatch, "place_call", fake_place)

    now = datetime.now(timezone.utc)
    await scheduler._process_voice_followup(graph, tid, now)
    await scheduler._process_voice_followup(graph, tid, now)

    assert len(calls) == 1


async def test_missing_telephony_fails_loudly_and_releases_the_claim(armed, monkeypatch):
    """A dial that never happened must not burn the candidate's only slot."""
    graph, cfg, tid = armed
    _force_window(monkeypatch)

    async def unconfigured(**kw):
        raise dispatch.TelephonyNotConfigured("LIVEKIT_SIP_TRUNK_ID is not set.")

    monkeypatch.setattr(dispatch, "place_call", unconfigured)

    line = await scheduler._process_voice_followup(graph, tid, datetime.now(timezone.utc))
    assert "dial failed" in (line or "")

    st = await _state(graph, cfg)
    # Re-armed for a retry rather than closed or stuck IN_PROGRESS.
    assert st["offer_followup"]["state"] == FollowupState.WAITING_FOR_INITIAL_CALL.value
    assert any(a["event"] == "VOICE_CALL_FAILED" for a in st["audit_log"])

    rows = await voice_calls.calls_for_thread(tid)
    assert rows == [] or all(r["call_status"] == "FAILED" for r in rows)


async def test_network_failure_does_not_burn_an_attempt(armed, monkeypatch):
    """
    A wifi drop is not the candidate's fault.

    Several real threads were closed permanently after a laptop lost DNS for
    half a minute: three "attempts" were spent without the phone ever ringing.
    Infrastructure failures must re-arm without counting.
    """
    graph, cfg, tid = armed
    _force_window(monkeypatch)

    async def dns_dead(**kw):
        raise RuntimeError(
            "Cannot connect to host onboard.livekit.cloud:443 ssl:default "
            "[Could not contact DNS servers]")

    monkeypatch.setattr(dispatch, "place_call", dns_dead)

    for _ in range(5):
        await scheduler._process_voice_followup(graph, tid, datetime.now(timezone.utc))

    fu = (await _state(graph, cfg))["offer_followup"]
    assert fu["state"] == FollowupState.WAITING_FOR_INITIAL_CALL.value, \
        "a network blip must never close the workflow"
    assert fu["attempts"] == 0, f"attempts should not accrue, got {fu['attempts']}"


async def test_carrier_rejection_does_count(armed, monkeypatch):
    """A real answer from the carrier is a real attempt."""
    graph, cfg, tid = armed
    _force_window(monkeypatch)

    async def rejected(**kw):
        raise RuntimeError(
            "SIP call failed: 400 32100 Trial accounts can only call "
            "verified caller IDs. (invalid_argument)")

    monkeypatch.setattr(dispatch, "place_call", rejected)
    await scheduler._process_voice_followup(graph, tid, datetime.now(timezone.utc))

    fu = (await _state(graph, cfg))["offer_followup"]
    assert fu["attempts"] == 1


async def test_misconfiguration_does_not_burn_an_attempt(armed, monkeypatch):
    """The operator must fix it; the candidate should not pay for it."""
    graph, cfg, tid = armed
    _force_window(monkeypatch)

    async def unconfigured(**kw):
        raise dispatch.TelephonyNotConfigured("LIVEKIT_SIP_TRUNK_ID is not a trunk id.")

    monkeypatch.setattr(dispatch, "place_call", unconfigured)
    for _ in range(4):
        await scheduler._process_voice_followup(graph, tid, datetime.now(timezone.utc))

    fu = (await _state(graph, cfg))["offer_followup"]
    assert fu["attempts"] == 0
    assert fu["state"] == FollowupState.WAITING_FOR_INITIAL_CALL.value


async def test_not_due_yet_does_nothing(armed, monkeypatch):
    graph, cfg, tid = armed
    _force_window(monkeypatch)

    called = []
    monkeypatch.setattr(dispatch, "place_call", lambda **kw: called.append(kw))

    fu = dict((await _state(graph, cfg))["offer_followup"])
    fu["due_at"] = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    await graph.aupdate_state(cfg, {"offer_followup": fu})

    assert await scheduler._process_voice_followup(
        graph, tid, datetime.now(timezone.utc)) is None
    assert called == []


async def test_disabled_flag_stops_the_scheduler_branch(armed, monkeypatch):
    graph, cfg, tid = armed
    monkeypatch.setenv("VOICE_AGENT_ENABLED", "false")

    called = []
    monkeypatch.setattr(dispatch, "place_call", lambda **kw: called.append(kw))

    assert await scheduler._process_voice_followup(
        graph, tid, datetime.now(timezone.utc)) is None
    assert called == []
