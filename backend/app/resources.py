"""Long-lived clients shared by the API process and the worker, opened once per process."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from redis.asyncio import Redis

from app.channel.inbound_guard import InboundGuard
from app.channel.job_queue import ArqJobQueue, JobQueue
from app.channel.whatsapp_client import WhatsAppClient
from app.config import Settings

HTTP_TIMEOUT_S = 20.0
DEFAULT_CONN_RETRIES = 3


@dataclass(frozen=True)
class Resources:
    redis: Redis
    arq_pool: ArqRedis
    http: httpx.AsyncClient
    inbound_guard: InboundGuard
    job_queue: JobQueue
    whatsapp: WhatsAppClient | None


@asynccontextmanager
async def open_resources(
    settings: Settings, *, conn_retries: int = DEFAULT_CONN_RETRIES
) -> AsyncIterator[Resources]:
    """Open Redis, the arq pool and the HTTP client; close them all on exit.

    Raises redis.exceptions.ConnectionError if Redis stays unreachable after `conn_retries`.
    """
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    redis_settings.conn_retries = conn_retries
    arq_pool = await create_pool(redis_settings)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    http = httpx.AsyncClient(timeout=HTTP_TIMEOUT_S)
    try:
        yield Resources(
            redis=redis,
            arq_pool=arq_pool,
            http=http,
            inbound_guard=InboundGuard(redis),
            job_queue=ArqJobQueue(arq_pool),
            whatsapp=_build_whatsapp(settings, http),
        )
    finally:
        await http.aclose()
        await redis.aclose()
        await arq_pool.aclose()


def _build_whatsapp(settings: Settings, http: httpx.AsyncClient) -> WhatsAppClient | None:
    if settings.wa_phone_number_id is None or settings.wa_access_token is None:
        return None
    return WhatsAppClient(
        http,
        phone_number_id=settings.wa_phone_number_id,
        access_token=settings.wa_access_token.get_secret_value(),
        base_url=settings.wa_graph_base_url,
    )
