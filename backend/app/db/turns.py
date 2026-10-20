"""The single write path for turns. Free text is scrubbed here, so no caller can forget to."""

import json
from collections.abc import Mapping

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.guardrails.pii import scrub


async def record_turn(
    conn: AsyncConnection,
    session_id: str,
    role: str,
    raw_text: str,
    *,
    criteria: Mapping[str, bool] | None = None,
    child_name: str | None = None,
    malrule_id: str | None = None,
) -> str:
    """Store one turn and return its id. `raw_text` never reaches the database unscrubbed.

    `criteria` is the coach's judgment of a teacher turn; its true count becomes `met_count`. The
    labels (`child_name`, `malrule_id`, the criteria ids) come from fixed lists today, but they are
    scrubbed too, so the guarantee does not depend on every caller keeping to that.
    """
    judged = None if criteria is None else {scrub(key): bool(met) for key, met in criteria.items()}
    result = await conn.execute(
        text(
            "insert into turns (session_id, role, text_scrubbed, malrule_id, child_name, "
            "criteria_json, met_count) "
            "values (:session_id, :role, :text, :malrule_id, :child_name, "
            "cast(:criteria as jsonb), :met_count) returning id"
        ),
        {
            "session_id": session_id,
            "role": role,
            "text": scrub(raw_text),
            "malrule_id": None if malrule_id is None else scrub(malrule_id),
            "child_name": None if child_name is None else scrub(child_name),
            "criteria": None if judged is None else json.dumps(judged),
            "met_count": None if judged is None else sum(judged.values()),
        },
    )
    return str(result.scalar_one())
