"""Mirror clips through the brain: kept only for a teacher who said yes, and only practice turns."""

import pytest

from app.core.dialogue import Utterance
from app.core.rehearsal_flow import RehearsalReply
from app.core.rehearsal_log import LoggedTurn
from app.core.router_brain import RouterBrain
from app.core.teacher_store import InMemoryTeacherStore
from tests.core.test_router_brain_rehearsal import (  # noqa: F401  (pytest fixtures)
    AFTER_TURN,
    SENDER,
    TOPIC,
    RecordingRehearsals,
    _brain,
    _hash,
    _plan,
    _say,
    _started,
    store,
)

RECORDING = b"OggS\x00\x02the-teacher-practising"
SECOND = b"OggS\x00\x02the-teacher-again"
MIME = "audio/ogg"


def _scored() -> LoggedTurn:
    return LoggedTurn(2, TOPIC, "A", "what is 52 - 27", {"C1": True, "C2": False})


def _spoken(text: str, audio: bytes, mime: str = MIME) -> Utterance:
    return Utterance(SENDER, text, "hi", True, False, audio=audio, audio_mime=mime)


def _turn() -> RehearsalReply:
    return RehearsalReply("RIYA: 25", AFTER_TURN, False, scored=_scored())


async def _practising(store: InMemoryTeacherStore, *replies: RehearsalReply) -> RouterBrain:
    brain = await _brain(store, RecordingRehearsals(_started(), *replies))
    await _plan(brain)
    await brain.respond(_say("yes"))
    return brain


async def test_saving_recordings_is_switched_on_by_the_teacher_saying_so(
    store: InMemoryTeacherStore,
):
    brain = await _brain(store, RecordingRehearsals())

    await brain.respond(_say("save my recordings"))

    assert store.teachers[_hash()].clip_opt_in is True


async def test_a_practice_recording_is_kept_once_the_teacher_has_opted_in(
    store: InMemoryTeacherStore,
):
    brain = await _practising(store, _turn())
    await brain.respond(_say("save my recordings"))

    await brain.respond(_spoken("Riya, what is 52 - 27?", RECORDING))

    kept = store.clips[_hash()]
    assert [(c.audio, c.mime) for c in kept] == [(RECORDING, MIME)]


async def test_a_practice_recording_is_not_kept_without_the_opt_in(
    store: InMemoryTeacherStore,
):
    brain = await _practising(store, _turn())

    await brain.respond(_spoken("Riya, what is 52 - 27?", RECORDING))

    assert _hash() not in store.clips


async def test_stopping_deletes_what_was_kept_and_keeps_nothing_new(
    store: InMemoryTeacherStore,
):
    brain = await _practising(store, _turn(), _turn())
    await brain.respond(_say("save my recordings"))
    await brain.respond(_spoken("first question", RECORDING))

    await brain.respond(_say("stop saving my recordings"))
    await brain.respond(_spoken("second question", SECOND))

    assert _hash() not in store.clips
    assert store.teachers[_hash()].clip_opt_in is False


async def test_only_the_first_and_the_latest_recording_are_kept(store: InMemoryTeacherStore):
    third = b"OggS\x00\x02third"
    brain = await _practising(store, _turn(), _turn(), _turn())
    await brain.respond(_say("save my recordings"))

    for audio in (RECORDING, SECOND, third):
        await brain.respond(_spoken("a question", audio))

    assert [c.audio for c in store.clips[_hash()]] == [RECORDING, third]


async def test_typed_messages_have_no_recording_to_keep(store: InMemoryTeacherStore):
    brain = await _practising(store, _turn())
    await brain.respond(_say("save my recordings"))

    await brain.respond(_say("Riya, what is 52 - 27?"))

    assert _hash() not in store.clips


async def test_a_recording_sent_outside_the_practice_is_not_kept(store: InMemoryTeacherStore):
    brain = await _brain(store, RecordingRehearsals())
    await brain.respond(_say("save my recordings"))

    await brain.respond(_spoken("help", RECORDING))

    assert _hash() not in store.clips


async def test_a_turn_the_coach_did_not_score_is_not_kept(store: InMemoryTeacherStore):
    unscored = RehearsalReply("Please try again.", AFTER_TURN, False)
    brain = await _practising(store, unscored)
    await brain.respond(_say("save my recordings"))

    await brain.respond(_spoken("mumble", RECORDING))

    assert _hash() not in store.clips


def test_the_recording_never_appears_in_the_utterance_repr():
    utterance = _spoken("hello", RECORDING)

    assert "the-teacher-practising" not in repr(utterance)


@pytest.mark.parametrize("mime", ["audio/webm", "audio/ogg"])
async def test_the_recording_keeps_the_type_it_arrived_with(store: InMemoryTeacherStore, mime: str):
    brain = await _practising(store, _turn())
    await brain.respond(_say("save my recordings"))

    await brain.respond(_spoken("a question", RECORDING, mime))

    assert store.clips[_hash()][0].mime == mime
