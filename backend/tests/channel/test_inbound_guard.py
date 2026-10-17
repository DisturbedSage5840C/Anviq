import fakeredis.aioredis
import pytest

from app.channel.inbound_guard import (
    DEDUPE_TTL_S,
    RATE_LIMIT_WINDOW_S,
    InboundGuard,
)


@pytest.fixture
async def redis():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture
def guard(redis) -> InboundGuard:
    return InboundGuard(redis, rate_limit=3)


async def test_first_delivery_of_a_message_is_claimed(guard) -> None:
    assert await guard.claim_message("wamid.1") is True


async def test_redelivery_of_the_same_message_is_rejected(guard) -> None:
    await guard.claim_message("wamid.1")

    assert await guard.claim_message("wamid.1") is False


async def test_distinct_messages_are_each_claimed(guard) -> None:
    assert await guard.claim_message("wamid.1") is True
    assert await guard.claim_message("wamid.2") is True


async def test_claim_expires_after_the_dedupe_window(guard, redis) -> None:
    await guard.claim_message("wamid.1")

    ttl = await redis.ttl("dedupe:wamid.1")

    assert 0 < ttl <= DEDUPE_TTL_S


async def test_sender_is_allowed_up_to_the_limit_then_blocked(guard) -> None:
    results = [await guard.allow_sender("sender-a") for _ in range(4)]

    assert results == [True, True, True, False]


async def test_senders_are_limited_independently(guard) -> None:
    for _ in range(3):
        await guard.allow_sender("sender-a")

    assert await guard.allow_sender("sender-b") is True


async def test_rate_window_has_a_ttl_so_a_sender_is_never_blocked_forever(guard, redis) -> None:
    await guard.allow_sender("sender-a")

    assert 0 < await redis.ttl("ratelimit:sender-a") <= RATE_LIMIT_WINDOW_S


async def test_counter_missing_its_ttl_is_repaired(guard, redis) -> None:
    await redis.set("ratelimit:sender-a", 2)
    assert await redis.ttl("ratelimit:sender-a") == -1

    await guard.allow_sender("sender-a")

    assert await redis.ttl("ratelimit:sender-a") > 0


async def test_released_message_can_be_claimed_again(guard) -> None:
    await guard.claim_message("wamid.1")

    await guard.release_message("wamid.1")

    assert await guard.claim_message("wamid.1") is True


async def test_releasing_an_unclaimed_message_is_harmless(guard) -> None:
    await guard.release_message("wamid.never-seen")

    assert await guard.claim_message("wamid.never-seen") is True
