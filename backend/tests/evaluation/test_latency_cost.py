from decimal import Decimal

import pytest

from app.evaluation.latency_cost import CallRow, summarize

INR_PER_USD = Decimal(84)


def _call(model: str = "claude-haiku-5-5", in_tok: int = 0, out_tok: int = 0) -> CallRow:
    return CallRow("coach", model, in_tok, out_tok, 0, 0, 1000)


def test_model_spend_is_recomputed_from_tokens_at_the_current_price_table():
    rows = [_call("claude-haiku-5-5", 1_000_000, 0), _call("claude-sonnet-5-5", 0, 1_000_000)]

    report = summarize(rows, Decimal(0), 1, INR_PER_USD)

    assert report["llm_usd"] == pytest.approx(0.10 + 10.0)


def test_speech_rupees_are_converted_and_added_per_teacher_day():
    report = summarize([_call("claude-haiku-5-5", 1_000_000, 0)], Decimal(84), 2, INR_PER_USD)

    assert report["speech_usd"] == pytest.approx(1.0)
    assert report["usd_per_teacher_day"] == pytest.approx((0.10 + 1.0) / 2)


def test_no_teacher_days_means_no_per_day_figure_and_no_pass():
    report = summarize([_call()], Decimal(0), 0, INR_PER_USD)

    assert report["usd_per_teacher_day"] is None and report["cost_pass"] is False


def test_latency_percentiles_are_grouped_by_purpose():
    rows = [CallRow("child", "m", 0, 0, 0, 0, ms) for ms in (100, 200, 300)]

    report = summarize(rows, Decimal(0), 1, INR_PER_USD)

    assert report["model_latency_ms"] == {"child": {"calls": 3, "p50": 200.0, "p95": 300.0}}
