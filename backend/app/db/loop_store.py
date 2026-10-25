"""Postgres adapters for the AI side: model spend, the teacher's place in the programme, mirrors.

Each call opens its own short transaction. They run after the router's per-teacher transaction has
committed (see `core/router_brain.py`), so no model call ever holds the teacher's lock.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.daily_loop import Position
from app.core.mirror import CYCLE_LENGTH, MirrorTurn, cycle_is_due
from app.db.mirror_store import cycle_started_at, finish_mirror, mirror_pair
from app.llm.client import Usage
from app.speech.metering import SpeechUsage

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


async def teacher_id_for(conn: AsyncConnection, phone_hash: bytes) -> str | None:
    row = await conn.execute(
        text("select id from teachers where phone_hash = :h"), {"h": phone_hash}
    )
    found = row.scalar_one_or_none()
    return None if found is None else str(found)


def week_for(started_at: datetime | None, now: datetime, *, demo_minutes: int | None) -> str:
    """Week A (modelled) for the first half of the cycle, then week B (faded)."""
    if started_at is None:
        return "A"
    cycle = CYCLE_LENGTH if demo_minutes is None else timedelta(minutes=demo_minutes)
    return "A" if now - started_at < cycle / 2 else "B"


class PostgresUsageSink:
    """Counts and cost only: there is no column a prompt or a reply could be written to."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def record(self, usage: Usage) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "insert into llm_usage (purpose, model, in_tok, out_tok, cache_read, "
                    "cache_write, latency_ms, est_cost_usd) values (:purpose, :model, :in_tok, "
                    ":out_tok, :cache_read, :cache_write, :latency_ms, :cost)"
                ),
                {
                    "purpose": usage.purpose,
                    "model": usage.model,
                    "in_tok": usage.in_tok,
                    "out_tok": usage.out_tok,
                    "cache_read": usage.cache_read,
                    "cache_write": usage.cache_write,
                    "latency_ms": usage.latency_ms,
                    "cost": usage.est_cost_usd,
                },
            )


class PostgresSpeechUsageSink:
    """Seconds or characters billed, and the estimated rupees: never the audio or the text."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def record(self, usage: SpeechUsage) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "insert into speech_usage (provider, kind, seconds_or_chars, est_cost_inr) "
                    "values (:provider, :kind, :amount, :cost)"
                ),
                {
                    "provider": usage.provider,
                    "kind": usage.kind,
                    "amount": usage.amount,
                    "cost": usage.est_cost_inr,
                },
            )


async def position_for(
    conn: AsyncConnection, phone_hash: bytes, now: datetime, *, demo_minutes: int | None
) -> Position:
    teacher_id = await teacher_id_for(conn, phone_hash)
    if teacher_id is None:
        return Position(1, "A")
    move = await conn.execute(
        text("select current_move from teachers where id = :t"), {"t": teacher_id}
    )
    started = await cycle_started_at(conn, teacher_id)
    return Position(int(move.scalar_one()), week_for(started, now, demo_minutes=demo_minutes))


async def due_pair(
    conn: AsyncConnection, phone_hash: bytes, now: datetime, *, demo_minutes: int | None
) -> tuple[MirrorTurn, MirrorTurn] | None:
    """The Day 1 and latest turns, once the cycle has run its length; else None."""
    teacher_id = await teacher_id_for(conn, phone_hash)
    if teacher_id is None:
        return None
    started = await cycle_started_at(conn, teacher_id)
    if started is None or not cycle_is_due(started, now, demo_minutes=demo_minutes):
        return None
    pair = await mirror_pair(conn, teacher_id)
    return None if pair is None else (pair.first, pair.latest)


async def complete_mirror(conn: AsyncConnection, phone_hash: bytes) -> None:
    teacher_id = await teacher_id_for(conn, phone_hash)
    if teacher_id is None:
        return
    pair = await mirror_pair(conn, teacher_id)
    if pair is not None:
        await finish_mirror(conn, teacher_id, pair)


class PostgresPositions:
    def __init__(
        self, engine: AsyncEngine, *, demo_minutes: int | None, clock: Clock = _utc_now
    ) -> None:
        self._engine = engine
        self._demo_minutes = demo_minutes
        self._clock = clock

    async def current(self, teacher: bytes) -> Position:
        async with self._engine.connect() as conn:
            return await position_for(conn, teacher, self._clock(), demo_minutes=self._demo_minutes)


class PostgresMirrors:
    def __init__(
        self, engine: AsyncEngine, *, demo_minutes: int | None, clock: Clock = _utc_now
    ) -> None:
        self._engine = engine
        self._demo_minutes = demo_minutes
        self._clock = clock

    async def comparable(self, teacher: bytes) -> tuple[MirrorTurn, MirrorTurn] | None:
        async with self._engine.connect() as conn:
            return await due_pair(conn, teacher, self._clock(), demo_minutes=self._demo_minutes)

    async def complete(self, teacher: bytes) -> None:
        async with self._engine.begin() as conn:
            await complete_mirror(conn, teacher)
