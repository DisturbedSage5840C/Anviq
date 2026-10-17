"""arq worker: consumes inbound WhatsApp jobs enqueued by the webhook.

Run with `arq app.worker.WorkerSettings`. The API process and the worker share the same
resource wiring (`open_resources`), so both talk to Redis, WhatsApp and the speech vendors
through identical clients.
"""

from contextlib import AsyncExitStack
from typing import Any

from arq.connections import RedisSettings
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.channel.messages import InboundMessage
from app.channel.pipeline import InboundPipeline
from app.config import Settings, get_settings
from app.core.dialogue import Brain
from app.core.router_brain import RouterBrain
from app.resources import Resources, open_resources
from app.speech.voices import voice_for


class _RedisEndpoint(BaseSettings):
    """Just the queue address: arq reads it when this module loads, before full Settings."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    redis_url: str = "redis://localhost:6379/0"


COACH_PERSONA = "coach"
MAX_TRIES = 2
JOB_TIMEOUT_S = 60


def build_pipeline(resources: Resources, settings: Settings, *, brain: Brain) -> InboundPipeline:
    if resources.whatsapp is None:
        raise RuntimeError("WA_PHONE_NUMBER_ID and WA_ACCESS_TOKEN are required to run the worker")
    return InboundPipeline(
        whatsapp=resources.whatsapp,
        stt=resources.stt,
        tts=resources.tts,
        brain=brain,
        voice=voice_for(settings.tts_provider, COACH_PERSONA),
    )


def build_brain(resources: Resources) -> Brain:
    return RouterBrain(resources.teacher_store, resources.keyring.phone_pepper)


async def handle_inbound(ctx: dict[str, Any], envelope: dict[str, Any]) -> None:
    pipeline: InboundPipeline = ctx["pipeline"]
    await pipeline.handle(InboundMessage.from_envelope(envelope))


async def on_startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    stack = AsyncExitStack()
    resources = await stack.enter_async_context(open_resources(settings))
    ctx["stack"] = stack
    ctx["pipeline"] = build_pipeline(resources, settings, brain=build_brain(resources))


async def on_shutdown(ctx: dict[str, Any]) -> None:
    await ctx["stack"].aclose()


class WorkerSettings:
    functions = [handle_inbound]
    on_startup = on_startup
    on_shutdown = on_shutdown
    max_tries = MAX_TRIES
    job_timeout = JOB_TIMEOUT_S
    redis_settings = RedisSettings.from_dsn(_RedisEndpoint().redis_url)
