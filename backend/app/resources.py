"""Long-lived clients shared by the API process and the worker, opened once per process."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.channel.inbound_guard import InboundGuard
from app.channel.job_queue import ArqJobQueue, JobQueue
from app.channel.twilio_client import TwilioWhatsAppClient
from app.channel.whatsapp_client import WhatsAppClient
from app.config import Settings
from app.core.teacher_store import TeacherStore
from app.db.teacher_store import PostgresTeacherStore
from app.privacy.keyring import Keyring, load_keyring
from app.speech.base import STTProvider, TTSProvider
from app.speech.factory import build_speech

HTTP_TIMEOUT_S = 20.0
DEFAULT_CONN_RETRIES = 3

# Meta's Cloud API client or Twilio's sandbox client; both satisfy the pipeline's WhatsAppPort.
WhatsAppChannel = WhatsAppClient | TwilioWhatsAppClient


@dataclass(frozen=True)
class Resources:
    redis: Redis
    arq_pool: ArqRedis
    http: httpx.AsyncClient
    inbound_guard: InboundGuard
    job_queue: JobQueue
    whatsapp: WhatsAppChannel | None
    stt: STTProvider | None
    tts: TTSProvider | None
    engine: AsyncEngine
    keyring: Keyring
    teacher_store: TeacherStore


@asynccontextmanager
async def open_resources(
    settings: Settings, *, conn_retries: int = DEFAULT_CONN_RETRIES
) -> AsyncIterator[Resources]:
    """Open Redis, the arq pool, the HTTP client and the DB engine; close them all on exit.

    The engine connects lazily, so an unreachable database surfaces on /readyz and on the first
    message rather than at startup.

    Raises redis.exceptions.ConnectionError if Redis stays unreachable after `conn_retries`.
    """
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    redis_settings.conn_retries = conn_retries
    arq_pool = await create_pool(redis_settings)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    http = httpx.AsyncClient(timeout=HTTP_TIMEOUT_S)
    stt, tts = build_speech(settings, http)
    keyring = load_keyring(settings)
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        yield Resources(
            redis=redis,
            arq_pool=arq_pool,
            http=http,
            inbound_guard=InboundGuard(redis),
            job_queue=ArqJobQueue(arq_pool),
            whatsapp=build_whatsapp(settings, http),
            stt=stt,
            tts=tts,
            engine=engine,
            keyring=keyring,
            teacher_store=PostgresTeacherStore(engine, keyring.field_cipher),
        )
    finally:
        await engine.dispose()
        await http.aclose()
        await redis.aclose()
        await arq_pool.aclose()


def build_whatsapp(settings: Settings, http: httpx.AsyncClient) -> WhatsAppChannel | None:
    """The outbound client for the configured provider, or None when it has no credentials."""
    if settings.whatsapp_provider == "twilio":
        return _build_twilio(settings, http)
    if settings.wa_phone_number_id is None or settings.wa_access_token is None:
        return None
    return WhatsAppClient(
        http,
        phone_number_id=settings.wa_phone_number_id,
        access_token=settings.wa_access_token.get_secret_value(),
        base_url=settings.wa_graph_base_url,
    )


def _build_twilio(settings: Settings, http: httpx.AsyncClient) -> TwilioWhatsAppClient | None:
    # Settings validation already requires all four when the provider is twilio.
    if (
        settings.twilio_account_sid is None
        or settings.twilio_auth_token is None
        or settings.twilio_whatsapp_from is None
    ):
        return None
    return TwilioWhatsAppClient(
        http,
        account_sid=settings.twilio_account_sid,
        auth_token=settings.twilio_auth_token.get_secret_value(),
        from_number=settings.twilio_whatsapp_from,
    )
