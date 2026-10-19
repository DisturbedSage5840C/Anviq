"""A WhatsApp conversation through the practice with the three children.

The real pipeline, router, brain, `PipelineDailyLoop`, `RehearsalFlow`, engine and codec run.
Only the network edges and the two model calls (the children's voice and the coach) are faked, so
this pins what a teacher reads, in order, and that the practice survives from message to message.
"""

import random

from app.content.copy import render
from app.core.children.verbalizer import ChildBrief
from app.core.coach import CoachRequest, CoachVerdict
from app.core.daily_loop import PipelineDailyLoop, Position
from app.core.planner import Planned, PlanQuestion, PlanRequest
from app.core.reflect import Reflected, ReflectionDraft, ReflectRequest
from app.core.rehearsal import RehearsalEngine
from app.core.rehearsal_flow import RehearsalFlow
from tests.channel.e2e_support import Harness, make_harness, text_message

TOPIC = "NUM.G2.SUB.REGROUP"
PLAN_TEXT = "Today: three questions on regrouping. Say 'yes' to practise."
QUESTION = PlanQuestion("What is 52 - 17?", "35", "use tens and ones")
CRITERIA = ("C1", "C2", "C3", "C4")


class ScriptedPlanner:
    async def plan(self, request: PlanRequest) -> Planned:
        return Planned(TOPIC, (QUESTION,) * 3, PLAN_TEXT)


class QuietReflector:
    async def reflect(self, request: ReflectRequest) -> Reflected:
        return Reflected(ReflectionDraft("s", "n", "e"), "Well done.")


class FixedPosition:
    async def current(self, teacher: bytes) -> Position:
        return Position(move_id=2, week="A")


class ClosedMirror:
    async def comparable(self, teacher: bytes) -> None:
        return None

    async def complete(self, teacher: bytes) -> None:
        return None


class EchoVoice:
    async def speak(self, brief: ChildBrief) -> str:
        return f"I think it is {brief.answer}."


class ScriptedCoach:
    """Hands out one verdict per question the teacher asks, and counts them."""

    def __init__(self, *met_counts: int) -> None:
        self.met_counts = list(met_counts)
        self.seen: list[CoachRequest] = []

    async def score(self, request: CoachRequest) -> CoachVerdict:
        self.seen.append(request)
        met = self.met_counts.pop(0)
        criteria = {cid: index < met for index, cid in enumerate(CRITERIA)}
        return CoachVerdict(2, criteria, {}, "Ask how they know.", "Good try.")


def _practice(coach: ScriptedCoach) -> RehearsalFlow:
    engine = RehearsalEngine(EchoVoice(), coach)
    return RehearsalFlow(engine, FixedPosition(), lambda: random.Random(1))


def _loop() -> PipelineDailyLoop:
    return PipelineDailyLoop(ScriptedPlanner(), QuietReflector(), FixedPosition(), ClosedMirror())


async def _onboard(harness: Harness) -> None:
    for body in ("hello", "English", "2", "yes"):
        await harness.pipeline.handle(text_message(body))


async def _say(harness: Harness, body: str) -> str:
    await harness.pipeline.handle(text_message(body))
    return harness.texts()[-1]


async def _plan_a_lesson(harness: Harness) -> None:
    await _say(harness, "plan")
    assert await _say(harness, "regrouping") == PLAN_TEXT


async def test_a_teacher_plans_says_yes_and_practises_until_three_good_questions():
    coach = ScriptedCoach(3, 1, 4, 2)
    harness = make_harness(loop=_loop(), rehearsal=_practice(coach))
    await _onboard(harness)
    await _plan_a_lesson(harness)

    started = await _say(harness, "yes")
    first = await _say(harness, "How did you get that?")
    second = await _say(harness, "What is the tens digit?")
    third = await _say(harness, "Can you show me with sticks?")
    last = await _say(harness, "Why did you borrow?")

    assert render("rehearsal_started", "en") in started
    assert "The problem on the board:" in started
    assert "I think it is" in first and render("coach_ok", "en") in first
    assert "Ask how they know." in second  # a weak question is coached, a good one is not
    assert render("rehearsal_summary_best", "en") in last
    assert [r.teacher_text for r in coach.seen] == [
        "How did you get that?",
        "What is the tens digit?",
        "Can you show me with sticks?",
        "Why did you borrow?",
    ]
    assert third.startswith(("Riya:", "Aman:", "Meena:"))  # a child answered every message


async def test_enough_ends_the_practice_and_the_next_message_is_handled_fresh():
    coach = ScriptedCoach(3)
    harness = make_harness(loop=_loop(), rehearsal=_practice(coach))
    await _onboard(harness)
    await _plan_a_lesson(harness)
    await _say(harness, "yes")
    await _say(harness, "How did you get that?")

    closing = await _say(harness, "enough")

    assert render("rehearsal_summary_best", "en") in closing
    assert await _say(harness, "plan") == render("ask_plan_topic", "en")
    assert len(coach.seen) == 1  # "enough" and "plan" never reached the coach


async def test_rehearse_from_the_menu_practises_the_last_plan_again():
    coach = ScriptedCoach()
    harness = make_harness(loop=_loop(), rehearsal=_practice(coach))
    await _onboard(harness)
    await _plan_a_lesson(harness)
    await _say(harness, "yes")
    await _say(harness, "enough")

    again = await _say(harness, "rehearse")

    assert render("rehearsal_started", "en") in again
    assert "The problem on the board:" in again


async def test_rehearse_before_any_plan_asks_the_teacher_to_plan_first():
    harness = make_harness(loop=_loop(), rehearsal=_practice(ScriptedCoach()))
    await _onboard(harness)

    assert await _say(harness, "rehearse") == render("rehearsal_needs_plan", "en")


async def test_without_a_model_the_practice_says_it_is_unavailable_and_the_menu_still_works():
    harness = make_harness()
    await _onboard(harness)

    assert await _say(harness, "rehearse") == render("rehearsal_unavailable", "en")
    await _say(harness, "plan")
    assert await _say(harness, "regrouping") == render("plan_unavailable", "en")
