import pytest

from app.content.copy import render
from app.core.ask.answer import AskReply, AskUnavailableError
from app.core.daily_loop import Mirrors, PipelineDailyLoop, Position
from app.core.mirror import MirrorTurn
from app.core.planner import AskBack, Planned, PlanQuestion, PlanRequest, PlanUnavailableError
from app.core.reflect import Reflected, ReflectionDraft, ReflectRequest, ReflectUnavailableError
from app.core.router import Phase

TEACHER = b"t" * 32
QUESTION = PlanQuestion("What is half?", "one of two", "show a roti")


class FakePlanner:
    def __init__(self, result: AskBack | Planned | Exception) -> None:
        self.result = result
        self.seen: list[PlanRequest] = []

    async def plan(self, request: PlanRequest) -> AskBack | Planned:
        self.seen.append(request)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeReflector:
    def __init__(self, result: Reflected | Exception) -> None:
        self.result = result
        self.seen: list[ReflectRequest] = []

    async def reflect(self, request: ReflectRequest) -> Reflected:
        self.seen.append(request)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakePositions:
    async def current(self, teacher: bytes) -> Position:
        return Position(move_id=3, week="B")


class FakeMirrors(Mirrors):
    def __init__(self, pair: tuple[MirrorTurn, MirrorTurn] | None) -> None:
        self.pair = pair
        self.completed: list[bytes] = []

    async def comparable(self, teacher: bytes) -> tuple[MirrorTurn, MirrorTurn] | None:
        return self.pair

    async def complete(self, teacher: bytes) -> None:
        self.completed.append(teacher)


def _loop(planner=None, reflector=None, mirrors=None) -> PipelineDailyLoop:
    return PipelineDailyLoop(
        planner=planner or FakePlanner(AskBack("which class?")),
        reflector=reflector or FakeReflector(ReflectUnavailableError("x")),
        positions=FakePositions(),
        mirrors=mirrors or FakeMirrors(None),
    )


async def test_a_plan_request_carries_the_teachers_move_and_week():
    planner = FakePlanner(Planned("fractions", (QUESTION,) * 3, "the plan"))

    reply = await _loop(planner=planner).plan(TEACHER, "en", "fractions")

    assert planner.seen == [PlanRequest("fractions", "en", 3, "B")]
    assert reply.text == "the plan"


async def test_a_finished_plan_offers_the_practice_and_names_its_topic():
    planner = FakePlanner(Planned("NUM.G2.SUB.REGROUP", (QUESTION,) * 3, "the plan"))

    reply = await _loop(planner=planner).plan(TEACHER, "en", "subtraction")

    assert reply.stay_in is Phase.REHEARSE_OFFER
    assert reply.topic_id == "NUM.G2.SUB.REGROUP"


async def test_a_question_back_names_no_topic():
    reply = await _loop(planner=FakePlanner(AskBack("which class?"))).plan(TEACHER, "en", "that")

    assert reply.topic_id is None


async def test_an_unclear_topic_puts_the_question_back_and_keeps_the_teacher_in_the_topic_prompt():
    reply = await _loop(planner=FakePlanner(AskBack("which class?"))).plan(TEACHER, "en", "that")

    assert reply.text == "which class?"
    assert reply.stay_in is Phase.PLAN_TOPIC


async def test_a_plan_that_cannot_be_made_says_so_honestly():
    reply = await _loop(planner=FakePlanner(PlanUnavailableError("no"))).plan(TEACHER, "hi", "x")

    assert reply.text == render("plan_unavailable", "hi")


async def test_a_reflection_request_carries_the_move():
    draft = ReflectionDraft("s", "n", "e")
    reflector = FakeReflector(Reflected(draft, "the reflection"))

    reply = await _loop(reflector=reflector).reflect(TEACHER, "en", "it went well")

    assert reflector.seen == [ReflectRequest("it went well", "en", 3)]
    assert reply.text == "the reflection"


