import random

import pytest

from app.content.copy import render
from app.core.children.personas import PERSONAS
from app.core.children.verbalizer import ChildBrief
from app.core.coach import CoachRequest, CoachUnavailableError, CoachVerdict
from app.core.daily_loop import Position
from app.core.rehearsal import RehearsalEngine
from app.core.rehearsal_codec import load
from app.core.rehearsal_flow import RehearsalFlow

TEACHER = b"t" * 32
TOPIC = "NUM.G2.SUB.REGROUP"
RIYA = PERSONAS[0]


class EchoVoice:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure

    async def speak(self, brief: ChildBrief) -> str:
        if self.failure is not None:
            raise self.failure
        return f"जवाब {brief.answer} है।"


class Coach:
    def __init__(self, *verdicts: CoachVerdict | Exception) -> None:
        self.verdicts = list(verdicts)

    async def score(self, request: CoachRequest) -> CoachVerdict:
        item = self.verdicts.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakePositions:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure

    async def current(self, teacher: bytes) -> Position:
        if self.failure is not None:
            raise self.failure
        return Position(move_id=2, week="A")


def verdict(met: int) -> CoachVerdict:
    ids = ("C1", "C2", "C3", "C4")
    return CoachVerdict(
        2, {cid: i < met for i, cid in enumerate(ids)}, {}, "Try asking how.", "Ok."
    )


def flow(
    *verdicts: CoachVerdict | Exception,
    voice: EchoVoice | None = None,
    positions: FakePositions | None = None,
) -> RehearsalFlow:
    engine = RehearsalEngine(voice or EchoVoice(), Coach(*verdicts))
    return RehearsalFlow(engine, positions or FakePositions(), lambda: random.Random(1))


async def test_a_practice_starts_with_the_children_ready_and_a_problem_on_the_board():
    reply = await flow().begin(TEACHER, "en", TOPIC)

    saved = load(reply.rehearsal_json or "")
    assert saved is not None and saved.topic_id == TOPIC
    assert (saved.move_id, saved.week, saved.turns) == (2, "A", 0)
    assert render("rehearsal_started", "en") in reply.text
    assert saved.problem.statement() in reply.text
    assert reply.finished is False


async def test_without_a_recent_plan_the_teacher_is_told_to_make_one_first():
    reply = await flow().begin(TEACHER, "en", None)

    assert reply.text == render("rehearsal_needs_plan", "en")
    assert reply.rehearsal_json is None
    assert reply.finished is True


async def test_a_topic_with_no_known_misconceptions_cannot_be_practised():
    reply = await flow().begin(TEACHER, "en", "NUM.NOPE")

    assert reply.text == render("rehearsal_unavailable", "en")
    assert reply.finished is True


async def test_if_the_teachers_position_cannot_be_found_the_practice_does_not_start():
    reply = await flow(positions=FakePositions(RuntimeError("db down"))).begin(TEACHER, "hi", TOPIC)

    assert reply.text == render("rehearsal_unavailable", "hi")
    assert reply.rehearsal_json is None
    assert reply.finished is True


async def test_a_turn_gets_the_childs_answer_under_her_name_and_saves_progress():
    started = await flow().begin(TEACHER, "en", TOPIC)

    reply = await flow(verdict(0)).turn(TEACHER, "en", "Who can tell me?", started.rehearsal_json)

    saved = load(reply.rehearsal_json or "")
    assert reply.text.startswith(f"{RIYA.name}: ")
    assert saved is not None and saved.turns == 1
    assert reply.finished is False


async def test_the_children_are_named_in_hindi_for_a_hindi_teacher():
    started = await flow().begin(TEACHER, "hi", TOPIC)

    reply = await flow(verdict(0)).turn(TEACHER, "hi", "कौन बताएगा?", started.rehearsal_json)

    assert reply.text.startswith(f"{RIYA.name_hi}: ")


async def test_a_weak_question_gets_a_kind_nudge():
    started = await flow().begin(TEACHER, "en", TOPIC)

    reply = await flow(verdict(0)).turn(TEACHER, "en", "Who can tell me?", started.rehearsal_json)

    assert "Try asking how." in reply.text


