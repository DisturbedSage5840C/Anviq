"""Cost report against a real Postgres: only usage inside the IST day window is summed."""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.ops.cost_report import build_cost_report, previous_ist_day

DAY_START, DAY_END = previous_ist_day(datetime(2026, 10, 18, 2, 30, tzinfo=UTC))


async def _clear_usage(conn: AsyncConnection) -> None:
    await conn.execute(text("delete from llm_usage"))
    await conn.execute(text("delete from speech_usage"))


async def _seed(conn: AsyncConnection, created_at: datetime) -> None:
    params = {"at": created_at}
    await conn.execute(
        text(
            "insert into llm_usage (purpose, model, in_tok, out_tok, latency_ms, est_cost_usd, "
            "created_at) values ('coach', 'm', 100, 50, 900, 0.010000, :at)"
        ),
        params,
    )
    await conn.execute(
        text(
            "insert into speech_usage (provider, kind, seconds_or_chars, est_cost_inr, created_at) "
            "values ('sarvam', 'stt', 10, 0.5, :at), ('sarvam', 'tts', 200, 0.2, :at)"
        ),
        params,
    )


async def test_report_sums_only_rows_inside_the_window(conn: AsyncConnection):
    await _clear_usage(conn)
    await _seed(conn, DAY_START)  # first instant of the day: counted
    await _seed(conn, DAY_END)  # first instant of the next day: not counted
    await _seed(conn, datetime(2026, 10, 16, 18, 29, tzinfo=UTC))  # day before: not counted

    report = await build_cost_report(conn, start=DAY_START, end=DAY_END)

    assert report.llm_calls == 1
    assert (report.llm_in_tok, report.llm_out_tok) == (100, 50)
    assert report.llm_cost_usd == Decimal("0.010000")
    assert report.stt_seconds == Decimal(10)
    assert report.tts_chars == Decimal(200)
    assert report.stt_cost_inr + report.tts_cost_inr == Decimal("0.7")


async def test_an_empty_day_reports_zeros(conn: AsyncConnection):
    await _clear_usage(conn)

    report = await build_cost_report(conn, start=DAY_START, end=DAY_END)

    assert report.llm_calls == 0
    assert report.llm_cost_usd == Decimal(0)
    assert report.stt_seconds == Decimal(0)
    assert report.tts_chars == Decimal(0)
