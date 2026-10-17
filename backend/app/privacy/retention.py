"""Storage limitation (DPDP): age out what the consent notice promised to age out.

Transcripts live 90 days. A session row only carries a derived summary, so it goes once its
last transcript has. Mirror clips carry their own expiry. Teachers, consents and rubric
results stay until the teacher asks for deletion. Webhook dedupe ids live in Redis with a TTL,
so they need no purge here.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

TRANSCRIPT_RETENTION_DAYS = 90


@dataclass(frozen=True)
class PurgeReport:
    turns: int
    sessions: int
    mirror_clips: int


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
    return PurgeReport(turns=turns, sessions=sessions, mirror_clips=mirror_clips)


async def _delete(conn: AsyncConnection, statement: str, **params: datetime) -> int:
    result = await conn.execute(text(statement), params)
    return result.rowcount
