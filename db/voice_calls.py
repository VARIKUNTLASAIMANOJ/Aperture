"""
Call records (§12) and the idempotency guard (§15).

WHY A TABLE AND NOT GRAPH STATE
-------------------------------
Everything else in this project lives in the LangGraph checkpoint, and the
follow-up STATE MACHINE still does. Transcripts do not: LangGraph rewrites the
full checkpoint on every super-step, so a multi-kilobyte transcript would be
copied on each one. Call records are also the one thing here that wants
cross-candidate querying ("how many declines this month"), which JSON inside a
checkpoint blob answers badly.

WHY RAW psycopg AND NOT SQLModel/Alembic
----------------------------------------
requirements.txt lists both, but the project contains no models and no
migrations — the only existing Postgres access (api.main._all_thread_ids,
core.scheduler) is raw psycopg. Following the code's actual convention beats
following its aspirational dependency list.

WHY THE UNIQUE CONSTRAINT MATTERS
---------------------------------
The state machine guards against the ordinary races. It does not survive two
workers, a retried job, or a restart mid-dial. `UNIQUE (thread_id, call_type)`
does: the second INSERT loses, deterministically, in the database. That is the
difference between "a candidate probably won't be called twice" and "a
candidate cannot be called twice".
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Optional

import psycopg

SCHEMA = """
CREATE TABLE IF NOT EXISTS voice_calls (
    id                  BIGSERIAL PRIMARY KEY,
    thread_id           TEXT        NOT NULL,
    candidate_id        TEXT,
    document_number     TEXT,
    call_type           TEXT        NOT NULL,
    phone_number        TEXT        NOT NULL,
    provider_call_id    TEXT,
    room_name           TEXT,
    call_status         TEXT        NOT NULL DEFAULT 'PENDING',
    call_outcome        TEXT,
    candidate_intent    TEXT,
    follow_up_required  BOOLEAN     NOT NULL DEFAULT FALSE,
    follow_up_date      TIMESTAMPTZ,
    reason_if_declined  TEXT,
    summary             TEXT,
    transcript          JSONB,
    call_started_at     TIMESTAMPTZ,
    call_ended_at       TIMESTAMPTZ,
    call_duration_s     INTEGER,
    attempt             INTEGER     NOT NULL DEFAULT 1,
    error_detail        TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- §15: one LIVE row per (thread, call type). A duplicate webhook, a retried
-- job or a second worker all collide here rather than placing a second call.
--
-- Partial on purpose. A FAILED attempt must stay in the table as evidence —
-- "we tried and the dial failed" is exactly what HR needs to see — while still
-- letting a retry claim the slot. Deleting the row to free the slot (the
-- original approach) silently destroyed the only record of the failure.
CREATE UNIQUE INDEX IF NOT EXISTS voice_calls_active_uniq
    ON voice_calls (thread_id, call_type)
    WHERE call_status IN ('PENDING', 'IN_PROGRESS', 'COMPLETED');

DROP INDEX IF EXISTS voice_calls_thread_type_uniq;

CREATE INDEX IF NOT EXISTS voice_calls_status_idx  ON voice_calls (call_status);
CREATE INDEX IF NOT EXISTS voice_calls_thread_idx  ON voice_calls (thread_id);
CREATE INDEX IF NOT EXISTS voice_calls_created_idx ON voice_calls (created_at DESC);

-- Added after the table shipped, so ALTER rather than a column in CREATE:
-- an existing deployment would never pick it up otherwise.
ALTER TABLE voice_calls ADD COLUMN IF NOT EXISTS candidate_name   TEXT;
ALTER TABLE voice_calls ADD COLUMN IF NOT EXISTS designation      TEXT;
ALTER TABLE voice_calls ADD COLUMN IF NOT EXISTS recording_url    TEXT;
"""


def _dsn() -> str:
    return os.environ.get(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost/onboarding_db"
    )


async def setup(dsn: str | None = None) -> None:
    """Idempotent. Called once from the FastAPI lifespan, beside checkpointer.setup()."""
    async with await psycopg.AsyncConnection.connect(dsn or _dsn()) as conn:
        await conn.execute(SCHEMA)
        await conn.commit()


async def claim_call(
    thread_id: str,
    call_type: str,
    phone_number: str,
    *,
    candidate_id: Optional[str] = None,
    candidate_name: Optional[str] = None,
    designation: Optional[str] = None,
    document_number: Optional[str] = None,
    attempt: int = 1,
    dsn: str | None = None,
) -> Optional[int]:
    """
    Atomically reserve the right to place one call.

    Returns the new row id, or None if this (thread, call_type) is already
    claimed — in which case the caller must NOT dial. This is the single
    chokepoint every dial path goes through.

    ON CONFLICT DO NOTHING rather than an upsert: a conflict means someone else
    owns this call, and quietly overwriting their row would re-open exactly the
    duplicate-dial window the constraint exists to close.
    """
    async with await psycopg.AsyncConnection.connect(dsn or _dsn()) as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO voice_calls
                    (thread_id, candidate_id, candidate_name, designation,
                     document_number, call_type, phone_number, call_status,
                     attempt)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'PENDING', %s)
                -- The WHERE clause names the PARTIAL index as the arbiter.
                -- A plain NOT EXISTS pre-check is not atomic: concurrent
                -- callers all pass it before any of them commits, and the
                -- loser then raises UniqueViolation instead of returning None.
                ON CONFLICT (thread_id, call_type)
                    WHERE call_status IN ('PENDING', 'IN_PROGRESS', 'COMPLETED')
                    DO NOTHING
                RETURNING id
                """,
                (thread_id, candidate_id, candidate_name, designation,
                 document_number, call_type, phone_number, attempt),
            )
            row = await cur.fetchone()
        await conn.commit()
    return row[0] if row else None


