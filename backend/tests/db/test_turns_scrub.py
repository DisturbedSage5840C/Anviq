"""The scrub-on-write guarantee must hold without a database: check what is handed to SQL."""

from typing import Any

from app.db.turns import record_turn
from app.guardrails.pii import EMAIL_PLACEHOLDER


class _RecordingConnection:
    """Captures the bound parameters of the insert; returns a canned turn id."""

    def __init__(self) -> None:
        self.params: list[dict[str, Any]] = []

    async def execute(self, statement: object, params: dict[str, Any]) -> "_RecordingConnection":
        self.params.append(params)
        return self

    def scalar_one(self) -> str:
        return "turn-1"


async def test_the_insert_receives_scrubbed_text_never_the_original():
    conn = _RecordingConnection()

    turn_id = await record_turn(conn, "session-1", "teacher", "mail me at a.b@example.org")  # type: ignore[arg-type]

    assert turn_id == "turn-1"
    [bound] = conn.params
    assert bound["text"] == f"mail me at {EMAIL_PLACEHOLDER}"
    assert "example.org" not in str(bound)
