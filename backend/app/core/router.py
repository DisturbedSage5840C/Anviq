"""Conversation router: a pure state machine, `(TeacherState, text) -> Transition`.

No I/O happens here. The handler returns the next state plus a list of effects (things to say,
rows to write); the caller applies them. That keeps every transition unit-testable offline.
"""

from dataclasses import dataclass, field, replace
from datetime import timedelta
from enum import StrEnum

from app.core.children.malrules.subtraction import TOPIC_REGROUP
from app.core.intents import (
    GlobalIntent,
    MenuIntent,
    classify_global,
    classify_menu,
    looks_like_question,
    parse_grade,
    parse_language,
    parse_yes_no,
)

CONSENT_VERSION = "v2"
MAX_QUESTION_CHARS = 500  # bounds what one question can cost; a teaching question fits easily
INACTIVITY_TIMEOUT = timedelta(minutes=30)
FIRST_REHEARSAL_TOPIC = TOPIC_REGROUP  # a new teacher has no plan yet, so Day 1 starts here


class Phase(StrEnum):
    NEW = "NEW"
    ONB_LANG = "ONB_LANG"
    ONB_GRADE = "ONB_GRADE"
    ONB_CONSENT = "ONB_CONSENT"
    ONB_FIRST_REHEARSAL = "ONB_FIRST_REHEARSAL"  # consented; a first practice is on offer
    IDLE = "IDLE"
    PLAN_TOPIC = "PLAN_TOPIC"  # asked what they teach tomorrow, waiting for the answer
    REFLECT_NOTES = "REFLECT_NOTES"  # asked how the lesson went, waiting for the answer
    ASK_QUESTION = "ASK_QUESTION"  # asked what they want to know, waiting for the question
    REHEARSE_OFFER = "REHEARSE_OFFER"  # shown a plan and asked whether to practise it now
    REHEARSE = "REHEARSE"  # practising on the three children; every message is a turn
    DELETE_CONFIRM = "DELETE_CONFIRM"


@dataclass(frozen=True)
class TeacherState:
    phase: Phase = Phase.NEW
    lang: str | None = None
    grade_band: str | None = None
    consented: bool = False
    resume: Phase | None = None  # where to go back to if a delete is not confirmed


@dataclass(frozen=True)
class Say:
    """Send the copy entry `key`, rendered in the teacher's language."""

    key: str


@dataclass(frozen=True)
class RecordConsent:
    version: str


@dataclass(frozen=True)
class WithdrawConsent:
    """Mark every active consent as revoked; the ledger rows stay as proof of what was agreed."""


@dataclass(frozen=True)
class EraseTeacher:
    """Delete everything stored about this teacher, including the stub row."""


@dataclass(frozen=True)
class OptOutReminders:
    pass


@dataclass(frozen=True)
class ExportData:
    """Reply with a summary of everything stored about this teacher. Reads only, never writes."""


@dataclass(frozen=True)
class MakePlan:
    """Prepare three questions for the lesson the teacher described. Needs the model, so it runs
    after the transaction commits."""

    text: str


@dataclass(frozen=True)
class MakeReflection:
    """Reflect on the lesson the teacher described. Needs the model, so it runs after commit."""

    text: str


@dataclass(frozen=True)
class ShowMirror:
    """Show the Day 1 and latest practice side by side, if the cycle has two sessions to compare."""


@dataclass(frozen=True)
class AskQuestion:
    """Answer a teaching question from the module library. Needs the model, so it runs after
    the transaction commits."""

    text: str


@dataclass(frozen=True)
class StartRehearsal:
    """Begin practising `topic_id`, or the topic of the teacher's latest plan if None. Reads the
    plan and the move they are on, so it runs after commit; if it cannot start, the teacher is put
    back at the menu."""

    topic_id: str | None = None


@dataclass(frozen=True)
class RehearseTurn:
    """The teacher's next question to the children. Needs the model, so it runs after commit."""

    text: str


@dataclass(frozen=True)
class EndRehearsal:
    """Forget the practice in progress."""


Effect = (
    Say
    | RecordConsent
    | WithdrawConsent
    | EraseTeacher
    | OptOutReminders
    | ExportData
    | MakePlan
    | MakeReflection
    | ShowMirror
    | AskQuestion
    | StartRehearsal
    | RehearseTurn
    | EndRehearsal
)


@dataclass(frozen=True)
class Transition:
    state: TeacherState
    effects: tuple[Effect, ...] = field(default_factory=tuple)


def _say(state: TeacherState, *keys: str, extra: tuple[Effect, ...] = ()) -> Transition:
    return Transition(state, (*extra, *(Say(k) for k in keys)))


