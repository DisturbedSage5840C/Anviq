import hashlib

import pytest

from app.content.copy import render
from app.core.dialogue import Utterance
from app.core.router import CONSENT_VERSION, Phase
from app.core.router_brain import RouterBrain
from app.core.teacher_store import InMemoryTeacherStore, deletion_log_prefix
from app.privacy.crypto import phone_hash

PEPPER = bytes(range(32))
SENDER = "919876543210"


@pytest.fixture
def store() -> InMemoryTeacherStore:
    return InMemoryTeacherStore()


@pytest.fixture
def brain(store: InMemoryTeacherStore) -> RouterBrain:
    return RouterBrain(store, PEPPER)


def _say(text: str, sender: str = SENDER) -> Utterance:
    return Utterance(sender, text, "hi", False, False)


def _hash(sender: str = SENDER) -> bytes:
    return phone_hash(PEPPER, sender)


async def _onboard(brain: RouterBrain, language: str = "English") -> None:
    for text in ("hello", language, "2", "yes"):
        await brain.respond(_say(text))


async def test_first_message_gets_a_bilingual_welcome(brain: RouterBrain):
    reply = await brain.respond(_say("hello"))

    assert render("welcome", "hi") in reply.text
    assert render("welcome", "en") in reply.text
    assert reply.speak is False  # no voice until we know the language


async def test_a_stranger_who_only_said_hello_leaves_no_trace(
    brain: RouterBrain, store: InMemoryTeacherStore
):
    await brain.respond(_say("hello"))

    # ONB_LANG is the first real phase, so a stub row exists but holds nothing identifying
    stored = store.teachers[_hash()]
    assert stored.state.phase is Phase.ONB_LANG
    assert stored.state.lang is None


async def test_onboarding_ends_in_the_menu_with_consent_on_file(
    brain: RouterBrain, store: InMemoryTeacherStore
):
    await _onboard(brain)

    stored = store.teachers[_hash()]
    assert stored.state.phase is Phase.IDLE
    assert stored.state.lang == "en"
    assert [c.version for c in stored.consents] == [CONSENT_VERSION]


async def test_consent_is_stamped_with_the_hash_of_the_text_the_teacher_saw(
    brain: RouterBrain, store: InMemoryTeacherStore
):
    await _onboard(brain, "English")

    expected = hashlib.sha256(render("consent_notice", "en").encode("utf-8")).hexdigest()
    assert store.teachers[_hash()].consents[0].text_sha256 == expected


async def test_replies_follow_the_chosen_language(brain: RouterBrain):
    await brain.respond(_say("hello"))
    reply = await brain.respond(_say("Hindi"))

    assert reply.text == render("ask_grade", "hi")
    assert reply.lang == "hi"
    assert reply.speak is True


async def test_declining_consent_leaves_nothing_behind(
    brain: RouterBrain, store: InMemoryTeacherStore
):
    for text in ("hello", "English", "2"):
        await brain.respond(_say(text))
    reply = await brain.respond(_say("no"))

    assert reply.text == render("consent_declined", "en")
    assert store.teachers == {}


async def test_delete_flow_erases_everything_and_logs_only_a_prefix(
    brain: RouterBrain, store: InMemoryTeacherStore
):
    await _onboard(brain)
    await brain.respond(_say("delete my data"))
    reply = await brain.respond(_say("yes, delete"))

    assert reply.text == render("deleted", "en")
    assert store.teachers == {}
    assert store.deletion_log == [deletion_log_prefix(_hash())]


async def test_cancelling_a_delete_returns_to_where_the_teacher_was(
    brain: RouterBrain, store: InMemoryTeacherStore
):
    await _onboard(brain)
    await brain.respond(_say("delete my data"))
    reply = await brain.respond(_say("no"))

    assert reply.text == render("delete_cancelled", "en")
    assert store.teachers[_hash()].state.phase is Phase.IDLE


async def test_different_senders_do_not_share_state(
    brain: RouterBrain, store: InMemoryTeacherStore
):
    await _onboard(brain)
    other = "911111111111"
    await brain.respond(_say("hello", other))

    assert store.teachers[_hash()].state.phase is Phase.IDLE
    assert store.teachers[_hash(other)].state.phase is Phase.ONB_LANG


async def test_the_sender_id_is_never_the_storage_key(
    brain: RouterBrain, store: InMemoryTeacherStore
):
    await brain.respond(_say("hello"))

    assert all(SENDER.encode() not in key for key in store.teachers)
