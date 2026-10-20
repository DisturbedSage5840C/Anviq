"""Persistence port for the conversation router, plus an in-memory fake for tests.

One `locked()` block is one message: the store serialises concurrent messages from the same
teacher and commits or rolls back everything done inside the block together.
"""

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Protocol

from app.core.rehearsal_log import LoggedTurn
from app.core.router import TeacherState

DELETION_LOG_PREFIX_BYTES = 8


def deletion_log_prefix(phone_hash: bytes) -> str:
    """The only trace a deletion leaves: enough to prove it happened, not to identify anyone."""
    return phone_hash[:DELETION_LOG_PREFIX_BYTES].hex()


class TeacherSession(Protocol):
    async def load(self) -> TeacherState: ...

    async def idle_for(self) -> timedelta | None:
        """Time since the teacher's last saved message; None if they are unknown."""
        ...

    async def save(self, state: TeacherState, wa_id: str) -> None:
        """Persist `state`. A NEW teacher has nothing worth keeping, so no row is created."""
        ...

    async def record_consent(self, version: str, text_sha256: str) -> None: ...

    async def withdraw_consent(self) -> None:
        """Revoke every active consent. The ledger rows are kept, marked as revoked."""
        ...

    async def erase(self) -> None:
        """Delete the teacher and everything they own, and log the deletion."""
        ...

    async def opt_out_reminders(self) -> None: ...

    async def load_rehearsal(self) -> "RehearsalSlot":
        """The last lesson topic and any practice in progress; empty for an unknown teacher."""
        ...

    async def save_last_topic(self, topic_id: str) -> None:
        """Remember the topic of the latest plan, so a practice can follow it. No-op if unknown."""
        ...

    async def save_rehearsal(self, rehearsal_json: str | None) -> None:
        """Keep, or with None clear, the practice in progress. No-op if the teacher is unknown."""
        ...

    async def replace_rehearsal(self, expected: str | None, new: str | None) -> bool:
        """Swap the practice for `new` only if it is still `expected`; False if it moved on."""
        ...

    async def log_practice_turn(self, turn: LoggedTurn) -> None:
        """Add a scored question to the teacher's open practice, opening one if there is none.

        Kept only for a teacher who has consented. Never raises: a practice that cannot be logged
        still goes on, and the message that carries it must still commit.
        """
        ...

    async def close_practice(self) -> None:
        """End whatever practice the teacher has open; the next scored turn starts a fresh one."""
        ...

    async def export(self) -> "TeacherExport | None":
        """Everything stored about the teacher that they may ask to see; None if nothing is."""
        ...


class TeacherStore(Protocol):
    def locked(self, phone_hash: bytes) -> AbstractAsyncContextManager[TeacherSession]: ...


@dataclass(frozen=True)
class ConsentRecord:
    version: str
    text_sha256: str
    revoked: bool = False


@dataclass(frozen=True)
class TeacherExport:
    """What a teacher is shown when they ask for their data. Deliberately omits the phone number.

    Practice appears as counts and a topic id, never as the teacher's words or the saved progress:
    a summary sent over WhatsApp should say what is kept, not repeat it.
    """

    lang: str | None
    grade_band: str | None
    consents: tuple[ConsentRecord, ...]
    reminders_opt_in: bool
    reminder_time: time | None = None
    last_reminded_on: date | None = None
    practice_count: int = 0
    scored_question_count: int = 0
    plan_topic_id: str | None = None
    practice_in_progress: bool = False


@dataclass(frozen=True)
class RehearsalSlot:
    """What a practice needs between messages: the topic to practise and the saved progress."""

    topic_id: str | None = None
    rehearsal_json: str | None = None


@dataclass(frozen=True)
class PracticeSession:
    """One practice as the in-memory store keeps it: the scored questions, and whether it ended."""

    move_id: int
    topic_id: str
    turns: tuple[LoggedTurn, ...] = ()
    ended: bool = False


@dataclass(frozen=True)
class StoredTeacher:
    state: TeacherState
    wa_id: str
    last_active_at: datetime
    consents: tuple[ConsentRecord, ...] = ()
    reminders_opt_in: bool = False
    rehearsal: RehearsalSlot = RehearsalSlot()
    reminder_time: time | None = None
    last_reminded_on: date | None = None


@dataclass
class InMemoryTeacherStore:
    """Test double with the same observable behaviour as the Postgres store."""

    teachers: dict[bytes, StoredTeacher] = field(default_factory=dict)
    deletion_log: list[str] = field(default_factory=list)
    practices: dict[bytes, tuple[PracticeSession, ...]] = field(default_factory=dict)
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    _locks: dict[bytes, asyncio.Lock] = field(default_factory=dict)

    @asynccontextmanager
    async def locked(self, phone_hash: bytes) -> AsyncIterator["_InMemorySession"]:
        lock = self._locks.setdefault(phone_hash, asyncio.Lock())
        async with lock:
            yield _InMemorySession(self, phone_hash)

    def now(self) -> datetime:
        return self.clock()