async def test_a_reflection_that_cannot_be_made_says_so_honestly():
    reply = await _loop(reflector=FakeReflector(ReflectUnavailableError("no"))).reflect(
        TEACHER, "en", "x"
    )

    assert reply.text == render("reflect_unavailable", "en")


async def test_the_mirror_before_two_sessions_says_there_is_nothing_to_compare():
    reply = await _loop(mirrors=FakeMirrors(None)).mirror(TEACHER, "en")

    assert reply.text == render("mirror_not_ready", "en")
    assert reply.plays_clips is False


async def test_the_mirror_shows_both_turns_and_unlocks_the_next_move_once():
    first = MirrorTurn("first words", {"a": False, "b": False})
    latest = MirrorTurn("later words", {"a": True, "b": True})
    mirrors = FakeMirrors((first, latest))

    reply = await _loop(mirrors=mirrors).mirror(TEACHER, "en")

    assert "first words" in reply.text
    assert "later words" in reply.text
    assert render("mirror_next_move", "en") in reply.text
    assert mirrors.completed == [TEACHER]
    assert reply.plays_clips is True


@pytest.mark.parametrize("lang", ["hi", "en"])
async def test_every_loop_message_has_copy_in_each_language(lang: str):
    for key in ("plan_unavailable", "reflect_unavailable", "mirror_not_ready", "mirror_next_move"):
        assert render(key, lang)


class PositionAt:
    def __init__(self, move_id: int) -> None:
        self.move_id = move_id

    async def current(self, teacher: bytes) -> Position:
        return Position(self.move_id, "A")


@pytest.mark.parametrize("move_id", range(1, 7))
async def test_plan_and_reflect_work_for_every_move_in_the_programme(move_id: int):
    planner = FakePlanner(Planned("fractions", (QUESTION,) * 3, "the plan"))
    reflector = FakeReflector(Reflected(ReflectionDraft("s", "n", "e"), "the reflection"))
    loop = PipelineDailyLoop(planner, reflector, PositionAt(move_id), FakeMirrors(None))

    await loop.plan(TEACHER, "en", "fractions")
    await loop.reflect(TEACHER, "en", "it went well")

    assert planner.seen[0].move_id == move_id
    assert reflector.seen[0].move_id == move_id


class FakeAsker:
    def __init__(self, result: AskReply | Exception) -> None:
        self.result = result
        self.seen: list[tuple[str, str]] = []

    async def answer(self, question: str, lang: str) -> AskReply:
        self.seen.append((question, lang))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _asking(asker: FakeAsker | None) -> PipelineDailyLoop:
    return PipelineDailyLoop(
        FakePlanner(AskBack("x")),
        FakeReflector(ReflectUnavailableError("x")),
        FakePositions(),
        FakeMirrors(None),
        asker=asker,
    )


async def test_a_question_is_answered_with_its_source_line():
    answer = AskReply("Use bundles.\n\nSource: NISHTHA 9", "Use bundles.", ("NISHTHA 9",), False)
    asker = FakeAsker(answer)

    reply = await _asking(asker).ask(TEACHER, "en", "How do I teach tens?")

    assert reply.text == answer.text
    assert reply.stay_in is None
    assert asker.seen == [("How do I teach tens?", "en")]


async def test_a_refusal_is_passed_on_as_it_is():
    refusal = AskReply("This isn't in the modules.", "This isn't in the modules.", (), True)

    reply = await _asking(FakeAsker(refusal)).ask(TEACHER, "en", "What is my salary?")

    assert reply.text == "This isn't in the modules."


async def test_an_unreachable_model_says_so_honestly(caplog):
    reply = await _asking(FakeAsker(AskUnavailableError("down"))).ask(TEACHER, "hi", "x?")

    assert reply.text == render("ask_unavailable", "hi")
    assert "AskUnavailableError" in caplog.text


async def test_without_a_corpus_the_question_is_reported_unavailable():
    reply = await _asking(None).ask(TEACHER, "en", "How do I teach tens?")

    assert reply.text == render("ask_unavailable", "en")
