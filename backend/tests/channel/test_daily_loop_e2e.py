"""A whole WhatsApp conversation: onboard, plan, reflect, mirror, delete.

The real pipeline, router and `PipelineDailyLoop` run. Only the network edges and the model
writers are faked, so this pins the order a teacher sees things in and that each request reaches
the right writer with the right move.
"""

from app.content.copy import render
from app.core.daily_loop import PipelineDailyLoop, Position
from app.core.mirror import MirrorTurn
from app.core.planner import AskBack, Planned, PlanQuestion, PlanRequest
from app.core.reflect import Reflected, ReflectionDraft, ReflectRequest
from tests.channel.e2e_support import Harness, make_harness, text_message

MOVE = 4
PLAN_TEXT = "Today: three questions on halves."
REFLECTION_TEXT = "You waited for the children. Next, ask why."
QUESTION = PlanQuestion("What is half of 8?", "4", "draw it")


class ScriptedPlanner:
    def __init__(self, *outcomes: AskBack | Planned) -> None:
        self.outcomes = list(outcomes)
        self.seen: list[PlanRequest] = []

    async def plan(self, request: PlanRequest) -> AskBack | Planned:
        self.seen.append(request)
        return self.outcomes.pop(0)


class FixedReflector:
    def __init__(self) -> None:
        self.seen: list[ReflectRequest] = []

    async def reflect(self, request: ReflectRequest) -> Reflected:
        self.seen.append(request)
        return Reflected(ReflectionDraft("s", "n", "e"), REFLECTION_TEXT)


class FixedPosition:
    async def current(self, teacher: bytes) -> Position:
        return Position(move_id=MOVE, week="A")


class ReadyMirror:
    def __init__(self) -> None:
        self.completed = 0

    async def comparable(self, teacher: bytes) -> tuple[MirrorTurn, MirrorTurn] | None:
        first = MirrorTurn("day one words", {"a": False})
        latest = MirrorTurn("day fourteen words", {"a": True})
        return first, latest

    async def complete(self, teacher: bytes) -> None:
        self.completed += 1


async def _onboard(harness: Harness) -> None:
    for body in ("hello", "English", "2", "yes"):
        await harness.pipeline.handle(text_message(body))


async def _say(harness: Harness, body: str) -> str:
    await harness.pipeline.handle(text_message(body))
    return harness.texts()[-1]


async def test_a_teacher_plans_reflects_looks_at_the_mirror_and_deletes_in_one_conversation():
    planner = ScriptedPlanner(Planned("halves", (QUESTION,) * 3, PLAN_TEXT))
    reflector, mirror = FixedReflector(), ReadyMirror()
    loop = PipelineDailyLoop(planner, reflector, FixedPosition(), mirror)
    harness = make_harness(loop=loop)
    await _onboard(harness)

    assert await _say(harness, "plan") == render("ask_plan_topic", "en")
    assert await _say(harness, "halves") == PLAN_TEXT
    assert await _say(harness, "reflect") == render("ask_reflect_notes", "en")
    assert await _say(harness, "it went well") == REFLECTION_TEXT
    shown = await _say(harness, "mirror")
    await _say(harness, "delete my data")
    assert await _say(harness, "yes, delete") == render("deleted", "en")

    assert planner.seen == [PlanRequest("halves", "en", MOVE, "A")]
    assert reflector.seen == [ReflectRequest("it went well", "en", MOVE)]
    assert "day one words" in shown and "day fourteen words" in shown
    assert render("mirror_next_move", "en") in shown
    assert mirror.completed == 1
    assert harness.store.teachers == {}


async def test_an_unclear_topic_is_asked_again_and_the_next_answer_is_still_the_topic():
    planner = ScriptedPlanner(
        AskBack("Which class is this for?"), Planned("halves", (QUESTION,) * 3, PLAN_TEXT)
    )
    loop = PipelineDailyLoop(planner, FixedReflector(), FixedPosition(), ReadyMirror())
    harness = make_harness(loop=loop)
    await _onboard(harness)

    await _say(harness, "plan")
    assert await _say(harness, "that thing") == "Which class is this for?"
    assert await _say(harness, "halves for class 2") == PLAN_TEXT

    assert [request.text for request in planner.seen] == ["that thing", "halves for class 2"]


async def test_without_a_model_loop_plan_reflect_and_mirror_each_say_they_are_unavailable():
    harness = make_harness()
    await _onboard(harness)

    await _say(harness, "plan")
    assert await _say(harness, "halves") == render("plan_unavailable", "en")
    await _say(harness, "reflect")
    assert await _say(harness, "notes") == render("reflect_unavailable", "en")
    assert await _say(harness, "mirror") == render("mirror_unavailable", "en")