@dataclass(frozen=True)
class _InMemorySession:
    store: InMemoryTeacherStore
    phone_hash: bytes

    async def load(self) -> TeacherState:
        stored = self.store.teachers.get(self.phone_hash)
        if stored is None:
            return TeacherState()
        return replace(stored.state, consented=any(not c.revoked for c in stored.consents))

    async def idle_for(self) -> timedelta | None:
        stored = self.store.teachers.get(self.phone_hash)
        return None if stored is None else self.store.now() - stored.last_active_at

    async def save(self, state: TeacherState, wa_id: str) -> None:
        now = self.store.now()
        existing = self.store.teachers.get(self.phone_hash)
        if existing is None:
            if state == TeacherState():
                return
            self.store.teachers[self.phone_hash] = StoredTeacher(
                state=state, wa_id=wa_id, last_active_at=now
            )
            return
        self.store.teachers[self.phone_hash] = replace(
            existing, state=state, wa_id=wa_id, last_active_at=now
        )

    async def record_consent(self, version: str, text_sha256: str) -> None:
        existing = self.store.teachers[self.phone_hash]
        record = ConsentRecord(version, text_sha256)
        self.store.teachers[self.phone_hash] = replace(
            existing, consents=(*existing.consents, record)
        )

    async def withdraw_consent(self) -> None:
        existing = self.store.teachers.get(self.phone_hash)
        if existing is None:
            return
        revoked = tuple(replace(c, revoked=True) for c in existing.consents)
        self.store.teachers[self.phone_hash] = replace(
            existing, consents=revoked, rehearsal=RehearsalSlot()
        )

    async def erase(self) -> None:
        self.store.practices.pop(self.phone_hash, None)
        if self.store.teachers.pop(self.phone_hash, None) is not None:
            self.store.deletion_log.append(deletion_log_prefix(self.phone_hash))

    async def opt_out_reminders(self) -> None:
        existing = self.store.teachers.get(self.phone_hash)
        if existing is not None:
            self.store.teachers[self.phone_hash] = replace(existing, reminders_opt_in=False)

    async def load_rehearsal(self) -> RehearsalSlot:
        stored = self.store.teachers.get(self.phone_hash)
        return RehearsalSlot() if stored is None else stored.rehearsal

    async def save_last_topic(self, topic_id: str) -> None:
        stored = self.store.teachers.get(self.phone_hash)
        if stored is not None:
            slot = replace(stored.rehearsal, topic_id=topic_id)
            self.store.teachers[self.phone_hash] = replace(stored, rehearsal=slot)

    async def save_rehearsal(self, rehearsal_json: str | None) -> None:
        stored = self.store.teachers.get(self.phone_hash)
        if stored is not None:
            slot = replace(stored.rehearsal, rehearsal_json=rehearsal_json)
            self.store.teachers[self.phone_hash] = replace(stored, rehearsal=slot)

    async def replace_rehearsal(self, expected: str | None, new: str | None) -> bool:
        stored = self.store.teachers.get(self.phone_hash)
        if stored is None or stored.rehearsal.rehearsal_json != expected:
            return False
        await self.save_rehearsal(new)
        return True

    async def log_practice_turn(self, turn: LoggedTurn) -> None:
        stored = self.store.teachers.get(self.phone_hash)
        if stored is None or all(c.revoked for c in stored.consents):
            return
        # A practice left open for another move or topic (its end was lost) is not this one.
        sessions = [
            replace(p, ended=True) if not p.ended and (p.move_id, p.topic_id) != _key(turn) else p
            for p in self.store.practices.get(self.phone_hash, ())
        ]
        open_at = next((i for i, p in enumerate(sessions) if not p.ended), None)
        if open_at is None:
            sessions.append(PracticeSession(*_key(turn), turns=(turn,)))
        else:
            sessions[open_at] = replace(sessions[open_at], turns=(*sessions[open_at].turns, turn))
        self.store.practices[self.phone_hash] = tuple(sessions)

    async def close_practice(self) -> None:
        sessions = self.store.practices.get(self.phone_hash)
        if sessions is not None:
            self.store.practices[self.phone_hash] = tuple(replace(p, ended=True) for p in sessions)

    async def export(self) -> TeacherExport | None:
        stored = self.store.teachers.get(self.phone_hash)
        if stored is None:
            return None
        practices = self.store.practices.get(self.phone_hash, ())
        return TeacherExport(
            lang=stored.state.lang,
            grade_band=stored.state.grade_band,
            consents=stored.consents,
            reminders_opt_in=stored.reminders_opt_in,
            reminder_time=stored.reminder_time,
            last_reminded_on=stored.last_reminded_on,
            practice_count=len(practices),
            scored_question_count=sum(len(p.turns) for p in practices),
            plan_topic_id=stored.rehearsal.topic_id,
            practice_in_progress=stored.rehearsal.rehearsal_json is not None,
        )


def _key(turn: LoggedTurn) -> tuple[int, str]:
    return turn.move_id, turn.topic_id
