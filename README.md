# Aperture — HR Onboarding Automation

A human-gated agent that runs the Indian offer-to-onboarding lifecycle end to
end: statutory payroll, offer and appointment letters, email dispatch, an
automated voice follow-up, and a reporting layer — with an approval gate in
front of anything that reaches a candidate.

Built on LangGraph with PostgreSQL checkpointing, so a workflow can sit paused
for days waiting on a human and resume in a different process.

```
Candidate selected
      ↓
Payroll computed          deterministic Python, no model touches the maths
      ↓
Offer Letter drafted      rendered from a template, not generated
      ↓
   ◆ HR approves          graph interrupt — nothing sends without this
      ↓
Offer Letter released     status flips when the mail actually leaves
      ↓
   ◆ Candidate decides    graph interrupt — can wait indefinitely
      ↓                   (voice agent calls if they go quiet)
Appointment Letter        drafted on acceptance, released only by HR
      ↓
Onboarding
```

---

## What it does

**Two-stage employment documentation.** Offer Letter and Appointment Letter are
separate documents with independent statuses. The Appointment Letter cannot be
issued before the candidate accepts, and the candidate cannot see it before HR
releases it.

**Indian payroll, computed not guessed.** One CTC figure in; Basic, HRA,
conveyance, medical and special allowance out, with EPF, ESI, professional tax,
gratuity accrual and TDS under both the old and new regimes. HRA treatment
follows metro classification; professional tax follows the state. 28 states,
8 union territories and 103 cities, with state/city pairings validated at the
edge so an offer cannot be priced against a location that does not exist.

**Human-in-the-loop by construction.** Three graph interrupts — HR approves the
offer dispatch, the candidate decides, HR releases the appointment. A paused
thread lives in the Postgres checkpoint, so closing the browser or restarting
the API does not strand it.

**Automated voice follow-up.** If a candidate goes quiet after an offer, a
LiveKit agent calls them: Deepgram speech-to-text, the project's own LLM,
Deepgram speech back. It records intent, handles "I need more time", schedules
a final call, and will not ask for another extension on that final call.

**Documents as PDFs.** Letters render from the same Jinja templates the on-screen
preview uses, with an embedded font so ₹ survives.

**Reporting.** Acceptance rate, median time-to-decision, funnel, decline
reasons, and a CSV export — all derived from the audit trail at request time.

---

## The rules it enforces

These live in one place (`core/lifecycle.py`) as pure functions over state, so
the API, the graph nodes and the UI all consult the same implementation.

| | |
|---|---|
| 1 | Only a `SELECTED` candidate can be issued an Offer Letter |
| 2 | An Offer Letter must be released before an Appointment Letter |
| 3 | The Appointment Letter needs the candidate's acceptance |
| 4 | A decline permanently blocks the Appointment Letter |
| 5 | The candidate never sees a document before it is released |
| 6 | The Appointment Letter is never released automatically |
| 7 | Offer and Appointment are separate documents with separate statuses |

**A phone call cannot accept an offer.** A verbal yes on the follow-up call
records `ACCEPTED_INTENT` and raises an HR notification — it never writes
`offer_letter.status`. Binding acceptance stays the token-guarded click in the
candidate portal, because an unauthenticated phone call is not an acceptable
basis for an employment contract.

---

## Stack

**Backend** — Python 3.12, FastAPI, LangGraph (`AsyncPostgresSaver`),
PostgreSQL, Jinja2, xhtml2pdf, Resend, LiveKit Agents + Deepgram.
LLM via NVIDIA NIM (OpenAI-compatible), used for prose only — never for payroll
or document bodies.

**Frontend** — Next.js 16 (App Router), React 19, TypeScript, Tailwind 3.4,
framer-motion, React Three Fiber (login screen only).

---

## Running it

### Prerequisites

PostgreSQL, Python 3.12+, Node 20+.

### Backend

```bash
pip install -r requirements.txt
cp .env.example .env     # then fill it in — see below
createdb onboarding_db
python3 -m uvicorn api.main:app --reload
```

The API creates its own tables on first boot. If `HR_PASSWORD` is unset it
generates one for the run and prints it:

```
[auth] no HR_PASSWORD set; generated one for this run:
[auth]   username: hr
[auth]   password: ...
```

### Frontend

```bash
cd frontend
npm install
npm run dev          # http://localhost:3000
```

