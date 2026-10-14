# Onboarding Agent — Frontend

An immersive, conversational console for the LangGraph onboarding service. A
WebGL agent anchors the page and morphs through the workflow; glass overlays
carry the actual work.

## Running it

The frontend needs the FastAPI service running.

**1. Backend** (from the repo root):

```bash
python3 -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

**2. Frontend:**

```bash
cd frontend && npm install && npm run dev
```

Open http://localhost:3000. Copy `.env.local.example` to `.env.local` if your
API is not on `http://localhost:8000`.

The masthead shows live backend reachability — `Agent online`, `Graph not
ready`, or `Backend offline` — so a dead service is visible before you fill in
a five-step form rather than after.

## Routes

| Route | What it is |
| --- | --- |
| `/` | Admin dashboard — dispatch counts, approval queue, attention queue, audit trail |
| `/onboard` | The immersive 3D onboarding flow |
| `/thread/[threadId]` | One workflow — approve or reject its dispatch |

### The correspondence log

Under the three panels on `/` is a scrolling log of every letter the agent has
produced, across all workflows. Opening a row shows the **fully rendered
email** — the exact HTML handed to Resend — plus subject and delivery status.

Kind (Offer / Rejection) and status (Sent / Awaiting approval / Failed /
Cancelled) are two separate chips on purpose. A rejection that was sent and an
offer still waiting at the gate are entirely different situations, and one
merged badge would blur exactly the distinction being scanned for.

This needed a backend addition: `_mask_email_queue` strips `variables`, so a
rejection notice's body was **not retrievable through the API at all**, even
though it sits in the checkpoint. `GET /onboarding/{id}/messages` now serves
rendered bodies, and `agents/email_node.py` exposes `render_email(item)` so the
dispatch path and the preview share one renderer — a preview can never drift
from what actually gets sent.

It is a separate endpoint rather than a field on `/candidates` because full
letter HTML on every roster row would bloat a list payload that is fetched
every 15 seconds, for data only occasionally opened.

**The letter renders in `<iframe sandbox="" srcDoc={html}>`.** The body is
model-generated HTML; `dangerouslySetInnerHTML` would be a live XSS sink on a
page that can approve binding offers. An empty `sandbox` grants nothing — no
scripts, no forms, no same-origin access — verified in-browser: the framed
document cannot reach `contentDocument` on this origin.

### Scheduled auto-send

At the approval gate, "Send later instead" reveals a `datetime-local` picker.
Approving then records the decision but **leaves the thread parked at the
interrupt**, with its queue marked `SCHEDULED`. `core/scheduler.py` releases it
at the appointed time by flipping items back to `PENDING` and resuming the
graph — so a scheduled send travels the identical `email_node` path as a manual
one. There is no second sending implementation to drift out of sync.

**Why not Celery.** `workers/celery_app.py` exists, but Celery needs a Redis
broker and a running worker, and neither is present here. Routing scheduled
sends through it would enqueue tasks that never execute — a scheduled offer
letter would simply never arrive, with nothing surfacing the failure. The
scheduler is therefore an asyncio loop inside the API process. The schedule
itself lives in the Postgres checkpoint, never in memory, so a restart
re-discovers every outstanding one.

The trade-off is explicit: nothing fires while the API is down. Rather than
silently sending a stale offer hours late, an item more than
`AUTO_SEND_GRACE_MINUTES` (default 30) past its slot is failed as a missed
window. Tunable with `AUTO_SEND_POLL_SECONDS` (default 20) and
`AUTO_SEND_GRACE_MINUTES`.

Rejecting a scheduled thread cancels it — `email_node` treats `SCHEDULED` as
undispatched, otherwise the letter would still go out on its timer after a
rejection.

`sent_at` is now recorded by `email_node` at the moment of dispatch, so the
correspondence log prefers it over the audit-derived timestamp.

Status and dispatch mode stay separate axes, and the log renders both:

| State | Shown as |
| --- | --- |
| `SCHEDULED` | **Pending to send** (violet) + the target date |
| `SENT` + `AUTO` | **Auto-sent** + an `AUTO` badge + real send time |
| `FAILED` + `AUTO` | **Failed auto-send** |
| `SENT` / `FAILED` + `MANUAL` | **Sent** / **Failed** |

Violet, not amber: a machine timer and "a human must act" are both unsent, but
only one is waiting on a person.

### Why `/thread/[threadId]` exists

Without it the approval gate lived **only** inside the browser session that
started the run. Closing that tab stranded the thread permanently: no other
screen could resume it, and the dashboard could count threads awaiting approval
without being able to act on any of them — a number with no verb attached.

Queue rows are real links to this route, so a workflow is deep-linkable and the
back button behaves. `LiveRun` is reused verbatim rather than reimplemented, so
there is exactly one implementation of the approval path.

