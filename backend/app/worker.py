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

from app.ai import build_router_brain
from app.channel.messages import InboundMessage
from app.channel.pipeline import InboundPipeline
from app.channel.reminders import (
    DueReminder,
    claim_due_reminders,
    reminder_template,
    reminder_window,
    still_reachable,
)
from app.config import Settings, get_settings
from app.core.dialogue import Brain
from app.core.router_brain import RouterBrain
from app.db.teacher_store import WA_ID_CONTEXT
from app.ops.cost_report import build_cost_report, previous_ist_day, render_cost_report
from app.ops.sentry import init_sentry
from app.privacy.crypto import FieldCipher
from app.privacy.retention import purge_expired
from app.resources import Resources, WhatsAppChannel, open_resources
from app.speech.voices import COACH_PERSONA, voice_for


class _RedisEndpoint(BaseSettings):
    """Just the queue address: arq reads it when this module loads, before full Settings."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    redis_url: str = "redis://localhost:6379/0"


logger = logging.getLogger(__name__)


class OpsWebhookError(RuntimeError):
    """The cost report could not be delivered. The message never includes the webhook URL."""


SENT, FAILED, SKIPPED = "sent", "failed", "skipped"
MAX_TRIES = 2
JOB_TIMEOUT_S = 60
REMINDER_JOB_TIMEOUT_S = 300  # a claimed batch of sends, not a single inbound message
META_CREDENTIALS = "WA_PHONE_NUMBER_ID and WA_ACCESS_TOKEN"


def build_pipeline(resources: Resources, settings: Settings, *, brain: Brain) -> InboundPipeline:
    if resources.whatsapp is None:
        raise RuntimeError(f"{_missing_credentials(settings)} are required to run the worker")
    return InboundPipeline(
        whatsapp=resources.whatsapp,
        stt=resources.stt,
        # The Twilio sandbox cannot send voice notes, so its replies are text only.
        tts=None if settings.whatsapp_provider == "twilio" else resources.tts,
        brain=brain,
        voice=voice_for(settings.tts_provider, COACH_PERSONA),
    )


def _missing_credentials(settings: Settings) -> str:
    if settings.whatsapp_provider == "twilio":
        return "TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and TWILIO_WHATSAPP_FROM"
    if settings.whatsapp_provider == "evolution":
        return (
            "EVOLUTION_BASE_URL, EVOLUTION_API_KEY, EVOLUTION_INSTANCE and EVOLUTION_WEBHOOK_SECRET"
        )
    return META_CREDENTIALS


def _credentials_hint(ctx: dict[str, Any]) -> str:
    """Which variables to set; a job context without settings (tests) defaults to Meta's."""
    settings: Settings | None = ctx.get("settings")
    return _missing_credentials(settings) if settings is not None else META_CREDENTIALS


def build_brain(resources: Resources, settings: Settings | None = None) -> Brain:
    """Without settings (tests only) there is no model and no budget; production passes them."""
    if settings is None:
        return RouterBrain(resources.teacher_store, resources.keyring.phone_pepper)
    return build_router_brain(resources, settings)


async def handle_inbound(ctx: dict[str, Any], envelope: dict[str, Any]) -> None:
    pipeline: InboundPipeline | None = ctx["pipeline"]
    if pipeline is None:
        raise RuntimeError(f"{_credentials_hint(ctx)} are required to handle inbound")
    await pipeline.handle(InboundMessage.from_envelope(envelope))


