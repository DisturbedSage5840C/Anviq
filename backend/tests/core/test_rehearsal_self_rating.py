"""Week B ("faded"): the coach asks the teacher to rate the question before it says what it saw."""

import random
from dataclasses import replace

import pytest

from app.content.copy import render
from app.core.children.verbalizer import ChildBrief
from app.core.coach import CoachRequest, CoachUnavailableError, CoachVerdict
from app.core.rehearsal import (
    GOOD_TURNS_TO_FINISH,
    RehearsalEngine,
    RehearsalState,
    start,
    wants_to_stop,
)

TOPIC = "NUM.G2.SUB.REGROUP"


class EchoVoice:
    async def speak(self, brief: ChildBrief) -> str:
        return f"जवाब {brief.answer} है।"


class Coach:
    def __init__(self, *verdicts: CoachVerdict | Exception) -> None:
        self.verdicts = list(verdicts)

    async def score(self, request: CoachRequest) -> CoachVerdict:
        item = self.verdicts.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def verdict(met: int) -> CoachVerdict:
    ids = ("C1", "C2", "C3", "C4")
    return CoachVerdict(
        2, {cid: i < met for i, cid in enumerate(ids)}, {}, "Try asking how.", "Good try."
    )


def engine(*verdicts: CoachVerdict | Exception) -> RehearsalEngine:
    return RehearsalEngine(EchoVoice(), Coach(*verdicts))


def fresh(week: str) -> RehearsalState:
    return start(TOPIC, 2, week, "en", random.Random(1))


async def asked_to_rate(met: int = 1) -> RehearsalState:
    outcome = await engine(verdict(met)).take_turn(fresh("B"), "Who can tell me?")
    return outcome.state


async def test_in_week_b_the_nudge_waits_for_the_teachers_own_rating() -> None:
    outcome = await engine(verdict(1)).take_turn(fresh("B"), "Who can tell me?")

    assert outcome.child is not None and outcome.child_text
    assert outcome.nudge is None
    assert outcome.ask_rating is True
    assert outcome.state.awaiting_rating is True
    assert outcome.finished is False


async def test_in_week_a_the_nudge_comes_straight_away() -> None:
    outcome = await engine(verdict(1)).take_turn(fresh("A"), "Who can tell me?")

    assert outcome.nudge is not None
    assert outcome.ask_rating is False
    assert outcome.state.awaiting_rating is False


@pytest.mark.parametrize("rating", ["1", "🌿", "३"])
async def test_a_rating_reveals_the_nudge_without_another_child_turn(rating: str) -> None:
    waiting = await asked_to_rate(met=1)

    outcome = await engine().take_turn(waiting, rating)  # no verdict queued: nothing is scored

    assert outcome.child is None and outcome.child_text == ""
    assert outcome.nudge is not None and "Good try." in outcome.nudge
    assert outcome.state.awaiting_rating is False
    assert outcome.state.turns == waiting.turns
    assert outcome.state.exchanges == waiting.exchanges
    assert outcome.finished is False


async def test_a_higher_rating_than_the_coachs_is_shown_beside_it() -> None:
    waiting = await asked_to_rate(met=1)  # 🌱

    outcome = await engine().take_turn(waiting, "3")

    assert outcome.nudge is not None
    assert render("self_rating_higher", "en").format(mine="🌳", coach="🌱") in outcome.nudge


async def test_a_lower_rating_than_the_coachs_is_shown_beside_it() -> None:
    waiting = await asked_to_rate(met=3)  # 🌳

    outcome = await engine().take_turn(waiting, "1")

    assert outcome.nudge is not None
    assert render("self_rating_lower", "en").format(mine="🌱", coach="🌳") in outcome.nudge


async def test_a_matching_rating_is_said_plainly() -> None:
    waiting = await asked_to_rate(met=2)  # 🌿

    outcome = await engine().take_turn(waiting, "2")

    assert outcome.nudge is not None
    assert render("self_rating_same", "en").format(mine="🌿", coach="🌿") in outcome.nudge


async def test_saying_something_else_skips_the_rating_and_carries_on() -> None:
    waiting = await asked_to_rate(met=1)

    outcome = await engine(verdict(1)).take_turn(waiting, "Riya, how did you get that?")

    assert outcome.child is not None
    assert outcome.state.turns == waiting.turns + 1
    assert outcome.ask_rating is True  # the new question is the one to rate now


async def test_a_digit_is_just_a_digit_when_no_rating_was_asked_for() -> None:
    outcome = await engine(verdict(0)).take_turn(fresh("B"), "2")

    assert outcome.child is not None
    assert outcome.state.turns == 1


async def test_the_closing_turn_gives_the_nudge_and_summary_with_nothing_to_rate() -> None:
    almost = replace(fresh("B"), good_turns=GOOD_TURNS_TO_FINISH - 1)

    outcome = await engine(verdict(4)).take_turn(almost, "How did you get that?")

    assert outcome.finished is True
    assert outcome.ask_rating is False
    assert outcome.nudge is not None
    assert outcome.summary
    assert outcome.state.awaiting_rating is False


async def test_if_the_coach_is_down_there_is_nothing_to_rate() -> None:
    outcome = await engine(CoachUnavailableError("x")).take_turn(fresh("B"), "Who?")

    assert outcome.verdict is None
    assert outcome.ask_rating is False
    assert outcome.state.awaiting_rating is False


async def test_saying_enough_while_waiting_ends_the_practice() -> None:
    waiting = await asked_to_rate()

    outcome = await engine().take_turn(waiting, "enough")

    assert outcome.finished is True
    assert outcome.summary


async def test_state_is_not_changed_by_a_rating() -> None:
    waiting = await asked_to_rate()

    await engine().take_turn(waiting, "2")

    assert waiting.awaiting_rating is True


@pytest.mark.parametrize("text", ["stop", "Stop!", "stop asking"])
def test_a_short_message_with_stop_in_it_ends_the_practice(text: str) -> None:
    assert wants_to_stop(text) is True
