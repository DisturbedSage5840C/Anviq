"""Daily cost report: the IST day window and the message the team reads."""

from datetime import UTC, datetime
from decimal import Decimal

from app.ops.cost_report import CostReport, previous_ist_day, render_cost_report

IST_DAY_START = datetime(2026, 10, 16, 18, 30, tzinfo=UTC)  # 00:00 IST on 17 Oct
IST_DAY_END = datetime(2026, 10, 17, 18, 30, tzinfo=UTC)  # 00:00 IST on 18 Oct


def test_previous_ist_day_is_the_whole_day_before_today_in_india():
    # 08:00 IST on 18 Oct is 02:30 UTC on 18 Oct.
    start, end = previous_ist_day(datetime(2026, 10, 18, 2, 30, tzinfo=UTC))

    assert (start, end) == (IST_DAY_START, IST_DAY_END)


def test_previous_ist_day_uses_the_indian_date_not_the_utc_date():
    # 23:00 UTC on 17 Oct is already 04:30 IST on 18 Oct: "yesterday" is still 17 Oct.
    start, end = previous_ist_day(datetime(2026, 10, 17, 23, 0, tzinfo=UTC))

    assert (start, end) == (IST_DAY_START, IST_DAY_END)


def test_render_lists_each_cost_with_its_unit():
    report = CostReport(
        start=IST_DAY_START,
        end=IST_DAY_END,
        llm_calls=12,
        llm_in_tok=3400,
        llm_out_tok=800,
        llm_cost_usd=Decimal("0.420000"),
        stt_seconds=Decimal("95.50"),
        stt_cost_inr=Decimal("1.2500"),
        tts_chars=Decimal("2100.00"),
        tts_cost_inr=Decimal("0.8000"),
    )

    message = render_cost_report(report)

    assert "2026-10-17" in message
    assert "12 calls" in message
    assert "$0.42" in message
    assert "95.5 s" in message
    assert "2100 chars" in message
    assert "₹2.05" in message  # STT and TTS together
