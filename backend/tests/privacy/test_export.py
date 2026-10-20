from datetime import date, time

import pytest

from app.content.copy import render
from app.core.teacher_store import ConsentRecord, TeacherExport
from app.privacy.export import render_export

LANGS = ("hi", "en")
FULL = TeacherExport(
    lang="en",
    grade_band="2",
    consents=(ConsentRecord("v1", "ab" * 32, revoked=True), ConsentRecord("v2", "cd" * 32)),
    reminders_opt_in=True,
)


@pytest.mark.parametrize("lang", LANGS)
def test_summary_starts_with_the_header_and_lists_every_stored_field(lang: str):
    text = render_export(FULL, lang)

    assert text.startswith(render("export_header", lang))
    assert f"{render('export_language', lang)}: en" in text
    assert f"{render('export_grade', lang)}: 2" in text
    assert f"{render('export_reminders', lang)}: {render('export_on', lang)}" in text


@pytest.mark.parametrize("lang", LANGS)
def test_each_consent_is_listed_with_its_status(lang: str):
    text = render_export(FULL, lang)

    assert f"{render('export_consent', lang)}: v1 ({render('export_revoked', lang)})" in text
    assert f"{render('export_consent', lang)}: v2 ({render('export_active', lang)})" in text


def test_consent_hashes_are_not_shown_because_they_mean_nothing_to_a_teacher():
    assert "ab" * 32 not in render_export(FULL, "en")


def test_a_field_the_teacher_never_gave_is_shown_as_a_dash_not_omitted():
    sparse = TeacherExport(lang=None, grade_band=None, consents=(), reminders_opt_in=False)

    text = render_export(sparse, "en")

    assert f"{render('export_language', 'en')}: –" in text
    assert f"{render('export_grade', 'en')}: –" in text
    assert f"{render('export_reminders', 'en')}: {render('export_off', 'en')}" in text
    assert render("export_consent", "en") not in text


def test_without_a_language_the_summary_is_given_in_both():
    text = render_export(TeacherExport(None, None, (), False), None)

    assert render("export_header", "hi") in text
    assert render("export_header", "en") in text


BUSY = TeacherExport(
    lang="en",
    grade_band="2",
    consents=(ConsentRecord("v1", "cd" * 32),),
    reminders_opt_in=True,
    reminder_time=time(7, 30),
    last_reminded_on=date(2026, 10, 19),
    practice_count=3,
    scored_question_count=11,
    plan_topic_id="NUM.G2.SUB.REGROUP",
    practice_in_progress=True,
)


@pytest.mark.parametrize("lang", LANGS)
def test_the_summary_counts_the_practice_without_repeating_what_the_teacher_said(lang: str):
    text = render_export(BUSY, lang)

    assert f"{render('export_practices', lang)}: 3" in text
    assert f"{render('export_questions', lang)}: 11" in text


@pytest.mark.parametrize("lang", LANGS)
def test_the_summary_shows_the_saved_plan_and_whether_a_practice_is_open(lang: str):
    text = render_export(BUSY, lang)

    assert f"{render('export_plan', lang)}: NUM.G2.SUB.REGROUP" in text
    assert f"{render('export_in_progress', lang)}: {render('export_yes', lang)}" in text


@pytest.mark.parametrize("lang", LANGS)
def test_the_summary_shows_the_reminder_time_and_the_last_reminder_day(lang: str):
    text = render_export(BUSY, lang)

    assert f"{render('export_reminder_time', lang)}: 07:30" in text
    assert f"{render('export_last_reminder', lang)}: 2026-10-19" in text


def test_a_teacher_with_no_practice_sees_zeros_and_dashes_not_missing_lines():
    sparse = TeacherExport(lang="en", grade_band="2", consents=(), reminders_opt_in=False)

    text = render_export(sparse, "en")

    assert f"{render('export_practices', 'en')}: 0" in text
    assert f"{render('export_questions', 'en')}: 0" in text
    assert f"{render('export_plan', 'en')}: –" in text
    assert f"{render('export_in_progress', 'en')}: {render('export_no', 'en')}" in text
    assert f"{render('export_reminder_time', 'en')}: –" in text
    assert f"{render('export_last_reminder', 'en')}: –" in text