Approval deliberately happens **on the thread page, not inline in the list**.
Approving sends a binding offer letter; that should not be a one-click action
taken from a row without sight of the recipient, the figures and the audit
trail.

`+ Onboard` (top right of the dashboard) is a real `<Link>`, so browser history
and the back button behave normally — ux-guidelines "Back Button" lists
`location.replace` as the anti-pattern.

One design language across both. The dashboard reuses the same tokens, glass
primitive and grain as the flow; only the *backdrop* differs, and deliberately:
`/` gets a CSS ambient layer instead of the WebGL agent. A dense operations
view does not earn a moving, high-frequency object behind its numbers, and it
would cost a render loop for pure decoration.

### What the dashboard does not claim

`lib/dashboardData.ts` deliberately ignores `kanban_column`. The backend's
`_derive_kanban_column` maps `ERROR` to `COMPLETED` — terminal, but not
successful — so counting that field verbatim reports failed dispatches as
completed work. Every figure is recomputed from the underlying fields.

Likewise the tile is labelled **Mails sent**, not "delivered": the backend only
knows Resend *accepted* the call, and the caption says so. Nothing here reports
opens or deliveries, because no webhook receiver exists to know them.

Freshness is labelled honestly too — the readout says `Live` only while the
last poll succeeded and is under 45s old, and flips to `Stale · 2m ago` or
`Offline` otherwise, per the matched "Real-Time / Operations" pattern.

### The exit lock on `/onboard`

After the run reaches a terminal state, a **Go back to dashboard** button
unlocks. Before that it is rendered visibly locked with the reason
("Approve or reject dispatch to finish this run."), so the control does not
appear from nowhere at the end.

It uses `aria-disabled` + `tabIndex={0}` rather than `disabled`, so keyboard and
screen-reader users can still reach it and hear *why* it is unavailable. The
masthead logo stays a live link to `/` throughout — a locked primary path must
never become a dead end (ux-guidelines: no keyboard traps).

The lock is opt-in (`lockExitUntilTerminal`) and **off** on `/thread/[id]`. It
is a reasonable speed bump right after you launch a run; it is not reasonable
when you arrived from the queue to review one, may legitimately leave without
deciding, and already have a breadcrumb above it.

## Stack

| Concern | Choice |
| --- | --- |
| Framework | Next.js 16 (App Router, React 19) |
| 3D | `@react-three/fiber` 9 + `three` 0.185 |
| Animation | `framer-motion` 12 |
| Styling | Tailwind CSS 3.4 |

The brief asked for "Next.js 14+". Next 14 was rejected: every `14.2.x` release
falls inside the advisory range `0.9.9 - 16.3.0-preview.10`, so the whole line
is unpatched. `npm audit` reports 0 vulnerabilities on the shipped versions.

`framer-motion` is pinned to `12.43.0` deliberately. `12.23.12` imports
`activeAnimations` from `motion-dom`, and its own `^12.23.12` range resolves to
`motion-dom@12.43.0`, which removed that export — a breaking change inside a
semver-compatible range. The two must move together.

## How it maps to the backend

Every field name in `lib/types.ts` matches the Pydantic models in
`api/main.py` byte-for-byte; payloads are sent raw.

| UI | Endpoint |
| --- | --- |
| Masthead status | `GET /health` |
| "Release to agent" | `POST /onboarding/trigger` |
| Live pipeline + audit | `GET /{id}/stream` (SSE), `GET /{id}/state`, `GET /{id}/audit` |
| Approval gate | `POST /{id}/approve`, `POST /{id}/reject-approval` |
| Correspondence log | `GET /onboarding/candidates` (rows), `GET /{id}/messages` (letter body, on open) |

Two conversions happen at the boundary, both in `lib/form.ts`:

- 401(k) is collected as whole percent and sent as a fraction (`6` → `0.06`).
- A `REJECTED` candidate sends `null` for employment/dates/compensation, since
  that path never reaches `financial_node` or `contract_node`.

The tax-jurisdiction dropdown lists exactly the keys in
`core/financial_calculator.py::STATE_TAX_RATES`. Offering all 50 states would
imply precision the backend does not have — anything unlisted silently uses the
5% `OTHER` fallback, which the last option says out loud.

### The stream is an observer, not a trigger

`GET /{id}/stream` is a read-only checkpoint poller. `useOnboardingStream` never
sends anything that could resume the graph. This matters: the graph pauses at
`interrupt_before=["email_node"]`, and any `None`-input call (`ainvoke`,
`astream_events`) *resumes* it. If merely opening the page advanced the thread
past its approval gate, the later `/approve` would have nothing left to resume
and the offer would silently never send.

### Dispatch outcome is read from the queue, never from HTTP 200

`POST /{id}/approve` returns 200 whenever the graph *resumed* — even if every
message failed at the provider. The terminal state in `LiveRun` is therefore
derived from each queue item's own `SENT` / `FAILED` / `CANCELLED` status, so a
failed or partial dispatch is reported as such, with the provider's reason and
an explicit "the candidate was not contacted".

