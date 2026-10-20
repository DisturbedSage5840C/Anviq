"""Redis counter behind the per-teacher daily cap on paid model steps.

Keys carry the teacher's keyed hash and the IST date, never a phone number, and expire on their own.
"""

from collections.abc import Callable
from datetime import datetime

from redis.asyncio import Redis

from app.ist import IST

SECONDS_PER_DAY = 24 * 60 * 60
# Outlives the IST day it counts, so a little clock skew cannot reopen a spent day.
BUDGET_KEY_TTL_S = 2 * SECONDS_PER_DAY


def _ist_now() -> datetime:
    return datetime.now(IST)


class RedisModelBudget:
    """Fixed-window counter per teacher per IST day, in the same style as `InboundGuard`."""

    def __init__(
        self,
        redis: Redis,
        limit: int,
        *,
        now: Callable[[], datetime] = _ist_now,
    ) -> None:
        self._redis = redis
        self._limit = limit
        self._now = now

    async def spend(self, teacher: bytes) -> bool:
        """Count this step against today (IST); True while the count is within the limit."""
        today = self._now().astimezone(IST).date().isoformat()
        key = f"modelsteps:{teacher.hex()}:{today}"
        # One transaction, so no crash can leave a counter that never expires.
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, BUDGET_KEY_TTL_S)
            count, _ = await pipe.execute()
        return int(count) <= self._limit
