"""Reminder claims against a real Postgres: only consenting, opted-in, due teachers, once a day."""

import asyncio
import os
from datetime import UTC, date, datetime, time
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.channel.reminders import claim_due_reminders, reminder_window, still_reachable

# 07:00 IST on 18 Oct: reminder times from 05:00 to 07:00 are due.
WINDOW = reminder_window(datetime(2026, 10, 18, 1, 30, tzinfo=UTC))


async def _teacher(
    conn: AsyncConnection,
    *,
    reminder_time: time | None = time(7, 0),
    opted_in: bool = True,
    consented: bool = True,
    lang: str = "hi",
    last_reminded_on: date | None = None,
) -> UUID:
    row = await conn.execute(
        text(
            "insert into teachers (phone_hash, wa_id_enc, lang, reminders_opt_in, reminder_time, "
            "consent_at, last_reminded_on) values "
            "(uuid_send(gen_random_uuid()) || uuid_send(gen_random_uuid()), "
            "uuid_send(gen_random_uuid()), :lang, :opted_in, :reminder_time, "
            "case when :consented then now() end, :last) returning id"
        ),
        {
            "lang": lang,
            "opted_in": opted_in,
            "reminder_time": reminder_time,
            "consented": consented,
            "last": last_reminded_on,
        },
    )
    return row.scalar_one()


async def _clear(conn: AsyncConnection) -> None:
    await conn.execute(text("delete from teachers"))


async def test_a_due_opted_in_teacher_is_claimed_with_the_data_needed_to_send(
    conn: AsyncConnection,
):
    await _clear(conn)
    await _teacher(conn, lang="en")

    claimed = await claim_due_reminders(conn, WINDOW)

    assert [reminder.lang for reminder in claimed] == ["en"]
    assert len(claimed[0].wa_id_enc) == 16


async def test_a_teacher_is_reminded_at_most_once_a_day(conn: AsyncConnection):
    await _clear(conn)
    await _teacher(conn)

    first = await claim_due_reminders(conn, WINDOW)
    second = await claim_due_reminders(conn, WINDOW)

    assert (len(first), len(second)) == (1, 0)


async def test_a_teacher_reminded_yesterday_is_due_again_today(conn: AsyncConnection):
    await _clear(conn)
    await _teacher(conn, last_reminded_on=date(2026, 10, 17))

    claimed = await claim_due_reminders(conn, WINDOW)

    assert len(claimed) == 1


async def test_teachers_who_must_not_be_messaged_are_never_claimed(conn: AsyncConnection):
    await _clear(conn)
    await _teacher(conn, opted_in=False)  # never asked for reminders, or said "बंद करो"
    await _teacher(conn, consented=False)  # consent withdrawn
    await _teacher(conn, reminder_time=None)  # opted in but never picked a time
    await _teacher(conn, reminder_time=time(7, 30))  # not yet time
    await _teacher(conn, reminder_time=time(4, 59))  # too stale to send now

    claimed = await claim_due_reminders(conn, WINDOW)

    assert claimed == []


async def test_the_edges_of_the_window_are_both_included(conn: AsyncConnection):
    await _clear(conn)
    await _teacher(conn, reminder_time=time(5, 0))
    await _teacher(conn, reminder_time=time(7, 0))

    claimed = await claim_due_reminders(conn, WINDOW)

    assert len(claimed) == 2


async def test_a_batch_limit_leaves_the_rest_for_the_next_tick(conn: AsyncConnection):
    await _clear(conn)
    for _ in range(3):
        await _teacher(conn)

    first = await claim_due_reminders(conn, WINDOW, limit=2)
    second = await claim_due_reminders(conn, WINDOW, limit=2)

    assert (len(first), len(second)) == (2, 1)


async def test_a_teacher_who_withdrew_or_was_erased_after_the_claim_is_no_longer_reachable(
    conn: AsyncConnection,
):
    await _clear(conn)
    withdrawn = await _teacher(conn)
    opted_out = await _teacher(conn)
    erased = await _teacher(conn)
    still_there = await _teacher(conn)
    await conn.execute(
        text("update teachers set consent_at = null where id = :id"), {"id": withdrawn}
    )
    await conn.execute(
        text("update teachers set reminders_opt_in = false where id = :id"), {"id": opted_out}
    )
    await conn.execute(text("delete from teachers where id = :id"), {"id": erased})

    reachable = [
        await still_reachable(conn, teacher_id)
        for teacher_id in (withdrawn, opted_out, erased, still_there)
    ]

    assert reachable == [False, False, False, True]


async def test_the_claim_is_served_by_an_index_in_its_own_order(conn: AsyncConnection):
    row = await conn.execute(
        text("select indexdef from pg_indexes where indexname = 'teachers_reminder_due'")
    )

    definition = row.scalar_one()

    assert "(reminder_time, id)" in definition
    assert "reminders_opt_in" in definition and "consent_at IS NOT NULL" in definition


async def test_two_workers_claiming_at_once_get_different_teachers():
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set")
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.begin() as setup:
        await _clear(setup)
        ids = [await _teacher(setup, reminder_time=time(5, minute)) for minute in range(6)]
    try:
        async with engine.connect() as first, engine.connect() as second:
            await first.begin()
            await second.begin()
            held = await claim_due_reminders(first, WINDOW, limit=3)
            # The first worker's rows stay locked until it commits. The second must step over
            # them, not wait for them, and still fill its own batch from the rest.
            taken = await asyncio.wait_for(claim_due_reminders(second, WINDOW, limit=3), timeout=5)
            await first.commit()
            await second.commit()
        both = [reminder.teacher_id for reminder in (*held, *taken)]
        assert len(held) == len(taken) == 3
        assert sorted(both) == sorted(ids)
    finally:
        async with engine.begin() as cleanup:
            await cleanup.execute(text("delete from teachers where id = any(:ids)"), {"ids": ids})
        await engine.dispose()
