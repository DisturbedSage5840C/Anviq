"""PostgresTrendsReader against the real public_trends view, as the dashboard_ro role."""

from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.dashboard.trends import K_ANONYMITY_THRESHOLD, PostgresTrendsReader, TrendRow
from tests.db.test_schema import _seed_teachers


class _EngineOnConnection:
    """Hands the test's rolled-back connection to the reader, already demoted to dashboard_ro."""

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    @asynccontextmanager
    async def connect(self):
        await self._conn.execute(text("set local role dashboard_ro"))
        yield self._conn


def _reader_on(conn: AsyncConnection) -> PostgresTrendsReader:
    return PostgresTrendsReader(_EngineOnConnection(conn))  # type: ignore[arg-type]


async def test_a_visible_cell_comes_back_as_a_typed_row(conn: AsyncConnection):
    await _seed_teachers(conn, K_ANONYMITY_THRESHOLD, cluster="K20")

    rows = await _reader_on(conn).trends(move_id=None)

    assert rows == [
        TrendRow(
            cluster_code="K20",
            move_id=1,
            iso_week="2026-W43",
            n_teachers=K_ANONYMITY_THRESHOLD,
            avg_improvement=1.0,
            avg_sessions=5.0,
        )
    ]


async def test_a_cell_below_the_threshold_never_reaches_the_reader(conn: AsyncConnection):
    await _seed_teachers(conn, K_ANONYMITY_THRESHOLD - 1, cluster="K19")

    assert await _reader_on(conn).trends(move_id=None) == []


async def test_the_move_filter_narrows_the_rows(conn: AsyncConnection):
    await _seed_teachers(conn, K_ANONYMITY_THRESHOLD, cluster="K20")

    assert await _reader_on(conn).trends(move_id=2) == []
    assert len(await _reader_on(conn).trends(move_id=1)) == 1
