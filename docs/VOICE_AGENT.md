# Voice follow-up agent

Automated phone follow-up for candidates who have received an Offer Letter but
have not yet responded.

```
Offer Letter dispatched  ──►  wait OFFER_CALL_DELAY_MINUTES
                              ──►  re-check eligibility
                                   ──►  LiveKit SIP dials the candidate
                                        Deepgram STT → NVIDIA NIM → Deepgram TTS
                                        ──►  outcome POSTed back to the API
                                             ──►  state machine advances
```

## The one rule to know before changing anything

**A phone call cannot accept an offer.**

A verbal "yes" records `ACCEPTED_INTENT` and raises an HR notification. It does
not touch `offer_letter.status`. Binding acceptance remains the token-guarded
click in the candidate portal, because an unauthenticated voice call is not an
acceptable basis for an employment contract.

Nothing in `voice/` or `api/voice.py` writes `offer_letter`. Keep it that way.

## Setup

### 1. Telephony (required for real calls)

LiveKit does **not** provide PSTN connectivity. You need a SIP trunk from a
telephony provider registered with LiveKit:

| Provider | Notes |
|---|---|
| Twilio | Easiest; Indian outbound needs extra approval |
| Plivo | India-friendly |
| Exotel | India-native; usually the right choice for Indian numbers |

Outbound commercial calling to Indian subscribers is subject to **TRAI/DLT
registration**. That is paperwork with a real timeline, not a config flag. Until
`LIVEKIT_SIP_TRUNK_ID` is set, `voice/dispatch.py` raises
`TelephonyNotConfigured` rather than silently doing nothing.

**`LIVEKIT_SIP_TRUNK_ID` is not a LiveKit credential.** A new LiveKit project
has zero trunks, and the `*.sip.livekit.cloud` hostname in the console is an
endpoint address, not a trunk. Pasting it produces
`twirp error unknown: object cannot be found` at dial time.

### Twilio → LiveKit, end to end

**In Twilio** — a phone number alone is not enough; you need Elastic SIP Trunking:

1. **Voice → Geographic Permissions**: enable the destination country. Twilio
   blocks most international destinations by default, India included. Skipping
   this fails every call with a permissions error.
2. **Elastic SIP Trunking → Trunks → Create**.
3. On that trunk, **Termination**: set a Termination SIP URI. You get
   `something.pstn.twilio.com` — this is the address LiveKit dials out through.
4. **Credential Lists**: create a username and password, attach it to the
   trunk's Termination. (IP access control lists are the alternative, but
   credentials are simpler and do not break when LiveKit's egress IPs change.)
5. **Numbers**: assign your purchased number to the trunk. It becomes the
   caller ID the candidate sees.

**Then create the LiveKit trunk:**

```bash
python3 -m scripts.create_livekit_trunk \
    --address  something.pstn.twilio.com \
    --number   +15551234567 \
    --username your-sip-user
```

It prints an `ST_...` id. Put that in `LIVEKIT_SIP_TRUNK_ID`, restart the API,
and check `/voice/status`. `python3 -m scripts.create_livekit_trunk --list`
shows what already exists.

The password is read from `TWILIO_SIP_PASSWORD` or prompted for — never passed
as an argument, where it would land in shell history.

### 2. Deepgram

One key covers both STT and TTS. Defaults are `nova-3` with `en-IN`, and
`aura-2-asteria-en` for the voice.

> Measure Deepgram's accuracy on real Indian-English calls before trusting it.
> A mis-transcribed "no" becoming "yes" is the expensive failure mode here.

### 3. Configure

Copy the voice block from `.env.example` into `.env`. The master switch is off
by default:

```bash
VOICE_AGENT_ENABLED=true
OFFER_CALL_DELAY_MINUTES=3        # 4320 for the 3-day production window
```

### 4. Run

Two processes. The API schedules and decides; the agent worker talks.

```bash
python3 -m uvicorn api.main:app --reload    # API + scheduler
python3 -m voice.agent dev                  # LiveKit agent worker
```

Check wiring without placing a call:

```bash
curl -s localhost:8000/voice/status
```

## How it fits the existing system

