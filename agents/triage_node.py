"""
Candidate Triage Node
─────────────────────
Evaluates selection_status and routes:
  REJECTED  → builds rejection email payload, queues it for HITL gate
  SELECTED  → validates required fields, transitions to financial_node
"""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from core.state import (
    ApprovalStatus,
    EmailQueueItem,
    NodeStatus,
    OnboardingState,
    SelectionStatus,
)
from utils.audit import emit_audit
from utils.llm import get_llm

# ---------------------------------------------------------------------------
# LLM prompt for empathetic rejection mail body generation
# (LLM used for prose ONLY — no financial logic here)
# ---------------------------------------------------------------------------

REJECTION_SYSTEM_PROMPT = """You are a compassionate HR communications specialist.
Generate a professional, empathetic rejection email body (HTML) for the candidate below.
Keep it warm, concise (3 short paragraphs), and never reveal specific reasons.
Return ONLY the inner HTML body — no <html>/<body> wrapper tags."""


async def triage_node(state: OnboardingState, config: RunnableConfig) -> dict:
    """LangGraph node: evaluate selection status and prepare next step."""

    candidate_name  = state.get("candidate_name",  "Candidate")
    candidate_email = state.get("candidate_email", "")
    role_title      = state.get("role_title",      "the role")
    status          = state.get("selection_status", SelectionStatus.PENDING)

    # ── REJECTED path ────────────────────────────────────────────────────────
    if status == SelectionStatus.REJECTED:
        llm = get_llm(temperature=0.4)   # Nemotron via NVIDIA NIM
        prompt = (
            f"Candidate: {candidate_name}\n"
            f"Role applied for: {role_title}\n"
            "Write the rejection email body."
        )
        response = await llm.ainvoke(
            [
                {"role": "system",  "content": REJECTION_SYSTEM_PROMPT},
                {"role": "user",    "content": prompt},
            ]
        )
        email_body_html: str = response.content  # type: ignore[attr-defined]

        rejection_email: EmailQueueItem = {
            "template_name":  "rejection_notice",
            "recipient_email": candidate_email,
            "recipient_name":  candidate_name,
            "variables": {
                "role_title":      role_title,
                "email_body_html": email_body_html,
            },
            "status":     "PENDING",
            "message_id": None,
        }

        return {
            "current_node":    "triage_node",
            "node_status":     NodeStatus.WAITING_HITL,
            "approval_status": ApprovalStatus.NEEDS_APPROVAL,
            "email_queue":     [*state.get("email_queue", []), rejection_email],
            "audit_log": emit_audit(
                node="triage_node",
                event="REJECTION_EMAIL_QUEUED",
                payload_summary=f"Rejection email prepared for candidate {state.get('candidate_id')}. Awaiting HR approval.",
            ),
        }

    # ── SELECTED path ────────────────────────────────────────────────────────
    # Validate required fields before advancing
    required = ["employment_type", "start_date", "raw_compensation_input"]
    missing  = [f for f in required if not state.get(f)]
    if missing:
        return {
            "current_node":  "triage_node",
            "node_status":   NodeStatus.ERROR,
            "error_message": f"Missing required fields for SELECTED path: {missing}",
            "audit_log": emit_audit(
                node="triage_node",
                event="VALIDATION_ERROR",
                payload_summary=f"Missing fields {missing} for candidate {state.get('candidate_id')}.",
            ),
        }

    return {
        "current_node": "triage_node",
        "node_status":  NodeStatus.COMPLETE,
        "audit_log": emit_audit(
            node="triage_node",
            event="CANDIDATE_SELECTED_ROUTED",
            payload_summary=f"Candidate {state.get('candidate_id')} selected. Routing to financial_node.",
        ),
    }


# ---------------------------------------------------------------------------
# Routing function used by the StateGraph conditional edge
# ---------------------------------------------------------------------------

def route_after_triage(state: OnboardingState) -> str:
    """Return the name of the next node based on triage outcome."""
    status      = state.get("selection_status")
    node_status = state.get("node_status")

    if node_status == NodeStatus.ERROR:
        return "error_handler"
    if status == SelectionStatus.REJECTED:
        return "email_node"         # → HITL gate → sends rejection
    return "financial_node"