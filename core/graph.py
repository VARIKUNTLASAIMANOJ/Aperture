"""
LangGraph StateGraph Builder
─────────────────────────────
Assembles all agent nodes into a compiled, checkpointed graph.

Key design decisions:
  - PostgreSQL checkpointer for durable state persistence across API calls.
  - `interrupt_before=["email_node"]` implements the HITL gate.
  - Conditional edges implement routing decisions without hardcoding topology.
"""

from __future__ import annotations

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, StateGraph

from agents.lifecycle_nodes import (
    appointment_node, offer_gate, onboarding_node,
    route_after_appointment, route_after_appointment_dispatch,
    route_after_dispatch, route_after_offer_gate,
)
from agents.offer_node import offer_node, route_after_offer
from agents.email_node import email_node
from agents.financial_node import financial_node, route_after_financial
from agents.triage_node import route_after_triage, triage_node
from core.state import NodeStatus, OnboardingState

# ---------------------------------------------------------------------------
# Error handler node (terminal)
# ---------------------------------------------------------------------------

async def error_handler(state: OnboardingState, config) -> dict:
    """Terminal node for unrecoverable errors — logs and stops the graph."""
    return {
        "current_node": "error_handler",
        "node_status":  NodeStatus.ERROR,
    }


# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------

async def build_graph(checkpointer):
    """
    Build and compile the onboarding StateGraph.
    Receives an already-initialised checkpointer from the FastAPI lifespan
    so its connection stays open for the full app lifetime.
    """
    # ── Build graph structure ────────────────────────────────────────────────
    builder = StateGraph(OnboardingState)

    builder.add_node("triage_node",    triage_node)
    builder.add_node("financial_node", financial_node)
    builder.add_node("offer_node",     offer_node)
    builder.add_node("email_node",     email_node)
    # Post-offer lifecycle (§2). `appointment_dispatch` deliberately reuses the
    # email_node FUNCTION under a second node name: registering it twice keeps
    # one dispatch implementation while giving the appointment stage its own
    # interrupt, instead of creating a cycle back through "email_node".
    builder.add_node("offer_gate",            offer_gate)
    builder.add_node("appointment_node",      appointment_node)
    builder.add_node("appointment_dispatch",  email_node)
    builder.add_node("onboarding_node",       onboarding_node)
    builder.add_node("error_handler",  error_handler)

    # Entry point
    builder.set_entry_point("triage_node")

    # Conditional edges
    builder.add_conditional_edges(
        "triage_node",
        route_after_triage,
        {
            "financial_node": "financial_node",
            "email_node":     "email_node",
            "error_handler":  "error_handler",
        },
    )
    builder.add_conditional_edges(
        "financial_node",
        route_after_financial,
        {
            "offer_node":    "offer_node",
            "error_handler": "error_handler",
        },
    )
    builder.add_conditional_edges(
        "offer_node",
        route_after_offer,
        {
            "email_node":    "email_node",
            "error_handler": "error_handler",
        },
    )
    # After the offer is dispatched the thread parks at offer_gate until the
    # candidate responds. A rejection notice or a failed dispatch ends here.
    # The self-edge is deliberate. A failed dispatch routes BACK to email_node,
    # which `interrupt_before` turns into "park at the approval gate" rather
    # than "run again" — giving HR somewhere to retry from. Without it a bounced
    # offer reached END and the thread could never be resumed.
    builder.add_conditional_edges(
        "email_node",
        route_after_dispatch,
        {
            "offer_gate": "offer_gate",
            "email_node": "email_node",
            "__end__":    END,
        },
    )
    builder.add_conditional_edges(
        "offer_gate",
        route_after_offer_gate,
        {
            "appointment_node": "appointment_node",
            "__end__":          END,
        },
    )
    builder.add_conditional_edges(
        "appointment_node",
        route_after_appointment,
        {
            "appointment_dispatch": "appointment_dispatch",
            "error_handler":        "error_handler",
        },
    )
    builder.add_conditional_edges(
        "appointment_dispatch",
        route_after_appointment_dispatch,
        {
            "appointment_dispatch": "appointment_dispatch",   # retry, parked
            "onboarding_node":      "onboarding_node",
        },
    )
    builder.add_edge("onboarding_node", END)

    # Terminal edges
    builder.add_edge("error_handler", END)

    # Checkpointer is created and managed externally (in lifespan) so it stays
    # open for the full app lifetime. Receive it as a parameter.
    graph = builder.compile(
        checkpointer=checkpointer,
        interrupt_before=[
            "email_node",            # HR approves the Offer Letter release
            "offer_gate",            # waits for the candidate's decision
            "appointment_dispatch",  # HR releases the Appointment Letter
        ],
    )

    return graph