| Concern | Reused, not rebuilt |
|---|---|
| Scheduling | `core/scheduler.py` — the existing asyncio poller, not Celery (no Redis) |
| Durability | Due times live in the LangGraph checkpoint, so restarts re-discover them |
| LLM | `utils/llm.nim_config()` — the same NVIDIA NIM endpoint and model |
| Auth | The same HMAC offer token the candidate portal uses |
| Rules | `core/lifecycle.can_call_candidate` — beside the existing employment rules |
| Audit | `utils/audit.emit_audit` — calls appear in the same trail as everything else |

The agent worker never touches the graph or Postgres. It reads candidate status
and reports outcomes over HTTP, so `core/lifecycle.py` stays the single
enforcement point.

## Eligibility (§19)

Checked immediately before every dial, not just when the call was scheduled —
the candidate may act during the delay window.

```
voice enabled? → not do-not-contact? → SELECTED? → offer released?
  → not accepted/declined/expired? → offer email actually SENT?
  → phone on record? → no call in progress? → attempts remaining?
  → inside calling hours?  →  dial
```

Any failure means **no call**. "Outside calling hours" defers; everything else
closes the follow-up with a reason.

## State machine (§10)

```
WAITING_FOR_INITIAL_CALL → INITIAL_CALL_IN_PROGRESS
    ├── ACCEPTED_INTENT / DECLINED ─────────────► CLOSED
    ├── NEEDS_TIME ────────► FINAL_CALL_PENDING ─► FINAL_CALL_IN_PROGRESS
    └── NO_ANSWER / BUSY ──► retry ×CALL_MAX_ATTEMPTS, then FINAL_CALL_PENDING
                                                   ├── FINAL_ACCEPTANCE_INTENT
                                                   ├── FINAL_DECLINE
                                                   └── FINAL_UNDECIDED → CLOSED
```

**The final call never schedules another.** Even `FINAL_UNDECIDED` closes, and
even if the model emits `NEEDS_TIME`, `core/voice_flow.advance` maps it to
`FINAL_UNDECIDED`. The prompt forbids asking for more time; the state machine
enforces it.

Call outcomes (`NO_ANSWER`, `BUSY`, `CALL_FAILED`, `INVALID_NUMBER`,
`DECLINED_CONTACT`, `COMPLETED`) are kept distinct from candidate intent.
Silence is never a decline.

## Duplicate protection (§15)

Two layers, because the state machine alone does not survive multiple workers:

1. The `offer_followup.state` transition to `*_IN_PROGRESS`.
2. **`UNIQUE (thread_id, call_type)` on `voice_calls`** — the real guard. A
   duplicate event, retried job or restarted worker loses the `INSERT`
   deterministically.

A dial that never reached anyone releases its claim so a retry can proceed; a
call that produced a conversation keeps it permanently.

Calls abandoned by a crash are reconciled on startup
(`voice_calls.reconcile_stale`), so a killed process cannot block a candidate's
follow-up forever.

## Data stored

`voice_calls` (Postgres, beside the checkpoint tables): call metadata, outcome,
intent, follow-up date, decline reason, summary and transcript.

Transcripts are deliberately **not** in graph state — LangGraph rewrites the
whole checkpoint on every super-step and would copy them repeatedly.

Phone numbers are masked (`+91*******210`) in every log, audit entry and API
response. Recording is **off** by default (`VOICE_RECORDING_ENABLED`); turning
it on is a compliance decision, and in India you should announce it on the call.

## Testing

```bash
python3 -m pytest tests/ -q
```

85 tests, none requiring LiveKit, Deepgram or telephony. The idempotency and
scheduler suites need Postgres and skip cleanly without it.

| File | Covers |
|---|---|
| `test_voice_eligibility.py` | §19 gates, phone normalisation, calling hours, timing |
| `test_voice_conversation.py` | §8 scenarios, §9 final call, prompt construction |
| `test_voice_idempotency.py` | §15 — including a 10-way concurrent claim race |
| `test_voice_scheduler.py` | §5/§14 scheduler branch on the real graph |
| `test_voice_graph_integration.py` | Arming from a real dispatch; failure paths |

## Production notes

- **The scheduler is O(threads) per poll.** It loads every thread's state every
  20 seconds. Fine at this scale; it will need an index or a due-time query
  before it is not.
- **Only one API process may run the scheduler.** Two would both poll. The
  database constraint prevents duplicate *calls*, but the wasted work is real.
- **Email-open tracking does not exist.** §6 Cases 1 and 2 both result in a
  call, so the control flow does not need it; add Resend webhooks only if you
  want the analytics.
- `INTERNAL_API_BASE` must be reachable from wherever the agent worker runs.
