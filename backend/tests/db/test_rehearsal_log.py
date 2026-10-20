"""A practice leaves one session and its scored turns, which is what the Day-14 mirror compares."""

import logging
import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.core.rehearsal_log import LoggedTurn
from app.core.router import Phase, TeacherState
from app.db.mirror_store import mirror_pair
from app.db.rehearsal_log import close_practices, log_turn
from app.db.teacher_store import PostgresTeacherStore
from app.guardrails.pii import PHONE_PLACEHOLDER
from app.privacy.crypto import FieldCipher

HASH = b"h" * 32
OTHER_HASH = b"o" * 32
TOPIC = "NUM.G2.SUB.REGROUP"


def _turn(words: str = "How did you get that?", met: tuple[str, ...] = ("C1", "C2")) -> LoggedTurn:
    criteria = {cid: cid in met for cid in ("C1", "C2", "C3", "C4")}
    return LoggedTurn(2, TOPIC, "A", words, criteria, "Riya", "REGROUP.NO_CARRY")


async def _teacher(conn: AsyncConnection, phone_hash: bytes = HASH) -> str:
    row = await conn.execute(
        text(
            "insert into teachers (phone_hash, wa_id_enc, lang, current_move, consent_at) "
            "values (:h, uuid_send(gen_random_uuid()), 'hi', 2, now()) returning id"
        ),
        {"h": phone_hash},
    )
    return str(row.scalar_one())


async def _sessions(conn: AsyncConnection, teacher_id: str) -> list[dict]:
    rows = await conn.execute(
        text(
            "select id, kind, move_id, topic_id, week, ended_at from sessions "
            "where teacher_id = :t order by started_at, id"
        ),
        {"t": teacher_id},
    )
    return [dict(row._mapping) for row in rows]


async def _turns(conn: AsyncConnection, session_id: object) -> list[dict]:
    rows = await conn.execute(
        text(
            "select role, text_scrubbed, malrule_id, child_name, criteria_json, met_count "
            "from turns where session_id = :s order by created_at, id"
        ),
        {"s": session_id},
    )
    return [dict(row._mapping) for row in rows]


async def test_the_first_scored_turn_opens_a_rehearse_session_for_the_move_and_topic(
    conn: AsyncConnection,
):
    teacher = await _teacher(conn)

    await log_turn(conn, HASH, _turn())

    [session] = await _sessions(conn, teacher)
    assert (session["kind"], session["move_id"], session["topic_id"], session["week"]) == (
        "rehearse",
        2,
        TOPIC,
        "A",
    )
    assert session["ended_at"] is None


async def test_the_turn_keeps_the_teachers_words_and_what_the_coach_judged(conn: AsyncConnection):
    teacher = await _teacher(conn)

    await log_turn(conn, HASH, _turn("How did you get that?", met=("C1", "C3")))

    [session] = await _sessions(conn, teacher)
    [stored] = await _turns(conn, session["id"])
    assert stored["role"] == "teacher"
    assert stored["text_scrubbed"] == "How did you get that?"
    assert stored["met_count"] == 2
    assert stored["child_name"] == "Riya"
    assert stored["malrule_id"] == "REGROUP.NO_CARRY"
    assert stored["criteria_json"] == {"C1": True, "C2": False, "C3": True, "C4": False}


async def test_a_phone_number_is_scrubbed_before_it_reaches_the_table(conn: AsyncConnection):
    teacher = await _teacher(conn)

    await log_turn(conn, HASH, _turn("Call me on 9876543210"))

    [session] = await _sessions(conn, teacher)
    [stored] = await _turns(conn, session["id"])
    assert stored["text_scrubbed"] == f"Call me on {PHONE_PLACEHOLDER}"


async def test_later_turns_of_the_same_practice_join_the_same_session(conn: AsyncConnection):
    teacher = await _teacher(conn)

    await log_turn(conn, HASH, _turn("first"))
    await log_turn(conn, HASH, _turn("second"))

    [session] = await _sessions(conn, teacher)
    # One test transaction stamps every row alike, so only the contents are compared.
    kept = [t["text_scrubbed"] for t in await _turns(conn, session["id"])]
    assert sorted(kept) == ["first", "second"]