async def purge_retention(ctx: dict[str, Any]) -> None:
    """Hourly: delete expired transcripts, empty sessions, mirror clips and demo codes, and
    close practices left unfinished."""
    resources: Resources = ctx["resources"]
    async with resources.engine.begin() as conn:
        report = await purge_expired(conn, now=datetime.now(UTC))
    logger.info(
        "retention purge: turns=%d sessions=%d mirror_clips=%d demo_codes=%d rehearsals=%d "
        "practices_closed=%d",
        report.turns,
        report.sessions,
        report.mirror_clips,
        report.demo_codes,
        report.rehearsals,
        report.practices_closed,
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


async def send_daily_reminders(ctx: dict[str, Any]) -> None:
    """Every quarter hour: send the approved reminder template to teachers whose time has come.

    Teachers are claimed (and stamped as reminded today) in one committed transaction before
    any send, so a crash or retry can drop a reminder but never message someone twice. One
    failed teacher never stops the rest, and the log carries counts only, never a number.
    """
    resources: Resources = ctx["resources"]
    settings: Settings | None = ctx.get("settings")
    if settings is not None and settings.whatsapp_provider == "twilio":
        # Reminders are template messages and the sandbox only allows free-form replies inside
        # 24 hours. Skip before claiming, so no teacher is stamped as reminded without a send.
        logger.info("daily reminders skipped: the Twilio sandbox cannot send templates")
        return
    if settings is not None and settings.whatsapp_provider == "evolution":
        # Evolution drives a plain WhatsApp account, which has no approved templates to send.
        logger.info("daily reminders skipped: the Evolution channel cannot send templates")
        return
    whatsapp = resources.whatsapp
    if whatsapp is None:
        raise RuntimeError(f"{_credentials_hint(ctx)} are required to send reminders")
    async with resources.engine.begin() as conn:
        due = await claim_due_reminders(conn, reminder_window(datetime.now(UTC)))
    cipher = resources.keyring.field_cipher
    outcomes = [await _send_reminder(resources, whatsapp, cipher, reminder) for reminder in due]
    logger.info(
        "daily reminders: claimed=%d sent=%d failed=%d skipped=%d",
        len(due),
        outcomes.count(SENT),
        outcomes.count(FAILED),
        outcomes.count(SKIPPED),
    )


async def _send_reminder(
    resources: Resources, whatsapp: WhatsAppChannel, cipher: FieldCipher, reminder: DueReminder
) -> str:
    try:
        async with resources.engine.begin() as conn:
            reachable = await still_reachable(conn, reminder.teacher_id)
        if not reachable:
            return SKIPPED
        wa_id = cipher.decrypt(reminder.wa_id_enc, context=WA_ID_CONTEXT)
        await whatsapp.send_template(wa_id, reminder_template(reminder.lang), reminder.lang)
    except Exception as exc:  # noqa: BLE001 - every teacher is already claimed; one must not lose the rest
        logger.warning("daily reminder not sent: %s", type(exc).__name__)
        return FAILED
    return SENT


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


ARQ_JOB_START_FORMAT = "%6.2fs → %s(%s)%s"  # arq.worker's "job started" line
REDACTED_JOB_ARGUMENTS = "…"


class JobArgumentRedactor(logging.Filter):
    """arq prints a job's arguments when it starts; for an inbound message that is a phone no."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.msg == ARQ_JOB_START_FORMAT and isinstance(record.args, tuple):
            elapsed, job_ref, _arguments, suffix = record.args
            record.args = (elapsed, job_ref, REDACTED_JOB_ARGUMENTS, suffix)
        return True


def redact_job_arguments_in_logs() -> None:
    """Install the redactor on arq's worker logger once, however often this is called."""
    arq_logger = logging.getLogger("arq.worker")
    if not any(isinstance(f, JobArgumentRedactor) for f in arq_logger.filters):
        arq_logger.addFilter(JobArgumentRedactor())


async def on_startup(ctx: dict[str, Any]) -> None:
    quiet_http_logs()
    redact_job_arguments_in_logs()
    settings = get_settings()
    init_sentry(settings.sentry_dsn, environment=settings.app_env)
    stack = AsyncExitStack()
    resources = await stack.enter_async_context(open_resources(settings))
    ctx["stack"] = stack
    ctx["settings"] = settings
    ctx["resources"] = resources
    ctx["pipeline"] = _inbound_pipeline_or_none(resources, settings)


def _inbound_pipeline_or_none(resources: Resources, settings: Settings) -> InboundPipeline | None:
    """Without WhatsApp credentials the worker still runs its cron jobs (retention, cost report).

    The browser demo does not use the queue, so a deployment may legitimately have no WhatsApp yet.
    """
    if resources.whatsapp is None:
        logger.warning("WhatsApp is not configured: inbound jobs will fail, cron jobs still run")
        return None
    return build_pipeline(resources, settings, brain=build_brain(resources, settings))


async def on_shutdown(ctx: dict[str, Any]) -> None:
    await ctx["stack"].aclose()


class WorkerSettings:
    functions = [handle_inbound]
    # arq schedules in UTC: 02:30 UTC is 08:00 IST.
    cron_jobs = [
        cron(purge_retention, minute=0),
        cron(daily_cost_report, hour=2, minute=30),
        cron(send_daily_reminders, minute={0, 15, 30, 45}, timeout=REMINDER_JOB_TIMEOUT_S),
    ]
    on_startup = on_startup
    on_shutdown = on_shutdown
    max_tries = MAX_TRIES
    job_timeout = JOB_TIMEOUT_S
    redis_settings = RedisSettings.from_dsn(_RedisEndpoint().redis_url)
