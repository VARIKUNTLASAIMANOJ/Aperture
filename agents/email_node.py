"""
Email Dispatch Node — Human-in-the-Loop Gate
─────────────────────────────────────────────
LangGraph's `interrupt_before=["email_node"]` suspends graph execution here.
The FastAPI /approve endpoint resumes the graph with approval_status=APPROVED.
On approval: renders Jinja2 HTML templates and dispatches via Resend API.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from jinja2 import Environment, FileSystemLoader, select_autoescape
from langchain_core.runnables import RunnableConfig

from core.state import ApprovalStatus, NodeStatus, OfferLetterStatus, OnboardingState
from core.voice_state import (
    FollowupState, initial_delay_minutes, next_calling_slot, voice_enabled,
)
from utils.audit import emit_audit
from utils.resend_client import send_email  # Resend replaces SMTP

# ---------------------------------------------------------------------------
# Jinja2 environment (templates in /templates/)
# ---------------------------------------------------------------------------

_jinja_env = Environment(
    loader=FileSystemLoader("templates"),
    autoescape=select_autoescape(["html"]),
)


def _render_template(template_name: str, variables: dict) -> str:
    """Render a Jinja2 template from /templates/ directory."""
    tmpl = _jinja_env.get_template(f"{template_name}.html.j2")
    return tmpl.render(**variables)


SUBJECT_BUILDERS = {
    "offer_letter":     lambda v: f"Your Offer Letter — {v.get('role_title', 'Position')}",
    "rejection_notice": lambda v: "Your Application Status Update",
    "offer_letter_email":
        lambda v: f"Your Offer Letter — {v.get('designation', 'Position')}",
    "appointment_letter_email":
        lambda v: f"Your Appointment Letter — {v.get('designation', 'Position')}",
}


def render_email(item: dict) -> tuple[str, str]:
    """
    Return (subject, full_html) for a queue item — exactly what Resend is
    handed.

    Shared by the dispatch node and the read-only messages endpoint so a
    preview can never drift from what actually gets sent. Previously the
    subject map lived inline inside the node, which meant any second caller
    would have had to duplicate it.
    """
    variables = {
        # Base URL for candidate action links. Injected here so every template
        # gets it without each node having to remember to pass it.
        "portal_url": os.environ.get("CANDIDATE_PORTAL_URL", "http://localhost:3000"),
        **item.get("variables", {}),
    }
    subject_fn = SUBJECT_BUILDERS.get(
        item.get("template_name", ""), lambda v: "HR Notification"
    )
    return subject_fn(variables), _render_template(item["template_name"], variables)


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

async def email_node(state: OnboardingState, config: RunnableConfig) -> dict:
    """
    LangGraph node: dispatches all PENDING emails in the queue via Resend.

    ⚠️  Registered with interrupt_before in the graph builder.
    Execution only reaches this function body AFTER HR has called /approve.
    """
    approval    = state.get("approval_status")
    email_queue = state.get("email_queue", [])

    # HR explicitly rejected the dispatch — cancel pending items and terminate
    # cleanly so the thread reaches END rather than sitting interrupted forever.
    if approval == ApprovalStatus.REJECTED:
        # SCHEDULED counts as undispatched: a rejection must also tear down a
        # future auto-send, or the letter would still go out on its timer.
        OPEN = ("PENDING", "SCHEDULED")
        cancelled = [
            {**item, "status": "CANCELLED", "scheduled_for": None}
            if item.get("status") in OPEN else item
            for item in email_queue
        ]
        cancelled_count = sum(1 for i in email_queue if i.get("status") in OPEN)
        return {
            "current_node": "email_node",
            "node_status":  NodeStatus.COMPLETE,
            "email_queue":  cancelled,
            "audit_log": emit_audit(
                node="email_node",
                event="DISPATCH_REJECTED",
                payload_summary=(
                    f"HR rejected dispatch — {cancelled_count} email(s) cancelled, none sent. "
                    f"Rejected by {state.get('approver_email', 'UNKNOWN')}."
                ),
                actor=f"HR_{state.get('approver_email', 'UNKNOWN')}",
            ),
        }

    # Guard: if somehow invoked without approval, block
    if approval != ApprovalStatus.APPROVED:
        return {
            "current_node": "email_node",
            "node_status":  NodeStatus.WAITING_HITL,
            "audit_log": emit_audit(
                node="email_node",
                event="WAITING_FOR_APPROVAL",
                payload_summary="Email dispatch halted — waiting for HR approval.",
            ),
        }

    updated_queue: list = []
    sent_count    = 0
    failed_ids:  list[str] = []

    for item in email_queue:
        # SCHEDULED items are intentionally skipped: the scheduler flips them
        # to PENDING when their time arrives, and only then do they dispatch.
        if item.get("status") != "PENDING":
            updated_queue.append(item)
            continue

        # Absent on manually-approved items; the scheduler sets AUTO up front.
        mode = item.get("dispatch_mode") or "MANUAL"

        try:
            # Same renderer the messages endpoint uses, so a preview can never
            # drift from what is actually dispatched.
            subject, html_body = render_email(item)

            # ── Dispatch via Resend ───────────────────────────────────────────
            message_id = send_email(
                to_email  = item["recipient_email"],
                subject   = subject,
                html_body = html_body,
            )

            updated_queue.append({
                **item,
                "status":        "SENT",
                "message_id":    message_id,
                "dispatch_mode": mode,
                # Recorded here rather than derived later: this is the only
                # moment the real dispatch time is known.
                "sent_at":       datetime.now(timezone.utc).isoformat(),
            })
            sent_count += 1

        except Exception as exc:
            updated_queue.append({
                **item,
                "status":        "FAILED",
                "message_id":    str(exc),
                "dispatch_mode": mode,
                "sent_at":       datetime.now(timezone.utc).isoformat(),
            })
            failed_ids.append(item["recipient_email"])

    final_status = NodeStatus.COMPLETE if not failed_ids else NodeStatus.ERROR

    patch: dict = {
        "current_node": "email_node",
        "node_status":  final_status,
        "email_queue":  updated_queue,
        "audit_log": emit_audit(
            node="email_node",
            event="EMAILS_DISPATCHED",
            payload_summary=(
                f"Resend: dispatched {sent_count} email(s). "
                f"{'Failed: ' + str(failed_ids) if failed_ids else 'All succeeded.'}"
            ),
        ),
    }

    # The Offer Letter becomes RELEASED at the moment its email actually
    # leaves — not when an endpoint says so.
    #
    # Three different paths approve this dispatch: the HITL /approve gate, the
    # auto-send scheduler, and /offer/release. Only the last one set the status,
    # so approving from the run panel put the letter in the candidate's inbox
    # while the server still held it as DRAFT. The candidate portal then read
    # "not yet released" and Rule 3 refused their acceptance. Deriving the
    # transition from the dispatch itself is the only way all three paths agree.
    #
    # Keyed on the template name, so this is inert when the same function runs
    # as `appointment_dispatch` (onboarding_node owns that transition).
    offer = dict(state.get("offer_letter") or {})
    offer_sent = any(
        i.get("template_name") == "offer_letter_email" and i.get("status") == "SENT"
        for i in updated_queue
    )
    undispatched = (None, "", OfferLetterStatus.NOT_CREATED.value, OfferLetterStatus.DRAFT.value)
    if offer_sent and offer.get("status") in undispatched:
        offer.update({
            "status":      OfferLetterStatus.RELEASED.value,
            "released_at": datetime.now(timezone.utc).isoformat(),
            "released_by": state.get("approver_email") or "hr-console",
        })
        patch["offer_letter"] = offer

        # §14 — arm the voice follow-up from the dispatch event itself, so a
        # thread is only ever called about an offer that genuinely reached the
        # candidate. The due time is persisted in the checkpoint rather than
        # held by a timer, so a restart re-discovers it (§15).
        if voice_enabled() and state.get("candidate_phone"):
            due = next_calling_slot(
                datetime.now(timezone.utc)
                + timedelta(minutes=initial_delay_minutes())
            )
            patch["offer_followup"] = {
                **(state.get("offer_followup") or {}),
                "state": FollowupState.WAITING_FOR_INITIAL_CALL.value,
                "due_at": due.isoformat(),
                "attempts": 0,
                "do_not_contact": bool(
                    (state.get("offer_followup") or {}).get("do_not_contact")),
                "armed_at": datetime.now(timezone.utc).isoformat(),
            }

        patch["audit_log"] = patch["audit_log"] + emit_audit(
            node="email_node",
            event="OFFER_LETTER_RELEASED",
            payload_summary=(
                f"Offer Letter {offer.get('document_number')} released to "
                f"{state.get('candidate_name')} on dispatch. "
                f"The candidate can now accept or decline."
            ),
            actor=f"HR_{state.get('approver_email', 'UNKNOWN')}",
        )

    return patch