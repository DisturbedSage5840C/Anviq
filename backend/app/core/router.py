"""Conversation router: a pure state machine, `(TeacherState, text) -> Transition`.

No I/O happens here. The handler returns the next state plus a list of effects (things to say,
rows to write); the caller applies them. That keeps every transition unit-testable offline.
"""

from dataclasses import dataclass, field, replace
from datetime import timedelta
from enum import StrEnum

from app.core.intents import (
    GlobalIntent,
    classify_global,
    parse_grade,
    parse_language,
    parse_yes_no,
)

CONSENT_VERSION = "v2"
INACTIVITY_TIMEOUT = timedelta(minutes=30)


class Phase(StrEnum):
    NEW = "NEW"
    ONB_LANG = "ONB_LANG"
    ONB_GRADE = "ONB_GRADE"
    ONB_CONSENT = "ONB_CONSENT"
    IDLE = "IDLE"
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


Effect = Say | RecordConsent | WithdrawConsent | EraseTeacher | OptOutReminders | ExportData


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
    if state.phase is Phase.DELETE_CONFIRM:
        answer = parse_yes_no(text)
        if answer is not None:
            return _resolve_delete(state, confirmed=answer)
    intent = classify_global(text)
    if intent is not None:
        return _handle_global(state, intent)
    return _HANDLERS[state.phase](state, text)


def _timed_out(idle_for: timedelta | None) -> bool:
    return idle_for is not None and idle_for >= INACTIVITY_TIMEOUT


def _after_delete_timeout(state: TeacherState, text: str) -> Transition:
    """A delete question left unanswered lapses: a late "yes" must never erase anything.

    The teacher is put back where they were and the message is handled from there.
    """
    restored = replace(state, phase=state.resume or Phase.NEW, resume=None)
    carried_on = handle(restored, text)
    return Transition(carried_on.state, (Say("delete_timed_out"), *carried_on.effects))


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
    granted = replace(state, consented=True, phase=Phase.IDLE)
    return _say(granted, "consent_thanks", "menu", extra=(RecordConsent(CONSENT_VERSION),))


def _on_idle(state: TeacherState, text: str) -> Transition:
    return _say(state, "menu")


def _on_delete_confirm(state: TeacherState, text: str) -> Transition:
    return _say(state, "delete_confirm")


_HANDLERS = {
    Phase.NEW: _on_new,
    Phase.ONB_LANG: _on_language,
    Phase.ONB_GRADE: _on_grade,
    Phase.ONB_CONSENT: _on_consent,
    Phase.IDLE: _on_idle,
    Phase.DELETE_CONFIRM: _on_delete_confirm,
}