### Voice worker (optional)

```bash
python3 -m voice.agent dev
```

> Editing `.env` does **not** restart `uvicorn --reload` — it only watches
> `*.py`. Restart manually after a config change.

### Minimum configuration

| Variable | Needed for |
|---|---|
| `DATABASE_URL` | everything |
| `CANDIDATE_TOKEN_SECRET` | signing candidate links and operator sessions |
| `PII_ENCRYPTION_KEY_B64` | PII at rest (also a fallback for the above) |
| `NVIDIA_API_KEY` | rejection-email prose, voice conversation |
| `RESEND_API_KEY`, `RESEND_FROM` | sending letters |
| `HR_PASSWORD` | console login (generated per run if unset) |

Voice additionally needs `LIVEKIT_*`, `DEEPGRAM_API_KEY` and a SIP trunk — see
[docs/VOICE_AGENT.md](docs/VOICE_AGENT.md).

---

## Tests

```bash
python3 -m pytest tests/ -q
```

**151 tests.** None require LiveKit, Deepgram or telephony; the database-backed
suites skip cleanly without Postgres.

| File | Covers |
|---|---|
| `test_auth.py` | Operator auth, and a guard that walks every route and fails if one answers an unauthenticated request |
| `test_dispatch_retry.py` | A bounced letter stays resumable instead of stranding the workflow |
| `test_pdf_and_reports.py` | PDF rendering, ₹ survival, reporting projections |
| `test_voice_eligibility.py` | Who may be called, and who may not |
| `test_voice_conversation.py` | Call outcomes, and that a final call cannot extend itself |
| `test_voice_idempotency.py` | Duplicate-call protection, including a 10-way concurrent race |
| `test_voice_scheduler.py` | The scheduler branch on the real graph |
| `test_voice_graph_integration.py` | Follow-up armed from a real dispatch |

Two of these are guards rather than feature tests: one fails if any new route is
reachable without a session, the other fails if a frontend component calls
`fetch()` directly instead of going through the API client — which is how an
endpoint silently starts returning 401 after it moves behind auth.

---

## Layout

```
agents/        LangGraph nodes — triage, financial, offer, email, lifecycle
core/
  graph.py     9-node StateGraph with three interrupts
  lifecycle.py the business rules, as pure functions
  state.py     the shared state schema
  scheduler.py in-process poller: scheduled sends and due voice calls
  india/       compensation, statutory config, documents, locations, PDF
  voice_*.py   call state machine and transitions
api/           FastAPI — auth, recruitment, voice, reports
voice/         LiveKit worker, dialer, prompts
templates/     Jinja2 letters and emails
frontend/      Next.js console and candidate portal
tests/
```

---

## Status

This is a working prototype, not a deployed product. Known gaps, stated plainly:

- **Onboarding cannot reach `COMPLETED`.** The employee-record form (PAN,
  Aadhaar, UAN, bank details) is not built, so workflows stop at "In progress".
  The state fields, encryption and validation exist; the UI does not.
- **The FY2025-26 statutory rates are seeded placeholders**, carrying a
  `verified_on` date the API exposes. Check them against the Finance Act before
  trusting any figure.
- **Voice calls need a SIP trunk.** LiveKit does not provide PSTN connectivity;
  outbound calling to Indian subscribers also requires TRAI/DLT registration.
- **Email delivery is sandboxed** unless you verify a domain with Resend.
- Threads created before the India localisation use the old US compensation
  model and will not show Indian breakups.

---

## Notes on a few decisions

**Documents are templates, not generations.** No model sits between the
computed salary and the letter a candidate reads. The LLM writes rejection
prose and conducts the voice call; it does not produce numbers or contract
terms.

**The release transition belongs to dispatch.** An Offer Letter becomes
`RELEASED` at the moment its email is accepted by the provider — not when an
endpoint says so. Three different paths approve a dispatch, and this is the only
way they agree.

**A failed dispatch parks, it does not end.** `route_after_dispatch` sends a
failure back to the gate, which `interrupt_before` turns into "wait for HR"
rather than "retry immediately" — so a bounced address can be corrected and
re-sent instead of stranding the candidate.

**`UNIQUE (thread_id, call_type)` is the real duplicate-call guard.** The state
machine handles the ordinary races; only a database constraint survives two
workers, a retried job and a restart.
