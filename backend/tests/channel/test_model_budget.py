"""A teacher's daily allowance of paid model steps, counted in Redis by IST day."""

from datetime import UTC, datetime

import fakeredis.aioredis
import pytest

from app.channel.model_budget import BUDGET_KEY_TTL_S, RedisModelBudget

TEACHER = bytes(range(32))
OTHER_TEACHER = bytes(range(1, 33))
IST_LATE_EVENING = datetime(2026, 1, 5, 18, 29, tzinfo=UTC)  # 23:59 IST
IST_PAST_MIDNIGHT = datetime(2026, 1, 5, 18, 31, tzinfo=UTC)  # 00:01 IST the next day


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
async def redis():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture
def clock() -> _Clock:
    return _Clock(IST_LATE_EVENING)


@pytest.fixture
def budget(redis, clock: _Clock) -> RedisModelBudget:
    return RedisModelBudget(redis, limit=3, now=clock)


async def test_a_teacher_may_spend_up_to_the_limit_then_is_stopped(budget: RedisModelBudget):
    results = [await budget.spend(TEACHER) for _ in range(4)]

    assert results == [True, True, True, False]


async def test_teachers_are_counted_independently(budget: RedisModelBudget):
    for _ in range(3):
        await budget.spend(TEACHER)

    assert await budget.spend(OTHER_TEACHER) is True


async def test_the_allowance_renews_at_midnight_in_india(budget: RedisModelBudget, clock: _Clock):
    for _ in range(3):
        await budget.spend(TEACHER)
    clock.now = IST_PAST_MIDNIGHT

    assert await budget.spend(TEACHER) is True


async def test_old_days_clean_themselves_up(budget: RedisModelBudget, redis):
    await budget.spend(TEACHER)

    [key] = [key async for key in redis.scan_iter("*")]

    assert 0 < await redis.ttl(key) <= BUDGET_KEY_TTL_S


async def test_the_key_names_the_hashed_teacher_and_the_day_never_a_phone_number(
    budget: RedisModelBudget, redis
):
    await budget.spend(TEACHER)

    [key] = [key async for key in redis.scan_iter("*")]

    assert key == f"modelsteps:{TEACHER.hex()}:2026-01-05"


async def test_the_real_clock_counts_todays_steps_in_india(redis):
    budget = RedisModelBudget(redis, limit=1)

    assert [await budget.spend(TEACHER), await budget.spend(TEACHER)] == [True, False]
