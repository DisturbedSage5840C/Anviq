"""Daily spend summary for the team: LLM tokens and dollars, speech seconds and characters."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

IST = timezone(timedelta(hours=5, minutes=30))  # India has no daylight saving


@dataclass(frozen=True)
class CostReport:
    start: datetime
    end: datetime
    llm_calls: int
    llm_in_tok: int
    llm_out_tok: int
    llm_cost_usd: Decimal
    stt_seconds: Decimal
    stt_cost_inr: Decimal
    tts_chars: Decimal
    tts_cost_inr: Decimal


def previous_ist_day(now: datetime) -> tuple[datetime, datetime]:
    """The whole Indian calendar day before `now`, as a half-open [start, end) window."""
    today = now.astimezone(IST).date()
    end = datetime.combine(today, time.min, tzinfo=IST)
    return end - timedelta(days=1), end


async def build_cost_report(conn: AsyncConnection, *, start: datetime, end: datetime) -> CostReport:
    """Sum usage created in [start, end). Runs inside the caller's transaction."""
    window = {"start": start, "end": end}
    llm = (
        await conn.execute(
            text(
                "select count(*), coalesce(sum(in_tok), 0), coalesce(sum(out_tok), 0), "
                "coalesce(sum(est_cost_usd), 0) from llm_usage "
                "where created_at >= :start and created_at < :end"
            ),
            window,
        )
    ).one()
    speech = {
        kind: (seconds_or_chars, cost_inr)
        for kind, seconds_or_chars, cost_inr in await conn.execute(
            text(
                "select kind, sum(seconds_or_chars), sum(est_cost_inr) from speech_usage "
                "where created_at >= :start and created_at < :end group by kind"
            ),
            window,
        )
    }
    stt_seconds, stt_cost_inr = speech.get("stt", (Decimal(0), Decimal(0)))
    tts_chars, tts_cost_inr = speech.get("tts", (Decimal(0), Decimal(0)))
    return CostReport(
        start=start,
        end=end,
        llm_calls=llm[0],
        llm_in_tok=llm[1],
        llm_out_tok=llm[2],
        llm_cost_usd=llm[3],
        stt_seconds=stt_seconds,
        stt_cost_inr=stt_cost_inr,
        tts_chars=tts_chars,
        tts_cost_inr=tts_cost_inr,
    )


def render_cost_report(report: CostReport) -> str:
    """A short plain-text message, fit for a Slack channel or an email body."""
    day = report.start.astimezone(IST).date().isoformat()
    speech_inr = report.stt_cost_inr + report.tts_cost_inr
    return "\n".join(
        (
            f"Anviq spend for {day} (IST)",
            f"• LLM: {report.llm_calls} calls, {report.llm_in_tok} tokens in, "
            f"{report.llm_out_tok} out, ${report.llm_cost_usd:.2f}",
            f"• STT: {_plain(report.stt_seconds)} s",
            f"• TTS: {_plain(report.tts_chars)} chars",
            f"• Speech total: ₹{speech_inr:.2f}",
        )
    )


def _plain(value: Decimal) -> str:
    """95.50 -> '95.5', 2100.00 -> '2100': no trailing zeros and never scientific notation."""
    return f"{value.normalize():f}"
