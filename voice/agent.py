"""
The LiveKit agent worker (§2, §17).

Runs as its OWN process, not inside FastAPI — LiveKit agents register with the
server and receive dispatched jobs:

    python -m voice.agent dev        # local
    python -m voice.agent start      # production

Candidate → Deepgram STT → NVIDIA NIM (the project's existing LLM) → Deepgram
TTS → candidate.

The agent never touches the graph or the database. It reads candidate status
and reports outcomes through the HTTP API, so core.lifecycle stays the single
enforcement point — a bug in this conversational code cannot corrupt the
employment lifecycle, and in particular cannot accept an offer.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

from livekit import agents  # noqa: E402
from livekit.agents import Agent, AgentSession, JobContext, RunContext, function_tool  # noqa: E402
from livekit.plugins import deepgram, openai, silero  # noqa: E402

from core.voice_state import CallOutcome, CandidateIntent  # noqa: E402
from utils.llm import nim_config  # noqa: E402
from voice.prompts import build_instructions, greeting  # noqa: E402

log = logging.getLogger("voice.agent")


class OfferFollowupAgent(Agent):
    """
    One call. Collects a decision and reports it exactly once.

    `self._reported` matters: the model can call the tool more than once in a
    long turn, and the outcome endpoint is the thing that advances the state
    machine. Reporting twice would be harmless thanks to server-side
    idempotency, but reporting DIFFERENT outcomes would not be.
    """

    def __init__(self, *, meta: dict[str, Any], status: dict[str, Any]) -> None:
        super().__init__(instructions=build_instructions(meta["call_type"], status))
        self._meta = meta
        self._status = status
        self._reported = False
        self._outcome: dict[str, Any] = {}

    # ── Tools the model may call ────────────────────────────────────────────

    @function_tool()
    async def record_outcome(
        self,
        ctx: RunContext,
        intent: str,
        summary: str,
        reason: Optional[str] = None,
        follow_up_when: Optional[str] = None,
    ) -> str:
        """
        Record the candidate's decision. Call this once, before ending the call.

        Args:
            intent: One of ACCEPTED_INTENT, DECLINED, NEEDS_TIME,
                FINAL_ACCEPTANCE_INTENT, FINAL_DECLINE, FINAL_UNDECIDED,
                NO_RESPONSE.
            summary: One or two sentences on what the candidate said.
            reason: Their reason, if they gave one for declining.
            follow_up_when: When they asked to be contacted, in their own words
                or as YYYY-MM-DD. Only for NEEDS_TIME on an initial call.
        """
        valid = {i.value for i in CandidateIntent}
        if intent not in valid:
            return f"Unknown intent. Use one of: {', '.join(sorted(valid))}."

        if self._meta["call_type"] == "FINAL" and intent in {
            CandidateIntent.NEEDS_TIME.value, CandidateIntent.ACCEPTED_INTENT.value,
            CandidateIntent.DECLINED.value,
        }:
            # §9 — map initial-call intents onto their final equivalents rather
            # than letting a FINAL call emit NEEDS_TIME, which would re-open the
            # follow-up loop the final call exists to end.
            intent = {
                CandidateIntent.NEEDS_TIME.value: CandidateIntent.FINAL_UNDECIDED.value,
                CandidateIntent.ACCEPTED_INTENT.value:
                    CandidateIntent.FINAL_ACCEPTANCE_INTENT.value,
                CandidateIntent.DECLINED.value: CandidateIntent.FINAL_DECLINE.value,
            }[intent]

        self._outcome = {
            "outcome": CallOutcome.COMPLETED.value,
            "intent": intent,
            "summary": summary,
            "reason_if_declined": reason,
            "requested_followup_date": (
                follow_up_when if self._meta["call_type"] != "FINAL" else None
            ),
        }
        self._reported = True
        log.info("outcome recorded: %s", intent)
        return "Recorded. Thank the candidate briefly and end the call."

    @function_tool()
    async def record_do_not_contact(self, ctx: RunContext, note: str = "") -> str:
        """Call this if the candidate asks not to be contacted again."""
        self._outcome = {
            "outcome": CallOutcome.DECLINED_CONTACT.value,
            "intent": CandidateIntent.NO_RESPONSE.value,
            "summary": note or "The candidate asked not to be contacted again.",
        }
        self._reported = True
        return "Acknowledged. Apologise briefly for the interruption and end the call."

    @function_tool()
    async def wrong_person(self, ctx: RunContext) -> str:
        """Call this if the person who answered is not the candidate."""
        self._outcome = {
            "outcome": CallOutcome.NO_ANSWER.value,
            "intent": CandidateIntent.NO_RESPONSE.value,
            "summary": "Someone other than the candidate answered.",
        }
        self._reported = True
        return (
            "Do not discuss the offer. Ask when the candidate can be reached, "
            "thank them, and end the call."
        )

    # ── Reporting back ──────────────────────────────────────────────────────

    def final_payload(self, transcript: list[dict]) -> dict[str, Any]:
        """
        What gets POSTed when the call ends.

        A call that connected but produced no tool call is NOT a decline — it
        is a completed call with no response, and the state machine treats
        those differently (§11).
        """
        payload = self._outcome or {
            "outcome": CallOutcome.COMPLETED.value,
            "intent": CandidateIntent.NO_RESPONSE.value,
            "summary": "The call connected but no decision was recorded.",
        }
        return {**payload, "transcript": transcript}


async def _fetch_status(api_base: str, thread_id: str, token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            f"{api_base}/candidate/{thread_id}/status", params={"token": token}
        )
        r.raise_for_status()
        return r.json()


async def _report(api_base: str, call_id: int, token: str, payload: dict) -> None:
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            f"{api_base}/voice/calls/{call_id}/outcome",
            params={"token": token}, json=payload,
        )
        r.raise_for_status()


def _transcript_of(session: AgentSession) -> list[dict]:
    """Flatten the session history into storable turns (§13)."""
    turns: list[dict] = []
    try:
        for item in session.history.items:
            role = getattr(item, "role", None)
            text = getattr(item, "text_content", None) or ""
            if role and text:
                turns.append({"role": role, "text": text})
    except Exception:          # history shape varies by version; never fail the call
        log.warning("could not extract transcript", exc_info=True)
    return turns


async def entrypoint(ctx: JobContext) -> None:
    meta = json.loads(ctx.job.metadata or "{}")
    thread_id = meta.get("thread_id", "")
    call_id = int(meta.get("call_id") or 0)
    token = meta.get("token", "")
    api_base = meta.get("api_base", "http://127.0.0.1:8000")

    if not (thread_id and call_id and token):
        log.error("job metadata incomplete; refusing to run: %s", meta)
        return

    # Re-check eligibility at the last possible moment. The candidate may have
    # accepted between the dial and the connection, and the API is the only
    # thing that knows (§6).
    status = await _fetch_status(api_base, thread_id, token)
    if (status.get("offer") or {}).get("status") in ("ACCEPTED", "DECLINED"):
        log.info("candidate already responded (%s) — ending without speaking",
                 (status.get("offer") or {}).get("status"))
        await _report(api_base, call_id, token, {
            "outcome": CallOutcome.COMPLETED.value,
            "intent": CandidateIntent.NO_RESPONSE.value,
            "summary": "Candidate had already responded in the portal; call ended.",
            "transcript": [],
        })
        return

    api_key, base_url, model = nim_config()

    agent = OfferFollowupAgent(meta=meta, status=status)
    session = AgentSession(
        stt=deepgram.STT(
            model=os.environ.get("DEEPGRAM_STT_MODEL", "nova-3"),
            # Indian English. Worth measuring on real calls before trusting it.
            language=os.environ.get("DEEPGRAM_STT_LANGUAGE", "en-IN"),
        ),
        llm=openai.LLM(
            model=model, api_key=api_key, base_url=base_url, temperature=0.3
        ),
        tts=deepgram.TTS(
            model=os.environ.get("DEEPGRAM_TTS_MODEL", "aura-2-asteria-en"),
        ),
        vad=silero.VAD.load(),
    )

    await session.start(room=ctx.room, agent=agent)
    await session.generate_reply(
        instructions=(
            f"Greet the person exactly as: "
            f"\"{greeting(meta['call_type'], status.get('candidate_name', ''))}\""
        )
    )

    try:
        await ctx.wait_for_disconnect()
    finally:
        try:
            await _report(api_base, call_id, token,
                          agent.final_payload(_transcript_of(session)))
        except Exception:
            # Losing the outcome would strand the thread IN_PROGRESS; the
            # scheduler's stale-call reconciliation is the backstop.
            log.exception("failed to report call outcome for call_id=%s", call_id)


if __name__ == "__main__":
    agents.cli.run_app(
        agents.WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name=os.environ.get("VOICE_AGENT_NAME", "offer-followup-agent"),
        )
    )
