"""The Brain that runs the conversation router against persistent teacher state."""

import hashlib
import logging
from dataclasses import replace

from app.content.copy import render
from app.core.daily_loop import DailyLoop, LoopReply
from app.core.dialogue import Reply, Utterance
from app.core.rehearsal_flow import RehearsalReply, Rehearsals
from app.core.router import (
    AskQuestion,
    EndRehearsal,
    EraseTeacher,
    ExportData,
    MakePlan,
    MakeReflection,
    OptOutReminders,
    Phase,
    RecordConsent,
    RehearseTurn,
    Say,
    ShowMirror,
    StartRehearsal,
    Transition,
    WithdrawConsent,
    handle,
)
from app.core.teacher_store import (
    RehearsalSlot,
    TeacherExport,
    TeacherSession,
    TeacherStore,
)
from app.privacy.crypto import phone_hash
from app.privacy.export import render_export

logger = logging.getLogger(__name__)

LoopEffect = MakePlan | MakeReflection | ShowMirror | AskQuestion
_LOOP_EFFECTS = (MakePlan, MakeReflection, ShowMirror, AskQuestion)
RehearsalEffect = StartRehearsal | RehearseTurn
_REHEARSAL_EFFECTS = (StartRehearsal, RehearseTurn)

PARAGRAPH_BREAK = "\n\n"
UNKNOWN_LANG_TTS = "hi"


def consent_text_sha256(lang: str | None) -> str:
    """Digest of the exact consent text the teacher was shown, for the consent ledger."""
    return hashlib.sha256(render("consent_notice", lang).encode("utf-8")).hexdigest()


class RouterBrain:
    """`loop` runs Plan, Reflect, Ask and Mirror; `rehearsal` runs the practice with the children.

    Without them those steps say "unavailable".
    """

    def __init__(
        self,
        store: TeacherStore,
        pepper: bytes,
        loop: DailyLoop | None = None,
        rehearsal: Rehearsals | None = None,
    ) -> None:
        self._store = store
        self._pepper = pepper
        self._loop = loop
        self._rehearsal = rehearsal

    async def respond(self, utterance: Utterance) -> Reply:
        key = phone_hash(self._pepper, utterance.sender_wa_id)
        slot = RehearsalSlot()
        async with self._store.locked(key) as session:
            before = await session.load()
            idle_for = await session.idle_for()
            transition = handle(before, utterance.text, idle_for=idle_for)
            if any(isinstance(effect, _REHEARSAL_EFFECTS) for effect in transition.effects):
                slot = await session.load_rehearsal()
            await session.save(transition.state, utterance.sender_wa_id)
            exports = await _apply_effects(session, transition)
        # After an erase the new state has forgotten the language, but the goodbye should not.
        lang = transition.state.lang or before.lang
        reply = _compose(transition, lang, exports)
        wa_id = utterance.sender_wa_id
        spoken = await self._run_loop_effects(key, wa_id, lang, transition)
        spoken += await self._run_rehearsal(key, wa_id, lang, transition, slot)
        if not spoken:
            return reply
        text = PARAGRAPH_BREAK.join(part for part in (reply.text, *spoken) if part)
        return replace(reply, text=text, speak=True, lang=lang or UNKNOWN_LANG_TTS)

    async def _run_loop_effects(
        self, key: bytes, wa_id: str, lang: str | None, transition: Transition
    ) -> list[str]:
        """Plan, Reflect, Ask and Mirror call the model, so they run after the database commit."""
        replies = [
            await self._run_one(key, lang or UNKNOWN_LANG_TTS, effect)
            for effect in transition.effects
            if isinstance(effect, _LOOP_EFFECTS)
        ]
        await self._settle_loop(key, wa_id, replies)
        return [reply.text for reply in replies]

    async def _run_one(self, key: bytes, lang: str, effect: LoopEffect) -> LoopReply:
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
                case AskQuestion(text):
                    return await self._loop.ask(key, lang, text)
        except Exception as exc:  # the teacher gets a kind message; the details never carry content
            logger.error("daily loop step failed: %s", type(exc).__name__)
            return LoopReply(render(unavailable, lang))

    async def _settle_loop(self, key: bytes, wa_id: str, replies: list[LoopReply]) -> None:
        """Remember which plan the teacher can practise, and where the next message belongs."""
        stay_in = next((r.stay_in for r in replies if r.stay_in is not None), None)
        topic_id = next((r.topic_id for r in replies if r.topic_id is not None), None)
        if stay_in is None and topic_id is None:
            return
        async with self._store.locked(key) as session:
            state = await session.load()
            if state.phase is not Phase.IDLE:  # the teacher moved on, or withdrew, meanwhile
                return
            if topic_id is not None:
                await session.save_last_topic(topic_id)
            if stay_in is not None:
                await session.save(replace(state, phase=stay_in), wa_id)

    async def _run_rehearsal(
        self,
        key: bytes,
        wa_id: str,
        lang: str | None,
        transition: Transition,
        slot: RehearsalSlot,
    ) -> list[str]:
        """The children answer through the model, so this too runs after the commit."""
        effect = next((e for e in transition.effects if isinstance(e, _REHEARSAL_EFFECTS)), None)
        if effect is None:
            return []
        reply = await self._rehearse(key, lang or UNKNOWN_LANG_TTS, effect, slot)
        if not await self._keep_rehearsal(key, wa_id, slot.rehearsal_json, reply):
            # A newer message was answered while this one was with the model; its answer stands.
            return [render("rehearsal_turn_failed", lang or UNKNOWN_LANG_TTS)]
        return [reply.text]

    async def _rehearse(
        self, key: bytes, lang: str, effect: RehearsalEffect, slot: RehearsalSlot
    ) -> RehearsalReply:
        if self._rehearsal is not None:
            try:
                if isinstance(effect, StartRehearsal):
                    return await self._rehearsal.begin(key, lang, effect.topic_id or slot.topic_id)
                return await self._rehearsal.turn(lang, effect.text, slot.rehearsal_json)
            except Exception as exc:  # the teacher is told; the type is the only safe detail
                logger.error("rehearsal step failed: %s", type(exc).__name__)
        return RehearsalReply(render("rehearsal_unavailable", lang), None, True)

    async def _keep_rehearsal(
        self, key: bytes, wa_id: str, expected: str | None, reply: RehearsalReply
    ) -> bool:
        """Save the practice, or end it, unless it moved on while the model was thinking.

        A teacher who left the practice meanwhile leaves nothing behind. False means another
        turn of this practice was saved first, so this one is dropped rather than rewinding it.
        """
        async with self._store.locked(key) as session:
            state = await session.load()
            if state.phase is not Phase.REHEARSE:
                return True
            if not await session.replace_rehearsal(expected, reply.rehearsal_json):
                return False
            if reply.finished:
                await session.save(replace(state, phase=Phase.IDLE), wa_id)
            return True


_UNAVAILABLE = {
    MakePlan: "plan_unavailable",
    MakeReflection: "reflect_unavailable",
    ShowMirror: "mirror_unavailable",
    AskQuestion: "ask_unavailable",
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
            case EndRehearsal():
                await session.save_rehearsal(None)
            case ExportData():
                exports.append(await session.export())
            case (
                Say()
                | MakePlan()
                | MakeReflection()
                | ShowMirror()
                | AskQuestion()
                | StartRehearsal()
                | RehearseTurn()
            ):
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
