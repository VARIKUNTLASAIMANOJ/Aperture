"""
§15 — duplicate-call protection, against the real Postgres.

The state machine is not the guard being tested here. Concurrent workers, a
retried job and a restart all bypass in-process state; only the database
constraint survives them, so these tests exercise it directly.

Skipped automatically when DATABASE_URL is unreachable.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import pytest_asyncio
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

from db import voice_calls  # noqa: E402

pytestmark = pytest.mark.asyncio

PHONE = "+919876543210"


@pytest.fixture(scope="module", autouse=True)
def _require_db():
    import psycopg
    try:
        with psycopg.connect(voice_calls._dsn(), connect_timeout=3) as conn:
            conn.execute("SELECT 1")
    except Exception as exc:
        pytest.skip(f"Postgres unavailable: {exc}")


@pytest_asyncio.fixture
async def thread_id():
    await voice_calls.setup()
    tid = f"test-{uuid.uuid4()}"
    yield tid
    import psycopg
    async with await psycopg.AsyncConnection.connect(voice_calls._dsn()) as conn:
        await conn.execute("DELETE FROM voice_calls WHERE thread_id = %s", (tid,))
        await conn.commit()


async def test_second_claim_on_the_same_call_is_refused(thread_id):
    first = await voice_calls.claim_call(thread_id, "INITIAL", PHONE)
    second = await voice_calls.claim_call(thread_id, "INITIAL", PHONE)
    assert first is not None
    assert second is None, "a duplicate event must not win a second claim"


async def test_concurrent_claims_produce_exactly_one_call(thread_id):
    """Ten workers race; nine must lose."""
    results = await asyncio.gather(*[
        voice_calls.claim_call(thread_id, "INITIAL", PHONE) for _ in range(10)
    ])
    winners = [r for r in results if r is not None]
    assert len(winners) == 1, f"expected 1 claim, got {len(winners)}"


async def test_initial_and_final_are_separate_claims(thread_id):
    assert await voice_calls.claim_call(thread_id, "INITIAL", PHONE) is not None
    assert await voice_calls.claim_call(thread_id, "FINAL", PHONE) is not None


async def test_released_claim_can_be_retried(thread_id):
    """A dial that never reached anyone must not burn the slot forever."""
    first = await voice_calls.claim_call(thread_id, "INITIAL", PHONE)
    await voice_calls.release_claim(first)
    retry = await voice_calls.claim_call(thread_id, "INITIAL", PHONE, attempt=2)
    assert retry is not None and retry != first


async def test_a_failed_dial_stays_visible_to_hr(thread_id):
    """
    Freeing the slot must not erase the evidence.

    Releasing used to DELETE the row, so a misconfigured SIP trunk showed up
    as an empty call list — the operator saw nothing at all, rather than a
    failed attempt with the provider's error on it.
    """
    call_id = await voice_calls.claim_call(thread_id, "INITIAL", PHONE)
    await voice_calls.update_call(call_id, error_detail="twirp error: object cannot be found")
    await voice_calls.release_claim(call_id)

    rows = await voice_calls.calls_for_thread(thread_id)
    assert len(rows) == 1, "the failed attempt must still be on record"
    assert rows[0]["call_status"] == "FAILED"
    assert rows[0]["call_outcome"] == "CALL_FAILED"
    assert "object cannot be found" in rows[0]["error_detail"]

    # And it must not block the retry.
    assert await voice_calls.claim_call(thread_id, "INITIAL", PHONE, attempt=2) is not None


async def test_only_one_live_claim_even_with_failures_present(thread_id):
    """Failed rows accumulate; only one live call may exist at a time."""
    first = await voice_calls.claim_call(thread_id, "INITIAL", PHONE)
    await voice_calls.release_claim(first)
    second = await voice_calls.claim_call(thread_id, "INITIAL", PHONE, attempt=2)

    assert await voice_calls.claim_call(thread_id, "INITIAL", PHONE, attempt=3) is None
    assert second is not None
    assert len(await voice_calls.calls_for_thread(thread_id)) == 2


async def test_different_threads_never_collide(thread_id):
    other = f"test-{uuid.uuid4()}"
    try:
        assert await voice_calls.claim_call(thread_id, "INITIAL", PHONE) is not None
        assert await voice_calls.claim_call(other, "INITIAL", PHONE) is not None
    finally:
        import psycopg
        async with await psycopg.AsyncConnection.connect(voice_calls._dsn()) as conn:
            await conn.execute("DELETE FROM voice_calls WHERE thread_id = %s", (other,))
            await conn.commit()


async def test_restart_reconciles_an_abandoned_call(thread_id):
    """A process killed mid-call must not block the candidate forever."""
    call_id = await voice_calls.claim_call(thread_id, "INITIAL", PHONE)
    await voice_calls.update_call(call_id, call_status="IN_PROGRESS")

    import psycopg
    async with await psycopg.AsyncConnection.connect(voice_calls._dsn()) as conn:
        await conn.execute(
            "UPDATE voice_calls SET created_at = now() - INTERVAL '1 hour' WHERE id = %s",
            (call_id,),
        )
        await conn.commit()

    assert await voice_calls.reconcile_stale(max_age_minutes=15) >= 1
    row = await voice_calls.get_call(call_id)
    assert row["call_status"] == "FAILED"
    assert row["call_outcome"] == "CALL_FAILED"


async def test_transcript_round_trips(thread_id):
    call_id = await voice_calls.claim_call(thread_id, "INITIAL", PHONE)
    turns = [{"role": "assistant", "text": "May I speak with Manoj?"},
             {"role": "user", "text": "Speaking."}]
    await voice_calls.update_call(call_id, transcript=turns, summary="Accepted verbally.")
    row = await voice_calls.get_call(call_id)
    assert row["transcript"] == turns
    assert row["summary"] == "Accepted verbally."


async def test_unknown_columns_are_ignored_not_injected(thread_id):
    call_id = await voice_calls.claim_call(thread_id, "INITIAL", PHONE)
    await voice_calls.update_call(call_id, **{"nonexistent_column": "x", "summary": "ok"})
    row = await voice_calls.get_call(call_id)
    assert row["summary"] == "ok"
