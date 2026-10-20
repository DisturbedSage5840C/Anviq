from datetime import UTC, datetime, timedelta

import pytest

from app.content.copy import render
from app.core.daily_loop import LoopReply
from app.core.dialogue import Utterance
from app.core.rehearsal_flow import RehearsalReply
from app.core.rehearsal_log import LoggedTurn
from app.core.router import FIRST_REHEARSAL_TOPIC, Phase
from app.core.router_brain import RouterBrain
from app.core.teacher_store import InMemoryTeacherStore
from app.privacy.crypto import phone_hash

PEPPER = bytes(range(32))
SENDER = "919876543210"
TOPIC = "NUM.G2.SUB.REGROUP"
STARTED = '{"turns": 0}'
AFTER_TURN = '{"turns": 1}'


class PlanningLoop:
    def __init__(self, topic_id: str | None = TOPIC, stay_in: Phase | None = None) -> None:
        self.topic_id = topic_id
        self.stay_in = Phase.REHEARSE_OFFER if stay_in is None else stay_in

    async def plan(self, teacher: bytes, lang: str, text: str) -> LoopReply:
        return LoopReply("THE PLAN", stay_in=self.stay_in, topic_id=self.topic_id)

    async def reflect(self, teacher: bytes, lang: str, text: str) -> LoopReply:
        return LoopReply("THE REFLECTION")

    async def mirror(self, teacher: bytes, lang: str) -> LoopReply:
        return LoopReply("THE MIRROR")

    async def ask(self, teacher: bytes, lang: str, text: str) -> LoopReply:
        return LoopReply("THE ANSWER")


class RecordingRehearsals:
    def __init__(self, *replies: RehearsalReply | Exception) -> None:
        self.replies = list(replies)
        self.begun: list[tuple[bytes, str, str | None]] = []
        self.turns: list[tuple[bytes, str, str, str | None]] = []

    def _next(self) -> RehearsalReply:
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def begin(self, teacher: bytes, lang: str, topic_id: str | None) -> RehearsalReply:
        self.begun.append((teacher, lang, topic_id))
        return self._next()

    async def turn(self, teacher: bytes, lang: str, text: str, saved: str | None) -> RehearsalReply:
        self.turns.append((teacher, lang, text, saved))
        return self._next()


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def _say(text: str) -> Utterance:
    return Utterance(SENDER, text, "hi", False, False)


def _hash() -> bytes:
    return phone_hash(PEPPER, SENDER)


def _started() -> RehearsalReply:
    return RehearsalReply("THE CHILDREN ARE READY", STARTED, False)


async def _brain(
    store: InMemoryTeacherStore,
    rehearsals: RecordingRehearsals | None,
    loop: PlanningLoop | None = None,
) -> RouterBrain:
    brain = RouterBrain(store, PEPPER, loop or PlanningLoop(), rehearsals)
    for text in ("hello", "English", "2", "yes"):
        await brain.respond(_say(text))
    return brain


async def _plan(brain: RouterBrain) -> None:
    await brain.respond(_say("plan"))
    await brain.respond(_say("subtraction for class 2"))


@pytest.fixture
def store() -> InMemoryTeacherStore:
    return InMemoryTeacherStore()


async def test_a_finished_plan_remembers_its_topic_and_offers_the_practice(
    store: InMemoryTeacherStore,
):
    brain = await _brain(store, RecordingRehearsals())

    await _plan(brain)

    stored = store.teachers[_hash()]
    assert stored.state.phase is Phase.REHEARSE_OFFER
    assert stored.rehearsal.topic_id == TOPIC


async def test_a_plan_that_asked_something_back_forgets_nothing_and_names_no_topic(
    store: InMemoryTeacherStore,
):
    brain = await _brain(store, RecordingRehearsals(), PlanningLoop(None, Phase.PLAN_TOPIC))

    await _plan(brain)

    stored = store.teachers[_hash()]
    assert stored.state.phase is Phase.PLAN_TOPIC
    assert stored.rehearsal.topic_id is None


async def test_saying_yes_to_the_offer_starts_the_practice_on_the_planned_topic(
    store: InMemoryTeacherStore,
):
    rehearsals = RecordingRehearsals(_started())
    brain = await _brain(store, rehearsals)
    await _plan(brain)

    reply = await brain.respond(_say("yes"))

    assert rehearsals.begun == [(_hash(), "en", TOPIC)]
    assert reply.text == "THE CHILDREN ARE READY"
    stored = store.teachers[_hash()]
    assert stored.state.phase is Phase.REHEARSE
    assert stored.rehearsal.rehearsal_json == STARTED


