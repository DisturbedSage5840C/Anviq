import random
from dataclasses import replace

import pytest

from app.core.children.personas import ChildState
from app.core.children.verbalizer import ChildBrief
from app.core.coach import CoachRequest, CoachUnavailableError, CoachVerdict
from app.core.rehearsal import (
    MAX_TURNS,
    RehearsalEngine,
    RehearsalState,
    start,
    summarise,
    wants_to_stop,
)

TOPIC = "NUM.G2.SUB.REGROUP"


class EchoVoice:
    """A child that follows the rules: says the answer, plus its steps when it explains."""

    def __init__(self) -> None:
        self.briefs: list[ChildBrief] = []

    async def speak(self, brief: ChildBrief) -> str:
        self.briefs.append(brief)
        steps = " ".join(brief.steps) if brief.explains else ""
        return f"जवाब {brief.answer} है। {steps}".strip()


class Coach:
    def __init__(self, *verdicts: CoachVerdict | Exception) -> None:
        self.verdicts = list(verdicts)
        self.requests: list[CoachRequest] = []

    async def score(self, request: CoachRequest) -> CoachVerdict:
        self.requests.append(request)
        item = self.verdicts.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def verdict(met: int, phrasing: str = "Try asking how.") -> CoachVerdict:
    ids = ("C1", "C2", "C3", "C4")
    return CoachVerdict(2, {cid: i < met for i, cid in enumerate(ids)}, {}, phrasing, "Good try.")


@pytest.fixture
def state() -> RehearsalState:
    return start(TOPIC, 2, "A", "en", random.Random(1))


def engine(*verdicts: CoachVerdict | Exception) -> tuple[RehearsalEngine, EchoVoice, Coach]:
    voice, coach = EchoVoice(), Coach(*verdicts)
    return RehearsalEngine(voice, coach), voice, coach


def test_start_picks_a_problem_the_main_misconception_fires_on(state: RehearsalState):
    assert state.problem.correct_answer()
    assert all(s is ChildState.CONFUSED for s in state.states.values())


def test_start_for_unknown_topic_is_an_error():
    with pytest.raises(ValueError):
        start("NUM.NOPE", 1, "A", "en", random.Random(0))


async def test_named_child_answers_with_the_computed_wrong_answer(state: RehearsalState):
    eng, voice, _ = engine(verdict(0))
    out = await eng.take_turn(state, "Riya, subtract please.")
    assert out.child is not None and out.child.key == "riya"
    assert out.malrule_id == state.primary_id
    wrong = voice.briefs[0].answer
    assert wrong != state.problem.correct_answer()
    assert wrong in out.child_text


async def test_unnamed_turns_rotate_riya_aman_meena(state: RehearsalState):
    eng, _, _ = engine(verdict(0), verdict(0), verdict(0))
    seen = []
    for _ in range(3):
        out = await eng.take_turn(state, "Who can tell me?")
        seen.append(out.child.key)  # type: ignore[union-attr]
        state = out.state
    assert seen == ["riya", "aman", "meena"]


async def test_a_good_turn_moves_the_child_a_step_and_changes_how_she_answers(state):
    eng, voice, _ = engine(verdict(4), verdict(4))
    first = await eng.take_turn(state, "Riya, how did you get it? Show me.")
    assert first.state.states["riya"] is ChildState.EXPLAINING
    assert first.child_text.count("ones:") == 1  # now she shows her (wrong) steps
    second = await eng.take_turn(first.state, "Riya, say more.")
    assert second.state.states["riya"] is ChildState.SELF_CORRECTING
    assert state.problem.correct_answer() in second.child_text
    assert second.malrule_id is None  # she no longer runs the misconception


async def test_a_weak_turn_leaves_the_child_where_she_was(state: RehearsalState):
    eng, _, _ = engine(verdict(0))
    out = await eng.take_turn(state, "Riya, is it right?")
    assert out.state.states["riya"] is ChildState.CONFUSED
    assert out.nudge and out.nudge.startswith("🌱")


async def test_a_good_turn_gets_a_thumbs_up_only(state: RehearsalState):
    eng, _, _ = engine(verdict(4))
    out = await eng.take_turn(state, "Riya, how did you get it?")
    assert out.nudge == "👍"


async def test_aman_knows_the_answer_but_cannot_explain_until_drawn_out(state):
    eng, voice, _ = engine(verdict(0), verdict(4))
    first = await eng.take_turn(state, "Aman, what did you get?")
    assert voice.briefs[0].answer == state.problem.correct_answer()
    assert voice.briefs[0].explains is False
    second = await eng.take_turn(first.state, "Aman, tell me how.")
    assert second.state.states["aman"] is ChildState.EXPLAINING
    assert second.malrule_id is None


async def test_meena_hesitates_the_first_time_and_answers_the_second(state):
    eng, voice, _ = engine(verdict(0), verdict(0))
    first = await eng.take_turn(state, "Meena, can you try?")
    assert "Umm" in first.child_text and not voice.briefs
    second = await eng.take_turn(first.state, "Take your time, Meena.")
    assert voice.briefs and second.child_text.startswith("जवाब")


async def test_coach_sees_the_childs_previous_words_not_the_new_reply(state):
    eng, _, coach = engine(verdict(0), verdict(0))
    first = await eng.take_turn(state, "Riya, go.")
    await eng.take_turn(first.state, "Aman, go.")
    assert coach.requests[0].child_text == ""
    assert coach.requests[1].child_text == first.child_text


async def test_if_the_coach_is_down_the_children_carry_on(state: RehearsalState):
    eng, _, _ = engine(CoachUnavailableError("down"))
    out = await eng.take_turn(state, "Riya, how?")
    assert out.verdict is None and out.nudge is None
    assert out.child_text and not out.finished
    assert out.state.exchanges == ()


async def test_three_good_turns_finish_with_the_best_question_and_a_phrase(state):
    eng, _, _ = engine(verdict(2, "Say this."), verdict(4), verdict(3))
    out = None
    for text in ("Riya, a?", "Aman, b best?", "Meena, c?"):
        out = await eng.take_turn(state, text)
        state = out.state
    assert out is not None and out.finished
    assert "Aman, b best?" in (out.summary or "")
    assert "Say this." in (out.summary or "")


async def test_six_turns_finish_even_without_good_ones(state: RehearsalState):
    eng, _, _ = engine(*[verdict(0)] * MAX_TURNS)
    out = None
    for _ in range(MAX_TURNS):
        assert out is None or not out.finished
        out = await eng.take_turn(state, "Riya, ok?")
        state = out.state
    assert out is not None and out.finished


async def test_saying_enough_ends_it_without_calling_anyone(state: RehearsalState):
    eng, voice, coach = engine()
    out = await eng.take_turn(state, "बस")
    assert out.finished and out.child is None and not voice.briefs and not coach.requests
    assert out.summary


@pytest.mark.parametrize(
    ("text", "stop"),
    [
        ("बस", True),
        ("enough", True),
        ("bas karo", True),
        ("Riya, bas itna batao kaise", False),
        ("", False),
    ],
)
def test_stop_words_only_count_in_a_short_message(text: str, stop: bool):
    assert wants_to_stop(text) is stop


def test_summary_with_nothing_scored_says_so(state: RehearsalState):
    assert "tomorrow" in summarise(state)


async def test_state_is_immutable_between_turns(state: RehearsalState):
    eng, _, _ = engine(verdict(4))
    before = dict(state.states)
    await eng.take_turn(state, "Riya, how?")
    assert dict(state.states) == before
    assert replace(state, turns=3).turns == 3