async def release_claim(call_id: int, dsn: str | None = None) -> None:
    """
    Free the slot so the call can be retried, WITHOUT losing the record.

    Used when the dial failed before anyone was reached (NO_ANSWER, BUSY,
    provider error). Marking the row FAILED drops it out of the partial unique
    index, so a retry can claim — while the attempt and its error_detail stay
    visible to HR.

    This used to DELETE the row. That freed the slot and destroyed the only
    evidence the call had been attempted: a trunk misconfiguration showed up as
    an empty call list rather than as a failure anyone could read.
    """
    async with await psycopg.AsyncConnection.connect(dsn or _dsn()) as conn:
        await conn.execute(
            """
            UPDATE voice_calls
               SET call_status = 'FAILED',
                   call_outcome = COALESCE(call_outcome, 'CALL_FAILED'),
                   updated_at = now()
             WHERE id = %s
            """,
            (call_id,),
        )
        await conn.commit()


async def update_call(call_id: int, dsn: str | None = None, **fields: Any) -> None:
    """Patch a call row. Unknown columns are ignored rather than raising."""
    allowed = {
        "provider_call_id", "room_name", "call_status", "call_outcome",
        "candidate_intent", "follow_up_required", "follow_up_date",
        "reason_if_declined", "summary", "transcript", "call_started_at",
        "call_ended_at", "call_duration_s", "error_detail", "recording_url",
    }
    sets, values = [], []
    for key, value in fields.items():
        if key not in allowed:
            continue
        sets.append(f"{key} = %s")
        values.append(json.dumps(value) if key == "transcript" and value is not None
                      else value)
    if not sets:
        return

    sets.append("updated_at = now()")
    values.append(call_id)
    async with await psycopg.AsyncConnection.connect(dsn or _dsn()) as conn:
        await conn.execute(
            f"UPDATE voice_calls SET {', '.join(sets)} WHERE id = %s", tuple(values)
        )
        await conn.commit()


async def get_call(call_id: int, dsn: str | None = None) -> Optional[dict]:
    async with await psycopg.AsyncConnection.connect(dsn or _dsn()) as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT * FROM voice_calls WHERE id = %s", (call_id,))
            row = await cur.fetchone()
            if not row:
                return None
            cols = [d.name for d in cur.description or []]
    return dict(zip(cols, row))


async def calls_for_thread(thread_id: str, dsn: str | None = None) -> list[dict]:
    async with await psycopg.AsyncConnection.connect(dsn or _dsn()) as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM voice_calls WHERE thread_id = %s ORDER BY created_at",
                (thread_id,),
            )
            rows = await cur.fetchall()
            cols = [d.name for d in cur.description or []]
    return [dict(zip(cols, r)) for r in rows]


async def reconcile_stale(max_age_minutes: int = 15, dsn: str | None = None) -> int:
    """
    Fail calls left IN_PROGRESS by a crash or restart.

    Without this a process killed mid-call leaves a row that blocks the
    candidate's follow-up forever — the claim is held by a call that no longer
    exists. Returns how many were reconciled.
    """
    async with await psycopg.AsyncConnection.connect(dsn or _dsn()) as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE voice_calls
                   SET call_status  = 'FAILED',
                       call_outcome = 'CALL_FAILED',
                       error_detail = 'Abandoned — the service restarted mid-call.',
                       updated_at   = now()
                 WHERE call_status IN ('PENDING', 'IN_PROGRESS')
                   AND created_at < now() - (%s * INTERVAL '1 minute')
                RETURNING id
                """,
                (max_age_minutes,),
            )
            rows = await cur.fetchall()
        await conn.commit()
    return len(rows)


async def recent_calls(limit: int = 100, dsn: str | None = None) -> list[dict]:
    """
    Every call, newest first — what the HR console's voice panel reads.

    Ordered by created_at rather than call_started_at so a call that failed
    before it ever connected still appears; those are the ones HR most needs
    to see, and ordering by a null column would bury them.
    """
    async with await psycopg.AsyncConnection.connect(dsn or _dsn()) as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM voice_calls ORDER BY created_at DESC LIMIT %s",
                (limit,),
            )
            rows = await cur.fetchall()
            cols = [d.name for d in cur.description or []]
    return [dict(zip(cols, r)) for r in rows]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
