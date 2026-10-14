"""
FastAPI Application — Onboarding Multi-Agent System
─────────────────────────────────────────────────────
Endpoints:
  POST /onboarding/trigger      — Start a new onboarding workflow
  POST /onboarding/approve      — HR approves email dispatch (HITL resume)
  GET  /onboarding/{id}/state   — Retrieve current graph state
  GET  /onboarding/{id}/stream  — SSE stream of agent events
  GET  /onboarding/{id}/audit   — Retrieve full audit trail
  POST /onboarding/{id}/reject-approval — HR rejects the approval queue item
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator, Optional

import uvicorn
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

# Load .env BEFORE importing anything that may read the environment during
# import. The application modules now read env lazily, so this is belt-and-
# braces rather than the sole guard — but the ordering is still the correct
# one and costs nothing.
load_dotenv()

from agents.email_node import render_email  # noqa: E402
from core.graph import build_graph  # noqa: E402
from core.india.locations import is_valid_city, is_valid_state, state_name  # noqa: E402
from core.scheduler import run_scheduler  # noqa: E402
from core.voice_state import PhoneError, normalize_phone  # noqa: E402
from utils.audit import emit_audit  # noqa: E402
from core.state import (  # noqa: E402
    ApprovalStatus,
    EmploymentType,
    RawCompensationInput,
    SelectionStatus,
)
# ---------------------------------------------------------------------------
# Lifespan — initialise graph once at startup
# ---------------------------------------------------------------------------

_graph = None          # module-level compiled graph instance
_db_url: str = ""      # store for direct DB queries
_checkpointer = None   # store reference to checkpointer for listing threads


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _graph, _db_url, _checkpointer
    # Use the psycopg3-style DSN (no +asyncpg driver prefix needed here)
    _db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost/onboarding_db"
    )
    # AsyncPostgresSaver.from_conn_string is an async context manager.
    # Keep it open for the full app lifetime so the connection pool stays alive.
    async with AsyncPostgresSaver.from_conn_string(_db_url) as checkpointer:
        await checkpointer.setup()   # creates checkpoint tables if absent
        _checkpointer = checkpointer
        _graph = await build_graph(checkpointer)

        # Call records live beside the checkpoints. Idempotent, and cheap
        # enough to run unconditionally so a fresh database needs no manual step.
        from db import voice_calls as _voice_calls

        await _voice_calls.setup(_db_url)
        # A process killed mid-call leaves a claim that would block the
        # candidate's follow-up forever; clear those on the way up.
        stale = await _voice_calls.reconcile_stale(dsn=_db_url)
        if stale:
            print(f"[voice] reconciled {stale} call(s) abandoned by a restart")

        # Operator auth. A fresh clone with no HR_PASSWORD gets a random one
        # printed once here, rather than booting wide open or refusing to boot.
        from core.auth import auth_enabled as _auth_on, bootstrap as _auth_bootstrap
        from core.auth import operator_username as _auth_user

        if not _auth_on():
            print("[auth] ⚠  HR_AUTH_ENABLED=false — the HR console is UNPROTECTED")
        else:
            generated = _auth_bootstrap()
            if generated:
                print("[auth] no HR_PASSWORD set; generated one for this run:")
                print(f"[auth]   username: {_auth_user()}")
                print(f"[auth]   password: {generated}")
                print("[auth] set HR_PASSWORD in .env to keep it across restarts")
            else:
                print(f"[auth] operator login enabled (user: {_auth_user()})")

        # Auto-send poller. Runs for the life of the app; schedules themselves
        # live in the checkpoint, so a restart re-discovers outstanding ones.
        stop_scheduler = asyncio.Event()
        scheduler_task = asyncio.create_task(
            run_scheduler(lambda: _graph, _db_url, stop_scheduler)
        )

        try:
            yield
        finally:
            stop_scheduler.set()
            scheduler_task.cancel()
            # Await the cancellation so the task cannot outlive the connection
            # pool it queries through.
            try:
                await scheduler_task
            except (asyncio.CancelledError, Exception):
                pass

    # checkpointer connection pool is closed automatically on exit
    _checkpointer = None


app = FastAPI(
    title="Enterprise Onboarding Multi-Agent API",
    version="1.0.0",
    description="LangGraph-powered onboarding lifecycle automation.",
    lifespan=lifespan,
)

from api import auth_routes, recruitment, reports  # noqa: E402
from api.deps import OperatorRequired  # noqa: E402


async def _all_thread_ids() -> list[str]:
    """Shared with the recruitment router so both read threads the same way."""
    import psycopg
    async with await psycopg.AsyncConnection.connect(_db_url) as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT DISTINCT thread_id FROM checkpoints WHERE checkpoint_ns = ''"
            )
            return [r[0] for r in await cur.fetchall()]


recruitment.bind(lambda: _graph, _all_thread_ids)

# Auth applied at ROUTER level. Protecting endpoints one by one is how the
# release endpoints end up exposed: there is no reminder when a new route is
# added. tests/test_auth.py asserts that every route is either protected or on
# an explicit public allowlist, so a future addition cannot quietly skip this.
app.include_router(auth_routes.router)                                   # public
app.include_router(recruitment.router, dependencies=[OperatorRequired])  # HR
app.include_router(recruitment.candidate_router)                         # thread token
reports.bind(lambda: _graph, _all_thread_ids)
app.include_router(reports.router, dependencies=[OperatorRequired])      # HR

from api import voice as voice_api  # noqa: E402

voice_api.bind(lambda: _graph)
app.include_router(voice_api.router, dependencies=[OperatorRequired])    # HR
app.include_router(voice_api.agent_router)                               # thread token

app.add_middleware(
    CORSMiddleware,
    # Explicit origins, not "*": with allow_credentials the wildcard is invalid
    # per the Fetch spec, and it let any page in an operator's browser call the
    # release endpoints. Override with DASHBOARD_ORIGINS (comma-separated).
    allow_origins=[
        o.strip() for o in os.environ.get(
            "DASHBOARD_ORIGINS",
            "http://localhost:3000,http://127.0.0.1:3000",
        ).split(",") if o.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Cross-origin JavaScript can only read a short list of response headers
    # unless they are named here. Without this the browser receives
    # Content-Disposition but hides it from the page, so every PDF and CSV
    # download fell back to a generic filename and the document number — the
    # thing that makes a saved letter findable later — was lost.
    expose_headers=["Content-Disposition"],
)


# ---------------------------------------------------------------------------
# Request / Response schemas (Pydantic v2)
# ---------------------------------------------------------------------------

class CompensationInputSchema(BaseModel):
    """
    Indian compensation input. HR quotes a single annual CTC and the engine
    derives the component breakup — the US model (base_pay / pay_frequency /
    401k / tax_state) has been removed entirely.
    """
    total_ctc: float = Field(gt=0, description="Annual CTC in INR")
    currency: str = "INR"
    tax_regime: str = "NEW"                     # NEW | OLD
    financial_year: Optional[str] = None        # defaults to the configured FY
    work_state: str                             # 2-letter Indian state/UT code
    work_city: str
    basic_pct: Optional[float] = None           # override default 40% of CTC
    performance_bonus: float = 0.0
    pf_on_actual_basic: bool = False

    @field_validator("tax_regime")
    @classmethod
    def valid_regime(cls, v: str) -> str:
        if v.upper() not in {"NEW", "OLD"}:
            raise ValueError("tax_regime must be NEW or OLD")
        return v.upper()

    @field_validator("work_state")
    @classmethod
    def valid_state(cls, v: str) -> str:
        if not is_valid_state(v):
            raise ValueError(
                f"'{v}' is not a valid Indian state or union territory code."
            )
        return v.upper()

    @model_validator(mode="after")
    def valid_state_city_pair(self):
        # §6.4 — invalid pairings such as Telangana + Chennai are rejected at
        # the edge, not silently priced with the wrong HRA and PT.
        if self.work_city and not is_valid_city(self.work_state, self.work_city):
            raise ValueError(
                f"{self.work_city} is not a recognised work location in "
                f"{state_name(self.work_state)}."
            )
        return self


class OnboardingTriggerRequest(BaseModel):
    candidate_id: str
    candidate_name: str
    candidate_email: EmailStr
    # §3 — the number the voice follow-up will dial. Optional so existing
    # callers keep working; without it the candidate is simply never called
    # (can_call_candidate refuses), rather than the trigger failing.
    candidate_phone: Optional[str] = None
    role_title: str
    department: str
    hiring_manager_email: EmailStr
    selection_status: SelectionStatus
    employment_type: Optional[EmploymentType] = None
    start_date: Optional[str] = None         # ISO-8601 — date of joining
    end_date: Optional[str] = None
    compensation: Optional[CompensationInputSchema] = None

    # ── Posting details that appear on both letters (§1, §2) ────────────────
    designation: Optional[str] = None        # falls back to role_title
    work_location_city: Optional[str] = None
    work_location_state: Optional[str] = None
    reporting_manager: Optional[str] = None
    working_hours: Optional[str] = None
    probation_period_months: Optional[int] = 6
    notice_period_days: Optional[int] = 60
    offer_conditions: Optional[str] = None

    @field_validator("candidate_phone")
    @classmethod
    def valid_phone(cls, v: Optional[str]) -> Optional[str]:
        # Normalised at the edge so exactly one canonical form is ever stored
        # — the dialer must never have to interpret what HR typed.
        if v in (None, ""):
            return None
        try:
            return normalize_phone(v)
        except PhoneError as exc:
            raise ValueError(str(exc)) from None

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def validate_date(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        try:
            datetime.fromisoformat(v)
        except ValueError:
            raise ValueError("Dates must be ISO-8601 format (YYYY-MM-DD)")
        return v


class ApprovalRequest(BaseModel):
    approved_by: str        # HR user identifier
    notes: Optional[str] = None
    # ISO-8601. Omit to dispatch immediately; supply a future instant to hand
    # the queue to the auto-send scheduler instead.
    send_at: Optional[str] = None

    @field_validator("send_at")
    @classmethod
    def validate_send_at(cls, v: Optional[str]) -> Optional[str]:
        if v in (None, ""):
            return None
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("send_at must be ISO-8601, e.g. 2026-09-01T09:30:00Z")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        # Small tolerance so a click a second after the picker's value was read
        # is not rejected as being in the past.
        if dt < datetime.now(timezone.utc) - timedelta(minutes=1):
            raise ValueError("send_at must be in the future")
        return dt.astimezone(timezone.utc).isoformat()


class RejectApprovalRequest(BaseModel):
    rejected_by: str
    reason: str


class OnboardingTriggerResponse(BaseModel):
    thread_id: str
    candidate_id: str
    status: str
    message: str


class StateResponse(BaseModel):
    thread_id: str
    candidate_id: str
    current_node: Optional[str]
    node_status: Optional[str]
    approval_status: Optional[str]
    selection_status: Optional[str]
    calculated_financials: Optional[dict]
    leave_allocations: Optional[dict]
    email_queue_summary: list[dict]
    error_message: Optional[str]


class CandidateResponse(BaseModel):
    """Composite candidate model for the dashboard Kanban board."""
    candidate_id: str
    thread_id: str
    candidate_name: str
    candidate_email: str
    role_title: str
    department: str
    hiring_manager_email: str
    employment_type: Optional[str] = None
    selection_status: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    current_node: Optional[str] = None
    node_status: Optional[str] = None
    approval_status: Optional[str] = None
    calculated_financials: Optional[dict] = None
    leave_allocations: Optional[dict] = None
    raw_compensation: Optional[dict] = None
    email_queue_summary: list[dict] = []
    kanban_column: str = "PENDING"
    offer_letter_html: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_graph():
    if _graph is None:
        raise HTTPException(status_code=503, detail="Graph not initialised yet.")
    return _graph


def _derive_kanban_column(state: dict) -> str:
    """
    Derive the frontend Kanban column from backend state.

    Order matters: the HITL check must come BEFORE the terminal checks. Both
    approval paths park at the interrupt with a state that otherwise looks
    finished — the rejection path with selection_status=REJECTED, the offer
    path with node_status=COMPLETE from contract_node — so checking terminal
    conditions first would file both under COMPLETED and hide them from the
    approver.
    """
    node_status = state.get("node_status", "IDLE")
    approval_status = state.get("approval_status", "NEEDS_APPROVAL")
    current_node = state.get("current_node", "INIT")
    email_queue = state.get("email_queue", [])

    # Errors are terminal regardless of anything else
    if node_status == "ERROR":
        return "COMPLETED"

    # An approval decision has been made — the workflow has run its course
    if approval_status in ("APPROVED", "REJECTED"):
        return "COMPLETED"

    # Awaiting human-in-the-loop: undecided approval with mail still queued,
    # or a node that explicitly parked itself.
    has_pending_email = any(item.get("status") == "PENDING" for item in email_queue)
    if node_status == "WAITING_HITL" or has_pending_email:
        return "AWAITING_APPROVAL"

    if node_status == "COMPLETE":
        return "COMPLETED"

    # In progress (actively running through nodes)
    if node_status == "RUNNING" or (current_node and current_node != "INIT"):
        return "IN_PROGRESS"

    # Default: not yet started
    return "PENDING"


def _build_initial_state(req: OnboardingTriggerRequest) -> dict:
    """Convert request body into initial OnboardingState dict."""
    comp_dict: RawCompensationInput = {}
    if req.compensation:
        comp_dict = req.compensation.model_dump()  # type: ignore[assignment]

    return {
        "candidate_id":           req.candidate_id,
        "candidate_name":         req.candidate_name,
        "candidate_email":        req.candidate_email,
        "candidate_phone":        req.candidate_phone,
        "role_title":             req.role_title,
        "department":             req.department,
        "hiring_manager_email":   req.hiring_manager_email,
        "selection_status":       req.selection_status,
        "employment_type":        req.employment_type,
        "start_date":             req.start_date,
        "end_date":               req.end_date,
        "raw_compensation_input": comp_dict,
        # Location lives on the state root as well as inside compensation so
        # the documents and Professional Tax lookup read one canonical value.
        "designation":            req.designation or req.role_title,
        "work_location_city":     req.work_location_city or comp_dict.get("work_city"),
        "work_location_state":    req.work_location_state or comp_dict.get("work_state"),
        "reporting_manager":      req.reporting_manager,
        "working_hours":          req.working_hours,
        "probation_period_months": req.probation_period_months,
        "notice_period_days":     req.notice_period_days,
        "offer_conditions":       req.offer_conditions,
        "offer_letter":           {"status": "NOT_CREATED"},
        "appointment_letter":     {"status": "NOT_ELIGIBLE"},
        "offer_followup":         {"state": "NOT_APPLICABLE", "attempts": 0,
                                   "do_not_contact": False},
        "onboarding_stage":       "NOT_STARTED",
        "email_queue":            [],
        "audit_log":              [],
        "approval_status":        ApprovalStatus.NEEDS_APPROVAL,
        "current_node":           "INIT",
        "node_status":            "IDLE",
    }


def _mask_email_queue(queue: list[dict]) -> list[dict]:
    """Strip full HTML bodies from queue items for summary responses."""
    summary = []
    for item in queue:
        summary.append({
            "template":      item.get("template_name"),
            "recipient":     item.get("recipient_email"),
            "status":        item.get("status"),
            "message_id":    item.get("message_id"),
            # Scheduling fields. Cheap scalars, unlike the letter bodies this
            # function exists to strip, and the dashboard needs them to show
            # whether a send is pending, auto-sent, or a missed auto-send.
            "scheduled_for": item.get("scheduled_for"),
            "dispatch_mode": item.get("dispatch_mode"),
            "sent_at":       item.get("sent_at"),
        })
    return summary


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/onboarding/trigger", response_model=OnboardingTriggerResponse,
          status_code=202, dependencies=[OperatorRequired])
async def trigger_onboarding(
    req: OnboardingTriggerRequest,
    graph=Depends(_get_graph),
):
    """
    Start a new onboarding workflow thread.
    Each candidate gets a unique thread_id for checkpointing.
    """
    thread_id = str(uuid.uuid4())
    config    = {"configurable": {"thread_id": thread_id}}

    initial_state = _build_initial_state(req)

    # Run the graph (will pause at interrupt_before=["email_node"])
    await graph.ainvoke(initial_state, config=config)

    return OnboardingTriggerResponse(
        thread_id    = thread_id,
        candidate_id = req.candidate_id,
        status       = "RUNNING",
        message      = "Onboarding workflow started. Graph will pause before email dispatch for HR approval.",
    )


@app.post("/onboarding/{thread_id}/approve", status_code=200,
          dependencies=[OperatorRequired])
async def approve_email_dispatch(
    thread_id: str,
    req: ApprovalRequest,
    graph=Depends(_get_graph),
):
    """
    HR approval endpoint — resumes the graph after the HITL interrupt.

    Without `send_at` this behaves as before: approve and dispatch now.

    With `send_at` the approval is recorded but the thread is deliberately LEFT
    PARKED at the interrupt, with its queue marked SCHEDULED. The auto-send
    scheduler releases it at the appointed time by flipping the items back to
    PENDING and resuming — so a scheduled send travels the identical
    `email_node` path as a manual one, and there is no second sending
    implementation to drift.
    """
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = await graph.aget_state(config)

    if not snapshot or not snapshot.values:
        raise HTTPException(status_code=404, detail=f"No state found for thread_id={thread_id}")

    patch: dict = {
        "approval_status": ApprovalStatus.APPROVED,
        "approver_email":  req.approved_by,
        "approver_notes":  req.notes,
    }

    # ── Scheduled dispatch ──────────────────────────────────────────────────
    if req.send_at:
        queue = snapshot.values.get("email_queue", [])
        scheduled = [
            {**item, "status": "SCHEDULED",
             "scheduled_for": req.send_at, "dispatch_mode": "AUTO"}
            if item.get("status") == "PENDING" else item
            for item in queue
        ]
        count = sum(1 for i in queue if i.get("status") == "PENDING")
        if count == 0:
            raise HTTPException(
                status_code=409,
                detail="Nothing to schedule — this thread has no pending email.",
            )

        patch["email_queue"] = scheduled
        patch["audit_log"] = emit_audit(
            node="approval",
            event="DISPATCH_SCHEDULED",
            payload_summary=(
                f"{count} email(s) approved for auto-send at {req.send_at} "
                f"by {req.approved_by}. Nothing sent yet."
            ),
            actor=f"HR_{req.approved_by}",
        )
        await graph.aupdate_state(config, patch)
        # No ainvoke: the thread stays at the interrupt until its time comes.
        return {
            "message": f"Approved. {count} email(s) scheduled for {req.send_at}.",
            "thread_id": thread_id,
            "scheduled_for": req.send_at,
            "scheduled_count": count,
        }

    # ── Immediate dispatch ──────────────────────────────────────────────────
    await graph.aupdate_state(config, patch)
    await graph.ainvoke(None, config=config)

    return {"message": "Approval accepted. Emails are being dispatched.", "thread_id": thread_id}


@app.post("/onboarding/{thread_id}/reject-approval", status_code=200,
          dependencies=[OperatorRequired])
async def reject_email_dispatch(
    thread_id: str,
    req: RejectApprovalRequest,
    graph=Depends(_get_graph),
):
    """
    HR rejects the email dispatch — workflow terminates without sending.

    The graph is resumed so it runs to END: email_node sees approval_status
    REJECTED, marks queued items CANCELLED, and does not dispatch. Without the
    resume the thread would stay parked at the interrupt indefinitely.
    """
    config = {"configurable": {"thread_id": thread_id}}

    await graph.aupdate_state(
        config,
        {
            "approval_status": ApprovalStatus.REJECTED,
            "approver_email":  req.rejected_by,
            "approver_notes":  req.reason,
        },
    )

    # Resume from the interrupted checkpoint so the thread closes out.
    await graph.ainvoke(None, config=config)

    return {"message": "Approval rejected. Workflow terminated without email dispatch.", "thread_id": thread_id}


@app.get("/onboarding/{thread_id}/messages", dependencies=[OperatorRequired])
async def get_onboarding_messages(
    thread_id: str,
    graph=Depends(_get_graph),
):
    """
    Rendered outbound mail for one thread — exactly the HTML handed to Resend.

    Read-only, and deliberately its own endpoint rather than a field on
    /candidates: full letter bodies on every row of the roster would make the
    list payload enormous for data almost never looked at. The body is fetched
    only when an operator opens a specific message.

    /state masks `variables`, so a rejection notice's body was previously not
    retrievable through the API at all even though it sits in the checkpoint.
    """
    config = {"configurable": {"thread_id": thread_id}}
    checkpoint = await graph.aget_state(config)

    if not checkpoint or not checkpoint.values:
        raise HTTPException(status_code=404, detail=f"No state found for thread_id={thread_id}")

    state = checkpoint.values
    messages = []
    for idx, item in enumerate(state.get("email_queue", [])):
        try:
            subject, html = render_email(item)
            render_error = None
        except Exception as exc:  # a template/variable problem must not 500 the list
            subject, html, render_error = "(unavailable)", None, str(exc)

        messages.append({
            "index":         idx,
            "template":      item.get("template_name"),
            "recipient":     item.get("recipient_email"),
            "recipient_name": item.get("recipient_name"),
            "status":        item.get("status"),
            "message_id":    item.get("message_id"),
            "subject":       subject,
            "html":          html,
            "render_error":  render_error,
        })

    return {
        "thread_id":     thread_id,
        "candidate_id":  state.get("candidate_id"),
        "candidate_name": state.get("candidate_name"),
        "messages":      messages,
    }


@app.get("/onboarding/{thread_id}/state", response_model=StateResponse,
         dependencies=[OperatorRequired])
async def get_onboarding_state(
    thread_id: str,
    graph=Depends(_get_graph),
):
    """Return current state snapshot for a workflow thread."""
    config = {"configurable": {"thread_id": thread_id}}
    checkpoint = await graph.aget_state(config)

    if not checkpoint or not checkpoint.values:
        raise HTTPException(status_code=404, detail=f"No state found for thread_id={thread_id}")

    state = checkpoint.values
    return StateResponse(
        thread_id            = thread_id,
        candidate_id         = state.get("candidate_id", ""),
        current_node         = state.get("current_node"),
        node_status          = state.get("node_status"),
        approval_status      = state.get("approval_status"),
        selection_status     = state.get("selection_status"),
        calculated_financials = state.get("calculated_financials"),
        leave_allocations    = state.get("leave_allocations"),
        email_queue_summary  = _mask_email_queue(state.get("email_queue", [])),
        error_message        = state.get("error_message"),
    )


@app.get("/onboarding/{thread_id}/audit", dependencies=[OperatorRequired])
async def get_audit_log(
    thread_id: str,
    graph=Depends(_get_graph),
):
    """Return the complete immutable audit trail for a workflow thread."""
    config = {"configurable": {"thread_id": thread_id}}
    checkpoint = await graph.aget_state(config)

    if not checkpoint or not checkpoint.values:
        raise HTTPException(status_code=404, detail=f"No state found for thread_id={thread_id}")

    return {
        "thread_id": thread_id,
        "audit_log": checkpoint.values.get("audit_log", []),
    }


_STREAM_POLL_SECONDS   = 1.0
_STREAM_HEARTBEAT_EVERY = 15     # polls between keep-alive comments
_STREAM_MAX_SECONDS    = 30 * 60


@app.get("/onboarding/{thread_id}/stream", dependencies=[OperatorRequired])
async def stream_agent_events(
    thread_id: str,
    request: Request,
    graph=Depends(_get_graph),
):
    """
    SSE endpoint — stream real-time agent state events to the dashboard.
    Emits one JSON event per observed checkpoint change.

    This endpoint is strictly READ-ONLY. It must never call astream_events /
    astream / ainvoke with a `None` input on this thread: for a graph paused at
    `interrupt_before=["email_node"]`, a None input RESUMES execution. Merely
    opening the dashboard's event stream would then push the thread past the
    HITL gate and on to END, after which /approve has nothing left to resume
    and the offer is silently never sent. So we poll checkpoints instead.
    """
    config = {"configurable": {"thread_id": thread_id}}

    def _checkpoint_id(snapshot) -> Optional[str]:
        return (snapshot.config or {}).get("configurable", {}).get("checkpoint_id")

    async def event_generator() -> AsyncGenerator[str, None]:
        last_seen: Optional[str] = None
        polls = 0
        started = datetime.now(timezone.utc)

        try:
            while True:
                if await request.is_disconnected():
                    return
                if (datetime.now(timezone.utc) - started).total_seconds() > _STREAM_MAX_SECONDS:
                    yield f"data: {json.dumps({'event': 'stream_timeout'})}\n\n"
                    return

                snapshot = await graph.aget_state(config)   # read-only, never resumes
                if not snapshot or not snapshot.values:
                    yield f"data: {json.dumps({'event': 'not_found', 'thread_id': thread_id})}\n\n"
                    return

                current = _checkpoint_id(snapshot)
                if current != last_seen:
                    last_seen = current
                    state = snapshot.values
                    # `next` is empty once the graph reaches END, and holds the
                    # pending node while parked at the HITL interrupt.
                    pending = list(snapshot.next or ())
                    yield "data: " + json.dumps({
                        "event":           "state_update",
                        "thread_id":       thread_id,
                        "checkpoint_id":   current,
                        "timestamp":       datetime.now(timezone.utc).isoformat(),
                        "current_node":    state.get("current_node"),
                        "node_status":     state.get("node_status"),
                        "approval_status": state.get("approval_status"),
                        "pending_nodes":   pending,
                        "kanban_column":   _derive_kanban_column(state),
                        "error_message":   state.get("error_message"),
                    }) + "\n\n"

                    if not pending:
                        yield f"data: {json.dumps({'event': 'done', 'thread_id': thread_id})}\n\n"
                        return

                polls += 1
                if polls % _STREAM_HEARTBEAT_EVERY == 0:
                    yield ": keep-alive\n\n"

                await asyncio.sleep(_STREAM_POLL_SECONDS)

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            yield f"data: {json.dumps({'event': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Dashboard aggregation endpoints
# ---------------------------------------------------------------------------

@app.get("/onboarding/candidates", response_model=list[CandidateResponse],
         dependencies=[OperatorRequired])
async def list_candidates(
    graph=Depends(_get_graph),
):
    """
    List ALL onboarding workflows with full state — used by the dashboard.
    Queries distinct thread_ids from the checkpoint database and fetches
    each thread's current state via the graph checkpointer.
    """
    import psycopg   # psycopg3 — already a dep of langgraph-checkpoint-postgres

    # 1) Get all distinct thread_ids from the checkpoints table
    thread_ids: list[str] = []
    try:
        async with await psycopg.AsyncConnection.connect(_db_url) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT DISTINCT thread_id FROM checkpoints WHERE checkpoint_ns = '' ORDER BY thread_id"
                )
                rows = await cur.fetchall()
                thread_ids = [row[0] for row in rows]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to query checkpoint database: {exc}")

    # 2) Fetch state for each thread
    candidates: list[CandidateResponse] = []
    for thread_id in thread_ids:
        try:
            config = {"configurable": {"thread_id": thread_id}}
            checkpoint = await graph.aget_state(config)
            if not checkpoint or not checkpoint.values:
                continue
            state = checkpoint.values

            candidates.append(CandidateResponse(
                candidate_id        = state.get("candidate_id", ""),
                thread_id           = thread_id,
                candidate_name      = state.get("candidate_name", "Unknown"),
                candidate_email     = state.get("candidate_email", ""),
                role_title          = state.get("role_title", ""),
                department          = state.get("department", ""),
                hiring_manager_email= state.get("hiring_manager_email", ""),
                employment_type     = state.get("employment_type"),
                selection_status    = state.get("selection_status"),
                start_date          = state.get("start_date"),
                end_date            = state.get("end_date"),
                current_node        = state.get("current_node"),
                node_status         = state.get("node_status"),
                approval_status     = state.get("approval_status"),
                calculated_financials = state.get("calculated_financials"),
                leave_allocations   = state.get("leave_allocations"),
                raw_compensation    = state.get("raw_compensation_input"),
                email_queue_summary = _mask_email_queue(state.get("email_queue", [])),
                kanban_column       = _derive_kanban_column(state),
                offer_letter_html   = state.get("offer_letter_html"),
            ))
        except Exception:
            # Skip threads with corrupt/unreadable state
            continue

    return candidates


@app.get("/onboarding/audit/all", dependencies=[OperatorRequired])
async def get_all_audit_logs(
    graph=Depends(_get_graph),
):
    """
    Aggregate audit logs across ALL threads — used by the dashboard Audit page.
    Returns entries enriched with thread_id and candidate_name.
    """
    import psycopg

    thread_ids: list[str] = []
    try:
        async with await psycopg.AsyncConnection.connect(_db_url) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT DISTINCT thread_id FROM checkpoints WHERE checkpoint_ns = '' ORDER BY thread_id"
                )
                rows = await cur.fetchall()
                thread_ids = [row[0] for row in rows]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to query checkpoint database: {exc}")

    all_entries: list[dict] = []
    for thread_id in thread_ids:
        try:
            config = {"configurable": {"thread_id": thread_id}}
            checkpoint = await graph.aget_state(config)
            if not checkpoint or not checkpoint.values:
                continue
            state = checkpoint.values
            candidate_name = state.get("candidate_name", "Unknown")
            for entry in state.get("audit_log", []):
                all_entries.append({
                    "thread_id":       thread_id,
                    "candidate_name":  candidate_name,
                    **entry,
                })
        except Exception:
            continue

    # Sort by timestamp descending
    all_entries.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    return {"audit_log": all_entries}


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "graph_ready": _graph is not None}


# ---------------------------------------------------------------------------
# Dev entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)