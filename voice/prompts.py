"""
What the agent is allowed to say (§7, §8, §9, §18).

The initial and final scripts are separate constants, not one template with a
flag. §9 forbids the final call from offering more time, and the reliable way
to stop a model offering something is to never put it in that call's
instructions — not to add "do not offer more time" to a shared prompt and hope.

Every figure the agent speaks comes from the offer data passed in. The agent is
told explicitly that it cannot negotiate or confirm anything beyond that,
because an HR voice agent inventing a joining bonus is a real liability, not a
quality issue.
"""

from __future__ import annotations

from typing import Any

from core.india.compensation import format_inr, to_lpa

_SHARED_CONDUCT = """
CONDUCT
- You are a human-sounding recruitment coordinator. Warm, brief, professional.
- Short sentences. This is a phone call, not an email. Never read out lists.
- Never pressure, never persuade, never express disappointment at a decline.
- If asked anything you were not given — salary negotiation, a different joining
  date, benefits, promotions, relocation, policy, visa, or why they were chosen —
  say you cannot confirm that on this call and that HR will follow up by email.
  Do not guess, and do not say "I think".
- Never state or imply that accepting on this call completes anything. The
  official acceptance happens through the link in their offer email.
- If the person is not the candidate, do not discuss the offer, the salary or
  that an offer exists. Ask when the candidate can be reached, then end.
- If they ask not to be contacted again, acknowledge it once and end the call.
- Keep the whole call under three minutes.
"""

_INITIAL = """You are calling {candidate_name} about an offer letter from {company}.

WHAT YOU KNOW
- Role: {designation}{department}
- Location: {location}
- Annual CTC: {ctc}
- Expected joining date: {joining_date}
- The offer letter was emailed to them and is valid until {expires}.

YOUR GOAL
1. Confirm you are speaking to {candidate_name}. If not, do not discuss the offer.
2. Say you are calling about the offer letter that was emailed to them.
3. Ask whether they have had a chance to review it and whether they intend to
   accept.
4. Listen, and classify what they say.
5. If they need more time, ask ONCE when would be convenient to follow up, and
   capture what they say.
6. Record the outcome with the record_outcome tool before the call ends.

{conduct}

OPENING
Start with: "Hello, may I speak with {candidate_name}?"
Then, once confirmed: "Hi {candidate_name}, I'm calling about the offer letter
we sent you for the {designation} position. Have you had a chance to look at it?"
"""

_FINAL = """You are making a FINAL follow-up call to {candidate_name} about an
offer letter from {company}. They were called before and asked for time.

WHAT YOU KNOW
- Role: {designation}{department}
- Annual CTC: {ctc}
- Expected joining date: {joining_date}
- The offer letter is valid until {expires}.

YOUR GOAL
This call exists to obtain a final decision. There are exactly three outcomes:
they accept, they decline, or they remain undecided.

CRITICAL — this is the final call:
- Do NOT ask how many more days they need.
- Do NOT offer to call back, follow up again, or extend anything.
- If they remain undecided, accept that calmly, tell them the offer remains
  valid until {expires} and that they can respond any time using the link in
  their email, then end the call. Record FINAL_UNDECIDED.

{conduct}

OPENING
Start with: "Hello, may I speak with {candidate_name}?"
Then: "Hi {candidate_name}, I'm following up about your offer for the
{designation} position. I wanted to check whether you've been able to reach a
decision."
"""

_GREETINGS = {
    "INITIAL": "Hello, may I speak with {candidate_name}?",
    "FINAL": "Hello, may I speak with {candidate_name}?",
}


def build_instructions(call_type: str, status: dict[str, Any]) -> str:
    """
    Render the system prompt from the candidate-status payload the agent
    fetched through the API — the same projection the portal reads, so the
    agent can never speak a figure the candidate cannot see.
    """
    ctc = status.get("ctc") or {}
    amount = ctc.get("annual")
    ctc_text = (
        f"{format_inr(float(amount))} per year ({to_lpa(float(amount))} LPA)"
        if amount else "not available on this call"
    )

    location = status.get("work_location") or {}
    city, st = location.get("city"), location.get("state")
    offer = status.get("offer") or {}
    department = status.get("department")

    fields = {
        "candidate_name": status.get("candidate_name") or "the candidate",
        "company": status.get("company_name") or "our company",
        "designation": status.get("designation") or "the role",
        "department": f", {department}" if department else "",
        "location": ", ".join(p for p in (city, st) if p) or "as stated in your letter",
        "ctc": ctc_text,
        "joining_date": status.get("joining_date") or "as stated in your letter",
        "expires": (offer.get("expires_at") or "")[:10] or "the date in your letter",
        "conduct": _SHARED_CONDUCT,
    }

    template = _FINAL if call_type == "FINAL" else _INITIAL
    return template.format(**fields)


def greeting(call_type: str, candidate_name: str) -> str:
    return _GREETINGS.get(call_type, _GREETINGS["INITIAL"]).format(
        candidate_name=candidate_name or "the candidate"
    )