async def test_closing_the_practice_ends_its_session_and_the_next_turn_starts_another(
    conn: AsyncConnection,
):
    teacher = await _teacher(conn)
    await log_turn(conn, HASH, _turn("first"))

    await close_practices(conn, HASH)
    await log_turn(conn, HASH, _turn("second"))

    closed, reopened = sorted(await _sessions(conn, teacher), key=lambda s: s["ended_at"] is None)
    assert closed["ended_at"] is not None
    assert reopened["ended_at"] is None
    assert closed["id"] != reopened["id"]


async def test_a_practice_left_open_for_another_move_is_closed_not_joined(conn: AsyncConnection):
    teacher = await _teacher(conn)
    await log_turn(conn, HASH, _turn("old"))
    other_move = LoggedTurn(
        3, TOPIC, "A", "new", {"C1": True, "C2": False, "C3": False, "C4": False}
    )

    await log_turn(conn, HASH, other_move)

    open_sessions = [s for s in await _sessions(conn, teacher) if s["ended_at"] is None]
    assert [s["move_id"] for s in open_sessions] == [3]
    assert len(await _sessions(conn, teacher)) == 2


async def test_closing_with_no_practice_open_is_harmless(conn: AsyncConnection):
    teacher = await _teacher(conn)

    await close_practices(conn, HASH)

    assert await _sessions(conn, teacher) == []


async def test_one_teachers_practice_never_touches_anothers(conn: AsyncConnection):
    mine, theirs = await _teacher(conn), await _teacher(conn, OTHER_HASH)
    await log_turn(conn, HASH, _turn("mine"))
    await log_turn(conn, OTHER_HASH, _turn("theirs"))

    await close_practices(conn, HASH)

    [mine_session] = await _sessions(conn, mine)
    [their_session] = await _sessions(conn, theirs)
    assert mine_session["ended_at"] is not None
    assert their_session["ended_at"] is None
    assert [t["text_scrubbed"] for t in await _turns(conn, their_session["id"])] == ["theirs"]


async def test_a_teacher_who_withdrew_consent_leaves_nothing_behind(conn: AsyncConnection):
    teacher = await _teacher(conn)
    await conn.execute(text("update teachers set consent_at = null where id = :t"), {"t": teacher})

    await log_turn(conn, HASH, _turn())

    assert await _sessions(conn, teacher) == []


async def test_a_teacher_who_is_not_known_is_ignored(conn: AsyncConnection):
    await log_turn(conn, b"x" * 32, _turn())
    await close_practices(conn, b"x" * 32)

    count = await conn.execute(text("select count(*) from sessions"))
    assert count.scalar_one() == 0


async def test_a_teacher_cannot_have_two_practices_open_at_once(conn: AsyncConnection):
    teacher = await _teacher(conn)
    await log_turn(conn, HASH, _turn())
    insert = "insert into sessions (teacher_id, kind) values (:t, 'rehearse')"

    with pytest.raises(IntegrityError):
        async with conn.begin_nested():
            await conn.execute(text(insert), {"t": teacher})


async def test_two_closed_practices_give_the_mirror_its_day_1_and_day_14_turns(
    conn: AsyncConnection,
):
    teacher = await _teacher(conn)
    start = datetime.now(UTC) - timedelta(days=14)
    for offset, (words, met) in enumerate(
        [("Who can tell me?", ("C1",)), ("How did you get that?", ("C1", "C2", "C3"))]
    ):
        await log_turn(conn, HASH, _turn(words, met=met))
        await close_practices(conn, HASH)
        await conn.execute(
            text(
                "update sessions set started_at = :at where teacher_id = :t and ended_at is not null "
                "and started_at >= now() - interval '1 minute'"
            ),
            {"at": start + timedelta(days=13 * offset), "t": teacher},
        )

    pair = await mirror_pair(conn, teacher)

    assert pair is not None
    assert (pair.first.text, pair.first.met_count) == ("Who can tell me?", 1)
    assert (pair.latest.text, pair.latest.met_count) == ("How did you get that?", 3)


