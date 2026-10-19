import re
from datetime import UTC, datetime, timedelta

import pytest

from app.content.copy import render
from app.core.mirror import (
    CYCLE_LENGTH,
    Growth,
    MirrorTurn,
    compare,
    cycle_is_due,
    growth_for,
    render_mirror,
)
from app.core.speech_budget import MIRROR_BUDGET_SECONDS, fits


def _turn(text: str, *met: str, of: tuple[str, ...] = ("C1", "C2", "C3", "C4")) -> MirrorTurn:
    return MirrorTurn(text=text, criteria={c: c in met for c in of})


@pytest.mark.parametrize(
    ("met_count", "expected"),
    [(0, Growth.SPROUT), (1, Growth.SPROUT), (2, Growth.LEAF), (3, Growth.TREE), (4, Growth.TREE)],
)
def test_growth_follows_how_many_criteria_were_met(met_count: int, expected: Growth):
    assert growth_for(met_count) is expected


def test_a_turn_counts_the_criteria_it_met():
    assert _turn("x", "C1", "C3").met_count == 2


def test_the_diff_names_what_was_gained_kept_and_still_open():
    first = _turn("Galat hai", "C1")
    latest = _turn("Show me how", "C1", "C2", "C3")

    diff = compare(first, latest)

    assert diff.gained == ("C2", "C3")
    assert diff.kept == ("C1",)
    assert diff.open == ("C4",)
    assert (diff.first_growth, diff.latest_growth) == (Growth.SPROUT, Growth.TREE)


def test_a_criterion_only_in_the_later_turn_counts_as_open_or_gained_by_its_value():
    diff = compare(_turn("a", "C1", of=("C1",)), _turn("b", "C1", "C5", of=("C1", "C5")))

    assert diff.gained == ("C5",)


def test_the_mirror_shows_both_quotes_and_the_growth_arrow():
    text = render_mirror(
        compare(_turn("Galat hai", "C1"), _turn("Show me", "C1", "C2", "C3")), "en"
    )

    assert render("mirror_day1", "en") in text
    assert render("mirror_today", "en") in text
    assert "Galat hai" in text
    assert "Show me" in text
    assert "🌱 → 🌳" in text


def test_growth_is_celebrated_in_words_not_numbers():
    text = render_mirror(compare(_turn("a", "C1"), _turn("b", "C1", "C2", "C3")), "en")

    assert render("mirror_grew", "en") in text
    assert not re.search(r"\d", text)


def test_no_change_is_met_with_encouragement_not_criticism():
    text = render_mirror(compare(_turn("a", "C1", "C2"), _turn("b", "C1", "C2")), "en")

    assert render("mirror_steady", "en") in text


def test_a_lower_day_14_turn_is_framed_as_a_cycle_to_build_on():
    text = render_mirror(compare(_turn("a", "C1", "C2", "C3"), _turn("b", "C1")), "en")

    assert render("mirror_steady", "en") in text
    assert render("mirror_grew", "en") not in text


def test_a_long_quote_is_cut_so_the_mirror_fits_its_speaking_budget():
    long = "सोचिए " * 400
    text = render_mirror(compare(_turn(long, "C1"), _turn(long, "C1", "C2")), "hi")

    assert fits(text, MIRROR_BUDGET_SECONDS)


def test_the_mirror_is_in_the_requested_language():
    text = render_mirror(compare(_turn("a", "C1"), _turn("b", "C1", "C2")), "hi")

    assert render("mirror_today", "hi") in text


NOW = datetime(2026, 11, 15, 9, 0, tzinfo=UTC)


def test_a_cycle_is_due_after_fourteen_days():
    assert cycle_is_due(NOW - CYCLE_LENGTH, NOW, demo_minutes=None)
    assert not cycle_is_due(NOW - CYCLE_LENGTH + timedelta(seconds=1), NOW, demo_minutes=None)


def test_demo_mode_shrinks_the_cycle_to_the_given_minutes():
    assert cycle_is_due(NOW - timedelta(minutes=5), NOW, demo_minutes=5)
    assert not cycle_is_due(NOW - timedelta(minutes=4), NOW, demo_minutes=5)


@pytest.mark.parametrize("bad", [0, -3])
def test_demo_minutes_must_be_positive(bad: int):
    with pytest.raises(ValueError, match="demo"):
        cycle_is_due(NOW, NOW, demo_minutes=bad)