def handle(state: TeacherState, text: str, *, idle_for: timedelta | None = None) -> Transition:
    """Advance the conversation by one inbound message.

    `idle_for` is how long the teacher was silent before this message (None: first contact).
    """
    if state.phase is Phase.DELETE_CONFIRM and _timed_out(idle_for):
        return _after_delete_timeout(state, text)
    if state.phase is Phase.REHEARSE and _timed_out(idle_for):
        return _after_rehearsal_timeout(state, text)
    if state.phase in _OFFER_PHASES and _timed_out(idle_for):
        # A "yes" a day later answers something else, so the offer lapses silently.
        return handle(replace(state, phase=Phase.IDLE), text)
    if state.phase is Phase.DELETE_CONFIRM:
        answer = parse_yes_no(text)
        if answer is not None:
            return _resolve_delete(state, confirmed=answer)
    intent = classify_global(text)
    if intent is not None and not _ends_the_practice(state, intent):
        return _handle_global(state, intent)
    if state.consented and state.phase in _MENU_PHASES and not _is_question_for_ask(state, text):
        choice = classify_menu(text)
        if choice is not None:
            return _handle_menu(state, choice)
    return _HANDLERS[state.phase](state, text)


def _is_question_for_ask(state: TeacherState, text: str) -> bool:
    """ "How to reflect?" is a question about reflecting, not a request to start Reflect."""
    return state.phase in _ASKING_PHASES and looks_like_question(text)


def _ends_the_practice(state: TeacherState, intent: GlobalIntent) -> bool:
    """Mid-practice "stop" ends the practice, not the reminders: the practice handles it."""
    return state.phase is Phase.REHEARSE and intent is GlobalIntent.STOP


def _timed_out(idle_for: timedelta | None) -> bool:
    return idle_for is not None and idle_for >= INACTIVITY_TIMEOUT


def _after_delete_timeout(state: TeacherState, text: str) -> Transition:
    """A delete question left unanswered lapses: a late "yes" must never erase anything.

    The teacher is put back where they were and the message is handled from there, except at the
    consent question: a stale "yes" answered "delete?", so it must not count as agreeing to the
    notice. There the notice is shown again.
    """
    restored = replace(state, phase=state.resume or Phase.NEW, resume=None)
    if restored.phase is Phase.ONB_CONSENT:
        return _say(restored, "delete_timed_out", "consent_notice")
    carried_on = handle(restored, text)
    return Transition(carried_on.state, (Say("delete_timed_out"), *carried_on.effects))


def _after_rehearsal_timeout(state: TeacherState, text: str) -> Transition:
    """A practice left for half an hour is over: the message is a fresh one, not the next turn."""
    carried_on = handle(replace(state, phase=Phase.IDLE), text)
    effects = (EndRehearsal(), Say("rehearsal_timed_out"), *carried_on.effects)
    return Transition(carried_on.state, effects)


def _handle_global(state: TeacherState, intent: GlobalIntent) -> Transition:
    if intent is GlobalIntent.DELETE:
        return _ask_delete_confirmation(state)
    if intent is GlobalIntent.WITHDRAW_CONSENT:
        return _withdraw_consent(state)
    if intent is GlobalIntent.EXPORT:
        return Transition(state, (ExportData(),))
    if intent is GlobalIntent.STOP:
        return _say(state, "stopped", extra=(OptOutReminders(),))
    return _say(state, "privacy" if intent is GlobalIntent.PRIVACY else "help")


def _handle_menu(state: TeacherState, choice: MenuIntent) -> Transition:
    if choice is MenuIntent.MIRROR:
        return Transition(replace(state, phase=Phase.IDLE), (ShowMirror(),))
    if choice is MenuIntent.PLAN:
        return _say(replace(state, phase=Phase.PLAN_TOPIC), "ask_plan_topic")
    if choice is MenuIntent.ASK:
        return _say(replace(state, phase=Phase.ASK_QUESTION), "ask_question_prompt")
    if choice is MenuIntent.REHEARSE:
        return _start_rehearsal(state)
    return _say(replace(state, phase=Phase.REFLECT_NOTES), "ask_reflect_notes")


def _start_rehearsal(state: TeacherState) -> Transition:
    return Transition(replace(state, phase=Phase.REHEARSE), (StartRehearsal(),))


def _withdraw_consent(state: TeacherState) -> Transition:
    if not state.consented:
        # nothing was ever agreed to, so withdrawing is the same as declining at the prompt
        return _say(TeacherState(), "consent_declined", extra=(EraseTeacher(),))
    asking_again = replace(state, phase=Phase.ONB_CONSENT, consented=False, resume=None)
    return _say(
        asking_again,
        "consent_withdrawn",
        "consent_notice",
        extra=(WithdrawConsent(), OptOutReminders()),
    )


def _ask_delete_confirmation(state: TeacherState) -> Transition:
    if state.phase is Phase.DELETE_CONFIRM:
        return _say(state, "delete_confirm")
    return _say(replace(state, phase=Phase.DELETE_CONFIRM, resume=state.phase), "delete_confirm")


