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

    `criteria` is the coach's judgment of a teacher turn; its true count becomes `met_count`.
    """
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
            "malrule_id": malrule_id,
            "child_name": child_name,
            "criteria": None if criteria is None else json.dumps(dict(criteria)),
            "met_count": None if criteria is None else sum(criteria.values()),
        },
    )
    return str(result.scalar_one())
