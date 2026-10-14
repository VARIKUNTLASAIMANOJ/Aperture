"""
Recovering a dispatch that failed.

The bug: `route_after_dispatch` sent a failed offer dispatch to END. The
thread had no `next` node, so nothing could resume it — every Resend bounce
permanently stranded a candidate, and the dashboard could count those threads
but never act on one.

The fix routes a failure back to the dispatch node, which `interrupt_before`
turns into "park at the gate". These tests pin that: a failed thread must stay
resumable, and a retry must travel the same send path.
"""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
os.environ.setdefault("CANDIDATE_TOKEN_SECRET", "test-secret-for-unit-tests")
os.environ["VOICE_AGENT_ENABLED"] = "false"   # keep the call path out of this

from langgraph.checkpoint.memory import MemorySaver  # noqa: E402

import agents.email_node as email_node_mod  # noqa: E402
from core.graph import build_graph  # noqa: E402
from core.lifecycle import offer_status  # noqa: E402

pytestmark = pytest.mark.asyncio

SEED = dict(
    candidate_id="CAND-R1", candidate_name="Manoj",
    candidate_email="bounces@example.com",
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

BOUNCE = "Invalid `to` field. Please use our testing email address."


class Mailer:
    """Fails until `fail` is cleared, so a retry can be made to succeed."""

    def __init__(self, fail: bool = True):
        self.fail = fail
        self.sent: list[tuple[str, str]] = []

    def __call__(self, to_email, subject, html_body):
        if self.fail:
            raise RuntimeError(BOUNCE)
        self.sent.append((to_email, subject))
        return f"msg_{len(self.sent)}"


async def _approve_and_dispatch(graph, cfg):
    await graph.aupdate_state(cfg, {"approval_status": "APPROVED",
                                    "approver_email": "hr@company.com"})
    await graph.ainvoke(None, config=cfg)


async def _run(monkeypatch, mailer, thread) -> tuple:
    monkeypatch.setattr(email_node_mod, "send_email", mailer)
    graph = await build_graph(MemorySaver())
    cfg = {"configurable": {"thread_id": thread}}
    await graph.ainvoke(dict(SEED), config=cfg)
    await _approve_and_dispatch(graph, cfg)
    return graph, cfg


async def _snapshot(graph, cfg):
    s = await graph.aget_state(cfg)
    return dict(s.values), s.next


# ── The core regression ─────────────────────────────────────────────────────

async def test_failed_dispatch_leaves_the_thread_resumable(monkeypatch):
    """The whole bug in one assertion: `next` must not be empty."""
    graph, cfg = await _run(monkeypatch, Mailer(fail=True), "r1")
    st, nxt = await _snapshot(graph, cfg)

    assert offer_status(st) == "DRAFT"
    assert nxt == ("email_node",), (
        f"a failed dispatch must park at the gate, got next={nxt!r} — "
        f"an empty tuple means the thread is stranded at END"
    )


async def test_failed_dispatch_does_not_release_the_offer(monkeypatch):
    graph, cfg = await _run(monkeypatch, Mailer(fail=True), "r2")
    st, _ = await _snapshot(graph, cfg)
    assert offer_status(st) == "DRAFT"
    assert [e["status"] for e in st["email_queue"]] == ["FAILED"]


async def test_retrying_after_fixing_the_address_sends_and_releases(monkeypatch):
    """The full recovery, exactly as the endpoint performs it."""
    mailer = Mailer(fail=True)
    graph, cfg = await _run(monkeypatch, mailer, "r3")

    st, _ = await _snapshot(graph, cfg)
    queue = [{**e, "status": "PENDING", "message_id": None,
              "recipient_email": "real@company.com"}
             if e["status"] == "FAILED" else e
             for e in st["email_queue"]]

    mailer.fail = False
    await graph.aupdate_state(cfg, {"email_queue": queue,
                                    "candidate_email": "real@company.com",
                                    "approval_status": "APPROVED"})
    await graph.ainvoke(None, config=cfg)

    st, nxt = await _snapshot(graph, cfg)
    assert mailer.sent and mailer.sent[0][0] == "real@company.com"
    assert offer_status(st) == "RELEASED"
    assert nxt == ("offer_gate",), f"should now await the candidate, got {nxt!r}"


async def test_a_second_failure_parks_again_rather_than_stranding(monkeypatch):
    """Retrying into the same bad address must stay recoverable."""
    mailer = Mailer(fail=True)
    graph, cfg = await _run(monkeypatch, mailer, "r4")

    for _ in range(3):
        st, _ = await _snapshot(graph, cfg)
        queue = [{**e, "status": "PENDING"} if e["status"] == "FAILED" else e
                 for e in st["email_queue"]]
        await graph.aupdate_state(cfg, {"email_queue": queue,
                                        "approval_status": "APPROVED"})
        await graph.ainvoke(None, config=cfg)

    st, nxt = await _snapshot(graph, cfg)
    assert nxt == ("email_node",)
    assert offer_status(st) == "DRAFT"


async def test_parking_does_not_resend_on_its_own(monkeypatch):
    """
    The self-edge must not become a send loop: routing back to email_node has
    to PARK (interrupt_before), not re-run it.
    """
    mailer = Mailer(fail=True)
    graph, cfg = await _run(monkeypatch, mailer, "r5")
    attempts_after_first = len(mailer.sent)

    # Resuming without resetting the queue: the item is FAILED, so email_node
    # skips it. Nothing should be sent, and it must still be parked.
    await graph.ainvoke(None, config=cfg)
    st, nxt = await _snapshot(graph, cfg)

    assert len(mailer.sent) == attempts_after_first
    assert nxt == ("email_node",)


# ── The paths that must still terminate ─────────────────────────────────────

async def test_hr_rejection_still_ends_the_thread(monkeypatch):
    """A cancelled dispatch is finished, not retryable — it must reach END."""
    monkeypatch.setattr(email_node_mod, "send_email", Mailer(fail=False))
    graph = await build_graph(MemorySaver())
    cfg = {"configurable": {"thread_id": "r6"}}
    await graph.ainvoke(dict(SEED), config=cfg)

    await graph.aupdate_state(cfg, {"approval_status": "REJECTED",
                                    "approver_email": "hr@company.com"})
    await graph.ainvoke(None, config=cfg)

    st, nxt = await _snapshot(graph, cfg)
    assert nxt == (), f"a rejected dispatch must terminate, got {nxt!r}"
    assert [e["status"] for e in st["email_queue"]] == ["CANCELLED"]


async def test_successful_dispatch_is_unchanged(monkeypatch):
    """The happy path must not have moved."""
    mailer = Mailer(fail=False)
    graph, cfg = await _run(monkeypatch, mailer, "r7")
    st, nxt = await _snapshot(graph, cfg)

    assert offer_status(st) == "RELEASED"
    assert nxt == ("offer_gate",)
    assert len(mailer.sent) == 1


async def test_a_thread_already_stranded_at_end_can_be_revived(monkeypatch):
    """
    Threads that reached END under the OLD routing must still be recoverable.

    Those exist in the live database — `next` is empty, so nothing can resume
    them. Reproduced here by forcing the old behaviour, then checking that the
    retry path (reset FAILED → PENDING, then update) brings the thread back to
    the dispatch gate. `aupdate_state` re-runs the router, which is what makes
    the revival possible at all.
    """
    import core.graph as graph_mod

    mailer = Mailer(fail=True)
    monkeypatch.setattr(email_node_mod, "send_email", mailer)

    # The pre-fix router: a failed dispatch goes straight to END.
    # Patched on core.graph, not on agents.lifecycle_nodes — build_graph
    # imported the function by name, so it holds its own reference and
    # patching the defining module has no effect on the compiled graph.
    monkeypatch.setattr(graph_mod, "route_after_dispatch",
                        lambda state: "__end__", raising=True)

    checkpointer = MemorySaver()
    graph = await build_graph(checkpointer)
    cfg = {"configurable": {"thread_id": "legacy"}}
    await graph.ainvoke(dict(SEED), config=cfg)
    await _approve_and_dispatch(graph, cfg)

    _, nxt = await _snapshot(graph, cfg)
    assert nxt == (), "precondition: the thread must be stranded at END"

    # Rebuild with the real router — the deployed code — against the SAME
    # checkpointer, so the stranded thread is carried over exactly as a
    # restart would carry it.
    monkeypatch.undo()
    monkeypatch.setattr(email_node_mod, "send_email", mailer)
    graph = await build_graph(checkpointer)

    st, _ = await _snapshot(graph, cfg)
    queue = [{**e, "status": "PENDING", "message_id": None,
              "recipient_email": "real@company.com"}
             if e["status"] == "FAILED" else e
             for e in st["email_queue"]]
    mailer.fail = False
    await graph.aupdate_state(cfg, {"email_queue": queue,
                                    "candidate_email": "real@company.com",
                                    "approval_status": "APPROVED"})

    _, revived = await _snapshot(graph, cfg)
    assert revived == ("email_node",), (
        f"the stranded thread should be back at the gate, got {revived!r}"
    )

    await graph.ainvoke(None, config=cfg)
    st, nxt = await _snapshot(graph, cfg)
    assert mailer.sent and mailer.sent[0][0] == "real@company.com"
    assert offer_status(st) == "RELEASED"
    assert nxt == ("offer_gate",)
