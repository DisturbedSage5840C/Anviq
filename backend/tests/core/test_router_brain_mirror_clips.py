"""The Day-14 mirror plays the teacher's first and latest kept recording back to them."""

import pytest

from app.content.copy import render
from app.core.daily_loop import LoopReply
from app.core.dialogue import ClipAudio
from app.core.teacher_store import InMemoryTeacherStore, StoredClip
from tests.core.test_router_brain_rehearsal import _brain, _hash, _say

FIRST = b"OggS\x00\x02day-one"
LATEST = b"OggS\x00\x02day-fourteen"
MIME = "audio/ogg"


@pytest.fixture
def store() -> InMemoryTeacherStore:
    return InMemoryTeacherStore()


class MirrorLoop:
    """A loop whose mirror either shows a real comparison or says there is nothing yet."""

    def __init__(self, *, comparison: bool = True) -> None:
        self.comparison = comparison

    async def plan(self, teacher: bytes, lang: str, text: str) -> LoopReply:
        return LoopReply("THE PLAN")

    async def reflect(self, teacher: bytes, lang: str, text: str) -> LoopReply:
        return LoopReply("THE REFLECTION")

    async def mirror(self, teacher: bytes, lang: str) -> LoopReply:
        return LoopReply("THE MIRROR", plays_clips=self.comparison)

    async def ask(self, teacher: bytes, lang: str, text: str) -> LoopReply:
        return LoopReply("THE ANSWER")


async def _keep(store: InMemoryTeacherStore, *recordings: bytes) -> None:
    async with store.locked(_hash()) as session:
        for audio in recordings:
            await session.save_clip(audio, MIME)


async def _opted_in(store: InMemoryTeacherStore, loop: MirrorLoop):
    brain = await _brain(store, None, loop)
    await brain.respond(_say("save my recordings"))
    return brain


async def test_the_mirror_carries_the_first_and_latest_recording_in_order(
    store: InMemoryTeacherStore,
):
    brain = await _opted_in(store, MirrorLoop())
    await _keep(store, FIRST, b"middle", LATEST)

    reply = await brain.respond(_say("mirror"))

    assert reply.clips == (
        ClipAudio(FIRST, MIME, render("mirror_day1", "en")),
        ClipAudio(LATEST, MIME, render("mirror_today", "en")),
    )


async def test_a_single_kept_recording_is_played_once(store: InMemoryTeacherStore):
    brain = await _opted_in(store, MirrorLoop())
    await _keep(store, FIRST)

    reply = await brain.respond(_say("mirror"))

    assert reply.clips == (ClipAudio(FIRST, MIME, render("mirror_today", "en")),)


async def test_a_teacher_who_never_opted_in_hears_no_recordings(store: InMemoryTeacherStore):
    brain = await _brain(store, None, MirrorLoop())
    await _keep(store, FIRST, LATEST)

    reply = await brain.respond(_say("mirror"))

    assert reply.clips == ()


async def test_no_recordings_are_played_when_the_mirror_has_nothing_to_compare(
    store: InMemoryTeacherStore,
):
    brain = await _opted_in(store, MirrorLoop(comparison=False))
    await _keep(store, FIRST, LATEST)

    reply = await brain.respond(_say("mirror"))

    assert reply.clips == ()


async def test_other_steps_never_carry_recordings(store: InMemoryTeacherStore):
    brain = await _opted_in(store, MirrorLoop())
    await _keep(store, FIRST, LATEST)

    reply = await brain.respond(_say("reflect"))

    assert reply.clips == ()


async def test_the_recording_bytes_never_reach_a_repr(store: InMemoryTeacherStore):
    brain = await _opted_in(store, MirrorLoop())
    await _keep(store, FIRST)

    reply = await brain.respond(_say("mirror"))

    assert "day-one" not in repr(reply)


async def test_a_store_failure_loses_the_recordings_but_not_the_mirror_text(
    store: InMemoryTeacherStore, monkeypatch: pytest.MonkeyPatch
):
    brain = await _opted_in(store, MirrorLoop())
    await _keep(store, FIRST, LATEST)

    async def broken(self: object) -> tuple[StoredClip, StoredClip]:
        raise RuntimeError("database down")

    monkeypatch.setattr(type(await _session(store)), "first_and_latest_clips", broken)

    reply = await brain.respond(_say("mirror"))

    assert "THE MIRROR" in reply.text
    assert reply.clips == ()


async def _session(store: InMemoryTeacherStore):
    async with store.locked(_hash()) as session:
        return session
