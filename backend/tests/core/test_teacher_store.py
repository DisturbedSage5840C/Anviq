"""Contract tests: the in-memory fake and the Postgres store must behave identically."""

import asyncio
import os
import secrets
from collections.abc import AsyncIterator
from dataclasses import replace

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.router import Phase, TeacherState
from app.core.teacher_store import InMemoryTeacherStore, TeacherStore, deletion_log_prefix
from app.db.teacher_store import PostgresTeacherStore
from app.privacy.crypto import FieldCipher

HAS_DB = bool(os.environ.get("DATABASE_URL"))
WA_ID = "919876543210"
ENROLLED = TeacherState(Phase.IDLE, lang="en", grade_band="2", consented=True)


class Harness:
    """A store plus the hooks tests need to look behind it."""

    def __init__(
        self,
        store: TeacherStore,
        *,
        memory: InMemoryTeacherStore | None = None,
        engine: AsyncEngine | None = None,
    ) -> None:
        self.store = store
        self.memory = memory
        self.engine = engine
        self.hashes: list[bytes] = []


@pytest.fixture(
    params=[
        "memory",
        pytest.param(
            "postgres", marks=pytest.mark.skipif(not HAS_DB, reason="DATABASE_URL not set")
        ),
    ]
)
async def harness(request: pytest.FixtureRequest) -> AsyncIterator[Harness]:
    if request.param == "memory":
        memory = InMemoryTeacherStore()
        yield Harness(memory, memory=memory)
        return
    engine = create_async_engine(os.environ["DATABASE_URL"])
    cipher = FieldCipher(secrets.token_bytes(32))
    harness = Harness(PostgresTeacherStore(engine, cipher), engine=engine)
    try:
        yield harness
    finally:
        async with engine.begin() as conn:
            await conn.execute(
                text("delete from teachers where phone_hash = any(:hashes)"),
                {"hashes": harness.hashes},
            )
            await conn.execute(
                text("delete from deletion_log where phone_hash_prefix8 = any(:prefixes)"),
                {"prefixes": [deletion_log_prefix(h) for h in harness.hashes]},
            )
        await engine.dispose()


@pytest.fixture
def phone_hash(harness: Harness) -> bytes:
    fresh = secrets.token_bytes(32)
    harness.hashes.append(fresh)
    return fresh


async def _save(h: Harness, phone_hash: bytes, state: TeacherState) -> None:
    """Save, and record consent when the state claims it, as the real flow always does."""
    async with h.store.locked(phone_hash) as session:
        await session.save(state, WA_ID)
        if state.consented:
            await session.record_consent("v1", "cd" * 32)


async def _load(h: Harness, phone_hash: bytes) -> TeacherState:
    async with h.store.locked(phone_hash) as session:
        return await session.load()


async def test_unknown_teacher_loads_as_new(harness: Harness, phone_hash: bytes):
    assert await _load(harness, phone_hash) == TeacherState()


async def test_saved_state_round_trips(harness: Harness, phone_hash: bytes):
    await _save(harness, phone_hash, ENROLLED)
    assert await _load(harness, phone_hash) == ENROLLED


async def test_saving_new_creates_no_row(harness: Harness, phone_hash: bytes):
    await _save(harness, phone_hash, TeacherState())
    assert await _load(harness, phone_hash) == TeacherState()
    assert not await _row_exists(harness, phone_hash)


async def test_language_is_unknown_until_chosen(harness: Harness, phone_hash: bytes):
    await _save(harness, phone_hash, TeacherState(Phase.ONB_LANG))
    assert (await _load(harness, phone_hash)).lang is None


async def test_resume_phase_survives_a_round_trip(harness: Harness, phone_hash: bytes):
    pending = TeacherState(
        Phase.DELETE_CONFIRM, lang="hi", grade_band="1", consented=True, resume=Phase.IDLE
    )
    await _save(harness, phone_hash, pending)
    assert await _load(harness, phone_hash) == pending


async def test_consent_is_recorded_with_its_text_hash(harness: Harness, phone_hash: bytes):
    await _save(harness, phone_hash, replace(ENROLLED, consented=False))
    async with harness.store.locked(phone_hash) as session:
        await session.record_consent("v1", "ab" * 32)
    assert await _consents(harness, phone_hash) == [("v1", "ab" * 32)]
    assert (await _load(harness, phone_hash)).consented is True


async def test_erase_removes_the_teacher_and_logs_only_a_hash_prefix(
    harness: Harness, phone_hash: bytes
):
    await _save(harness, phone_hash, ENROLLED)
    async with harness.store.locked(phone_hash) as session:
        await session.erase()
    assert await _load(harness, phone_hash) == TeacherState()
    assert await _consents(harness, phone_hash) == []
    assert await _deletion_logged(harness, phone_hash)


async def test_erasing_an_unknown_teacher_logs_nothing(harness: Harness, phone_hash: bytes):
    async with harness.store.locked(phone_hash) as session:
        await session.erase()
    assert not await _deletion_logged(harness, phone_hash)


async def test_withdrawing_consent_revokes_it_but_keeps_the_ledger_row(
    harness: Harness, phone_hash: bytes
):
    await _save(harness, phone_hash, ENROLLED)
    async with harness.store.locked(phone_hash) as session:
        await session.withdraw_consent()
    assert await _consents(harness, phone_hash) == [("v1", "cd" * 32)]
    assert await _revoked_flags(harness, phone_hash) == [True]
    assert (await _load(harness, phone_hash)).consented is False


