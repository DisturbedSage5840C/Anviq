"""Erasure against a real Postgres: nothing linked to the teacher may survive, and the log keeps
only the hash prefix."""

import secrets

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.teacher_store import deletion_log_prefix
from app.db.teacher_store import _PostgresSession
from app.privacy.crypto import KEY_BYTES, FieldCipher

PHONE_HASH = secrets.token_bytes(32)
SEEDED_TABLES = frozenset(
    {"consents", "sessions", "move_progress", "mirror_clips", "teacher_week_stats"}
)


async def _seed_teacher_with_everything(conn: AsyncConnection) -> str:
    teacher_id = str(
        (
            await conn.execute(
                text(
                    "insert into teachers (phone_hash, wa_id_enc, lang) "
                    "values (:h, uuid_send(gen_random_uuid()), 'hi') returning id"
                ),
                {"h": PHONE_HASH},
            )
        ).scalar_one()
    )
    params = {"t": teacher_id}
    await conn.execute(
        text(
            "insert into consents (teacher_id, version, text_sha256, channel) "
            "values (:t, 'v2', 'ab', 'whatsapp')"
        ),
        params,
    )
    session_id = (
        await conn.execute(
            text("insert into sessions (teacher_id, kind) values (:t, 'rehearse') returning id"),
            params,
        )
    ).scalar_one()
    turn_id = (
        await conn.execute(
            text(
                "insert into turns (session_id, role, text_scrubbed) "
                "values (:s, 'teacher', 'hi') returning id"
            ),
            {"s": session_id},
        )
    ).scalar_one()
    await conn.execute(
        text(
            "insert into move_progress (teacher_id, move_id, cycle_no, day1_turn_id) "
            "values (:t, 1, 1, :turn)"
        ),
        {**params, "turn": turn_id},
    )
    await conn.execute(
        text(
            "insert into mirror_clips (teacher_id, turn_id, audio_enc, expires_at) "
            "values (:t, :turn, uuid_send(gen_random_uuid()), now() + interval '1 day')"
        ),
        {**params, "turn": turn_id},
    )
    await conn.execute(
        text(
            "insert into teacher_week_stats (teacher_id, move_id, iso_week, met_delta) "
            "values (:t, 1, '2026-W42', 0.5)"
        ),
        params,
    )
    return teacher_id


async def _tables_keyed_by_teacher(conn: AsyncConnection) -> list[str]:
    rows = await conn.execute(
        text(
            "select table_name from information_schema.columns "
            "where table_schema = current_schema() and column_name = 'teacher_id'"
        )
    )
    return [row[0] for row in rows]


async def _erase(conn: AsyncConnection) -> None:
    await _PostgresSession(conn, FieldCipher(secrets.token_bytes(KEY_BYTES)), PHONE_HASH).erase()


async def _count(conn: AsyncConnection, query: str, teacher_id: str) -> int:
    return (await conn.execute(text(query), {"t": teacher_id})).scalar_one()


async def test_every_table_keyed_by_teacher_is_seeded_so_the_erase_check_cannot_pass_vacuously(
    conn: AsyncConnection,
):
    keyed = set(await _tables_keyed_by_teacher(conn))

    # a new teacher-keyed table must be added to the seed before this test goes green again
    assert keyed - {"teachers"} <= SEEDED_TABLES, keyed - SEEDED_TABLES


async def test_erase_leaves_no_row_in_any_table_keyed_by_teacher(conn: AsyncConnection):
    teacher_id = await _seed_teacher_with_everything(conn)
    tables = await _tables_keyed_by_teacher(conn)
    for table in tables:
        before = await _count(
            conn,
            f"select count(*) from {table} where teacher_id = :t",  # noqa: S608
            teacher_id,
        )
        assert before > 0, f"{table} was not seeded"

    await _erase(conn)

    for table in tables:
        left = await _count(
            conn,
            f"select count(*) from {table} where teacher_id = :t",  # noqa: S608
            teacher_id,
        )
        assert left == 0, f"{table} still holds {left} row(s) for the erased teacher"


async def test_erase_removes_the_teachers_turns_and_the_teacher_row(conn: AsyncConnection):
    teacher_id = await _seed_teacher_with_everything(conn)

    await _erase(conn)

    assert await _count(conn, "select count(*) from teachers where id = :t", teacher_id) == 0
    turns = "select count(*) from turns where session_id in (select id from sessions where teacher_id = :t)"
    assert await _count(conn, turns, teacher_id) == 0


async def test_erase_records_only_the_hash_prefix(conn: AsyncConnection):
    await _seed_teacher_with_everything(conn)

    await _erase(conn)

    rows = await conn.execute(
        text(
            "select phone_hash_prefix8, completed_at from deletion_log where phone_hash_prefix8 = :p"
        ),
        {"p": deletion_log_prefix(PHONE_HASH)},
    )
    [(prefix, completed_at)] = rows.all()
    assert prefix == PHONE_HASH[:8].hex()
    assert completed_at is not None
