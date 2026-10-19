"""The mirror reads a teacher's Day 1 and latest best turns for the current move and advances it."""

import json
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.mirror_store import cycle_started_at, finish_mirror, mirror_pair


async def _teacher(conn: AsyncConnection, *, move: int = 1, cycle: int = 1) -> str:
    row = await conn.execute(
        text(
            "insert into teachers (phone_hash, wa_id_enc, lang, current_move, cycle_no) values "
            "(uuid_send(gen_random_uuid()) || uuid_send(gen_random_uuid()), "
            "uuid_send(gen_random_uuid()), 'hi', :move, :cycle) returning id"
        ),
        {"move": move, "cycle": cycle},
    )
    return str(row.scalar_one())


async def _session(conn: AsyncConnection, teacher: str, move: int, started: datetime) -> str:
    row = await conn.execute(
        text(
            "insert into sessions (teacher_id, kind, move_id, started_at) "
            "values (:t, 'rehearse', :move, :at) returning id"
        ),
        {"t": teacher, "move": move, "at": started},
    )
    return str(row.scalar_one())


async def _turn(
    conn: AsyncConnection,
    session: str,
    words: str,
    met: tuple[str, ...] = (),
    *,
    role: str = "teacher",
    of: tuple[str, ...] = ("C1", "C2", "C3"),
) -> str:
    criteria = {criterion: criterion in met for criterion in of}
    row = await conn.execute(
        text(
            "insert into turns (session_id, role, text_scrubbed, criteria_json, met_count) "
            "values (:s, :role, :words, cast(:criteria as jsonb), :met) returning id"
        ),
        {
            "s": session,
            "role": role,
            "words": words,
            "criteria": json.dumps(criteria),
            "met": len(met),
        },
    )
    return str(row.scalar_one())


DAY_ONE = datetime.fromisoformat("2026-10-01T09:00:00+00:00")
DAY_FOURTEEN = DAY_ONE + timedelta(days=13)


async def test_one_session_is_not_enough_to_compare(conn: AsyncConnection):
    teacher = await _teacher(conn)
    session = await _session(conn, teacher, 1, DAY_ONE)
    await _turn(conn, session, "what is this?", ("C1",))

    assert await mirror_pair(conn, teacher) is None


async def test_it_compares_the_best_teacher_turn_of_the_first_and_latest_sessions(
    conn: AsyncConnection,
):
    teacher = await _teacher(conn)
    first = await _session(conn, teacher, 1, DAY_ONE)
    await _turn(conn, first, "weak start", ("C1",))
    best_first = await _turn(conn, first, "better start", ("C1", "C2"))
    await _turn(conn, first, "coach words", ("C1", "C2", "C3"), role="coach")
    middle = await _session(conn, teacher, 1, DAY_ONE + timedelta(days=5))
    await _turn(conn, middle, "middle", ("C1", "C2", "C3"))
    latest = await _session(conn, teacher, 1, DAY_FOURTEEN)
    await _turn(conn, latest, "so so", ("C1",))
    best_latest = await _turn(conn, latest, "great now", ("C1", "C2", "C3"))

    pair = await mirror_pair(conn, teacher)

    assert pair is not None
    assert (pair.first_id, pair.latest_id) == (best_first, best_latest)
    assert pair.first.text == "better start"
    assert pair.first.criteria == {"C1": True, "C2": True, "C3": False}
    assert pair.latest.met_count == 3


async def test_other_moves_do_not_count(conn: AsyncConnection):
    teacher = await _teacher(conn, move=2)
    await _turn(conn, await _session(conn, teacher, 2, DAY_ONE), "move two", ("C1",))
    await _turn(conn, await _session(conn, teacher, 1, DAY_FOURTEEN), "move one", ("C1", "C2"))

    assert await mirror_pair(conn, teacher) is None


async def test_the_cycle_starts_when_the_first_session_of_the_move_started(conn: AsyncConnection):
    teacher = await _teacher(conn)
    await _session(conn, teacher, 1, DAY_FOURTEEN)
    await _session(conn, teacher, 1, DAY_ONE)
    await _session(conn, teacher, 2, DAY_ONE - timedelta(days=3))

    assert await cycle_started_at(conn, teacher) == DAY_ONE


async def test_a_teacher_who_has_not_practised_has_no_cycle_start(conn: AsyncConnection):
    assert await cycle_started_at(conn, await _teacher(conn)) is None


async def _progress(conn: AsyncConnection, teacher: str) -> list:
    rows = await conn.execute(
        text(
            "select move_id, cycle_no, day1_turn_id, day14_turn_id, status "
            "from move_progress where teacher_id = :t order by cycle_no, move_id"
        ),
        {"t": teacher},
    )
    return [tuple(str(v) if v is not None else None for v in row) for row in rows]


async def _position(conn: AsyncConnection, teacher: str) -> tuple[int, int]:
    row = await conn.execute(
        text("select current_move, cycle_no from teachers where id = :t"), {"t": teacher}
    )
    return tuple(row.one())  # type: ignore[return-value]


async def _two_sessions(conn: AsyncConnection, teacher: str, move: int) -> None:
    await _turn(conn, await _session(conn, teacher, move, DAY_ONE), "then", ("C1",))
    await _turn(conn, await _session(conn, teacher, move, DAY_FOURTEEN), "now", ("C1", "C2"))


async def test_finishing_records_the_pair_and_unlocks_the_next_move(conn: AsyncConnection):
    teacher = await _teacher(conn, move=3)
    await _two_sessions(conn, teacher, 3)
    pair = await mirror_pair(conn, teacher)
    assert pair is not None

    await finish_mirror(conn, teacher, pair)

    assert await _progress(conn, teacher) == [
        ("3", "1", pair.first_id, pair.latest_id, "done"),
    ]
    assert await _position(conn, teacher) == (4, 1)


async def test_finishing_twice_advances_only_once(conn: AsyncConnection):
    teacher = await _teacher(conn, move=3)
    await _two_sessions(conn, teacher, 3)
    pair = await mirror_pair(conn, teacher)
    assert pair is not None

    await finish_mirror(conn, teacher, pair)
    await finish_mirror(conn, teacher, pair)

    assert await _position(conn, teacher) == (4, 1)
    assert len(await _progress(conn, teacher)) == 1


async def test_after_the_last_move_the_teacher_starts_the_next_cycle_at_move_one(
    conn: AsyncConnection,
):
    teacher = await _teacher(conn, move=6, cycle=1)
    await _two_sessions(conn, teacher, 6)
    pair = await mirror_pair(conn, teacher)
    assert pair is not None

    await finish_mirror(conn, teacher, pair)

    assert await _position(conn, teacher) == (1, 2)
