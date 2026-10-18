"""arq worker: consumes inbound WhatsApp jobs enqueued by the webhook.

Run with `arq app.worker.WorkerSettings`. The API process and the worker share the same
resource wiring (`open_resources`), so both talk to Redis, WhatsApp and the speech vendors
through identical clients.
"""

import logging
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from typing import Any

import httpx
from arq import cron
from arq.connections import RedisSettings
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.channel.messages import InboundMessage
from app.channel.pipeline import InboundPipeline
from app.config import Settings, get_settings
from app.core.dialogue import Brain
from app.core.router_brain import RouterBrain
from app.ops.cost_report import build_cost_report, previous_ist_day, render_cost_report
from app.privacy.retention import purge_expired
from app.resources import Resources, open_resources
from app.speech.voices import voice_for


class _RedisEndpoint(BaseSettings):
    """Just the queue address: arq reads it when this module loads, before full Settings."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    redis_url: str = "redis://localhost:6379/0"


logger = logging.getLogger(__name__)


class OpsWebhookError(RuntimeError):
    """The cost report could not be delivered. The message never includes the webhook URL."""


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


async def purge_retention(ctx: dict[str, Any]) -> None:
    """Hourly: delete expired transcripts, empty sessions and mirror clips in one transaction."""
    resources: Resources = ctx["resources"]
    async with resources.engine.begin() as conn:
        report = await purge_expired(conn, now=datetime.now(UTC))
    logger.info(
        "retention purge: turns=%d sessions=%d mirror_clips=%d",
        report.turns,
        report.sessions,
        report.mirror_clips,
    )


async def daily_cost_report(ctx: dict[str, Any]) -> None:
    """Daily 08:00 IST: summarise yesterday's LLM and speech spend and send it to the team.

    Without OPS_WEBHOOK_URL the report is only logged. A rejected post raises, so the failure
    shows up in the worker log instead of the report silently going missing.
    """
    resources: Resources = ctx["resources"]
    settings: Settings = ctx["settings"]
    start, end = previous_ist_day(datetime.now(UTC))
    async with resources.engine.begin() as conn:
        report = await build_cost_report(conn, start=start, end=end)
    message = render_cost_report(report)
    logger.info(message)
    if settings.ops_webhook_url is None:
        return
    await _post_to_ops_webhook(resources.http, settings.ops_webhook_url.get_secret_value(), message)


async def _post_to_ops_webhook(http: httpx.AsyncClient, url: str, message: str) -> None:
    """Post the report. The webhook URL is a credential, so no error may carry it."""
    try:
        response = await http.post(url, json={"text": message})
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise OpsWebhookError(
            f"ops webhook rejected the report: HTTP {exc.response.status_code}"
        ) from None
    except httpx.HTTPError as exc:
        raise OpsWebhookError(f"ops webhook unreachable: {type(exc).__name__}") from None


def quiet_http_logs() -> None:
    """httpx logs every request URL at INFO; keep the webhook URL out of the worker log."""
    logging.getLogger("httpx").setLevel(logging.WARNING)


async def on_startup(ctx: dict[str, Any]) -> None:
    quiet_http_logs()
    settings = get_settings()
    stack = AsyncExitStack()
    resources = await stack.enter_async_context(open_resources(settings))
    ctx["stack"] = stack
    ctx["settings"] = settings
    ctx["resources"] = resources
    ctx["pipeline"] = build_pipeline(resources, settings, brain=build_brain(resources))


async def on_shutdown(ctx: dict[str, Any]) -> None:
    await ctx["stack"].aclose()


class WorkerSettings:
    functions = [handle_inbound]
    # arq schedules in UTC: 02:30 UTC is 08:00 IST.
    cron_jobs = [
        cron(purge_retention, minute=0),
        cron(daily_cost_report, hour=2, minute=30),
    ]
    on_startup = on_startup
    on_shutdown = on_shutdown
    max_tries = MAX_TRIES
    job_timeout = JOB_TIMEOUT_S
    redis_settings = RedisSettings.from_dsn(_RedisEndpoint().redis_url)