async def test_if_the_coach_is_down_the_teacher_is_told_and_can_carry_on():
    started = await flow().begin(TEACHER, "en", TOPIC)

    reply = await flow(CoachUnavailableError("x")).turn(
        TEACHER, "en", "Who?", started.rehearsal_json
    )

    assert render("rehearsal_coach_unavailable", "en") in reply.text
    assert reply.finished is False
    assert reply.rehearsal_json is not None


async def test_three_good_turns_end_the_practice_with_a_summary_and_clear_the_save():
    saved = (await flow().begin(TEACHER, "en", TOPIC)).rehearsal_json
    reply = None
    for _ in range(3):
        reply = await flow(verdict(4)).turn(TEACHER, "en", "How did you get that?", saved)
        saved = reply.rehearsal_json

    assert reply is not None and reply.finished is True
    assert reply.rehearsal_json is None
    assert render("rehearsal_summary_best", "en") in reply.text


async def test_saying_enough_ends_the_practice_without_scoring_anything():
    started = await flow().begin(TEACHER, "en", TOPIC)

    reply = await flow().turn(TEACHER, "en", "enough", started.rehearsal_json)

    assert reply.text == render("rehearsal_summary_none", "en")
    assert reply.rehearsal_json is None
    assert reply.finished is True


@pytest.mark.parametrize("saved", [None, "", "not json", '{"topic_id": "NUM.NOPE"}'])
async def test_a_practice_with_nothing_usable_saved_ends_instead_of_crashing(saved: str | None):
    reply = await flow().turn(TEACHER, "en", "Who can tell me?", saved)

    assert reply.text == render("rehearsal_unavailable", "en")
    assert reply.rehearsal_json is None
    assert reply.finished is True


class RecordingCoach(Coach):
    def __init__(self, *verdicts: CoachVerdict | Exception) -> None:
        super().__init__(*verdicts)
        self.seen: list[str] = []

    async def score(self, request: CoachRequest) -> CoachVerdict:
        self.seen.append(request.teacher_text)
        return await super().score(request)


class RecordingVoice(EchoVoice):
    def __init__(self) -> None:
        super().__init__()
        self.seen: list[str] = []

    async def speak(self, brief: ChildBrief) -> str:
        self.seen.append(brief.teacher_text)
        return await super().speak(brief)


async def test_a_phone_number_the_teacher_says_never_reaches_the_model():
    coach, voice = RecordingCoach(verdict(0)), RecordingVoice()
    practice = RehearsalFlow(
        RehearsalEngine(voice, coach), FakePositions(), lambda: random.Random(1)
    )
    started = await practice.begin(TEACHER, "en", TOPIC)

    await practice.turn(
        TEACHER, "en", "How did you get that? Call me on 98765 43210.", started.rehearsal_json
    )

    assert coach.seen and voice.seen
    assert not any("98765" in text for text in (*coach.seen, *voice.seen))


async def test_a_failing_turn_keeps_the_practice_so_the_teacher_can_try_again():
    started = await flow().begin(TEACHER, "en", TOPIC)
    broken = flow(verdict(0), voice=EchoVoice(RuntimeError("model down")))

    reply = await broken.turn(TEACHER, "en", "Who can tell me?", started.rehearsal_json)

    assert reply.text == render("rehearsal_turn_failed", "en")
    assert reply.rehearsal_json == started.rehearsal_json
    assert reply.finished is False


class WeekBPositions(FakePositions):
    async def current(self, teacher: bytes) -> Position:
        return Position(move_id=2, week="B")


def faded_flow(*verdicts: CoachVerdict | Exception) -> RehearsalFlow:
    return RehearsalFlow(
        RehearsalEngine(EchoVoice(), Coach(*verdicts)), WeekBPositions(), lambda: random.Random(1)
    )


async def test_in_week_b_the_teacher_is_asked_to_rate_before_hearing_the_nudge():
    started = await faded_flow().begin(TEACHER, "en", TOPIC)

    reply = await faded_flow(verdict(1)).turn(
        TEACHER, "en", "Who can tell me?", started.rehearsal_json
    )

    assert reply.text.startswith(f"{RIYA.name}: ")
    assert render("self_rating_prompt", "en") in reply.text
    assert "Try asking how." not in reply.text
    assert reply.finished is False
    saved = load(reply.rehearsal_json or "")
    assert saved is not None and saved.awaiting_rating is True


