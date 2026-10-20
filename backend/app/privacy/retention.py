"""Storage limitation (DPDP): age out what the consent notice promised to age out.

Transcripts live 90 days. A session row only carries a derived summary, so it goes once its
last transcript has. Mirror clips carry their own expiry. Teachers, consents and rubric
results stay until the teacher asks for deletion. Webhook dedupe ids live in Redis with a TTL,
so they need no purge here. Demo codes go once expired. A practice with the AI children holds
the teacher's own words, so one left unfinished for a day is cleared (the topic stays) and its
logged session is closed where the teacher last spoke, so the next practice starts a fresh one.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

TRANSCRIPT_RETENTION_DAYS = 90
REHEARSAL_RETENTION = timedelta(days=1)


@dataclass(frozen=True)
class PurgeReport:
    turns: int
    sessions: int
    mirror_clips: int
    demo_codes: int = 0
    rehearsals: int = 0
    practices_closed: int = 0


async def purge_expired(conn: AsyncConnection, *, now: datetime) -> PurgeReport:
    """Delete everything past its retention. Runs inside the caller's transaction.

    A turn exactly at the cutoff is kept: only strictly older rows are purged.
    """
    cutoff = now - timedelta(days=TRANSCRIPT_RETENTION_DAYS)
    turns = await _delete(conn, "delete from turns where created_at < :cutoff", cutoff=cutoff)
    sessions = await _delete(
        conn,
        "delete from sessions s where s.started_at < :cutoff "
        "and not exists (select 1 from turns t where t.session_id = s.id)",
        cutoff=cutoff,
    )
    mirror_clips = await _delete(conn, "delete from mirror_clips where expires_at < :now", now=now)
    demo_codes = await _delete(conn, "delete from demo_codes where expires_at < :now", now=now)
    rehearsals = await _delete(
        conn,
        "update teachers set rehearsal_json = null "
        "where rehearsal_json is not null and last_active_at < :stale",
        stale=now - REHEARSAL_RETENTION,
    )
    practices_closed = await _delete(
        conn,
        "update sessions s set ended_at = t.last_active_at from teachers t "
        "where t.id = s.teacher_id and s.kind = 'rehearse' and s.ended_at is null "
        "and t.last_active_at < :stale",
        stale=now - REHEARSAL_RETENTION,
    )
    return PurgeReport(
        turns=turns,
        sessions=sessions,
        mirror_clips=mirror_clips,
        demo_codes=demo_codes,
        rehearsals=rehearsals,
        practices_closed=practices_closed,
    )


async def _delete(conn: AsyncConnection, statement: str, **params: datetime) -> int:
    """Run a purge statement and count the rows it removed or cleared."""
    result = await conn.execute(text(statement), params)
    return result.rowcount
