"""Integration tests for the privacy-critical schema. Need a migrated Postgres at DATABASE_URL."""

import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")

PRIVATE_TABLES = (
    "teachers",
    "consents",
    "sessions",
    "turns",
    "move_progress",
    "mirror_clips",
    "teacher_week_stats",
    "deletion_log",
    "llm_usage",
    "speech_usage",
)
K_ANONYMITY_THRESHOLD = 20


async def _seed_teachers(conn: AsyncConnection, count: int, *, cluster: str = "C1") -> list[str]:
    ids: list[str] = []
    for _ in range(count):
        row = await conn.execute(
            text(
                "insert into teachers (phone_hash, wa_id_enc, lang, cluster_code) "
                "values (uuid_send(gen_random_uuid()) || uuid_send(gen_random_uuid()), uuid_send(gen_random_uuid()), 'hi', :cluster) "
                "returning id"
            ),
            {"cluster": cluster},
        )
        teacher_id = str(row.scalar_one())
        await conn.execute(
            text(
                "insert into teacher_week_stats "
                "(teacher_id, cluster_code, move_id, iso_week, met_delta, sessions) "
                "values (:id, :cluster, 1, '2026-W43', 1.0, 5)"
            ),
            {"id": teacher_id, "cluster": cluster},
        )
        ids.append(teacher_id)
    return ids


async def _trend_rows_as_dashboard(conn: AsyncConnection) -> list[tuple[str, int]]:
    await conn.execute(text("set local role dashboard_ro"))
    rows = await conn.execute(text("select cluster_code, n_teachers from public_trends"))
    return [(r.cluster_code, r.n_teachers) for r in rows]


async def test_a_cell_with_fewer_than_k_teachers_is_suppressed(conn: AsyncConnection):
    await _seed_teachers(conn, K_ANONYMITY_THRESHOLD - 1, cluster="K19")

    assert await _trend_rows_as_dashboard(conn) == []


async def test_a_cell_with_exactly_k_teachers_is_visible(conn: AsyncConnection):
    await _seed_teachers(conn, K_ANONYMITY_THRESHOLD, cluster="K20")

    assert await _trend_rows_as_dashboard(conn) == [("K20", K_ANONYMITY_THRESHOLD)]


async def test_dashboard_role_cannot_read_any_private_table(conn: AsyncConnection):
    await conn.execute(text("set local role dashboard_ro"))

    for table in PRIVATE_TABLES:
        nested = await conn.begin_nested()
        with pytest.raises(DBAPIError, match="permission denied"):
            await conn.execute(text(f"select 1 from {table} limit 1"))
        await nested.rollback()


async def test_row_level_security_is_enabled_on_every_private_table(conn: AsyncConnection):
    rows = await conn.execute(
        text(
            "select relname from pg_class "
            "where relname = any(:names) and relkind = 'r' and not relrowsecurity"
        ),
        {"names": list(PRIVATE_TABLES)},
    )

    assert [r.relname for r in rows] == []


async def test_deleting_a_teacher_removes_everything_that_hangs_off_them(conn: AsyncConnection):
    [teacher_id] = await _seed_teachers(conn, 1)
    await conn.execute(
        text(
            "insert into consents (teacher_id, version, text_sha256, channel) "
            "values (:id, 'v1', 'abc', 'whatsapp')"
        ),
        {"id": teacher_id},
    )
    session = await conn.execute(
        text("insert into sessions (teacher_id, kind) values (:id, 'rehearse') returning id"),
        {"id": teacher_id},
    )
    await conn.execute(
        text("insert into turns (session_id, role, text_scrubbed) values (:s, 'teacher', 'hi')"),
        {"s": session.scalar_one()},
    )

    await conn.execute(text("delete from teachers where id = :id"), {"id": teacher_id})

    for table in ("consents", "sessions", "teacher_week_stats"):
        remaining = await conn.execute(
            text(f"select count(*) from {table} where teacher_id = :id"), {"id": teacher_id}
        )
        assert remaining.scalar_one() == 0
    assert (await conn.execute(text("select count(*) from turns"))).scalar_one() == 0


async def test_the_same_phone_cannot_register_twice(conn: AsyncConnection):
    insert = text("insert into teachers (phone_hash, wa_id_enc, lang) values (:h, :w, 'hi')")
    params = {"h": b"\x01" * 32, "w": b"\x02" * 16}
    await conn.execute(insert, params)

    nested = await conn.begin_nested()
    with pytest.raises(DBAPIError, match="duplicate key"):
        await conn.execute(insert, params)
    await nested.rollback()


async def test_trends_view_is_a_security_barrier(conn: AsyncConnection):
    row = await conn.execute(
        text("select reloptions from pg_class where relname = 'public_trends'")
    )

    assert "security_barrier=true" in row.scalar_one()


async def test_published_teacher_count_is_bucketed_so_one_joiner_is_invisible(
    conn: AsyncConnection,
):
    await _seed_teachers(conn, K_ANONYMITY_THRESHOLD + 4, cluster="K24")

    assert await _trend_rows_as_dashboard(conn) == [("K24", K_ANONYMITY_THRESHOLD)]


async def test_published_averages_are_coarsely_rounded(conn: AsyncConnection):
    [first, *rest] = await _seed_teachers(conn, K_ANONYMITY_THRESHOLD, cluster="KR")
    await conn.execute(
        text("update teacher_week_stats set met_delta = 1.04 where teacher_id = :id"),
        {"id": first},
    )
    await conn.execute(text("set local role dashboard_ro"))

    row = await conn.execute(text("select avg_improvement from public_trends"))

    assert str(row.scalar_one()) == "1.0"
