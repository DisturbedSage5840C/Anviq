"""Indian Standard Time, the clock teachers and the team live by."""

from datetime import timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))  # India has no daylight saving
