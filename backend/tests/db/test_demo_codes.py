"""Demo codes against a real Postgres: seven-day expiry, a turn budget, nothing stored in the clear."""

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.web.demo_codes import (
    DEMO_CODE_TTL,
    claim_turn,
    hash_code,
    issue_code,
    refund_turn,
    web_identity,
)

PEPPER = b"p" * 32
NOW = datetime(2026, 10, 18, 9, 0, tzinfo=UTC)


async def test_an_issued_code_works_until_its_turns_run_out(conn: AsyncConnection):
    code = await issue_code(conn, PEPPER, now=NOW, turns=2)

    results = [await claim_turn(conn, PEPPER, code, now=NOW) for _ in range(3)]

    expected = web_identity(hash_code(PEPPER, code))
    assert results == [expected, expected, None]


async def test_a_code_stops_working_after_seven_days(conn: AsyncConnection):
    code = await issue_code(conn, PEPPER, now=NOW, turns=5)

    last_moment = NOW + DEMO_CODE_TTL - timedelta(seconds=1)
    expiry = NOW + DEMO_CODE_TTL

    assert await claim_turn(conn, PEPPER, code, now=last_moment) is not None
    assert await claim_turn(conn, PEPPER, code, now=expiry) is None


async def test_an_unknown_code_is_refused(conn: AsyncConnection):
    assert await claim_turn(conn, PEPPER, "never-issued", now=NOW) is None


async def test_only_a_hash_is_stored_never_the_code(conn: AsyncConnection):
    code = await issue_code(conn, PEPPER, now=NOW, turns=1)

    stored = (await conn.execute(text("select code_hash from demo_codes"))).scalars().all()

    assert hash_code(PEPPER, code) in [bytes(value) for value in stored]
    assert all(code.encode() not in bytes(value) for value in stored)


async def test_a_refunded_turn_can_be_spent_again(conn: AsyncConnection):
    code = await issue_code(conn, PEPPER, now=NOW, turns=1)
    await claim_turn(conn, PEPPER, code, now=NOW)

    await refund_turn(conn, PEPPER, code)

    assert await claim_turn(conn, PEPPER, code, now=NOW) is not None


async def test_a_refund_for_an_unknown_code_changes_nothing(conn: AsyncConnection):
    await refund_turn(conn, PEPPER, "never-issued")

    assert (await conn.execute(text("select count(*) from demo_codes"))).scalar_one() == 0


async def test_concurrent_claims_never_overspend_a_single_turn():
    """Separate committed connections racing for one turn: exactly one wins."""
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set")
    engine = create_async_engine(os.environ["DATABASE_URL"])
    code_hash = None
    try:
        async with engine.begin() as setup:
            code = await issue_code(setup, PEPPER, now=NOW, turns=1)
        code_hash = hash_code(PEPPER, code)

        async def claim() -> str | None:
            async with engine.begin() as racer:
                return await claim_turn(racer, PEPPER, code, now=NOW)

        results = await asyncio.gather(*(claim() for _ in range(8)))
    finally:
        if code_hash is not None:
            async with engine.begin() as cleanup:
                await cleanup.execute(
                    text("delete from demo_codes where code_hash = :h"), {"h": code_hash}
                )
        await engine.dispose()

    assert sum(result is not None for result in results) == 1