async def _enrolled_teacher(store: PostgresTeacherStore, phone_hash: bytes) -> None:
    async with store.locked(phone_hash) as session:
        await session.save(TeacherState(Phase.IDLE, lang="en", grade_band="2"), "919876543210")
        await session.record_consent("v1", "cd" * 32)


async def _forget(engine, phone_hash: bytes) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("delete from teachers where phone_hash = :h"), {"h": phone_hash})
    await engine.dispose()


async def test_the_session_commits_the_practice_with_the_message():
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set")
    engine = create_async_engine(os.environ["DATABASE_URL"])
    store = PostgresTeacherStore(engine, FieldCipher(os.urandom(32)))
    phone_hash = os.urandom(32)
    try:
        await _enrolled_teacher(store, phone_hash)

        async with store.locked(phone_hash) as session:
            await session.log_practice_turn(_turn("engine"))
            await session.close_practice()

        async with engine.connect() as conn:
            teacher = await conn.execute(
                text("select id from teachers where phone_hash = :h"), {"h": phone_hash}
            )
            [session_row] = await _sessions(conn, str(teacher.scalar_one()))
            assert session_row["ended_at"] is not None
            assert [t["text_scrubbed"] for t in await _turns(conn, session_row["id"])] == ["engine"]
    finally:
        await _forget(engine, phone_hash)


async def test_a_log_that_fails_rolls_back_alone_and_the_message_still_commits(monkeypatch):
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set")
    engine = create_async_engine(os.environ["DATABASE_URL"])
    store = PostgresTeacherStore(engine, FieldCipher(os.urandom(32)))
    phone_hash = os.urandom(32)

    async def breaks_the_statement(conn: AsyncConnection, who: bytes, turn: LoggedTurn) -> None:
        await conn.execute(text("select 1 / 0"))  # aborts a transaction that has no savepoint

    try:
        await _enrolled_teacher(store, phone_hash)
        monkeypatch.setattr("app.db.teacher_store.log_turn", breaks_the_statement)

        async with store.locked(phone_hash) as session:
            await session.log_practice_turn(_turn())
            await session.save_last_topic(TOPIC)  # would raise if the failure had poisoned it

        async with engine.connect() as conn:
            kept = await conn.execute(
                text("select last_topic_id from teachers where phone_hash = :h"),
                {"h": phone_hash},
            )
            assert kept.scalar_one() == TOPIC
    finally:
        await _forget(engine, phone_hash)


async def test_a_close_that_fails_is_logged_by_type_alone_and_the_message_still_commits(
    monkeypatch, caplog
):
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set")
    engine = create_async_engine(os.environ["DATABASE_URL"])
    store = PostgresTeacherStore(engine, FieldCipher(os.urandom(32)))
    phone_hash = os.urandom(32)

    class Carries(Exception):
        """Stands in for a driver error whose text quotes the statement and its values."""

    async def breaks_quoting_words(conn: AsyncConnection, who: bytes) -> None:
        raise Carries("update sessions ... teacher said: a private question")

    try:
        await _enrolled_teacher(store, phone_hash)
        monkeypatch.setattr("app.db.teacher_store.close_practices", breaks_quoting_words)
        caplog.set_level(logging.ERROR, logger="app.db.teacher_store")

        async with store.locked(phone_hash) as session:
            await session.close_practice()
            await session.save_last_topic(TOPIC)  # would raise if the failure had poisoned it

        async with engine.connect() as conn:
            kept = await conn.execute(
                text("select last_topic_id from teachers where phone_hash = :h"),
                {"h": phone_hash},
            )
            assert kept.scalar_one() == TOPIC
        assert [r.getMessage() for r in caplog.records] == ["practice close failed: Carries"]
        assert "private question" not in caplog.text
    finally:
        await _forget(engine, phone_hash)
