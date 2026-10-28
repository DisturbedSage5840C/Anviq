from decimal import Decimal

import pytest

from app.evaluation.assumed_day import (
    ASSUMED_DAY,
    COST_TARGET_USD,
    MEASURED_PROFILES,
    AssumedDay,
    price_day,
)

INR_PER_USD = Decimal(84)


def test_every_call_in_the_assumed_day_has_a_measured_profile():
    assert set(ASSUMED_DAY.calls) <= set(MEASURED_PROFILES)


def test_an_empty_day_costs_nothing():
    result = price_day(AssumedDay(calls={}, stt_seconds=0, tts_characters=0), INR_PER_USD)

    assert result["usd_per_teacher_day"] == 0.0


def test_model_spend_is_the_call_count_times_the_priced_profile():
    day = AssumedDay(calls={"coach": 5}, stt_seconds=0, tts_characters=0)

    result = price_day(day, INR_PER_USD)

    # 5 coach turns at claude-sonnet-5-5: (300*2 + 1020*2*0.05 + 510*2*1.25 + 510*10) / 1e6 each
    assert result["llm_usd"] == pytest.approx(5 * 0.007077, abs=1e-6)
    assert result["speech_usd"] == 0.0


def test_speech_is_priced_at_the_google_rates_in_rupees_then_converted():
    day = AssumedDay(calls={}, stt_seconds=100, tts_characters=1000)

    result = price_day(day, INR_PER_USD)

    # 100 s * Rs 0.0224 + 1000 chars * Rs 0.001344 = Rs 3.584
    assert result["speech_usd"] == pytest.approx(3.584 / 84, abs=1e-6)


def test_the_verdict_follows_the_target():
    cheap = price_day(AssumedDay(calls={"child": 5}, stt_seconds=0, tts_characters=0), INR_PER_USD)
    dear = price_day(ASSUMED_DAY, INR_PER_USD)

    assert cheap["cost_pass"] is True
    assert dear["usd_per_teacher_day"] > COST_TARGET_USD
    assert dear["cost_pass"] is False


def test_pricing_the_coach_on_another_model_changes_only_the_coach_lines():
    base = price_day(ASSUMED_DAY, INR_PER_USD)

    cheaper = price_day(ASSUMED_DAY, INR_PER_USD, model_overrides={"coach": "claude-haiku-5-5"})

    assert cheaper["llm_usd"] < base["llm_usd"]
    assert cheaper["speech_usd"] == base["speech_usd"]
    assert base["by_purpose_usd"]["child"] == cheaper["by_purpose_usd"]["child"]


def test_an_unknown_call_name_is_rejected_not_priced_at_zero():
    with pytest.raises(KeyError):
        price_day(AssumedDay(calls={"nope": 1}, stt_seconds=0, tts_characters=0), INR_PER_USD)
