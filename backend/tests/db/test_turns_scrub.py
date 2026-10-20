"""The scrub-on-write guarantee must hold without a database: check what is handed to SQL."""

from typing import Any

from app.db.turns import record_turn
from app.guardrails.pii import EMAIL_PLACEHOLDER, PHONE_PLACEHOLDER


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


async def test_the_labels_a_practice_stores_are_scrubbed_like_the_words():
    conn = _RecordingConnection()

    await record_turn(
        conn,  # type: ignore[arg-type]
        "session-1",
        "teacher",
        "How did you get that?",
        criteria={"C1": True, "mail a.b@example.org": False},
        child_name="Riya 9876543210",
        malrule_id="REGROUP a.b@example.org",
    )

    [bound] = conn.params
    assert bound["child_name"] == f"Riya {PHONE_PLACEHOLDER}"
    assert bound["malrule_id"] == f"REGROUP {EMAIL_PLACEHOLDER}"
    assert bound["criteria"] == f'{{"C1": true, "mail {EMAIL_PLACEHOLDER}": false}}'
    assert bound["met_count"] == 1
    assert "example.org" not in str(bound)
    assert "9876543210" not in str(bound)


async def test_a_turn_with_no_labels_stores_none_for_them():
    conn = _RecordingConnection()

    await record_turn(conn, "session-1", "teacher", "hello")  # type: ignore[arg-type]

    [bound] = conn.params
    assert (bound["child_name"], bound["malrule_id"], bound["criteria"]) == (None, None, None)


async def test_two_labels_that_scrub_alike_still_count_both_judgments():
    conn = _RecordingConnection()
    criteria = {"a@x.org": True, "b@y.org": True}

    await record_turn(conn, "session-1", "teacher", "hi", criteria=criteria)  # type: ignore[arg-type]

    [bound] = conn.params
    assert bound["met_count"] == 2
