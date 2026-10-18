"""Plain-text summary of what is stored about a teacher, for the 'send me my data' command."""

from app.content.copy import BILINGUAL_SEPARATOR, LANGS, render
from app.core.teacher_store import ConsentRecord, TeacherExport

NOT_GIVEN = "–"
LINE_BREAK = "\n"


def render_export(export: TeacherExport, lang: str | None) -> str:
    """The summary in `lang`; an unknown language gets Hindi then English, as `render` does."""
    if lang is None:
        return BILINGUAL_SEPARATOR.join(render_export(export, each) for each in LANGS)
    reminders = render("export_on" if export.reminders_opt_in else "export_off", lang)
    lines = (
        render("export_header", lang),
        _bullet("export_language", export.lang or NOT_GIVEN, lang),
        _bullet("export_grade", export.grade_band or NOT_GIVEN, lang),
        *(_consent_bullet(consent, lang) for consent in export.consents),
        _bullet("export_reminders", reminders, lang),
    )
    return LINE_BREAK.join(lines)


def _bullet(label_key: str, value: str, lang: str) -> str:
    return f"• {render(label_key, lang)}: {value}"


def _consent_bullet(consent: ConsentRecord, lang: str) -> str:
    status = render("export_revoked" if consent.revoked else "export_active", lang)
    return _bullet("export_consent", f"{consent.version} ({status})", lang)
