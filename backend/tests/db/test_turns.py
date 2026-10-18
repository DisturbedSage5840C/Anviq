"""Turns are the only place free text is stored, so the scrubber must run on the way in."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.turns import record_turn
from app.guardrails.pii import PHONE_PLACEHOLDER


async def _session(conn: AsyncConnection) -> str:
    teacher_id = (
        await conn.execute(
            text(
                "insert into teachers (phone_hash, wa_id_enc, lang) values "
                "(uuid_send(gen_random_uuid()) || uuid_send(gen_random_uuid()), "
                "uuid_send(gen_random_uuid()), 'hi') returning id"
            )
        )
    ).scalar_one()
    return str(
        (
            await conn.execute(
                text("insert into sessions (teacher_id, kind) values (:t, 'ask') returning id"),
                {"t": teacher_id},
            )
        ).scalar_one()
    )


async def _stored_text(conn: AsyncConnection, turn_id: str) -> str:
    row = await conn.execute(
        text("select text_scrubbed from turns where id = :id"), {"id": turn_id}
    )
    return row.scalar_one()


async def test_a_phone_number_is_scrubbed_before_it_reaches_the_table(conn: AsyncConnection):
    session_id = await _session(conn)

    turn_id = await record_turn(conn, session_id, "teacher", "call me on 9876543210")

    stored = await _stored_text(conn, turn_id)
    assert stored == f"call me on {PHONE_PLACEHOLDER}"
    assert "9876543210" not in stored


async def test_a_pupils_name_is_scrubbed_but_text_without_pii_is_kept(conn: AsyncConnection):
    session_id = await _session(conn)

    named = await record_turn(conn, session_id, "teacher", "Pinky cannot blend")
    plain = await record_turn(conn, session_id, "coach", "Try segmenting first")

    assert "Pinky" not in await _stored_text(conn, named)
    assert await _stored_text(conn, plain) == "Try segmenting first"
