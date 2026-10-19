"""Postgres side of the Day-14 mirror: pick the two turns to compare, then unlock the next move.

A cycle is the teacher's sessions on `teachers.current_move` since `teachers.cycle_started_at`.
Only the teacher's own scored turns are candidates: the coach's words are never held up as theirs.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from itertools import groupby
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.mirror import MirrorTurn

LAST_MOVE = 6

_CYCLE_SESSIONS = (
    "from sessions s join teachers t on t.id = s.teacher_id "
    "where t.id = :teacher and s.move_id = t.current_move "
    "and s.started_at >= coalesce(t.cycle_started_at, date '-infinity')"
)


@dataclass(frozen=True)
class MirrorPair:
    move_id: int
    cycle_no: int
    first_id: str
    latest_id: str
    first: MirrorTurn
    latest: MirrorTurn


@dataclass(frozen=True)
class _Candidate:
    turn_id: str
    session_id: str
    turn: MirrorTurn
    created_at: datetime


def _criteria(raw: str | Mapping[str, Any]) -> dict[str, bool]:
    decoded = json.loads(raw) if isinstance(raw, str) else raw
    return {key: bool(value) for key, value in decoded.items()}


async def cycle_started_at(conn: AsyncConnection, teacher_id: str) -> datetime | None:
    """When the teacher first practised the current move this cycle; None if they have not."""
    row = await conn.execute(
        text(f"select min(s.started_at) {_CYCLE_SESSIONS}"), {"teacher": teacher_id}
    )
    started: datetime | None = row.scalar_one()
    return started


async def _position(conn: AsyncConnection, teacher_id: str) -> tuple[int, int]:
    row = await conn.execute(
        text("select current_move, cycle_no from teachers where id = :teacher"),
        {"teacher": teacher_id},
    )
    move_id, cycle_no = row.one()
    return int(move_id), int(cycle_no)


async def _candidates(conn: AsyncConnection, teacher_id: str) -> list[_Candidate]:
    rows = await conn.execute(
        text(
            "select u.id, s.id as session_id, u.text_scrubbed, u.criteria_json, u.created_at "
            "from turns u join sessions s on s.id = u.session_id "
            "join teachers t on t.id = s.teacher_id "
            "where t.id = :teacher and s.move_id = t.current_move "
            "and s.started_at >= coalesce(t.cycle_started_at, date '-infinity') "
            "and u.role = 'teacher' and u.criteria_json is not null "
            "order by s.started_at, s.id, u.created_at, u.id"
        ),
        {"teacher": teacher_id},
    )
    return [
        _Candidate(
            str(row.id),
            str(row.session_id),
            MirrorTurn(row.text_scrubbed, _criteria(row.criteria_json)),
            row.created_at,
        )
        for row in rows
    ]


def _best(session_turns: list[_Candidate]) -> _Candidate:
    """Highest score wins; on a tie the earlier turn, so the pick never depends on row order."""
    return max(session_turns, key=lambda c: (c.turn.met_count, -c.created_at.timestamp()))


async def mirror_pair(conn: AsyncConnection, teacher_id: str) -> MirrorPair | None:
    """Best turn of the first session against that of the latest; None before two sessions."""
    by_session = [
        list(turns)
        for _, turns in groupby(await _candidates(conn, teacher_id), lambda c: c.session_id)
    ]
    if len(by_session) < 2:
        return None
    first, latest = _best(by_session[0]), _best(by_session[-1])
    move_id, cycle_no = await _position(conn, teacher_id)
    return MirrorPair(move_id, cycle_no, first.turn_id, latest.turn_id, first.turn, latest.turn)


async def finish_mirror(conn: AsyncConnection, teacher_id: str, pair: MirrorPair) -> None:
    """Record the compared turns and unlock the next move. Safe to call twice: it advances once."""
    recorded = await conn.execute(
        text(
            "insert into move_progress (teacher_id, move_id, cycle_no, day1_turn_id, "
            "day14_turn_id, status) "
            "values (:teacher, :move, :cycle, :first, :latest, 'done') "
            "on conflict (teacher_id, move_id, cycle_no) do update set "
            "day1_turn_id = excluded.day1_turn_id, day14_turn_id = excluded.day14_turn_id, "
            "status = 'done' where move_progress.status <> 'done' "
            "returning move_id"
        ),
        {
            "teacher": teacher_id,
            "move": pair.move_id,
            "cycle": pair.cycle_no,
            "first": pair.first_id,
            "latest": pair.latest_id,
        },
    )
    if recorded.first() is None:
        return
    await conn.execute(
        text(
            "update teachers set "
            "cycle_no = case when current_move >= :last then cycle_no + 1 else cycle_no end, "
            "current_move = case when current_move >= :last then 1 else current_move + 1 end, "
            "cycle_started_at = current_date "
            "where id = :teacher and current_move = :move and cycle_no = :cycle"
        ),
        {"teacher": teacher_id, "last": LAST_MOVE, "move": pair.move_id, "cycle": pair.cycle_no},
    )
