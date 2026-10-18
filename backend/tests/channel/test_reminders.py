"""Daily reminders: which IST window is due now, and which approved template to send."""

from datetime import UTC, date, datetime, time

import pytest

from app.channel.reminders import reminder_template, reminder_window


def test_the_window_runs_from_the_catch_up_limit_to_now_in_indian_time():
    # 01:30 UTC is 07:00 IST.
    window = reminder_window(datetime(2026, 10, 18, 1, 30, tzinfo=UTC))

    assert window.today == date(2026, 10, 18)
    assert window.latest == time(7, 0)
    assert window.earliest == time(5, 0)


def test_the_window_uses_the_indian_date_not_the_utc_date():
    # 19:00 UTC on 17 Oct is 00:30 IST on 18 Oct.
    window = reminder_window(datetime(2026, 10, 17, 19, 0, tzinfo=UTC))

    assert window.today == date(2026, 10, 18)


def test_the_window_never_reaches_back_into_yesterday():
    # 00:30 IST: a 2h catch-up would start at 22:30 the day before, which is another day.
    window = reminder_window(datetime(2026, 10, 17, 19, 0, tzinfo=UTC))

    assert window.earliest == time.min
    assert window.latest == time(0, 30)


def test_the_last_tick_of_the_day_also_covers_the_minutes_no_tick_lands_on():
    # 23:45 IST is the last quarter-hour tick; a 23:50 reminder would otherwise never fire.
    window = reminder_window(datetime(2026, 10, 18, 18, 15, tzinfo=UTC))

    assert window.today == date(2026, 10, 18)
    assert window.latest == time.max


def test_before_the_last_tick_the_window_ends_at_the_current_time():
    window = reminder_window(datetime(2026, 10, 18, 18, 0, tzinfo=UTC))  # 23:30 IST

    assert window.latest == time(23, 30)


@pytest.mark.parametrize(
    ("lang", "template"),
    [("hi", "daily_plan_reminder_hi"), ("en", "daily_plan_reminder_en")],
)
def test_each_language_has_its_own_approved_template(lang: str, template: str):
    assert reminder_template(lang) == template


def test_an_unknown_language_is_refused_instead_of_guessing_a_template():
    with pytest.raises(ValueError, match="fr"):
        reminder_template("fr")
