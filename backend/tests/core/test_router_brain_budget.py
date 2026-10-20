"""A teacher who has used the day's paid model steps is told so, and nothing paid for runs."""

import pytest

from app.content.copy import render
from app.core.daily_loop import LoopReply
from app.core.dialogue import Utterance
from app.core.rehearsal_flow import RehearsalReply
from app.core.router import Phase
from app.core.router_brain import RouterBrain
from app.core.teacher_store import InMemoryTeacherStore
from app.privacy.crypto import phone_hash

PEPPER = bytes(range(32))
SENDER = "919876543210"
TOPIC = "NUM.G2.SUB.REGROUP"
STARTED = '{"turns": 0}'
AFTER_TURN = '{"turns": 1}'


class Budget:
    """Allows the first `allowed` steps, or raises when Redis is down."""

    def __init__(self, allowed: int, *, broken: bool = False) -> None:
        self.allowed = allowed
        self.broken = broken
        self.asked: list[bytes] = []

    async def spend(self, teacher: bytes) -> bool:
        self.asked.append(teacher)
        if self.broken:
            raise ConnectionError("redis is down")
        return len(self.asked) <= self.allowed


class Loop:
    def __init__(self) -> None:
        self.planned: list[str] = []

    async def plan(self, teacher: bytes, lang: str, text: str) -> LoopReply:
        self.planned.append(text)
        return LoopReply("THE PLAN", stay_in=Phase.REHEARSE_OFFER, topic_id=TOPIC)

    async def reflect(self, teacher: bytes, lang: str, text: str) -> LoopReply:
        return LoopReply("THE REFLECTION")

    async def mirror(self, teacher: bytes, lang: str) -> LoopReply:
        return LoopReply("THE MIRROR")

    async def ask(self, teacher: bytes, lang: str, text: str) -> LoopReply:
        return LoopReply("THE ANSWER")


class Rehearsals:
    def __init__(self) -> None:
        self.begun = 0
        self.turns = 0

    async def begin(self, teacher: bytes, lang: str, topic_id: str | None) -> RehearsalReply:
        self.begun += 1
        return RehearsalReply("THE CHILDREN ARE READY", STARTED, False)

    async def turn(self, teacher: bytes, lang: str, text: str, saved: str | None) -> RehearsalReply:
        self.turns += 1
        return RehearsalReply("RIYA: 25", AFTER_TURN, False)


def _say(text: str) -> Utterance:
    return Utterance(SENDER, text, "hi", False, False)


def _hash() -> bytes:
    return phone_hash(PEPPER, SENDER)


@pytest.fixture
def store() -> InMemoryTeacherStore:
    return InMemoryTeacherStore()


async def _teacher(
    store: InMemoryTeacherStore, budget: Budget
) -> tuple[RouterBrain, Loop, Rehearsals]:
    loop, rehearsals = Loop(), Rehearsals()
    brain = RouterBrain(store, PEPPER, loop, rehearsals, budget)
    for text in ("hello", "English", "2", "yes", "plan"):
        await brain.respond(_say(text))
    return brain, loop, rehearsals


async def test_a_step_within_the_allowance_runs_and_is_charged_to_the_teacher(
    store: InMemoryTeacherStore,
):
    budget = Budget(allowed=5)
    brain, loop, _ = await _teacher(store, budget)

    reply = await brain.respond(_say("subtraction for class 2"))

    assert "THE PLAN" in reply.text
    assert loop.planned == ["subtraction for class 2"]
    assert budget.asked == [_hash()]


async def test_a_loop_step_over_the_allowance_says_so_and_runs_nothing(store: InMemoryTeacherStore):
    brain, loop, _ = await _teacher(store, Budget(allowed=0))

    reply = await brain.respond(_say("subtraction for class 2"))

    assert render("daily_limit", "en") in reply.text
    assert loop.planned == []


async def test_starting_a_practice_over_the_allowance_ends_it_instead_of_trapping_the_teacher(
    store: InMemoryTeacherStore,
):
    brain, _, rehearsals = await _teacher(store, Budget(allowed=1))
    await brain.respond(_say("subtraction for class 2"))

    reply = await brain.respond(_say("yes"))

    assert render("daily_limit", "en") in reply.text
    assert rehearsals.begun == 0
    assert store.teachers[_hash()].state.phase is Phase.IDLE


async def test_a_practice_turn_over_the_allowance_ends_the_practice_and_clears_it(
    store: InMemoryTeacherStore,
):
    brain, _, rehearsals = await _teacher(store, Budget(allowed=2))
    await brain.respond(_say("subtraction for class 2"))
    await brain.respond(_say("yes"))

    reply = await brain.respond(_say("how did you get that?"))

    assert render("daily_limit", "en") in reply.text
    assert rehearsals.turns == 0
    stored = store.teachers[_hash()]
    assert stored.state.phase is Phase.IDLE
    assert stored.rehearsal.rehearsal_json is None


async def test_a_budget_that_cannot_be_read_gives_the_kind_unavailable_message(
    store: InMemoryTeacherStore,
):
    brain, loop, _ = await _teacher(store, Budget(allowed=5, broken=True))

    reply = await brain.respond(_say("subtraction for class 2"))

    assert render("plan_unavailable", "en") in reply.text
    assert loop.planned == []


async def test_a_practice_whose_budget_cannot_be_read_says_it_could_not_start(
    store: InMemoryTeacherStore,
):
    working = Budget(allowed=1)
    brain, _, rehearsals = await _teacher(store, working)
    await brain.respond(_say("subtraction for class 2"))
    working.broken = True

    reply = await brain.respond(_say("yes"))

    assert render("rehearsal_unavailable", "en") in reply.text
    assert rehearsals.begun == 0


async def test_a_practice_turn_whose_budget_cannot_be_read_keeps_the_practice_going(
    store: InMemoryTeacherStore,
):
    working = Budget(allowed=2)
    brain, _, rehearsals = await _teacher(store, working)
    await brain.respond(_say("subtraction for class 2"))
    await brain.respond(_say("yes"))
    working.broken = True

    reply = await brain.respond(_say("how did you get that?"))

    assert render("rehearsal_turn_failed", "en") in reply.text
    assert rehearsals.turns == 0
    stored = store.teachers[_hash()]
    assert stored.state.phase is Phase.REHEARSE
    assert stored.rehearsal.rehearsal_json == STARTED


def test_the_limit_message_exists_in_both_languages():
    assert render("daily_limit", "hi").strip()
    assert render("daily_limit", "en").strip()
