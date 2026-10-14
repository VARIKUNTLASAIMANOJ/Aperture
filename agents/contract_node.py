"""
Contract & Compliance Manager Node
────────────────────────────────────
1. Queries Qdrant vector store for region-specific compliance rules (RAG).
2. Uses LLM to draft the legally-compliant offer letter / contractor agreement
   (LLM generates prose ONLY; all financial figures come from state — already calculated).
3. Schedules contract expiry alerts for contractors via Celery/Temporal.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from langchain_core.runnables import RunnableConfig

from core.state import EmailQueueItem, EmploymentType, NodeStatus, OnboardingState
from utils.audit import emit_audit
from utils.llm import get_llm

# ---------------------------------------------------------------------------
# Contract generation system prompt
# ---------------------------------------------------------------------------

CONTRACT_SYSTEM_PROMPT = """You are a senior employment law paralegal AI.
Generate a professional offer letter / employment agreement in clean HTML.
You will receive all financial figures and leave entitlements pre-calculated — 
insert them verbatim. Do not modify, recompute, or approximate any numbers.
The document must include:
  1. Position details (role, department, start date, manager)
  2. Compensation schedule (gross/net, pay frequency, deductions breakdown)
  3. Leave entitlements (PTO, sick leave, parental leave)
  4. Contract duration (if applicable, end date and renewal terms)
  5. Standard employment conditions placeholder sections
  6. Signature block for candidate and HR representative
Return ONLY the HTML string, beginning with <div class="contract-document">."""


# ---------------------------------------------------------------------------
# Qdrant RAG helper (stub — wire to your Qdrant instance)
# ---------------------------------------------------------------------------

async def _fetch_compliance_rules(state_code: str, employment_type: str) -> str:
    """
    Query Qdrant for region + employment-type compliance snippets.
    Returns a concatenated string of relevant policy chunks.
    
    Production: replace with actual Qdrant client call:
        from qdrant_client import AsyncQdrantClient
        client = AsyncQdrantClient(url=settings.QDRANT_URL)
        results = await client.search(collection_name="compliance_docs", ...)
    """
    # Placeholder compliance rules — replace with real RAG retrieval
    return (
        f"[State: {state_code}] At-will employment applies. "
        f"Employment type: {employment_type}. "
        "Standard non-compete clauses prohibited under state statute. "
        "Mandatory arbitration clause disclosure required. "
        "FMLA eligibility: 12 months tenure + 1,250 hours worked."
    )


# ---------------------------------------------------------------------------
# Contract expiry scheduler
# ---------------------------------------------------------------------------

def _schedule_expiry_alerts(candidate_id: str, end_date_iso: str) -> None:
    """
    Schedule T-30, T-15, T-7 alerts for contractor end_date.
    
    Production (Celery example):
        from workers.celery_app import send_contract_expiry_alert
        end = date.fromisoformat(end_date_iso)
        for days_before in [30, 15, 7]:
            eta = end - timedelta(days=days_before)
            send_contract_expiry_alert.apply_async(
                args=[candidate_id, days_before],
                eta=datetime.combine(eta, datetime.min.time(), tzinfo=timezone.utc)
            )
    
    Production (Temporal example):
        from temporalio.client import Client
        client = await Client.connect("temporal:7233")
        await client.start_workflow(
            ContractExpiryWorkflow.run,
            args=[candidate_id, end_date_iso],
            id=f"contract-expiry-{candidate_id}",
            task_queue="onboarding-queue",
        )
    """
    end = date.fromisoformat(end_date_iso)
    for days_before in [30, 15, 7]:
        alert_date = end - timedelta(days=days_before)
        # Log scheduled alerts (replace with actual scheduler call above)
        print(f"[SCHEDULER] Alert for {candidate_id} at T-{days_before}: {alert_date}")


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

async def contract_node(state: OnboardingState, config: RunnableConfig) -> dict:
    """LangGraph node: generate offer letter and schedule expiry alerts."""

    candidate_id    = state.get("candidate_id", "UNKNOWN")
    employment_type = state["employment_type"]
    financials      = state.get("calculated_financials", {})
    leave           = state.get("leave_allocations", {})
    tax_state       = state.get("raw_compensation_input", {}).get("tax_state", "OTHER")

    try:
        # ── Step 1: RAG — fetch compliance rules ─────────────────────────────
        compliance_rules = await _fetch_compliance_rules(
            state_code=tax_state,
            employment_type=employment_type,
        )

        # ── Step 2: Build the LLM context (numbers come from state) ──────────
        context_payload = {
            "candidate_name":  state.get("candidate_name"),
            "role_title":      state.get("role_title"),
            "department":      state.get("department"),
            "hiring_manager":  state.get("hiring_manager_email"),
            "start_date":      state.get("start_date"),
            "end_date":        state.get("end_date"),
            "employment_type": employment_type,
            "financials":      financials,
            "leave":           leave,
            "compliance_rules": compliance_rules,
        }
        user_message = (
            "Generate the employment agreement for:\n"
            + json.dumps(context_payload, indent=2, default=str)
        )

        # ── Step 3: LLM generates prose/HTML only (Nemotron via NVIDIA NIM) ───
        llm = get_llm(temperature=0.1)
        response = await llm.ainvoke(
            [
                {"role": "system", "content": CONTRACT_SYSTEM_PROMPT},
                {"role": "user",   "content": user_message},
            ]
        )
        offer_letter_html: str = response.content  # type: ignore[attr-defined]

        # ── Step 4: Build offer email payload for HITL gate ──────────────────
        offer_email: EmailQueueItem = {
            "template_name":   "offer_letter",
            "recipient_email": state.get("candidate_email", ""),
            "recipient_name":  state.get("candidate_name", ""),
            "variables": {
                "offer_letter_html": offer_letter_html,
                "start_date":        state.get("start_date"),
                "role_title":        state.get("role_title"),
            },
            "status":     "PENDING",
            "message_id": None,
        }

        # ── Step 5: Schedule expiry alerts for contractors ───────────────────
        end_date = state.get("end_date")
        if end_date and employment_type != EmploymentType.FULL_TIME:
            _schedule_expiry_alerts(candidate_id, end_date)

        return {
            "current_node":     "contract_node",
            "node_status":      NodeStatus.COMPLETE,
            "offer_letter_html": offer_letter_html,
            "approval_status":  "NEEDS_APPROVAL",
            "email_queue":      [*state.get("email_queue", []), offer_email],
            "error_message":    None,
            "audit_log": emit_audit(
                node="contract_node",
                event="OFFER_LETTER_GENERATED",
                payload_summary=(
                    f"Candidate {candidate_id}: offer letter generated. "
                    f"Employment={employment_type}. "
                    f"{'Expiry alerts scheduled for ' + end_date if end_date else 'No end date.'}"
                ),
            ),
        }

    except Exception as exc:
        return {
            "current_node":  "contract_node",
            "node_status":   NodeStatus.ERROR,
            "error_message": str(exc),
            "audit_log": emit_audit(
                node="contract_node",
                event="CONTRACT_GENERATION_ERROR",
                payload_summary=f"Candidate {candidate_id}: contract gen failed — {exc}",
            ),
        }


def route_after_contract(state: OnboardingState) -> str:
    if state.get("node_status") == NodeStatus.ERROR:
        return "error_handler"
    return "email_node"