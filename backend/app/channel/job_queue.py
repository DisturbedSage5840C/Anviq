"""Job queue port for inbound messages, with the arq adapter used in production."""

from typing import Any, Protocol

from arq.connections import ArqRedis

HANDLE_INBOUND_JOB = "handle_inbound"


class JobQueue(Protocol):
    async def enqueue(self, envelope: dict[str, Any], *, job_id: str) -> None:
        """Queue one inbound message. `job_id` makes arq itself ignore duplicate ids."""
        ...


class ArqJobQueue:
    def __init__(self, pool: ArqRedis) -> None:
        self._pool = pool

    async def enqueue(self, envelope: dict[str, Any], *, job_id: str) -> None:
        await self._pool.enqueue_job(HANDLE_INBOUND_JOB, envelope, _job_id=job_id)
