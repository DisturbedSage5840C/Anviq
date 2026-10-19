import hashlib
from datetime import UTC, datetime, timedelta

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


async def test_withdrawing_consent_revokes_the_ledger_row_and_shows_the_notice_again(
    brain: RouterBrain, store: InMemoryTeacherStore
):
    await _onboard(brain)

    reply = await brain.respond(_say("withdraw my consent"))

    stored = store.teachers[_hash()]
    assert [c.revoked for c in stored.consents] == [True]
    assert stored.state.phase is Phase.ONB_CONSENT
    assert stored.reminders_opt_in is False
    assert reply.text == f"{render('consent_withdrawn', 'en')}\n\n{render('consent_notice', 'en')}"


async def test_export_sends_the_stored_profile_in_the_teachers_language(brain: RouterBrain):
    await _onboard(brain)

    reply = await brain.respond(_say("send me my data"))

    assert reply.text.startswith(render("export_header", "en"))
    assert f"{render('export_grade', 'en')}: 2" in reply.text
    assert f"{render('export_consent', 'en')}: {CONSENT_VERSION}" in reply.text
    assert reply.lang == "en"


async def test_export_follows_a_hindi_speaker_into_hindi(brain: RouterBrain):
    await _onboard(brain, "Hindi")

    reply = await brain.respond(_say("मेरा डेटा भेजो"))

    assert reply.text.startswith(render("export_header", "hi"))


async def test_export_never_includes_the_whatsapp_number(brain: RouterBrain):
    await _onboard(brain)

    reply = await brain.respond(_say("send me my data"))

    assert SENDER not in reply.text


def _contents(store: InMemoryTeacherStore) -> dict[bytes, tuple]:
    """What is stored about each teacher, ignoring when they last wrote."""
    return {
        key: (t.state, t.wa_id, t.consents, t.reminders_opt_in) for key, t in store.teachers.items()
    }


async def test_export_changes_nothing_that_is_stored(
    brain: RouterBrain, store: InMemoryTeacherStore
):
    await _onboard(brain)
    before = _contents(store)

    await brain.respond(_say("send me my data"))

    assert _contents(store) == before


async def test_export_for_a_stranger_says_nothing_is_stored(brain: RouterBrain):
    reply = await brain.respond(_say("send me my data"))

    assert reply.text == render("export_nothing", None)
    assert reply.speak is False


async def test_exporting_after_withdrawing_shows_the_consent_as_withdrawn(brain: RouterBrain):
    await _onboard(brain)
    await brain.respond(_say("withdraw my consent"))

    reply = await brain.respond(_say("send me my data"))

    assert render("export_revoked", "en") in reply.text


async def test_saying_yes_after_withdrawing_starts_a_new_consent(
    brain: RouterBrain, store: InMemoryTeacherStore
):
    await _onboard(brain)
    await brain.respond(_say("withdraw my consent"))

    await brain.respond(_say("yes"))

    stored = store.teachers[_hash()]
    assert [c.revoked for c in stored.consents] == [True, False]
    assert stored.state.phase is Phase.IDLE


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, by: timedelta) -> None:
        self.now += by


async def test_a_yes_sent_after_the_timeout_does_not_delete_the_teacher():
    clock = _Clock()
    store = InMemoryTeacherStore(clock=clock)
    brain = RouterBrain(store, PEPPER)
    await _onboard(brain)
    await brain.respond(_say("delete my data"))

    clock.advance(timedelta(minutes=31))
    reply = await brain.respond(_say("yes"))

    assert _hash() in store.teachers
    assert store.deletion_log == []
    assert render("delete_timed_out", "en") in reply.text


async def test_a_yes_sent_within_the_timeout_still_deletes_the_teacher():
    clock = _Clock()
    store = InMemoryTeacherStore(clock=clock)
    brain = RouterBrain(store, PEPPER)
    await _onboard(brain)
    await brain.respond(_say("delete my data"))

    clock.advance(timedelta(minutes=29))
    await brain.respond(_say("yes"))

    assert _hash() not in store.teachers
