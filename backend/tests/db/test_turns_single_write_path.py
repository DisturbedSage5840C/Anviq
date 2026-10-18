"""`record_turn` scrubs, so it must be the only code in app/ that inserts into turns."""

import re
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"
ALLOWED = APP / "db" / "turns.py"
INSERT_INTO_TURNS = re.compile(r"insert\s+into\s+turns\b", re.IGNORECASE)


def test_only_record_turn_inserts_into_turns():
    offenders = [
        str(path.relative_to(APP))
        for path in APP.rglob("*.py")
        if path != ALLOWED and INSERT_INTO_TURNS.search(path.read_text(encoding="utf-8"))
    ]

    assert offenders == []
