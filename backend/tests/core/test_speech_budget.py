import pytest

from app.core.speech_budget import (
    PLAN_BUDGET_SECONDS,
    REFLECT_BUDGET_SECONDS,
    SPOKEN_CHARS_PER_SECOND,
    estimated_seconds,
    fits,
    truncate_to_budget,
)


def test_empty_text_takes_no_time():
    assert estimated_seconds("") == 0


def test_estimate_scales_with_length():
    text = "क" * (SPOKEN_CHARS_PER_SECOND * 10)
    assert estimated_seconds(text) == pytest.approx(10)


def test_whitespace_runs_count_once_because_tts_does_not_pause_on_them():
    assert estimated_seconds("a  \n\n  b") == estimated_seconds("a b")


def test_text_exactly_on_the_budget_fits():
    on_budget = "a" * (SPOKEN_CHARS_PER_SECOND * PLAN_BUDGET_SECONDS)
    assert fits(on_budget, PLAN_BUDGET_SECONDS)
    assert not fits(on_budget + "a", PLAN_BUDGET_SECONDS)


def test_reflect_budget_is_shorter_than_the_plan_budget():
    assert REFLECT_BUDGET_SECONDS < PLAN_BUDGET_SECONDS


def test_truncation_leaves_short_text_alone():
    assert truncate_to_budget("छोटा वाक्य।", PLAN_BUDGET_SECONDS) == "छोटा वाक्य।"


def test_truncation_cuts_at_the_last_whole_sentence_inside_the_budget():
    sentence = "यह एक वाक्य है। "
    long_text = sentence * 200
    cut = truncate_to_budget(long_text, REFLECT_BUDGET_SECONDS)
    assert fits(cut, REFLECT_BUDGET_SECONDS)
    assert cut.endswith("।")
    assert len(cut) > SPOKEN_CHARS_PER_SECOND * REFLECT_BUDGET_SECONDS - len(sentence) * 2


def test_truncation_of_one_endless_sentence_still_respects_the_budget():
    cut = truncate_to_budget("word " * 500, REFLECT_BUDGET_SECONDS)
    assert fits(cut, REFLECT_BUDGET_SECONDS)
    assert cut