async def test_replying_with_a_rating_then_shows_the_nudge_and_keeps_the_practice():
    started = await faded_flow().begin(TEACHER, "en", TOPIC)
    asked = await faded_flow(verdict(1)).turn(
        TEACHER, "en", "Who can tell me?", started.rehearsal_json
    )

    reply = await faded_flow().turn(TEACHER, "en", "🌳", asked.rehearsal_json)

    assert render("self_rating_higher", "en").format(mine="🌳", coach="🌱") in reply.text
    assert "Try asking how." in reply.text
    assert not reply.text.startswith(f"{RIYA.name}")
    saved = load(reply.rehearsal_json or "")
    assert saved is not None and saved.awaiting_rating is False and saved.turns == 1
    assert reply.finished is False


async def test_the_rating_prompt_is_in_hindi_for_a_hindi_teacher():
    started = await faded_flow().begin(TEACHER, "hi", TOPIC)

    reply = await faded_flow(verdict(1)).turn(TEACHER, "hi", "कौन बताएगा?", started.rehearsal_json)

    assert render("self_rating_prompt", "hi") in reply.text


async def test_the_last_turn_of_week_b_still_ends_with_the_nudge_and_summary():
    saved = (await faded_flow().begin(TEACHER, "en", TOPIC)).rehearsal_json
    reply = None
    for _ in range(3):
        reply = await faded_flow(verdict(4)).turn(TEACHER, "en", "How did you get that?", saved)
        saved = reply.rehearsal_json
        if not reply.finished:
            saved = (await faded_flow().turn(TEACHER, "en", "2", saved)).rehearsal_json

    assert reply is not None and reply.finished is True
    assert render("self_rating_prompt", "en") not in reply.text
    assert render("rehearsal_summary_best", "en") in reply.text


async def test_a_scored_question_comes_back_with_what_the_coach_judged():
    started = await flow().begin(TEACHER, "en", TOPIC)

    reply = await flow(verdict(2)).turn(TEACHER, "en", "Who can tell me?", started.rehearsal_json)

    turn = reply.scored
    assert turn is not None
    assert (turn.move_id, turn.topic_id, turn.week) == (2, TOPIC, "A")
    assert turn.teacher_text == "Who can tell me?"
    assert dict(turn.criteria) == {"C1": True, "C2": True, "C3": False, "C4": False}
    assert turn.child_name == RIYA.name


async def test_what_the_teacher_said_is_scrubbed_before_it_is_handed_back_to_be_logged():
    started = await flow().begin(TEACHER, "en", TOPIC)

    reply = await flow(verdict(1)).turn(
        TEACHER, "en", "How did you get that? Call me on 98765 43210.", started.rehearsal_json
    )

    assert reply.scored is not None and "98765" not in reply.scored.teacher_text


async def test_a_turn_the_coach_could_not_score_has_nothing_to_log():
    started = await flow().begin(TEACHER, "en", TOPIC)

    reply = await flow(CoachUnavailableError("x")).turn(
        TEACHER, "en", "Who?", started.rehearsal_json
    )

    assert reply.scored is None


async def test_rating_the_question_in_week_b_does_not_log_it_twice():
    started = await faded_flow().begin(TEACHER, "en", TOPIC)
    asked = await faded_flow(verdict(1)).turn(
        TEACHER, "en", "Who can tell me?", started.rehearsal_json
    )

    rated = await faded_flow().turn(TEACHER, "en", "2", asked.rehearsal_json)

    assert asked.scored is not None
    assert rated.scored is None


async def test_saying_enough_ends_the_practice_without_a_turn_to_log():
    started = await flow().begin(TEACHER, "en", TOPIC)

    reply = await flow().turn(TEACHER, "en", "enough", started.rehearsal_json)

    assert reply.finished is True
    assert reply.scored is None


async def test_starting_a_practice_has_nothing_to_log():
    started = await flow().begin(TEACHER, "en", TOPIC)

    assert started.scored is None