## The 3D agent

`lib/agentState.ts` is the single source of truth. Each mood is a set of
**targets** — colour, displacement amplitude, noise frequency, spin, pulse,
shell radius, particle energy. Nothing is ever assigned directly; `AgentCore`
damps toward them every frame, so a step change reads as the object physically
transforming.

Before launch, mood tracks the form step. After launch, `moodFromBackend()`
maps live graph state onto it:

| Graph state | Mood | Reads as |
| --- | --- | --- |
| `triage_node` | `deciding` | faceted, tense, nearly still |
| `financial_node` | `computing` | rigid, fast, mechanical |
| `contract_node` | `drafting` | molten, fluid, high amplitude |
| parked at `email_node` | `holding` | amber, slow breathing |
| `COMPLETE` | `settled` | cools to green, goes quiet |
| `ERROR` | `fault` | red, jittery, high frequency |

The surface is a custom shader (`components/scene/shaders.ts`): fbm simplex
noise displaces an icosahedron along its normals, and the normal is
**recomputed** from two tangent-offset samples. Without that recompute the
lighting stays glued to the undisplaced sphere and the morph reads as a texture
slide rather than geometry actually moving.

Damping uses `THREE.MathUtils.damp`, not `lerp(a, b, 0.1)` — the latter moves
twice as fast on a 120 Hz display as on a 60 Hz one, making transition speed
depend on the user's monitor.

## Design decisions and their provenance

Generated with the `ui-ux-pro-max` skill. Two results were **rejected on
inspection** rather than applied:

- `--design-system` returned **Brutalism** (instant transitions, 0px corners,
  `#FAF5FF` background) with an AI-purple palette. That is the direct opposite
  of the cinematic glassmorphism requested, and the palette was explicitly
  ruled out. Not used.
- The colour database is almost entirely light-mode. The dark **structure**
  (background, card, `rgba(255,255,255,0.08)` borders, `#94A3B8` muted text)
  comes from its one dark row; the **hue** is substituted to teal/cyan. This
  substitution is documented, not a database match.

Applied as matched:

- **Glassmorphism** — exact match, dark supported, carries
  `risk:conditional|requires:contrast-text-4.5`. That risk is real and drove
  two fixes below.
- **Inter** — matched on mood "dark, cinematic, technical, precision, premium".
- **Next.js**: page stays a Server Component; the client boundary is one leaf
  down. `NEXT_PUBLIC_` prefix for the API URL.
- **three.js**: render loop pauses on hidden tab (`frameloop="never"`) — R3F's
  equivalent of `setAnimationLoop(null)`.
- **UX guidelines**: visible step progress; labels never replaced by
  placeholders; errors beside their field and wired via `aria-describedby`;
  submit states show loading → success/error; reduced-motion respected.

### Two things the glass risk flag caught

1. **The panel substrate is a dark tint, not a white veil.** A purely
   translucent white panel inherits whatever the WebGL layer is doing behind
   it, and body text drops under 4.5:1 the moment the agent drifts underneath.
2. **The agent is anchored in the left column, not centre-screen.** Parking a
   bright, moving, high-frequency object directly behind body text cannot be
   rescued by tuning panel opacity. On two-column layouts the object occupies
   the upper-left band and the copy sits beneath it; below `lg` it retreats and
   shrinks, and the panel takes the foreground.

### Verified, not assumed

Measured in-browser against the running app:

- **0** contrast failures across all rendered text (WCAG AA, computed against
  resolved backgrounds). One token — `--c-fg-faint` — failed at 4.19:1 and was
  raised to 5.6:1; it is used for timestamps and thread ids, which is real text.
- **0** horizontal overflow at 375 / 768 / 1024 / 1440.
- All touch targets ≥ 44px, except the `sr-only` skip link which expands on
  focus.
- Shader compiles with no WebGL errors.

## Accessibility notes

- The canvas is `aria-hidden` and `pointer-events-none`. It is atmosphere; it
  never carries information alone — every mood has a text caption beside it.
- The decision fork is a real `radiogroup`: arrow keys move, `aria-checked`
  carries state, so selection is not communicated by colour alone.
- Failing validation moves focus to the first invalid control.
- Under `prefers-reduced-motion`, step transitions become opacity-only, the
  agent stops breathing and drifting, and pointer parallax is disabled — but
  the object still renders and still changes colour, so mood remains legible.
- If WebGL is unavailable or the context is lost, the scene falls back to a
  static gradient and the UI stays fully usable.

## Known gaps

- There is no route to open an **existing** thread. Each session tracks only
  the workflow it started, so a half-approved run cannot be resumed from a
  fresh tab. `GET /onboarding/candidates` already returns everything a
  review screen would need.
- No auth. The approve endpoint sends a legally-binding offer letter and
  `approved_by` is currently a hardcoded console identifier.