async def test_each_message_in_the_practice_is_a_turn_and_progress_is_kept(
    store: InMemoryTeacherStore,
):
    rehearsals = RecordingRehearsals(_started(), RehearsalReply("RIYA: 25", AFTER_TURN, False))
    brain = await _brain(store, rehearsals)
    await _plan(brain)
    await brain.respond(_say("yes"))

    reply = await brain.respond(_say("Riya, what is 52 - 27?"))

    assert rehearsals.turns == [(_hash(), "en", "Riya, what is 52 - 27?", STARTED)]
    assert reply.text == "RIYA: 25"
    assert reply.speak is True
    stored = store.teachers[_hash()]
    assert stored.state.phase is Phase.REHEARSE
    assert stored.rehearsal.rehearsal_json == AFTER_TURN


async def test_a_finished_practice_clears_its_save_and_returns_to_the_menu(
    store: InMemoryTeacherStore,
):
    rehearsals = RecordingRehearsals(_started(), RehearsalReply("WELL DONE", None, True))
    brain = await _brain(store, rehearsals)
    await _plan(brain)
    await brain.respond(_say("yes"))

    await brain.respond(_say("enough"))

    stored = store.teachers[_hash()]
    assert stored.state.phase is Phase.IDLE
    assert stored.rehearsal.rehearsal_json is None
    assert stored.rehearsal.topic_id == TOPIC  # a new practice on the same plan is allowed


async def test_rehearse_from_the_menu_uses_the_last_plan(store: InMemoryTeacherStore):
    rehearsals = RecordingRehearsals(_started())
    brain = await _brain(store, rehearsals)
    await _plan(brain)
    await brain.respond(_say("no"))  # decline the offer

    reply = await brain.respond(_say("rehearse"))

    assert rehearsals.begun == [(_hash(), "en", TOPIC)]
    assert reply.text == "THE CHILDREN ARE READY"
    assert store.teachers[_hash()].state.phase is Phase.REHEARSE


async def test_without_a_rehearsal_service_the_teacher_is_told_and_not_stuck(
    store: InMemoryTeacherStore,
):
    brain = await _brain(store, None)

    reply = await brain.respond(_say("rehearse"))

    assert reply.text == render("rehearsal_unavailable", "en")
    assert store.teachers[_hash()].state.phase is Phase.IDLE


async def test_a_crashing_rehearsal_is_reported_and_the_teacher_is_not_stuck(
    store: InMemoryTeacherStore,
):
    brain = await _brain(store, RecordingRehearsals(RuntimeError("boom")))
    await _plan(brain)

    reply = await brain.respond(_say("yes"))

    assert reply.text == render("rehearsal_unavailable", "en")
    assert store.teachers[_hash()].state.phase is Phase.IDLE


async def test_a_practice_left_for_half_an_hour_is_cleared_and_the_message_is_fresh():
    clock = _Clock()
    store = InMemoryTeacherStore(clock=clock)
    rehearsals = RecordingRehearsals(_started())
    brain = await _brain(store, rehearsals)
    await _plan(brain)
    await brain.respond(_say("yes"))

    clock.now += timedelta(minutes=31)
    reply = await brain.respond(_say("help"))

    assert render("rehearsal_timed_out", "en") in reply.text
    assert rehearsals.turns == []
    stored = store.teachers[_hash()]
    assert stored.rehearsal.rehearsal_json is None
    assert stored.state.phase is Phase.IDLE


async def test_withdrawing_consent_mid_practice_leaves_nothing_behind(
    store: InMemoryTeacherStore,
):
    brain_holder: list[RouterBrain] = []

    class WithdrawsDuringTurn(RecordingRehearsals):
        async def turn(
            self, teacher: bytes, lang: str, text: str, saved: str | None
        ) -> RehearsalReply:
            await brain_holder[0].respond(_say("withdraw consent"))  # arrives while we think
            return await super().turn(teacher, lang, text, saved)

    rehearsals = WithdrawsDuringTurn(_started(), RehearsalReply("RIYA: 25", AFTER_TURN, False))
    brain = await _brain(store, rehearsals)
    brain_holder.append(brain)
    await _plan(brain)
    await brain.respond(_say("yes"))

    await brain.respond(_say("Riya, what is 52 - 27?"))

    stored = store.teachers[_hash()]
    assert stored.rehearsal.rehearsal_json is None
    assert stored.rehearsal.topic_id is None
    assert stored.state.phase is not Phase.REHEARSE


async def _two_turns_at_once(
    store: InMemoryTeacherStore, slow: RehearsalReply, quick: RehearsalReply
) -> str:
    """The first turn is still with the model when the teacher's next message goes all the way."""
    brain_holder: list[RouterBrain] = []

    class AnotherTurnGetsThrough(RecordingRehearsals):
        async def turn(
            self, teacher: bytes, lang: str, text: str, saved: str | None
        ) -> RehearsalReply:
            reply = await super().turn(teacher, lang, text, saved)
            if text == "first":
                await brain_holder[0].respond(_say("second"))
            return reply

    brain = await _brain(store, AnotherTurnGetsThrough(_started(), slow, quick))
    brain_holder.append(brain)
    await _plan(brain)
    await brain.respond(_say("yes"))

    return (await brain.respond(_say("first"))).text


