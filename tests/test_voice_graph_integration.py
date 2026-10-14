"""
The follow-up must be armed by the real graph, not just by a unit test calling
arm_initial directly — and the August offer-release behaviour must survive the
change. Runs the actual StateGraph on an in-memory checkpointer with Resend
stubbed; no network, no telephony.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
os.environ["VOICE_AGENT_ENABLED"] = "true"
os.environ["OFFER_CALL_DELAY_MINUTES"] = "3"
os.environ.setdefault("CANDIDATE_TOKEN_SECRET", "test-secret-for-unit-tests")

from langgraph.checkpoint.memory import MemorySaver  # noqa: E402

import agents.email_node as email_node_mod  # noqa: E402
from core.graph import build_graph  # noqa: E402
from core.lifecycle import can_call_candidate, offer_status  # noqa: E402
from core.voice_flow import call_type_for, is_due  # noqa: E402
from core.voice_state import CallType, FollowupState  # noqa: E402

pytestmark = pytest.mark.asyncio

SEED = dict(
    candidate_id="CAND-V1",
    candidate_name="Manoj",
    candidate_email="candidate@example.com",
    candidate_phone="+919876543210",
    role_title="Finance Executive",
    designation="Finance Executive",
    department="Finance",
    employment_type="FULL_TIME",
    selection_status="SELECTED",
    start_date="2026-12-01",
    work_location_state="KA",
    work_location_city="Bengaluru",
    reporting_manager="A. Rao",
    raw_compensation_input={
        "total_ctc": 2500000, "tax_regime": "NEW", "work_state": "KA",
        "work_city": "Bengaluru", "employment_type": "FULL_TIME",
        "performance_bonus": 0,
    },
    offer_letter={"status": "NOT_CREATED"},
    appointment_letter={"status": "NOT_ELIGIBLE"},
    offer_followup={"state": "NOT_APPLICABLE", "attempts": 0, "do_not_contact": False},
    email_queue=[], audit_log=[], approval_status="NEEDS_APPROVAL",
)


@pytest.fixture
def stub_resend(monkeypatch):
    sent = []

    def fake_send(to_email, subject, html_body):
        sent.append((to_email, subject))
        return f"msg_{len(sent)}"

    monkeypatch.setattr(email_node_mod, "send_email", fake_send)
    return sent


async def _run_to_dispatch(seed: dict, thread: str):
    graph = await build_graph(MemorySaver())
    cfg = {"configurable": {"thread_id": thread}}
    await graph.ainvoke(dict(seed), config=cfg)
    await graph.aupdate_state(cfg, {
        "approval_status": "APPROVED", "approver_email": "hr@company.com"})
    await graph.ainvoke(None, config=cfg)
    return graph, cfg, dict((await graph.aget_state(cfg)).values)


async def test_dispatch_arms_the_followup(stub_resend):
    _, _, st = await _run_to_dispatch(SEED, "v1")

    assert offer_status(st) == "RELEASED"          # August behaviour intact
    fu = st["offer_followup"]
    assert fu["state"] == FollowupState.WAITING_FOR_INITIAL_CALL.value
    assert fu["due_at"] and fu["attempts"] == 0
    assert call_type_for(fu) == CallType.INITIAL.value


async def test_followup_is_not_due_immediately(stub_resend):
    _, _, st = await _run_to_dispatch(SEED, "v2")
    assert not is_due(st["offer_followup"], datetime.now(timezone.utc))


async def test_failed_dispatch_arms_nothing(monkeypatch):
    """No mail, no release, no call — the three must stay consistent."""
    def boom(to_email, subject, html_body):
        raise RuntimeError("Invalid `to` field.")

    monkeypatch.setattr(email_node_mod, "send_email", boom)
    _, _, st = await _run_to_dispatch(SEED, "v3")

    assert offer_status(st) == "DRAFT"
    assert st["offer_followup"]["state"] == "NOT_APPLICABLE"
    assert not can_call_candidate(st)


async def test_candidate_without_phone_is_released_but_never_armed(stub_resend):
    """Missing phone must not block the offer — only the call."""
    seed = {**SEED, "candidate_phone": None}
    _, _, st = await _run_to_dispatch(seed, "v4")

    assert offer_status(st) == "RELEASED"
    assert st["offer_followup"]["state"] == "NOT_APPLICABLE"
    chk = can_call_candidate(st)
    assert not chk and "phone" in chk.reason.lower()


async def test_rejected_candidate_never_arms_a_call(monkeypatch):
    """§4 — a rejection email must not put anyone in the call queue."""
    sent = []
    monkeypatch.setattr(email_node_mod, "send_email",
                        lambda to_email, subject, html_body: sent.append(subject) or "m1")
    monkeypatch.setattr(
        "agents.triage_node.get_llm",
        lambda temperature=0.2: type("L", (), {
            "ainvoke": staticmethod(
                lambda msgs: _async_value(type("R", (), {"content": "<p>Thanks.</p>"})())
            )
        })(),
    )
    seed = {**SEED, "selection_status": "REJECTED"}
    _, _, st = await _run_to_dispatch(seed, "v5")

    assert st["offer_followup"]["state"] == "NOT_APPLICABLE"
    assert not can_call_candidate(st)


async def _async_value(v):
    return v


async def test_phone_is_read_from_the_offer_thread_only(stub_resend):
    """
    §3 — the number must come from the same record as the offer.

    Two live threads with different numbers: each state carries its own, and
    nothing in the call path can resolve a number by name or email.
    """
    _, _, a = await _run_to_dispatch({**SEED, "candidate_phone": "+919876543210"}, "vA")
    _, _, b = await _run_to_dispatch(
        {**SEED, "candidate_id": "CAND-V2", "candidate_phone": "+918123456789"}, "vB")

    assert a["candidate_phone"] == "+919876543210"
    assert b["candidate_phone"] == "+918123456789"
    assert a["candidate_name"] == b["candidate_name"]   # same name, different numbers
