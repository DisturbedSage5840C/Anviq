"""The Brain that runs the conversation router against persistent teacher state."""

import hashlib

from app.content.copy import render
from app.core.dialogue import Reply, Utterance
from app.core.router import (
    EraseTeacher,
    OptOutReminders,
    RecordConsent,
    Say,
    Transition,
    WithdrawConsent,
    handle,
)
from app.core.teacher_store import TeacherSession, TeacherStore
from app.privacy.crypto import phone_hash

PARAGRAPH_BREAK = "\n\n"
UNKNOWN_LANG_TTS = "hi"


def consent_text_sha256(lang: str | None) -> str:
    """Digest of the exact consent text the teacher was shown, for the consent ledger."""
    return hashlib.sha256(render("consent_notice", lang).encode("utf-8")).hexdigest()


class RouterBrain:
    def __init__(self, store: TeacherStore, pepper: bytes) -> None:
        self._store = store
        self._pepper = pepper

    async def respond(self, utterance: Utterance) -> Reply:
        key = phone_hash(self._pepper, utterance.sender_wa_id)
        async with self._store.locked(key) as session:
            before = await session.load()
            transition = handle(before, utterance.text)
            await session.save(transition.state, utterance.sender_wa_id)
            await _apply_effects(session, transition)
        # After an erase the new state has forgotten the language, but the goodbye should not.
        lang = transition.state.lang or before.lang
        return _compose(transition, lang)


async def _apply_effects(session: TeacherSession, transition: Transition) -> None:
    for effect in transition.effects:
        match effect:
            case RecordConsent(version):
                await session.record_consent(version, consent_text_sha256(transition.state.lang))
            case WithdrawConsent():
                await session.withdraw_consent()
            case EraseTeacher():
                await session.erase()
            case OptOutReminders():
                await session.opt_out_reminders()
            case Say():
                pass  # spoken after the transaction commits, not stored


def _compose(transition: Transition, lang: str | None) -> Reply:
    keys = [effect.key for effect in transition.effects if isinstance(effect, Say)]
    text = PARAGRAPH_BREAK.join(render(key, lang) for key in keys)
    return Reply(text=text, lang=lang or UNKNOWN_LANG_TTS, speak=lang is not None)
