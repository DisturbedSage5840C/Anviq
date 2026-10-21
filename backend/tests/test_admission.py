from typing import Any

import pytest

from app.api.admission import QueueUnavailableError, admit
from app.channel.messages import InboundKind, InboundMessage
from app.channel.sender_key import sender_key
from app.config import Settings

MESSAGE = InboundMessage("SM1", "919800000001", InboundKind.TEXT, 1_792_000_000, text="hi")


class FakeGuard:
    def __init__(self, *, fresh: bool = True, allowed: bool = True) -> None:
        self.fresh = fresh
        self.allowed = allowed
        self.released: list[str] = []
        self.rate_checked: list[str] = []

    async def claim_message(self, wa_message_id: str) -> bool:
        return self.fresh

    async def release_message(self, wa_message_id: str) -> None:
        self.released.append(wa_message_id)

    async def allow_sender(self, key: str) -> bool:
        self.rate_checked.append(key)
        return self.allowed


class RecordingQueue:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.jobs: list[tuple[dict[str, Any], str]] = []

    async def enqueue(self, envelope: dict[str, Any], *, job_id: str) -> None:
        if self.fail:
            raise ConnectionError("redis down")
        self.jobs.append((envelope, job_id))


async def test_a_fresh_message_from_an_allowed_sender_is_queued_under_its_own_id(
    settings: Settings,
) -> None:
    guard, queue = FakeGuard(), RecordingQueue()

    queued = await admit(MESSAGE, settings, guard, queue)

    assert queued == 1
    assert queue.jobs == [(MESSAGE.to_envelope(), "SM1")]
    assert guard.rate_checked == [sender_key(settings, "919800000001")]


async def test_a_redelivered_message_is_dropped_before_the_rate_limit_is_charged(
    settings: Settings,
) -> None:
    guard, queue = FakeGuard(fresh=False), RecordingQueue()

    queued = await admit(MESSAGE, settings, guard, queue)

    assert queued == 0
    assert queue.jobs == [] and guard.rate_checked == []


async def test_a_sender_over_the_limit_is_dropped_without_queueing(settings: Settings) -> None:
    guard, queue = FakeGuard(allowed=False), RecordingQueue()

    queued = await admit(MESSAGE, settings, guard, queue)

    assert queued == 0 and queue.jobs == []


async def test_a_queue_failure_releases_the_claim_so_a_resend_gets_through(
    settings: Settings,
) -> None:
    guard, queue = FakeGuard(), RecordingQueue(fail=True)

    with pytest.raises(QueueUnavailableError):
        await admit(MESSAGE, settings, guard, queue)

    assert guard.released == ["SM1"]