async def test_consenting_again_after_a_withdrawal_adds_a_second_active_row(
    harness: Harness, phone_hash: bytes
):
    await _save(harness, phone_hash, ENROLLED)
    async with harness.store.locked(phone_hash) as session:
        await session.withdraw_consent()
        await session.record_consent("v1", "ef" * 32)
    assert await _revoked_flags(harness, phone_hash) == [True, False]
    assert (await _load(harness, phone_hash)).consented is True


async def test_withdrawing_with_nothing_to_withdraw_changes_nothing(
    harness: Harness, phone_hash: bytes
):
    await _save(harness, phone_hash, replace(ENROLLED, consented=False))
    async with harness.store.locked(phone_hash) as session:
        await session.withdraw_consent()
    assert await _consents(harness, phone_hash) == []


async def test_opt_out_reminders_turns_the_flag_off(harness: Harness, phone_hash: bytes):
    await _save(harness, phone_hash, ENROLLED)
    async with harness.store.locked(phone_hash) as session:
        await session.opt_out_reminders()
    assert await _reminders_on(harness, phone_hash) is False


async def test_concurrent_messages_from_one_teacher_are_serialised(
    harness: Harness, phone_hash: bytes
):
    order: list[str] = []

    async def message(tag: str) -> None:
        async with harness.store.locked(phone_hash) as session:
            order.append(f"{tag}:in")
            await asyncio.sleep(0.05)
            await session.save(ENROLLED, WA_ID)
            order.append(f"{tag}:out")

    await asyncio.gather(message("a"), message("b"))
    assert order[0][0] == order[1][0] and order[2][0] == order[3][0]


async def test_a_failure_inside_the_block_rolls_back_every_write(
    harness: Harness, phone_hash: bytes
):
    if harness.engine is None:
        pytest.skip("rollback is a database property")
    with pytest.raises(RuntimeError):
        async with harness.store.locked(phone_hash) as session:
            await session.save(ENROLLED, WA_ID)
            raise RuntimeError("boom")
    assert await _load(harness, phone_hash) == TeacherState()


async def test_the_whatsapp_id_is_not_stored_in_the_clear(harness: Harness, phone_hash: bytes):
    if harness.engine is None:
        pytest.skip("only the database stores bytes")
    await _save(harness, phone_hash, ENROLLED)
    async with harness.engine.connect() as conn:
        stored = (
            await conn.execute(
                text("select wa_id_enc from teachers where phone_hash = :h"), {"h": phone_hash}
            )
        ).scalar_one()
    assert WA_ID.encode() not in bytes(stored)


# --- helpers that look behind the store -------------------------------------------------------


async def _row_exists(h: Harness, phone_hash: bytes) -> bool:
    if h.memory is not None:
        return phone_hash in h.memory.teachers
    assert h.engine is not None
    async with h.engine.connect() as conn:
        found = await conn.execute(
            text("select 1 from teachers where phone_hash = :h"), {"h": phone_hash}
        )
        return found.first() is not None


async def _consents(h: Harness, phone_hash: bytes) -> list[tuple[str, str]]:
    if h.memory is not None:
        stored = h.memory.teachers.get(phone_hash)
        return [(c.version, c.text_sha256) for c in stored.consents] if stored else []
    assert h.engine is not None
    async with h.engine.connect() as conn:
        rows = await conn.execute(
            text(
                "select c.version, c.text_sha256 from consents c "
                "join teachers t on t.id = c.teacher_id where t.phone_hash = :h"
            ),
            {"h": phone_hash},
        )
        return [(r[0], r[1]) for r in rows]


async def _revoked_flags(h: Harness, phone_hash: bytes) -> list[bool]:
    """Per consent row, oldest first: has it been revoked?"""
    if h.memory is not None:
        stored = h.memory.teachers.get(phone_hash)
        return [c.revoked for c in stored.consents] if stored else []
    assert h.engine is not None
    async with h.engine.connect() as conn:
        rows = await conn.execute(
            text(
                "select c.revoked_at is not null from consents c "
                "join teachers t on t.id = c.teacher_id where t.phone_hash = :h "
                "order by c.granted_at, c.id"
            ),
            {"h": phone_hash},
        )
        return [bool(r[0]) for r in rows]


async def _deletion_logged(h: Harness, phone_hash: bytes) -> bool:
    prefix = deletion_log_prefix(phone_hash)
    if h.memory is not None:
        return prefix in h.memory.deletion_log
    assert h.engine is not None
    async with h.engine.connect() as conn:
        found = await conn.execute(
            text("select 1 from deletion_log where phone_hash_prefix8 = :p"), {"p": prefix}
        )
        return found.first() is not None


async def _reminders_on(h: Harness, phone_hash: bytes) -> bool:
    if h.memory is not None:
        return h.memory.teachers[phone_hash].reminders_opt_in
    assert h.engine is not None
    async with h.engine.connect() as conn:
        return bool(
            (
                await conn.execute(
                    text("select reminders_opt_in from teachers where phone_hash = :h"),
                    {"h": phone_hash},
                )
            ).scalar_one()
        )
