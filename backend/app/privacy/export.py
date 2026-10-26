"""Plain-text summary of what is stored about a teacher, for the 'send me my data' command."""

from datetime import date, time

from app.content.copy import BILINGUAL_SEPARATOR, LANGS, render
from app.core.teacher_store import ConsentRecord, TeacherExport

NOT_GIVEN = "–"
LINE_BREAK = "\n"


def render_export(export: TeacherExport, lang: str | None) -> str:
    """The summary in `lang`; an unknown language gets Hindi then English, as `render` does."""
    if lang is None:
        return BILINGUAL_SEPARATOR.join(render_export(export, each) for each in LANGS)
    reminders = render("export_on" if export.reminders_opt_in else "export_off", lang)
    in_progress = render("export_yes" if export.practice_in_progress else "export_no", lang)
    clips = str(export.clip_count) if export.clip_opt_in else render("export_clips_off", lang)
    lines = (
        render("export_header", lang),
        _bullet("export_language", export.lang or NOT_GIVEN, lang),
        _bullet("export_grade", export.grade_band or NOT_GIVEN, lang),
        *(_consent_bullet(consent, lang) for consent in export.consents),
        _bullet("export_reminders", reminders, lang),
        _bullet("export_reminder_time", _clock(export.reminder_time), lang),
        _bullet("export_last_reminder", _day(export.last_reminded_on), lang),
        _bullet("export_practices", str(export.practice_count), lang),
        _bullet("export_questions", str(export.scored_question_count), lang),
        _bullet("export_plan", export.plan_topic_id or NOT_GIVEN, lang),
        _bullet("export_in_progress", in_progress, lang),
        _bullet("export_clips", clips, lang),
    )
    return LINE_BREAK.join(lines)


def _clock(at: time | None) -> str:
    return NOT_GIVEN if at is None else at.strftime("%H:%M")


def _day(on: date | None) -> str:
    return NOT_GIVEN if on is None else on.isoformat()


def _bullet(label_key: str, value: str, lang: str) -> str:
    return f"• {render(label_key, lang)}: {value}"


def _consent_bullet(consent: ConsentRecord, lang: str) -> str:
    status = render("export_revoked" if consent.revoked else "export_active", lang)
    return _bullet("export_consent", f"{consent.version} ({status})", lang)
