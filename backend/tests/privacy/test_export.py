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