async def test_a_slow_turn_cannot_overwrite_a_turn_that_finished_before_it(
    store: InMemoryTeacherStore,
):
    slow = RehearsalReply("SLOW CHILD", '{"turns": 1, "slow": true}', False)
    quick = RehearsalReply("QUICK CHILD", AFTER_TURN, False)

    text = await _two_turns_at_once(store, slow, quick)

    assert render("rehearsal_turn_failed", "en") in text
    assert "SLOW CHILD" not in text
    stored = store.teachers[_hash()]
    assert stored.rehearsal.rehearsal_json == AFTER_TURN
    assert stored.state.phase is Phase.REHEARSE


async def test_a_slow_turn_that_ends_the_practice_cannot_end_the_one_that_moved_on(
    store: InMemoryTeacherStore,
):
    slow = RehearsalReply("SLOW SUMMARY", None, True)
    quick = RehearsalReply("QUICK CHILD", AFTER_TURN, False)

    await _two_turns_at_once(store, slow, quick)

    stored = store.teachers[_hash()]
    assert stored.rehearsal.rehearsal_json == AFTER_TURN
    assert stored.state.phase is Phase.REHEARSE


async def test_a_corrupt_save_ends_the_practice_instead_of_trapping_the_teacher(
    store: InMemoryTeacherStore,
):
    ended = RehearsalReply("LET US START AGAIN", None, True)
    rehearsals = RecordingRehearsals(_started(), ended)
    brain = await _brain(store, rehearsals)
    await _plan(brain)
    await brain.respond(_say("yes"))
    async with store.locked(_hash()) as session:
        await session.save_rehearsal("{not json")

    reply = await brain.respond(_say("Riya, what is 52 - 27?"))

    assert rehearsals.turns == [(_hash(), "en", "Riya, what is 52 - 27?", "{not json")]
    assert reply.text == "LET US START AGAIN"
    stored = store.teachers[_hash()]
    assert stored.state.phase is Phase.IDLE
    assert stored.rehearsal.rehearsal_json is None


@pytest.mark.parametrize("rating", ["1", "2", "3", "🌱", "🌿", "🌳"])
async def test_a_rating_reaches_the_practice_instead_of_being_taken_for_a_command(
    store: InMemoryTeacherStore, rating: str
):
    rehearsals = RecordingRehearsals(_started(), RehearsalReply("NUDGE", AFTER_TURN, False))
    brain = await _brain(store, rehearsals)
    await _plan(brain)
    await brain.respond(_say("yes"))

    reply = await brain.respond(_say(rating))

    assert rehearsals.turns == [(_hash(), "en", rating, STARTED)]
    assert reply.text == "NUDGE"
    assert store.teachers[_hash()].state.phase is Phase.REHEARSE


async def test_saying_yes_to_the_first_practice_starts_it_on_the_starter_topic(
    store: InMemoryTeacherStore,
):
    rehearsals = RecordingRehearsals(_started())
    brain = await _brain(store, rehearsals)  # onboarded, first practice on offer

    reply = await brain.respond(_say("yes"))

    assert rehearsals.begun == [(_hash(), "en", FIRST_REHEARSAL_TOPIC)]
    assert reply.text == "THE CHILDREN ARE READY"
    stored = store.teachers[_hash()]
    assert stored.state.phase is Phase.REHEARSE
    assert stored.rehearsal.rehearsal_json == STARTED


async def test_the_first_practice_does_not_pose_as_a_plan(store: InMemoryTeacherStore):
    rehearsals = RecordingRehearsals(_started())
    brain = await _brain(store, rehearsals)

    await brain.respond(_say("yes"))

    assert store.teachers[_hash()].rehearsal.topic_id is None


async def test_declining_the_first_practice_shows_the_menu_and_starts_nothing(
    store: InMemoryTeacherStore,
):
    rehearsals = RecordingRehearsals()
    brain = await _brain(store, rehearsals)

    reply = await brain.respond(_say("no"))

    assert reply.text == render("menu", "en")
    assert rehearsals.begun == []
    assert store.teachers[_hash()].state.phase is Phase.IDLE


async def test_if_the_first_practice_cannot_start_the_teacher_is_told_and_lands_on_the_menu(
    store: InMemoryTeacherStore,
):
    rehearsals = RecordingRehearsals(RuntimeError("model down"))
    brain = await _brain(store, rehearsals)

    reply = await brain.respond(_say("yes"))

    assert render("rehearsal_unavailable", "en") in reply.text
    assert store.teachers[_hash()].state.phase is Phase.IDLE


