"""The Brain that runs the conversation router against persistent teacher state."""

import hashlib
import logging
from dataclasses import replace

from app.content.copy import render
from app.core.daily_loop import DailyLoop, LoopReply
from app.core.dialogue import Reply, Utterance
from app.core.router import (
    EraseTeacher,
    ExportData,
    MakePlan,
    MakeReflection,
    OptOutReminders,
    Phase,
    RecordConsent,
    Say,
    ShowMirror,
    Transition,
    WithdrawConsent,
    handle,
)
from app.core.teacher_store import TeacherExport, TeacherSession, TeacherStore
from app.privacy.crypto import phone_hash
from app.privacy.export import render_export

logger = logging.getLogger(__name__)

PARAGRAPH_BREAK = "\n\n"
UNKNOWN_LANG_TTS = "hi"


def consent_text_sha256(lang: str | None) -> str:
    """Digest of the exact consent text the teacher was shown, for the consent ledger."""
    return hashlib.sha256(render("consent_notice", lang).encode("utf-8")).hexdigest()


class RouterBrain:
    """`loop` runs Plan, Reflect and Mirror. Without one they answer "unavailable", not silence."""

    def __init__(self, store: TeacherStore, pepper: bytes, loop: DailyLoop | None = None) -> None:
        self._store = store
        self._pepper = pepper
        self._loop = loop

    async def respond(self, utterance: Utterance) -> Reply:
        key = phone_hash(self._pepper, utterance.sender_wa_id)
        async with self._store.locked(key) as session:
            before = await session.load()
            idle_for = await session.idle_for()
            transition = handle(before, utterance.text, idle_for=idle_for)
            await session.save(transition.state, utterance.sender_wa_id)
            exports = await _apply_effects(session, transition)
        # After an erase the new state has forgotten the language, but the goodbye should not.
        lang = transition.state.lang or before.lang
        reply = _compose(transition, lang, exports)
        looped = await self._run_loop_effects(key, utterance.sender_wa_id, lang, transition)
        if not looped:
            return reply
        text = PARAGRAPH_BREAK.join(
            part for part in (reply.text, *(r.text for r in looped)) if part
        )
        return replace(reply, text=text, speak=True, lang=lang or UNKNOWN_LANG_TTS)

    async def _run_loop_effects(
        self, key: bytes, wa_id: str, lang: str | None, transition: Transition
    ) -> list[LoopReply]:
        """Plan, Reflect and Mirror call the model, so they run after the database commit."""
        replies = [
            await self._run_one(key, lang or UNKNOWN_LANG_TTS, effect)
            for effect in transition.effects
            if isinstance(effect, MakePlan | MakeReflection | ShowMirror)
        ]
        stay_in = next((r.stay_in for r in replies if r.stay_in is not None), None)
        if stay_in is not None:
            await self._return_to(key, wa_id, stay_in)
        return replies

    async def _run_one(
        self, key: bytes, lang: str, effect: MakePlan | MakeReflection | ShowMirror
    ) -> LoopReply:
        unavailable = _UNAVAILABLE[type(effect)]
        if self._loop is None:
            return LoopReply(render(unavailable, lang))
        try:
            match effect:
                case MakePlan(text):
                    return await self._loop.plan(key, lang, text)
                case MakeReflection(text):
                    return await self._loop.reflect(key, lang, text)
                case ShowMirror():
                    return await self._loop.mirror(key, lang)
        except Exception as exc:  # the teacher gets a kind message; the details never carry content
            logger.error("daily loop step failed: %s", type(exc).__name__)
            return LoopReply(render(unavailable, lang))

    async def _return_to(self, key: bytes, wa_id: str, phase: Phase) -> None:
        """The loop asked something back, so the next message belongs to that prompt."""
        async with self._store.locked(key) as session:
            state = await session.load()
            if state.phase is Phase.IDLE:
                await session.save(replace(state, phase=phase), wa_id)


_UNAVAILABLE = {
    MakePlan: "plan_unavailable",
    MakeReflection: "reflect_unavailable",
    ShowMirror: "mirror_unavailable",
}


async def _apply_effects(
    session: TeacherSession, transition: Transition
) -> list[TeacherExport | None]:
    """Run the writes in order. Returns one entry per ExportData effect (None: nothing stored)."""
    exports: list[TeacherExport | None] = []
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
            case ExportData():
                exports.append(await session.export())
            case Say() | MakePlan() | MakeReflection() | ShowMirror():
                pass  # spoken or run after the transaction commits, not stored
    return exports


def _compose(
    transition: Transition, lang: str | None, exports: list[TeacherExport | None]
) -> Reply:
    keys = [effect.key for effect in transition.effects if isinstance(effect, Say)]
    paragraphs = [render(key, lang) for key in keys]
    paragraphs.extend(
        render_export(found, lang) if found else render("export_nothing", lang) for found in exports
    )
    text = PARAGRAPH_BREAK.join(paragraphs)
    return Reply(text=text, lang=lang or UNKNOWN_LANG_TTS, speak=lang is not None)
