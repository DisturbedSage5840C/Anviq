"""Demo codes that let someone outside the WhatsApp test list try the web room.

A code is 128 random bits, shown once to whoever issues it. Only its keyed hash is stored, so a
database leak does not hand out working codes, and the hash (not the code) names the visitor.
"""

import hashlib
import hmac
import re
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

DEMO_CODE_TTL = timedelta(days=7)
DEFAULT_TURNS = 20
MAX_TURNS = 1000  # a typo must not mint a free-for-all code
CODE_BYTES = 16
CODE_CHARS = 22  # token_urlsafe(16): 16 bytes, base64url without padding
# What generate_code() produces, so anything else can be refused without touching the database.
CODE_PATTERN = re.compile(rf"[A-Za-z0-9_-]{{{CODE_CHARS}}}")
HASH_DOMAIN = b"web.demo_code:"
IDENTITY_PREFIX = "web:"
IDENTITY_HEX_CHARS = 32


def generate_code() -> str:
    return secrets.token_urlsafe(CODE_BYTES)


def hash_code(pepper: bytes, code: str) -> bytes:
    """Keyed hash, domain-separated from the phone-number hash that shares the pepper."""
    return hmac.new(pepper, HASH_DOMAIN + code.encode(), hashlib.sha256).digest()


def web_identity(code_hash: bytes) -> str:
    """Opaque stand-in for a WhatsApp id; the brain and rate limiter see this, never the code."""
    return IDENTITY_PREFIX + code_hash.hex()[:IDENTITY_HEX_CHARS]


async def issue_code(
    conn: AsyncConnection, pepper: bytes, *, now: datetime, turns: int = DEFAULT_TURNS
) -> str:
    """Create a code valid for seven days and `turns` turns. The only time it is visible."""
    if not 1 <= turns <= MAX_TURNS:
        raise ValueError(f"turns must be between 1 and {MAX_TURNS}")
    code = generate_code()
    await conn.execute(
        text(
            "insert into demo_codes (code_hash, created_at, expires_at, turns_left) "
            "values (:code_hash, :now, :expires_at, :turns)"
        ),
        {
            "code_hash": hash_code(pepper, code),
            "now": now,
            "expires_at": now + DEMO_CODE_TTL,
            "turns": turns,
        },
    )
    return code


async def claim_turn(
    conn: AsyncConnection, pepper: bytes, code: str, *, now: datetime
) -> str | None:
    """Spend one turn of the code. Returns the visitor's identity, or None if it cannot be used.

    One statement checks expiry and budget and decrements, so concurrent requests cannot
    overspend the budget.
    """
    code_hash = hash_code(pepper, code)
    row = await conn.execute(
        text(
            "update demo_codes set turns_left = turns_left - 1 "
            "where code_hash = :code_hash and expires_at > :now and turns_left > 0 "
            "returning 1"
        ),
        {"code_hash": code_hash, "now": now},
    )
    return web_identity(code_hash) if row.first() is not None else None


async def refund_turn(conn: AsyncConnection, pepper: bytes, code: str) -> None:
    """Give back a turn that was claimed but not served (it failed, or the coach could not help)."""
    await conn.execute(
        text("update demo_codes set turns_left = turns_left + 1 where code_hash = :code_hash"),
        {"code_hash": hash_code(pepper, code)},
    )


class PostgresDemoCodes:
    """The web room's view of the code table, one short transaction per claim."""

    def __init__(
        self,
        engine: AsyncEngine,
        pepper: bytes,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._engine = engine
        self._pepper = pepper
        self._clock = clock

    async def claim(self, code: str) -> str | None:
        async with self._engine.begin() as conn:
            return await claim_turn(conn, self._pepper, code, now=self._clock())

    async def refund(self, code: str) -> None:
        async with self._engine.begin() as conn:
            await refund_turn(conn, self._pepper, code)
