from dataclasses import replace
from datetime import timedelta

import pytest

from app.core.router import (
    CONSENT_VERSION,
    INACTIVITY_TIMEOUT,
    EraseTeacher,
    ExportData,
    MakePlan,
    MakeReflection,
    OptOutReminders,
    Phase,
    RecordConsent,
    Say,
    ShowMirror,
    TeacherState,
    WithdrawConsent,
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


ENROLLED = TeacherState(phase=Phase.IDLE, lang="en", grade_band="2", consented=True)


def test_withdrawing_consent_revokes_it_stops_reminders_and_asks_again():
    t = handle(ENROLLED, "withdraw consent")

    assert t.state == TeacherState(Phase.ONB_CONSENT, lang="en", grade_band="2", consented=False)
    assert t.effects[:2] == (WithdrawConsent(), OptOutReminders())
    assert _keys(t) == ["consent_withdrawn", "consent_notice"]


def test_consenting_again_after_a_withdrawal_records_a_fresh_consent():
    t = _walk("withdraw consent", "yes", start=ENROLLED)

    assert t.state == ENROLLED
    assert RecordConsent(version=CONSENT_VERSION) in t.effects


def test_withdrawing_while_a_delete_is_pending_drops_the_pending_delete():
    pending = TeacherState(Phase.DELETE_CONFIRM, "hi", "2", consented=True, resume=Phase.IDLE)

    t = handle(pending, "सहमति वापस")

    assert t.state.phase is Phase.ONB_CONSENT
    assert t.state.resume is None


def test_withdrawing_before_ever_consenting_is_the_same_as_declining():
    start = TeacherState(Phase.ONB_CONSENT, lang="en", grade_band="2")

    t = handle(start, "withdraw consent")

    assert t.state == TeacherState()
    assert EraseTeacher() in t.effects
    assert _keys(t) == ["consent_declined"]


@pytest.mark.parametrize("text", ["send me my data", "मेरा डेटा भेजो"])
def test_asking_for_a_copy_of_the_data_requests_an_export_and_changes_nothing(text: str):
    t = handle(ENROLLED, text)

    assert t.state == ENROLLED
    assert t.effects == (ExportData(),)


def test_export_is_available_mid_onboarding_without_losing_the_place():
    start = TeacherState(Phase.ONB_GRADE, lang="hi")

    t = handle(start, "send me my data")

    assert t.state == start
    assert ExportData() in t.effects


def test_export_does_not_delete_anything():
    t = handle(ENROLLED, "send me my data")

    assert not any(isinstance(e, EraseTeacher) for e in t.effects)


PENDING_DELETE = TeacherState(
    phase=Phase.DELETE_CONFIRM, lang="hi", grade_band="2", consented=True, resume=Phase.IDLE
)
RESTORED = TeacherState(phase=Phase.IDLE, lang="hi", grade_band="2", consented=True)


def test_stale_yes_does_not_confirm_a_delete_asked_half_an_hour_ago():
    t = handle(PENDING_DELETE, "हाँ, मिटाओ", idle_for=INACTIVITY_TIMEOUT)
    assert not any(isinstance(e, EraseTeacher) for e in t.effects)
    assert t.state == RESTORED
    assert _keys(t) == ["delete_timed_out", "menu"]


def test_yes_just_inside_the_timeout_still_confirms_the_delete():
    t = handle(PENDING_DELETE, "हाँ, मिटाओ", idle_for=INACTIVITY_TIMEOUT - timedelta(seconds=1))
    assert EraseTeacher() in t.effects


def test_asking_again_after_the_timeout_starts_a_fresh_confirmation():
    t = handle(PENDING_DELETE, "delete my data", idle_for=INACTIVITY_TIMEOUT)
    assert t.state.phase is Phase.DELETE_CONFIRM
    assert t.state.resume is Phase.IDLE
    assert _keys(t) == ["delete_timed_out", "delete_confirm"]


def test_a_stale_yes_is_never_taken_as_consent_to_the_privacy_notice():
    # the teacher asked to delete while the consent question was open; their late "yes" answered
    # "delete?", so it must not be read as agreeing to the notice
    asked_mid_consent = TeacherState(
        phase=Phase.DELETE_CONFIRM, lang="en", grade_band="2", resume=Phase.ONB_CONSENT
    )
    t = handle(asked_mid_consent, "yes", idle_for=INACTIVITY_TIMEOUT)

    assert not any(isinstance(e, RecordConsent) for e in t.effects)
    assert not any(isinstance(e, EraseTeacher) for e in t.effects)
    assert t.state.phase is Phase.ONB_CONSENT
    assert t.state.consented is False
    assert _keys(t) == ["delete_timed_out", "consent_notice"]


@pytest.mark.parametrize("phase", [Phase.ONB_LANG, Phase.ONB_GRADE, Phase.IDLE])
def test_idle_teachers_outside_a_delete_prompt_carry_on_where_they_were(phase: Phase):
    start = TeacherState(phase=phase, lang="en", grade_band="1", consented=True)
    quiet = handle(start, "umm", idle_for=timedelta(days=3))
    assert quiet == handle(start, "umm")


IDLE_TEACHER = TeacherState(phase=Phase.IDLE, lang="en", grade_band="2", consented=True)


def test_asking_for_a_plan_waits_for_the_topic():
    t = handle(IDLE_TEACHER, "plan")
    assert t.state.phase is Phase.PLAN_TOPIC
    assert _keys(t) == ["ask_plan_topic"]


def test_the_topic_is_handed_on_as_a_plan_request_and_the_teacher_is_idle_again():
    t = handle(replace(IDLE_TEACHER, phase=Phase.PLAN_TOPIC), "fractions tomorrow, Gr 3")
    assert t.state.phase is Phase.IDLE
    assert t.effects == (MakePlan("fractions tomorrow, Gr 3"),)


def test_asking_to_reflect_waits_for_the_notes():
    t = handle(IDLE_TEACHER, "reflect")
    assert t.state.phase is Phase.REFLECT_NOTES
    assert _keys(t) == ["ask_reflect_notes"]


def test_the_notes_are_handed_on_as_a_reflection_request():
    t = handle(replace(IDLE_TEACHER, phase=Phase.REFLECT_NOTES), "the children enjoyed it")
    assert t.state.phase is Phase.IDLE
    assert t.effects == (MakeReflection("the children enjoyed it"),)


def test_the_mirror_is_shown_at_once_without_leaving_idle():
    t = handle(IDLE_TEACHER, "mirror")
    assert t.state.phase is Phase.IDLE
    assert t.effects == (ShowMirror(),)


def test_a_menu_word_while_waiting_for_a_topic_switches_task():
    t = handle(replace(IDLE_TEACHER, phase=Phase.PLAN_TOPIC), "reflect")
    assert t.state.phase is Phase.REFLECT_NOTES


def test_a_menu_word_is_ignored_before_consent_is_given():
    waiting = TeacherState(phase=Phase.ONB_CONSENT, lang="en", grade_band="2")
    assert handle(waiting, "plan").state.phase is Phase.ONB_CONSENT


def test_delete_while_waiting_for_a_topic_returns_to_the_topic_prompt_if_cancelled():
    waiting = replace(IDLE_TEACHER, phase=Phase.PLAN_TOPIC)
    asked = handle(waiting, "delete my data")
    assert asked.state.resume is Phase.PLAN_TOPIC
    assert handle(asked.state, "no").state.phase is Phase.PLAN_TOPIC


def test_a_topic_sent_days_after_the_prompt_is_still_taken():
    waiting = replace(IDLE_TEACHER, phase=Phase.PLAN_TOPIC)
    t = handle(waiting, "fractions", idle_for=timedelta(days=2))
    assert t.state.phase is Phase.IDLE
    assert t.effects == (MakePlan("fractions"),)
