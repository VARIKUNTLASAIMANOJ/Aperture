"""
One-shot repair for threads whose Offer Letter email was sent while the letter
itself stayed DRAFT.

Before the RELEASED transition moved into email_node, only /offer/release wrote
it. Approving from the run panel (or letting the auto-send scheduler fire)
dispatched the mail without it — so the candidate held a working link to a
portal that reported "Offer Letter — Not yet released" and refused their
acceptance under Rule 3.

This promotes exactly those threads: an offer_letter_email marked SENT is
proof the mail left, which is the same condition email_node now uses. Threads
where dispatch failed, was cancelled, or is still scheduled are left alone.

    python3 -m scripts.repair_offer_release           # report only
    python3 -m scripts.repair_offer_release --apply   # write the fix
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone

import psycopg
from dotenv import load_dotenv
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

load_dotenv()

from core.graph import build_graph  # noqa: E402
from core.state import OfferLetterStatus  # noqa: E402
from utils.audit import emit_audit  # noqa: E402

UNRELEASED = (None, "", OfferLetterStatus.NOT_CREATED.value, OfferLetterStatus.DRAFT.value)


def needs_repair(state: dict) -> bool:
    offer = state.get("offer_letter") or {}
    if offer.get("status") not in UNRELEASED:
        return False
    # Without a rendered body there is no letter to release, whatever the
    # queue says.
    if not offer.get("html"):
        return False
    return any(
        e.get("template_name") == "offer_letter_email" and e.get("status") == "SENT"
        for e in state.get("email_queue", [])
    )


async def main(apply: bool) -> int:
    db_url = os.environ.get(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost/onboarding_db"
    )

    async with await psycopg.AsyncConnection.connect(db_url) as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT DISTINCT thread_id FROM checkpoints WHERE checkpoint_ns = ''"
            )
            thread_ids = [r[0] for r in await cur.fetchall()]

    async with AsyncPostgresSaver.from_conn_string(db_url) as checkpointer:
        graph = await build_graph(checkpointer)
        repaired = 0

        for tid in thread_ids:
            cfg = {"configurable": {"thread_id": tid}}
            try:
                snapshot = await graph.aget_state(cfg)
            except Exception as exc:
                print(f"  ?  {tid}  could not read — {exc}")
                continue
            if not snapshot or not snapshot.values:
                continue

            state = dict(snapshot.values)
            if not needs_repair(state):
                continue

            offer = dict(state["offer_letter"])
            name = state.get("candidate_name") or state.get("candidate_id") or "?"
            doc_no = offer.get("document_number")
            # The dispatch timestamp is the honest release time; fall back to
            # now only for queue items written before sent_at was recorded.
            sent_at = next(
                (e.get("sent_at") for e in state.get("email_queue", [])
                 if e.get("template_name") == "offer_letter_email"
                 and e.get("status") == "SENT"),
                None,
            )
            released_at = sent_at or datetime.now(timezone.utc).isoformat()

            print(f"  →  {tid}  {name}  {doc_no}  DRAFT → RELEASED  ({released_at[:19]})")
            repaired += 1

            if apply:
                offer.update({
                    "status": OfferLetterStatus.RELEASED.value,
                    "released_at": released_at,
                    "released_by": state.get("approver_email") or "hr-console",
                })
                await graph.aupdate_state(cfg, {
                    "offer_letter": offer,
                    "audit_log": emit_audit(
                        node="repair", event="OFFER_LETTER_RELEASED",
                        payload_summary=(
                            f"Offer Letter {doc_no} marked released — the email had "
                            f"already been dispatched to {name} but the status was "
                            f"never updated."
                        ),
                        actor="MAINTENANCE",
                    ),
                })

    if repaired == 0:
        print("Nothing to repair — every dispatched Offer Letter is already released.")
    elif apply:
        print(f"\nRepaired {repaired} thread(s). Their candidate links now work.")
    else:
        print(f"\n{repaired} thread(s) would be repaired. Re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main("--apply" in sys.argv)))
