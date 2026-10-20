"""Where a practice is kept: a `rehearse` session per practice, a `turns` row per scored question.

The Day-1/Day-14 mirror reads these rows (`mirror_store`), so a practice that is never written
here is a mirror that never fires.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.rehearsal_log import LoggedTurn
from app.db.loop_store import teacher_id_for
from app.db.turns import record_turn


async def log_turn(conn: AsyncConnection, phone_hash: bytes, turn: LoggedTurn) -> None:
    """Add a scored question to the teacher's open practice, opening one if there is none.

    A teacher who withdrew consent while the model was thinking leaves nothing behind.
    """
    teacher_id = await _consented_teacher_id(conn, phone_hash)
    if teacher_id is None:
        return
    # Reusing the open practice is an upsert, so a concurrent close cannot slip between two steps.
    opened = await conn.execute(
        text(
            "insert into sessions (teacher_id, kind, move_id, topic_id, week) "
            "values (:teacher_id, 'rehearse', :move_id, :topic_id, :week) "
            "on conflict (teacher_id) where kind = 'rehearse' and ended_at is null "
            "do update set started_at = sessions.started_at returning id"
        ),
        {
            "teacher_id": teacher_id,
            "move_id": turn.move_id,
            "topic_id": turn.topic_id,
            "week": turn.week,
        },
    )
    await record_turn(
        conn,
        str(opened.scalar_one()),
        "teacher",
        turn.teacher_text,
        criteria=turn.criteria,
        child_name=turn.child_name,
        malrule_id=turn.malrule_id,
    )


async def _consented_teacher_id(conn: AsyncConnection, phone_hash: bytes) -> str | None:
    row = await conn.execute(
        text("select id from teachers where phone_hash = :h and consent_at is not null"),
        {"h": phone_hash},
    )
    found = row.scalar_one_or_none()
    return None if found is None else str(found)


async def close_practices(conn: AsyncConnection, phone_hash: bytes) -> None:
    """End whatever practice the teacher has open; the next scored turn starts a fresh one."""
    teacher_id = await teacher_id_for(conn, phone_hash)
    if teacher_id is None:
        return
    await conn.execute(
        text(
            "update sessions set ended_at = now() "
            "where teacher_id = :teacher_id and kind = 'rehearse' and ended_at is null"
        ),
        {"teacher_id": teacher_id},
    )


class PostgresRehearsalLog:
    """Each call is its own transaction, so a turn is kept even if the reply later fails."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def begin(self, teacher: bytes) -> None:
        async with self._engine.begin() as conn:
            await close_practices(conn, teacher)

    async def record(self, teacher: bytes, turn: LoggedTurn) -> None:
        async with self._engine.begin() as conn:
            await log_turn(conn, teacher, turn)

    async def end(self, teacher: bytes) -> None:
        async with self._engine.begin() as conn:
            await close_practices(conn, teacher)
