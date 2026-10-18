"""Reminder claims against a real Postgres: only consenting, opted-in, due teachers, once a day."""

from datetime import UTC, date, datetime, time
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

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
