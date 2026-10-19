"""Read side of the mentor dashboard: the k-anonymous `public_trends` view and nothing else."""

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

# Frozen into the public_trends view by migration 0002. The view is what enforces it; this
# copy only lets the page say "fewer than 20 teachers" next to a cell that is missing.
K_ANONYMITY_THRESHOLD = 20
MAX_ROWS = 500

_TRENDS_SQL = text(
    """
    select cluster_code, move_id, iso_week, n_teachers, avg_improvement, avg_sessions
    from public_trends
    where cast(:move_id as smallint) is null or move_id = cast(:move_id as smallint)
    order by iso_week desc, cluster_code, move_id
    limit :limit
    """
)


@dataclass(frozen=True)
class TrendRow:
    cluster_code: str
    move_id: int
    iso_week: str
    n_teachers: int
    avg_improvement: float
    avg_sessions: float


class TrendsReader(Protocol):
    async def trends(self, *, move_id: int | None) -> list[TrendRow]: ...


class PostgresTrendsReader:
    """Needs an engine that logs in as `dashboard_ro`, which can select this one view only."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def trends(self, *, move_id: int | None) -> list[TrendRow]:
        async with self._engine.connect() as conn:
            result = await conn.execute(_TRENDS_SQL, {"move_id": move_id, "limit": MAX_ROWS})
            return [
                TrendRow(
                    cluster_code=row.cluster_code,
                    move_id=row.move_id,
                    iso_week=row.iso_week,
                    n_teachers=row.n_teachers,
                    avg_improvement=float(row.avg_improvement),
                    avg_sessions=float(row.avg_sessions),
                )
                for row in result
            ]
