"""Opt-in daily reminders: who is due now, and which approved WhatsApp template to send."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.ist import IST

# A worker that was down still delivers a reminder this late, but never a stale one after it.
CATCH_UP = timedelta(hours=2)

# The worker ticks every quarter hour; on the day's last tick (23:45 IST) the window runs to the end
# of the day, so a reminder set for 23:46-23:59 is sent a few minutes early rather than never.
LAST_TICK = time(23, 45)

# One tick claims at most this many teachers, so the sends finish well inside the job timeout. The
# rest are still due on the next tick, which the catch-up window covers.
CLAIM_BATCH = 100

REMINDER_TEMPLATES = {"hi": "daily_plan_reminder_hi", "en": "daily_plan_reminder_en"}


@dataclass(frozen=True)
class ReminderWindow:
    """Reminder times (IST wall clock) that are due on `today`."""

    today: date
    earliest: time
    latest: time


def reminder_window(now: datetime) -> ReminderWindow:
    local = now.astimezone(IST)
    start_of_day = datetime.combine(local.date(), time.min, tzinfo=IST)
    earliest = max(local - CATCH_UP, start_of_day)
    latest = time.max if local.time() >= LAST_TICK else local.time()
    return ReminderWindow(today=local.date(), earliest=earliest.time(), latest=latest)


@dataclass(frozen=True)
class DueReminder:
    teacher_id: UUID
    lang: str
    wa_id_enc: bytes


# Stamping last_reminded_on and returning the rows is one statement, so the claim and the "already
# sent today" mark cannot drift apart. skip locked keeps two workers off the same teacher. The pick
# is a materialized CTE so it runs once: as an `id in (... limit ...)` subquery the planner may
# rescan it for every row of the outer scan, and each rescan can claim more than the batch.
_CLAIM_DUE = text(
    """
    with due as materialized (
        select id from teachers
        where reminders_opt_in
          and consent_at is not null
          and reminder_time between :earliest and :latest
          and last_reminded_on is distinct from :today
        order by reminder_time, id
        limit :batch
        for update skip locked
    )
    update teachers set last_reminded_on = :today
    from due
    where teachers.id = due.id
    returning teachers.id, teachers.lang, teachers.wa_id_enc
    """
)


async def claim_due_reminders(
    conn: AsyncConnection, window: ReminderWindow, *, limit: int = CLAIM_BATCH
) -> list[DueReminder]:
    """Mark every due teacher as reminded today and return who to message.

    Claiming before sending makes delivery at-most-once: a crash or retry can drop a reminder
    but never double-message a teacher.
    """
    rows = await conn.execute(
        _CLAIM_DUE,
        {
            "today": window.today,
            "earliest": window.earliest,
            "latest": window.latest,
            "batch": limit,
        },
    )
    return [
        DueReminder(teacher_id=row.id, lang=row.lang, wa_id_enc=bytes(row.wa_id_enc))
        for row in rows
    ]


async def still_reachable(conn: AsyncConnection, teacher_id: UUID) -> bool:
    """Whether the teacher still consents and wants reminders, checked just before each send.

    Sends follow the claim by seconds; a withdrawal or erasure in between must win.
    """
    row = await conn.execute(
        text(
            "select 1 from teachers where id = :id and consent_at is not null and reminders_opt_in"
        ),
        {"id": teacher_id},
    )
    return row.first() is not None


def reminder_template(lang: str) -> str:
    try:
        return REMINDER_TEMPLATES[lang]
    except KeyError:
        raise ValueError(f"no reminder template for language {lang!r}") from None
