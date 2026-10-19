"""Postgres implementation of the teacher store: one transaction per message."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.router import Phase, TeacherState
from app.core.teacher_store import (
    ConsentRecord,
    RehearsalSlot,
    TeacherExport,
    deletion_log_prefix,
)
from app.privacy.crypto import FieldCipher

DEFAULT_LANG = "hi"  # teachers.lang is NOT NULL; the real choice arrives one step after the stub
LANGUAGE_UNKNOWN_PHASES = frozenset({Phase.NEW, Phase.ONB_LANG})
WA_ID_CONTEXT = b"teachers.wa_id"
ADVISORY_KEY_BYTES = 8


def _advisory_key(phone_hash: bytes) -> int:
    return int.from_bytes(phone_hash[:ADVISORY_KEY_BYTES], "big", signed=True)


class PostgresTeacherStore:
    def __init__(self, engine: AsyncEngine, cipher: FieldCipher) -> None:
        self._engine = engine
        self._cipher = cipher

    @asynccontextmanager
    async def locked(self, phone_hash: bytes) -> AsyncIterator["_PostgresSession"]:
        """Serialise messages per teacher; commit on clean exit, roll back on any exception."""
        async with self._engine.begin() as conn:
            await conn.execute(
                text("select pg_advisory_xact_lock(:key)"), {"key": _advisory_key(phone_hash)}
            )
            yield _PostgresSession(conn, self._cipher, phone_hash)


@dataclass(frozen=True)
class _PostgresSession:
    conn: AsyncConnection
    cipher: FieldCipher
    phone_hash: bytes

    async def load(self) -> TeacherState:
        row = (
            await self.conn.execute(
                text(
                    "select state, lang, grade_band, consent_version, resume_state "
                    "from teachers where phone_hash = :h"
                ),
                {"h": self.phone_hash},
            )
        ).first()
        if row is None:
            return TeacherState()
        phase = Phase(row.state)
        return TeacherState(
            phase=phase,
            lang=None if phase in LANGUAGE_UNKNOWN_PHASES else row.lang,
            grade_band=row.grade_band,
            consented=row.consent_version is not None,
            resume=Phase(row.resume_state) if row.resume_state else None,
        )

    async def idle_for(self) -> timedelta | None:
        idle = (
            await self.conn.execute(
                text("select now() - last_active_at from teachers where phone_hash = :h"),
                {"h": self.phone_hash},
            )
        ).scalar_one_or_none()
        return idle

    async def save(self, state: TeacherState, wa_id: str) -> None:
        if state.phase is Phase.NEW:
            return  # nothing worth keeping before the teacher has said anything real
        await self.conn.execute(
            text(
                "insert into teachers (phone_hash, wa_id_enc, lang, grade_band, state, "
                "resume_state) values (:h, :wa, coalesce(:lang, :default_lang), :grade, "
                ":state, :resume) "
                "on conflict (phone_hash) do update set wa_id_enc = excluded.wa_id_enc, "
                "lang = coalesce(:lang, teachers.lang), grade_band = excluded.grade_band, "
                "state = excluded.state, resume_state = excluded.resume_state, "
                "last_active_at = now()"
            ),
            {
                "h": self.phone_hash,
                "wa": self.cipher.encrypt(wa_id, context=WA_ID_CONTEXT),
                "state": state.phase.value,
                "lang": state.lang,
                "default_lang": DEFAULT_LANG,
                "grade": state.grade_band,
                "resume": state.resume.value if state.resume else None,
            },
        )

    async def record_consent(self, version: str, text_sha256: str) -> None:
        teacher_id = (
            await self.conn.execute(
                text(
                    "update teachers set consent_version = :v, consent_at = now() "
                    "where phone_hash = :h returning id"
                ),
                {"v": version, "h": self.phone_hash},
            )
        ).scalar_one()
        await self.conn.execute(
            text(
                "insert into consents (teacher_id, version, text_sha256, channel) "
                "values (:id, :v, :sha, 'whatsapp')"
            ),
            {"id": teacher_id, "v": version, "sha": text_sha256},
        )

    async def withdraw_consent(self) -> None:
        await self.conn.execute(
            text(
                "update consents set revoked_at = now() where revoked_at is null "
                "and teacher_id = (select id from teachers where phone_hash = :h)"
            ),
            {"h": self.phone_hash},
        )
        await self.conn.execute(
            text(
                "update teachers set consent_version = null, consent_at = null, "
                "last_topic_id = null, rehearsal_json = null where phone_hash = :h"
            ),
            {"h": self.phone_hash},
        )

    async def erase(self) -> None:
        deleted = await self.conn.execute(
            text("delete from teachers where phone_hash = :h"), {"h": self.phone_hash}
        )
        if deleted.rowcount:
            await self.conn.execute(
                text(
                    "insert into deletion_log (phone_hash_prefix8, completed_at) values (:p, now())"
                ),
                {"p": deletion_log_prefix(self.phone_hash)},
            )

    async def opt_out_reminders(self) -> None:
        await self.conn.execute(
            text("update teachers set reminders_opt_in = false where phone_hash = :h"),
            {"h": self.phone_hash},
        )

    async def load_rehearsal(self) -> RehearsalSlot:
        row = (
            await self.conn.execute(
                text("select last_topic_id, rehearsal_json from teachers where phone_hash = :h"),
                {"h": self.phone_hash},
            )
        ).first()
        return RehearsalSlot() if row is None else RehearsalSlot(row[0], row[1])

    async def save_last_topic(self, topic_id: str) -> None:
        await self.conn.execute(
            text("update teachers set last_topic_id = :topic where phone_hash = :h"),
            {"topic": topic_id, "h": self.phone_hash},
        )

    async def save_rehearsal(self, rehearsal_json: str | None) -> None:
        await self.conn.execute(
            text("update teachers set rehearsal_json = :json where phone_hash = :h"),
            {"json": rehearsal_json, "h": self.phone_hash},
        )

    async def replace_rehearsal(self, expected: str | None, new: str | None) -> bool:
        result = await self.conn.execute(
            text(
                "update teachers set rehearsal_json = cast(:new as text) "
                "where phone_hash = :h "
                "and rehearsal_json is not distinct from cast(:expected as text)"
            ),
            {"new": new, "expected": expected, "h": self.phone_hash},
        )
        return result.rowcount > 0

    async def export(self) -> TeacherExport | None:
        row = (
            await self.conn.execute(
                text(
                    "select id, state, lang, grade_band, reminders_opt_in "
                    "from teachers where phone_hash = :h"
                ),
                {"h": self.phone_hash},
            )
        ).first()
        if row is None:
            return None
        consents = await self.conn.execute(
            text(
                "select version, text_sha256, revoked_at is not null from consents "
                "where teacher_id = :id order by granted_at, id"
            ),
            {"id": row.id},
        )
        return TeacherExport(
            lang=None if Phase(row.state) in LANGUAGE_UNKNOWN_PHASES else row.lang,
            grade_band=row.grade_band,
            consents=tuple(ConsentRecord(r[0], r[1], bool(r[2])) for r in consents),
            reminders_opt_in=row.reminders_opt_in,
        )
