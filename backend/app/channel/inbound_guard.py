"""Redis-backed idempotency and per-sender rate limiting for the webhook.

Meta retries deliveries it thinks failed, so every message id is claimed once.
Sender keys are opaque (a keyed hash) so raw phone numbers never become Redis keys.
"""

from redis.asyncio import Redis

DEDUPE_TTL_S = 7 * 24 * 60 * 60
RATE_LIMIT_PER_HOUR = 60
RATE_LIMIT_WINDOW_S = 60 * 60


class InboundGuard:
    def __init__(
        self,
        redis: Redis,
        *,
        rate_limit: int = RATE_LIMIT_PER_HOUR,
        window_s: int = RATE_LIMIT_WINDOW_S,
        dedupe_ttl_s: int = DEDUPE_TTL_S,
    ) -> None:
        self._redis = redis
        self._rate_limit = rate_limit
        self._window_s = window_s
        self._dedupe_ttl_s = dedupe_ttl_s

    async def claim_message(self, wa_message_id: str) -> bool:
        """True the first time a message id is seen, False for every redelivery."""
        claimed = await self._redis.set(
            f"dedupe:{wa_message_id}", "1", nx=True, ex=self._dedupe_ttl_s
        )
        return bool(claimed)

    async def release_message(self, wa_message_id: str) -> None:
        """Undo a claim when the message could not be queued, so Meta's retry is accepted."""
        await self._redis.delete(f"dedupe:{wa_message_id}")

    async def allow_sender(self, sender_key: str) -> bool:
        """Fixed-window counter: at most `rate_limit` messages per window per sender."""
        key = f"ratelimit:{sender_key}"
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.ttl(key)
            count, ttl = await pipe.execute()
        # A crash between INCR and EXPIRE would leave a counter that never resets.
        if ttl < 0:
            await self._redis.expire(key, self._window_s)
        return int(count) <= self._rate_limit
