"""Retention purge against a real Postgres: what ages out, what must survive."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.privacy.retention import (
    REHEARSAL_RETENTION,
    TRANSCRIPT_RETENTION_DAYS,
    PurgeReport,
    purge_expired,
)

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
CUTOFF = NOW - timedelta(days=TRANSCRIPT_RETENTION_DAYS)
DAY = timedelta(days=1)


async def _teacher(conn: AsyncConnection) -> str:
    row = await conn.execute(
        text(
            "insert into teachers (phone_hash, wa_id_enc, lang) values "
            "(uuid_send(gen_random_uuid()) || uuid_send(gen_random_uuid()), "
            "uuid_send(gen_random_uuid()), 'hi') returning id"
        )
    )
    return str(row.scalar_one())


async def _session(conn: AsyncConnection, teacher_id: str, started_at: datetime) -> str:
    row = await conn.execute(
        text(
            "insert into sessions (teacher_id, kind, started_at, ended_at) "
            "values (:t, 'rehearse', :at, :at) returning id"
        ),
        {"t": teacher_id, "at": started_at},
    )
    return str(row.scalar_one())


async def _turn(conn: AsyncConnection, session_id: str, created_at: datetime) -> str:
    row = await conn.execute(
        text(
            "insert into turns (session_id, role, text_scrubbed, created_at) "
            "values (:s, 'teacher', 'hello', :at) returning id"
        ),
        {"s": session_id, "at": created_at},
    )
    return str(row.scalar_one())


async def _clip(conn: AsyncConnection, teacher_id: str, expires_at: datetime) -> str:
    row = await conn.execute(
        text(
            "insert into mirror_clips (teacher_id, audio_enc, expires_at) "
            "values (:t, uuid_send(gen_random_uuid()), :at) returning id"
        ),
        {"t": teacher_id, "at": expires_at},
    )
    return str(row.scalar_one())


async def _exists(conn: AsyncConnection, table: str, row_id: str) -> bool:
    row = await conn.execute(text(f"select 1 from {table} where id = :id"), {"id": row_id})  # noqa: S608
    return row.first() is not None


async def test_turns_older_than_the_retention_window_are_deleted(conn: AsyncConnection):
    session = await _session(conn, await _teacher(conn), NOW - 10 * DAY)
    old = await _turn(conn, session, CUTOFF - DAY)
    recent = await _turn(conn, session, NOW - DAY)

    report = await purge_expired(conn, now=NOW)

    assert not await _exists(conn, "turns", old)
    assert await _exists(conn, "turns", recent)
    assert report.turns == 1


async def test_a_turn_exactly_at_the_cutoff_is_kept(conn: AsyncConnection):
    session = await _session(conn, await _teacher(conn), NOW - DAY)
    boundary = await _turn(conn, session, CUTOFF)

    await purge_expired(conn, now=NOW)

    assert await _exists(conn, "turns", boundary)


async def test_an_old_session_with_no_turns_left_is_deleted_with_its_summary(
    conn: AsyncConnection,
):
    old_session = await _session(conn, await _teacher(conn), CUTOFF - 5 * DAY)
    await _turn(conn, old_session, CUTOFF - 5 * DAY)

    report = await purge_expired(conn, now=NOW)

    assert not await _exists(conn, "sessions", old_session)
    assert report.sessions == 1


async def test_an_old_session_that_still_has_a_recent_turn_is_kept(conn: AsyncConnection):
    session = await _session(conn, await _teacher(conn), CUTOFF - DAY)
    await _turn(conn, session, NOW - DAY)

    await purge_expired(conn, now=NOW)

    assert await _exists(conn, "sessions", session)


async def test_expired_mirror_clips_are_deleted_and_live_ones_kept(conn: AsyncConnection):
    teacher = await _teacher(conn)
    expired = await _clip(conn, teacher, NOW - timedelta(minutes=1))
    live = await _clip(conn, teacher, NOW + 3 * DAY)

    report = await purge_expired(conn, now=NOW)

    assert not await _exists(conn, "mirror_clips", expired)
    assert await _exists(conn, "mirror_clips", live)
    assert report.mirror_clips == 1


async def test_expired_demo_codes_are_deleted_and_live_ones_kept(conn: AsyncConnection):
    await conn.execute(text("delete from demo_codes"))
    for code_hash, expires_at in ((b"expired", NOW - timedelta(minutes=1)), (b"live", NOW + DAY)):
        await conn.execute(
            text("insert into demo_codes (code_hash, expires_at, turns_left) values (:h, :at, 5)"),
            {"h": code_hash, "at": expires_at},
        )

    report = await purge_expired(conn, now=NOW)

    remaining = (await conn.execute(text("select code_hash from demo_codes"))).scalars().all()
    assert [bytes(code_hash) for code_hash in remaining] == [b"live"]
    assert report.demo_codes == 1


async def _practising(conn: AsyncConnection, teacher_id: str, last_active_at: datetime) -> None:
    await conn.execute(
        text(
            "update teachers set rehearsal_json = '{\"turns\": 1}', "
            "last_topic_id = 'NUM.G2.SUB.REGROUP', last_active_at = :at where id = :t"
        ),
        {"t": teacher_id, "at": last_active_at},
    )


async def _practice_and_topic(
    conn: AsyncConnection, teacher_id: str
) -> tuple[str | None, str | None]:
    row = await conn.execute(
        text("select rehearsal_json, last_topic_id from teachers where id = :t"), {"t": teacher_id}
    )
    found = row.one()
    return found[0], found[1]


async def test_a_practice_abandoned_for_over_a_day_is_cleared_but_the_topic_stays(
    conn: AsyncConnection,
):
    teacher = await _teacher(conn)
    await _practising(conn, teacher, NOW - REHEARSAL_RETENTION - timedelta(minutes=1))

    report = await purge_expired(conn, now=NOW)

    assert await _practice_and_topic(conn, teacher) == (None, "NUM.G2.SUB.REGROUP")
    assert report.rehearsals == 1


async def test_a_practice_still_inside_its_day_is_kept(conn: AsyncConnection):
    teacher = await _teacher(conn)
    await _practising(conn, teacher, NOW - REHEARSAL_RETENTION)

    report = await purge_expired(conn, now=NOW)

    assert await _practice_and_topic(conn, teacher) == ('{"turns": 1}', "NUM.G2.SUB.REGROUP")
    assert report.rehearsals == 0


async def _open_practice(conn: AsyncConnection, teacher_id: str, last_active_at: datetime) -> str:
    await conn.execute(
        text("update teachers set last_active_at = :at where id = :t"),
        {"t": teacher_id, "at": last_active_at},
    )
    row = await conn.execute(
        text(
            "insert into sessions (teacher_id, kind, started_at) "
            "values (:t, 'rehearse', :at) returning id"
        ),
        {"t": teacher_id, "at": last_active_at},
    )
    return str(row.scalar_one())


async def _ended_at(conn: AsyncConnection, session_id: str) -> datetime | None:
    row = await conn.execute(text("select ended_at from sessions where id = :s"), {"s": session_id})
    return row.scalar_one()


async def test_a_practice_left_open_for_over_a_day_is_closed_when_the_teacher_last_spoke(
    conn: AsyncConnection,
):
    teacher = await _teacher(conn)
    stale_since = NOW - REHEARSAL_RETENTION - timedelta(minutes=1)
    session = await _open_practice(conn, teacher, stale_since)

    report = await purge_expired(conn, now=NOW)

    assert await _ended_at(conn, session) == stale_since
    assert report.practices_closed == 1


async def test_a_practice_whose_teacher_is_still_inside_the_day_stays_open(conn: AsyncConnection):
    teacher = await _teacher(conn)
    session = await _open_practice(conn, teacher, NOW - REHEARSAL_RETENTION)

    report = await purge_expired(conn, now=NOW)

    assert await _ended_at(conn, session) is None
    assert report.practices_closed == 0


async def test_closing_abandoned_practices_leaves_their_turns_and_other_sessions(
    conn: AsyncConnection,
):
    teacher = await _teacher(conn)
    stale = NOW - 2 * DAY
    session = await _open_practice(conn, teacher, stale)
    turn = await _turn(conn, session, stale)
    finished = await _session(conn, await _teacher(conn), stale)

    await purge_expired(conn, now=NOW)

    assert await _exists(conn, "turns", turn)
    assert await _ended_at(conn, finished) == stale


async def test_purging_never_touches_the_teacher_or_their_progress(conn: AsyncConnection):
    teacher = await _teacher(conn)
    await _clip(conn, teacher, NOW - DAY)

    await purge_expired(conn, now=NOW)

    assert await _exists(conn, "teachers", teacher)


async def test_a_second_purge_finds_nothing_to_do(conn: AsyncConnection):
    session = await _session(conn, await _teacher(conn), CUTOFF - DAY)
    await _turn(conn, session, CUTOFF - DAY)

    await purge_expired(conn, now=NOW)

    assert await purge_expired(conn, now=NOW) == PurgeReport(
        turns=0, sessions=0, mirror_clips=0, demo_codes=0, practices_closed=0
    )
