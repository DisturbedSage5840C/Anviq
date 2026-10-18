"""The single write path for turns. Free text is scrubbed here, so no caller can forget to."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.guardrails.pii import scrub


async def record_turn(conn: AsyncConnection, session_id: str, role: str, raw_text: str) -> str:
    """Store one turn and return its id. `raw_text` never reaches the database unscrubbed."""
    result = await conn.execute(
        text(
            "insert into turns (session_id, role, text_scrubbed) "
            "values (:session_id, :role, :text) returning id"
        ),
        {"session_id": session_id, "role": role, "text": scrub(raw_text)},
    )
    return str(result.scalar_one())