def _resolve_delete(state: TeacherState, *, confirmed: bool) -> Transition:
    if confirmed:
        return _say(TeacherState(), "deleted", extra=(EraseTeacher(),))
    return _say(replace(state, phase=state.resume or Phase.NEW, resume=None), "delete_cancelled")


def _on_new(state: TeacherState, text: str) -> Transition:
    return _say(replace(state, phase=Phase.ONB_LANG), "welcome", "ask_language")


def _on_language(state: TeacherState, text: str) -> Transition:
    lang = parse_language(text)
    if lang is None:
        return _say(state, "language_retry")
    return _say(replace(state, lang=lang, phase=Phase.ONB_GRADE), "ask_grade")


def _on_grade(state: TeacherState, text: str) -> Transition:
    grade = parse_grade(text)
    if grade is None:
        return _say(state, "grade_retry")
    return _say(replace(state, grade_band=grade, phase=Phase.ONB_CONSENT), "consent_notice")


def _on_consent(state: TeacherState, text: str) -> Transition:
    answer = parse_yes_no(text)
    if answer is None:
        return _say(state, "consent_retry")
    if not answer:
        return _say(TeacherState(), "consent_declined", extra=(EraseTeacher(),))
    granted = replace(state, consented=True, phase=Phase.ONB_FIRST_REHEARSAL)
    return _say(
        granted, "consent_thanks", "first_rehearsal_offer", extra=(RecordConsent(CONSENT_VERSION),)
    )


def _on_first_rehearsal(state: TeacherState, text: str) -> Transition:
    answer = parse_yes_no(text)
    idle = replace(state, phase=Phase.IDLE)
    if answer and state.consented:
        return Transition(
            replace(state, phase=Phase.REHEARSE), (StartRehearsal(FIRST_REHEARSAL_TOPIC),)
        )
    if answer is None:
        return _on_idle(idle, text)  # a question is still answered
    return _say(idle, "menu")


def _on_idle(state: TeacherState, text: str) -> Transition:
    if state.consented and looks_like_question(text):
        return Transition(state, (AskQuestion(text[:MAX_QUESTION_CHARS]),))
    return _say(state, "menu")


def _on_plan_topic(state: TeacherState, text: str) -> Transition:
    return Transition(replace(state, phase=Phase.IDLE), (MakePlan(text),))


def _on_reflect_notes(state: TeacherState, text: str) -> Transition:
    return Transition(replace(state, phase=Phase.IDLE), (MakeReflection(text),))


def _on_ask_question(state: TeacherState, text: str) -> Transition:
    idle = replace(state, phase=Phase.IDLE)
    if not state.consented:
        return _say(idle, "menu")
    return Transition(idle, (AskQuestion(text[:MAX_QUESTION_CHARS]),))


def _on_rehearse_offer(state: TeacherState, text: str) -> Transition:
    answer = parse_yes_no(text)
    if answer:
        return _start_rehearsal(state)
    if answer is None:
        return _on_idle(replace(state, phase=Phase.IDLE), text)
    return _say(replace(state, phase=Phase.IDLE), "menu")


def _on_rehearse(state: TeacherState, text: str) -> Transition:
    if not state.consented:
        return _say(replace(state, phase=Phase.IDLE), "menu", extra=(EndRehearsal(),))
    return Transition(state, (RehearseTurn(text[:MAX_QUESTION_CHARS]),))


def _on_delete_confirm(state: TeacherState, text: str) -> Transition:
    return _say(state, "delete_confirm")


_HANDLERS = {
    Phase.NEW: _on_new,
    Phase.ONB_LANG: _on_language,
    Phase.ONB_GRADE: _on_grade,
    Phase.ONB_CONSENT: _on_consent,
    Phase.ONB_FIRST_REHEARSAL: _on_first_rehearsal,
    Phase.IDLE: _on_idle,
    Phase.PLAN_TOPIC: _on_plan_topic,
    Phase.REFLECT_NOTES: _on_reflect_notes,
    Phase.ASK_QUESTION: _on_ask_question,
    Phase.REHEARSE_OFFER: _on_rehearse_offer,
    Phase.REHEARSE: _on_rehearse,
    Phase.DELETE_CONFIRM: _on_delete_confirm,
}

# REHEARSE is not here: while practising, "plan" is something to say to a child, not a command.
_OFFER_PHASES = frozenset({Phase.REHEARSE_OFFER, Phase.ONB_FIRST_REHEARSAL})
_MENU_PHASES = frozenset(
    {Phase.IDLE, Phase.PLAN_TOPIC, Phase.REFLECT_NOTES, Phase.ASK_QUESTION} | _OFFER_PHASES
)
_ASKING_PHASES = frozenset({Phase.IDLE, Phase.ASK_QUESTION} | _OFFER_PHASES)
