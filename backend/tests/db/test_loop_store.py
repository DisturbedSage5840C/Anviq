"""Postgres adapters behind Plan, Reflect, Mirror, Ask Anviq and the spend log."""

import hashlib
import json
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.ask.chunking import Chunk
from app.db.corpus import search_chunks, store_chunks
from app.db.loop_store import complete_mirror, due_pair, position_for, week_for

DAY_ONE = datetime.fromisoformat("2026-10-01T09:00:00+00:00")


async def _teacher(conn: AsyncConnection, name: str, move: int = 2) -> bytes:
    phone_hash = hashlib.sha256(name.encode()).digest()
    await conn.execute(
        text(
            "insert into teachers (phone_hash, wa_id_enc, lang, current_move, cycle_no) "
            "values (:h, '\\x00', 'hi', :move, 1)"
        ),
        {"h": phone_hash, "move": move},
    )
    return phone_hash


async def _session_with_turn(
    conn: AsyncConnection, phone_hash: bytes, move: int, at: datetime, met: tuple[str, ...]
) -> None:
    session = await conn.execute(
        text(
            "insert into sessions (teacher_id, kind, move_id, started_at) "
            "select id, 'rehearse', :move, :at from teachers where phone_hash = :h returning id"
        ),
        {"h": phone_hash, "move": move, "at": at},
    )
    criteria = {c: c in met for c in ("C1", "C2", "C3", "C4")}
    await conn.execute(
        text(
            "insert into turns (session_id, role, text_scrubbed, criteria_json, met_count) "
            "values (:s, 'teacher', 'q', cast(:c as jsonb), :m)"
        ),
        {"s": session.scalar_one(), "c": json.dumps(criteria), "m": len(met)},
    )


def test_week_a_then_b_and_demo_mode_scales_the_cycle():
    assert week_for(None, DAY_ONE, demo_minutes=None) == "A"
    assert week_for(DAY_ONE, DAY_ONE + timedelta(days=6), demo_minutes=None) == "A"
    assert week_for(DAY_ONE, DAY_ONE + timedelta(days=7), demo_minutes=None) == "B"
    assert week_for(DAY_ONE, DAY_ONE + timedelta(minutes=6), demo_minutes=10) == "B"


async def test_unknown_teacher_starts_at_move_one_week_a(conn: AsyncConnection):
    position = await position_for(conn, b"\x01" * 32, DAY_ONE, demo_minutes=None)
    assert (position.move_id, position.week) == (1, "A")


async def test_position_reads_the_current_move_and_cycle_week(conn: AsyncConnection):
    teacher = await _teacher(conn, "pos")
    await _session_with_turn(conn, teacher, 2, DAY_ONE, ("C1",))
    later = DAY_ONE + timedelta(days=8)
    position = await position_for(conn, teacher, later, demo_minutes=None)
    assert (position.move_id, position.week) == (2, "B")


async def test_mirror_waits_for_the_cycle_then_compares_and_unlocks(conn: AsyncConnection):
    teacher = await _teacher(conn, "mirror")
    await _session_with_turn(conn, teacher, 2, DAY_ONE, ("C1",))
    await _session_with_turn(conn, teacher, 2, DAY_ONE + timedelta(days=13), ("C1", "C2", "C3"))
    assert await due_pair(conn, teacher, DAY_ONE + timedelta(days=13), demo_minutes=None) is None
    pair = await due_pair(conn, teacher, DAY_ONE + timedelta(days=14), demo_minutes=None)
    assert pair is not None and (pair[0].met_count, pair[1].met_count) == (1, 3)
    await complete_mirror(conn, teacher)
    move = await conn.execute(
        text("select current_move from teachers where phone_hash = :h"), {"h": teacher}
    )
    assert move.scalar_one() == 3


async def test_corpus_chunks_are_found_by_words_in_their_language(conn: AsyncConnection):
    chunks = [
        Chunk(
            "NISHTHA FLN",
            9,
            "Numeracy",
            "3",
            "3.2",
            "Bundles",
            4,
            "en",
            "use bundles of ten sticks",
        ),
        Chunk("NISHTHA FLN", 9, "Numeracy", "3", "3.2", "बंडल", 4, "hi", "दस तीलियों के बंडल"),
    ]
    assert await store_chunks(conn, chunks, [None, None]) == 2
    found = await search_chunks(conn, "How do bundles help?", "en", 5)
    assert found and found[0].label == "NISHTHA FLN Course 9: Numeracy, Module 3, §3.2"
    assert 0 < found[0].score < 1
    hindi = await search_chunks(conn, "बंडल क्या है", "hi", 5)
    assert hindi and "तीलियों" in hindi[0].text
    assert await search_chunks(conn, "salary transfer", "en", 5) == []


async def test_usage_rows_hold_counts_and_cost_only(conn: AsyncConnection):
    columns = await conn.execute(
        text("select column_name from information_schema.columns where table_name = 'llm_usage'")
    )
    names = {row[0] for row in columns}
    assert not names & {"prompt", "text", "content", "reply", "messages"}


async def test_completing_for_an_unknown_teacher_is_a_no_op(conn: AsyncConnection):
    await complete_mirror(conn, b"\x02" * 32)
