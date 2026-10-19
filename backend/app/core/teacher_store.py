"""Persistence port for the conversation router, plus an in-memory fake for tests.

One `locked()` block is one message: the store serialises concurrent messages from the same
teacher and commits or rolls back everything done inside the block together.
"""

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Protocol

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
    """What a teacher is shown when they ask for their data. Deliberately omits the phone number."""

    lang: str | None
    grade_band: str | None
    consents: tuple[ConsentRecord, ...]
    reminders_opt_in: bool


@dataclass(frozen=True)
class StoredTeacher:
    state: TeacherState
    wa_id: str
    last_active_at: datetime
    consents: tuple[ConsentRecord, ...] = ()
    reminders_opt_in: bool = False


@dataclass
class InMemoryTeacherStore:
    """Test double with the same observable behaviour as the Postgres store."""

    teachers: dict[bytes, StoredTeacher] = field(default_factory=dict)
    deletion_log: list[str] = field(default_factory=list)
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
        self.store.teachers[self.phone_hash] = replace(existing, consents=revoked)

    async def erase(self) -> None:
        if self.store.teachers.pop(self.phone_hash, None) is not None:
            self.store.deletion_log.append(deletion_log_prefix(self.phone_hash))

    async def opt_out_reminders(self) -> None:
        existing = self.store.teachers.get(self.phone_hash)
        if existing is not None:
            self.store.teachers[self.phone_hash] = replace(existing, reminders_opt_in=False)

    async def export(self) -> TeacherExport | None:
        stored = self.store.teachers.get(self.phone_hash)
        if stored is None:
            return None
        return TeacherExport(
            lang=stored.state.lang,
            grade_band=stored.state.grade_band,
            consents=stored.consents,
            reminders_opt_in=stored.reminders_opt_in,
        )