# --- the practice log is written inside the message's own locked block --------------------------


def _scored(words: str) -> LoggedTurn:
    return LoggedTurn(2, TOPIC, "A", words, {"C1": True, "C2": False, "C3": False, "C4": False})


def _practices(store: InMemoryTeacherStore) -> list[tuple[list[str], bool]]:
    return [([t.teacher_text for t in p.turns], p.ended) for p in store.practices.get(_hash(), ())]


async def _practising(store: InMemoryTeacherStore, *replies: RehearsalReply) -> RouterBrain:
    brain = await _brain(store, RecordingRehearsals(_started(), *replies))
    await _plan(brain)
    await brain.respond(_say("yes"))
    return brain


async def test_a_scored_turn_that_stands_is_logged(store: InMemoryTeacherStore):
    brain = await _practising(store, RehearsalReply("RIYA: 25", AFTER_TURN, False, _scored("one")))

    await brain.respond(_say("Riya, what is 52 - 27?"))

    assert _practices(store) == [(["one"], False)]


async def test_a_turn_without_a_score_leaves_no_practice_behind(store: InMemoryTeacherStore):
    brain = await _practising(store, RehearsalReply("RIYA: 25", AFTER_TURN, False))

    await brain.respond(_say("hmm"))

    assert _practices(store) == []


async def test_a_slow_turn_that_was_dropped_is_not_logged(store: InMemoryTeacherStore):
    slow = RehearsalReply("SLOW CHILD", '{"turns": 1, "slow": true}', False, _scored("slow"))
    quick = RehearsalReply("QUICK CHILD", AFTER_TURN, False, _scored("quick"))

    await _two_turns_at_once(store, slow, quick)

    assert _practices(store) == [(["quick"], False)]


async def test_a_turn_that_arrives_after_consent_was_withdrawn_is_not_logged(
    store: InMemoryTeacherStore,
):
    brain_holder: list[RouterBrain] = []

    class WithdrawsDuringTurn(RecordingRehearsals):
        async def turn(
            self, teacher: bytes, lang: str, text: str, saved: str | None
        ) -> RehearsalReply:
            await brain_holder[0].respond(_say("withdraw consent"))
            return await super().turn(teacher, lang, text, saved)

    scored = RehearsalReply("RIYA: 25", AFTER_TURN, False, _scored("late"))
    brain = await _brain(store, WithdrawsDuringTurn(_started(), scored))
    brain_holder.append(brain)
    await _plan(brain)
    await brain.respond(_say("yes"))

    await brain.respond(_say("Riya, what is 52 - 27?"))

    assert _practices(store) == []


async def test_a_finished_practice_closes_its_logged_session(store: InMemoryTeacherStore):
    brain = await _practising(
        store,
        RehearsalReply("RIYA: 25", AFTER_TURN, False, _scored("one")),
        RehearsalReply("WELL DONE", None, True, _scored("two")),
    )

    await brain.respond(_say("one"))
    await brain.respond(_say("two"))

    assert _practices(store) == [(["one", "two"], True)]


async def test_saying_enough_closes_the_logged_session(store: InMemoryTeacherStore):
    brain = await _practising(
        store,
        RehearsalReply("RIYA: 25", AFTER_TURN, False, _scored("one")),
        RehearsalReply("WELL DONE", None, True),
    )

    await brain.respond(_say("one"))
    await brain.respond(_say("enough"))

    assert _practices(store) == [(["one"], True)]


async def test_a_practice_that_timed_out_closes_its_logged_session():
    clock = _Clock()
    store = InMemoryTeacherStore(clock=clock)
    brain = await _practising(store, RehearsalReply("RIYA: 25", AFTER_TURN, False, _scored("one")))
    await brain.respond(_say("one"))

    clock.now += timedelta(minutes=31)
    await brain.respond(_say("help"))

    assert _practices(store) == [(["one"], True)]


async def test_starting_a_practice_closes_one_the_teacher_left_open(store: InMemoryTeacherStore):
    brain = await _brain(store, RecordingRehearsals(_started()))
    async with store.locked(_hash()) as session:
        await session.log_practice_turn(_scored("abandoned"))
    await _plan(brain)

    await brain.respond(_say("yes"))

    assert _practices(store) == [(["abandoned"], True)]


async def test_withdrawing_consent_closes_the_practice_the_teacher_left_open(
    store: InMemoryTeacherStore,
):
    brain = await _practising(store, RehearsalReply("RIYA: 25", AFTER_TURN, False, _scored("one")))
    await brain.respond(_say("one"))

    await brain.respond(_say("withdraw consent"))

    assert _practices(store) == [(["one"], True)]
