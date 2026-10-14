"""
Offer Letter node (§1).

Replaces the LLM-authored contract for the offer stage. The document is
rendered deterministically from state — no model sits between the computed
salary and the letter the candidate reads.

Produces a DRAFT offer record plus the queued email; the actual release
happens when HR approves dispatch at the existing HITL gate.
"""

from __future__ import annotations

from datetime import datetime, timezone

from langchain_core.runnables import RunnableConfig

from core.india.documents import render_offer_letter
from core.state import EmailQueueItem, NodeStatus, OfferLetterStatus, OnboardingState
from utils.audit import emit_audit
from utils.tokens import PURPOSE_OFFER, issue_token


async def offer_node(state: OnboardingState, config: RunnableConfig) -> dict:
    candidate_id = state.get("candidate_id", "UNKNOWN")

    try:
        html, doc_no, expires_at = render_offer_letter(dict(state))

        # One token per thread, minted here and reused for every candidate
        # action on this offer. Signed over thread + purpose, so it cannot be
        # replayed against the appointment endpoints.
        thread_id = (config or {}).get("configurable", {}).get("thread_id", "")
        token = state.get("candidate_access_token") or issue_token(thread_id, PURPOSE_OFFER)

        now = datetime.now(timezone.utc).isoformat()
        offer_record = {
            "document_type": "OFFER_LETTER",
            "status": OfferLetterStatus.DRAFT.value,
            "html": html,
            "generated_at": now,
            "expires_at": expires_at,
            "document_number": doc_no,
        }

        email: EmailQueueItem = {
            "template_name": "offer_letter_email",
            "recipient_email": state.get("candidate_email", ""),
            "recipient_name": state.get("candidate_name", ""),
            "variables": {
                "candidate_name": state.get("candidate_name", ""),
                "designation": state.get("designation") or state.get("role_title", ""),
                "offer_letter_html": html,
                "document_number": doc_no,
                "action_token": token,
                "thread_id": thread_id,
            },
            "status": "PENDING",
            "message_id": None,
        }

        return {
            "current_node": "offer_node",
            "node_status": NodeStatus.COMPLETE,
            "offer_letter": offer_record,
            # Legacy mirror so the existing correspondence log keeps working.
            "offer_letter_html": html,
            "candidate_access_token": token,
            "approval_status": "NEEDS_APPROVAL",
            "email_queue": [*state.get("email_queue", []), email],
            "error_message": None,
            "audit_log": emit_audit(
                node="offer_node",
                event="OFFER_LETTER_GENERATED",
                payload_summary=(
                    f"Offer Letter {doc_no} drafted for {candidate_id}. "
                    f"Awaiting HR release. Valid until {expires_at[:10]}."
                ),
            ),
        }

    except Exception as exc:
        return {
            "current_node": "offer_node",
            "node_status": NodeStatus.ERROR,
            "error_message": str(exc),
            "audit_log": emit_audit(
                node="offer_node",
                event="OFFER_LETTER_ERROR",
                payload_summary=f"{candidate_id}: offer generation failed — {exc}",
            ),
        }


def route_after_offer(state: OnboardingState) -> str:
    if state.get("node_status") == NodeStatus.ERROR:
        return "error_handler"
    return "email_node"
