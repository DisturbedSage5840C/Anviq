"""spoken_turn: the voice note of a rehearsal turn is built from the outcome, not read off the text."""

import random

import pytest

from app.core.children.personas import PERSONAS
from app.core.coach import CoachVerdict
from app.core.rehearsal import TurnOutcome, start
from app.core.rehearsal_voice import spoken_turn

RIYA = PERSONAS[0]
STATE = start("NUM.G2.SUB.REGROUP", 2, "A", "en", random.Random(1))
CHILD_LINE = "I got 38. I worked it out by thinking."
EMOJI = ("🌱", "🌿", "🌳", "👍")


def verdict(met: int, feedback: str = "Try asking how.", better: str = "How did you get it?"):
    ids = ("C1", "C2", "C3", "C4")
    return CoachVerdict(2, {cid: i < met for i, cid in enumerate(ids)}, {}, better, feedback)


def outcome(**changes: object) -> TurnOutcome:
    base: dict[str, object] = {
        "state": STATE,
        "child": RIYA,
        "child_text": CHILD_LINE,
        "malrule_id": None,
        "verdict": verdict(1),
        "nudge": "🌱 Try asking how.\nYou could say: How did you get it?",
        "finished": False,
        "summary": None,
    }
    return TurnOutcome(**{**base, **changes})  # type: ignore[arg-type]


def test_the_child_speaks_first_without_a_name_label() -> None:
    spoken = spoken_turn(outcome(), "en")

    assert spoken.startswith(CHILD_LINE)
    assert f"{RIYA.name}:" not in spoken


def test_the_coach_part_follows_the_child_part() -> None:
    spoken = spoken_turn(outcome(), "en")

    assert spoken.index(CHILD_LINE) < spoken.index("Try asking how.")


def test_the_growth_level_is_said_in_a_word_not_an_emoji() -> None:
    spoken = spoken_turn(outcome(verdict=verdict(1)), "en")

    assert "sprout" in spoken.lower()
    assert not any(symbol in spoken for symbol in EMOJI)


@pytest.mark.parametrize(("met", "word"), [(1, "sprout"), (2, "leaf"), (3, "tree")])
def test_each_growth_level_has_its_own_word(met: int, word: str) -> None:
    spoken = spoken_turn(outcome(verdict=verdict(met)), "en")

    assert word in spoken.lower()


def test_the_better_phrasing_is_offered_in_words() -> None:
    spoken = spoken_turn(outcome(), "en")

    assert "You could say" in spoken
    assert "How did you get it?" in spoken


def test_a_good_question_is_praised_in_words_not_a_thumbs_up() -> None:
    spoken = spoken_turn(outcome(verdict=verdict(4), nudge="👍"), "en")

    assert not any(symbol in spoken for symbol in EMOJI)
    assert "good question" in spoken.lower()


def test_a_week_b_rating_prompt_follows_the_child_without_symbols() -> None:
    spoken = spoken_turn(outcome(ask_rating=True, nudge=None, verdict=None), "en")

    assert spoken.startswith(CHILD_LINE)
    assert not any(symbol in spoken for symbol in EMOJI)
    assert len(spoken) > len(CHILD_LINE)


def test_the_summary_is_spoken_last() -> None:
    spoken = spoken_turn(outcome(summary="Your best question today\nHow did you think?"), "en")

    assert spoken.index("Try asking how.") < spoken.index("Your best question today")


def test_hindi_uses_hindi_words_for_the_coach_part() -> None:
    spoken = spoken_turn(outcome(verdict=verdict(2)), "hi")

    assert "पत्ती" in spoken
    assert not any(symbol in spoken for symbol in EMOJI)


def test_without_a_child_the_summary_alone_is_spoken() -> None:
    spoken = spoken_turn(
        outcome(child=None, child_text="", verdict=None, nudge=None, summary="All done."), "en"
    )

    assert spoken == "All done."
