"""Retention purge against a real Postgres: what ages out, what must survive."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.privacy.retention import TRANSCRIPT_RETENTION_DAYS, PurgeReport, purge_expired

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
            "insert into sessions (teacher_id, kind, started_at) "
            "values (:t, 'rehearse', :at) returning id"
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


async def test_purging_never_touches_the_teacher_or_their_progress(conn: AsyncConnection):
    teacher = await _teacher(conn)
    await _clip(conn, teacher, NOW - DAY)

    await purge_expired(conn, now=NOW)

    assert await _exists(conn, "teachers", teacher)


async def test_a_second_purge_finds_nothing_to_do(conn: AsyncConnection):
    session = await _session(conn, await _teacher(conn), CUTOFF - DAY)
    await _turn(conn, session, CUTOFF - DAY)

    await purge_expired(conn, now=NOW)

    assert await purge_expired(conn, now=NOW) == PurgeReport(turns=0, sessions=0, mirror_clips=0)
