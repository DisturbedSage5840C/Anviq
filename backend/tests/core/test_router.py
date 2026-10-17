import pytest

from app.core.router import (
    CONSENT_VERSION,
    EraseTeacher,
    OptOutReminders,
    Phase,
    RecordConsent,
    Say,
    TeacherState,
    handle,
)


def _keys(transition) -> list[str]:
    return [e.key for e in transition.effects if isinstance(e, Say)]


def _walk(*texts: str, start: TeacherState | None = None):
    state = start or TeacherState()
    last = None
    for text in texts:
        last = handle(state, text)
        state = last.state
    return last


def test_first_message_gets_welcome_and_asks_language():
    t = handle(TeacherState(), "Namaste")
    assert t.state.phase is Phase.ONB_LANG
    assert _keys(t) == ["welcome", "ask_language"]


def test_language_answer_is_stored_and_grade_is_asked():
    t = _walk("Namaste", "हिंदी")
    assert t.state.lang == "hi"
    assert t.state.phase is Phase.ONB_GRADE
    assert _keys(t) == ["ask_grade"]


def test_unrecognised_language_is_asked_again_without_advancing():
    t = _walk("Namaste", "French")
    assert t.state.phase is Phase.ONB_LANG
    assert _keys(t) == ["language_retry"]


def test_grade_answer_is_stored_and_consent_notice_is_shown():
    t = _walk("Namaste", "English", "2 और 3 मिली-जुली")
    assert t.state.grade_band == "multi"
    assert t.state.phase is Phase.ONB_CONSENT
    assert _keys(t) == ["consent_notice"]


def test_unrecognised_grade_is_asked_again():
    t = _walk("Namaste", "Hindi", "7")
    assert t.state.phase is Phase.ONB_GRADE
    assert _keys(t) == ["grade_retry"]


def test_nothing_is_recorded_before_consent():
    t = _walk("Namaste", "Hindi", "2")
    assert not any(isinstance(e, RecordConsent) for e in t.effects)
    assert t.state.consented is False


def test_consent_yes_records_the_versioned_consent_and_opens_the_menu():
    t = _walk("Namaste", "Hindi", "2", "हाँ")
    assert RecordConsent(version=CONSENT_VERSION) in t.effects
    assert t.state.consented is True
    assert t.state.phase is Phase.IDLE
    assert _keys(t) == ["consent_thanks", "menu"]


def test_consent_no_erases_the_stub_and_starts_over():
    t = _walk("Namaste", "Hindi", "2", "नहीं")
    assert EraseTeacher() in t.effects
    assert t.state == TeacherState()
    assert _keys(t) == ["consent_declined"]


def test_unclear_consent_answer_is_asked_again():
    t = _walk("Namaste", "Hindi", "2", "शायद")
    assert t.state.phase is Phase.ONB_CONSENT
    assert _keys(t) == ["consent_retry"]


def test_idle_replies_with_the_menu_until_modules_exist():
    start = TeacherState(phase=Phase.IDLE, lang="hi", grade_band="2", consented=True)
    t = handle(start, "कुछ भी")
    assert t.state == start
    assert _keys(t) == ["menu"]


def test_delete_asks_for_confirmation_and_remembers_where_to_resume():
    start = TeacherState(phase=Phase.IDLE, lang="hi", grade_band="2", consented=True)
    t = handle(start, "मेरा डेटा मिटाओ")
    assert t.state.phase is Phase.DELETE_CONFIRM
    assert t.state.resume is Phase.IDLE
    assert _keys(t) == ["delete_confirm"]
    assert not any(isinstance(e, EraseTeacher) for e in t.effects)


def test_confirmed_delete_erases_everything_and_resets_to_new():
    start = TeacherState(phase=Phase.IDLE, lang="hi", grade_band="2", consented=True)
    t = _walk("Delete my data", "हाँ, मिटाओ", start=start)
    assert EraseTeacher() in t.effects
    assert t.state == TeacherState()
    assert _keys(t) == ["deleted"]


def test_declined_delete_returns_to_the_previous_phase():
    start = TeacherState(phase=Phase.IDLE, lang="hi", grade_band="2", consented=True)
    t = _walk("Delete my data", "नहीं", start=start)
    assert t.state == start
    assert _keys(t) == ["delete_cancelled"]


def test_unclear_answer_to_delete_confirmation_asks_again_and_keeps_resume():
    start = TeacherState(phase=Phase.ONB_GRADE, lang="en")
    t = _walk("delete my data", "umm", start=start)
    assert t.state.phase is Phase.DELETE_CONFIRM
    assert t.state.resume is Phase.ONB_GRADE
    assert _keys(t) == ["delete_confirm"]


def test_repeating_the_delete_command_does_not_lose_the_resume_phase():
    start = TeacherState(phase=Phase.IDLE, lang="hi", consented=True)
    t = _walk("delete my data", "delete my data", start=start)
    assert t.state.resume is Phase.IDLE


def test_stop_opts_out_of_reminders_without_changing_phase():
    start = TeacherState(phase=Phase.IDLE, lang="hi", consented=True)
    t = handle(start, "बंद करो")
    assert OptOutReminders() in t.effects
    assert t.state == start
    assert _keys(t) == ["stopped"]


@pytest.mark.parametrize(("text", "key"), [("who sees this", "privacy"), ("मदद", "help")])
def test_privacy_and_help_answer_in_place_in_any_phase(text: str, key: str):
    start = TeacherState(phase=Phase.ONB_CONSENT, lang="hi", grade_band="2")
    t = handle(start, text)
    assert t.state == start
    assert _keys(t) == [key]


def test_a_long_sentence_containing_stop_is_not_an_opt_out():
    start = TeacherState(phase=Phase.IDLE, lang="en", consented=True)
    t = handle(start, "please do not stop the lesson plan now")
    assert not any(isinstance(e, OptOutReminders) for e in t.effects)


def test_state_is_never_mutated():
    start = TeacherState()
    handle(start, "Namaste")
    assert start == TeacherState()
