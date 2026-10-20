import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from app import worker
from app.channel.job_queue import HANDLE_INBOUND_JOB
from app.channel.messages import InboundKind, InboundMessage
from app.channel.reminders import DueReminder, ReminderWindow
from app.channel.whatsapp_client import WhatsAppError
from app.config import Settings
from app.core.dialogue import EchoBrain
from app.db.teacher_store import WA_ID_CONTEXT
from app.ist import IST
from app.ops.cost_report import CostReport, render_cost_report
from app.privacy.crypto import FieldCipher
from app.privacy.retention import PurgeReport


class RecordingPipeline:
    def __init__(self) -> None:
        self.handled: list[InboundMessage] = []

    async def handle(self, message: InboundMessage) -> None:
        self.handled.append(message)


def _message() -> InboundMessage:
    return InboundMessage(
        wa_message_id="wamid.1",
        sender_wa_id="919999999999",
        kind=InboundKind.TEXT,
        timestamp=1_792_000_000,
        text="नमस्ते",
    )


async def test_handle_inbound_rebuilds_the_message_and_runs_the_pipeline():
    pipeline = RecordingPipeline()
    message = _message()

    await worker.handle_inbound({"pipeline": pipeline}, message.to_envelope())

    assert pipeline.handled == [message]


def test_worker_registers_the_job_name_the_webhook_enqueues():
    names = {fn.__name__ for fn in worker.WorkerSettings.functions}

    assert HANDLE_INBOUND_JOB in names


def test_worker_retries_a_failed_job_once_and_bounds_its_runtime():
    assert worker.WorkerSettings.max_tries == 2
    assert 0 < worker.WorkerSettings.job_timeout <= 120


def test_build_pipeline_requires_whatsapp_credentials(settings: Settings):
    resources: Any = type("R", (), {"whatsapp": None, "stt": None, "tts": None})()

    with pytest.raises(RuntimeError, match="WA_PHONE_NUMBER_ID"):
        worker.build_pipeline(resources, settings, brain=EchoBrain())


def test_build_pipeline_wires_the_coach_voice_for_the_selected_tts(settings: Settings):
    resources: Any = type("R", (), {"whatsapp": object(), "stt": None, "tts": None})()

    pipeline = worker.build_pipeline(resources, settings, brain=EchoBrain())

    assert pipeline is not None


def test_build_brain_runs_the_router_on_the_resources_store_and_pepper():
    from app.core.router_brain import RouterBrain

    store = object()
    keyring = type("K", (), {"phone_pepper": bytes(32)})()
    resources: Any = type("R", (), {"teacher_store": store, "keyring": keyring})()

    brain = worker.build_brain(resources)

    assert isinstance(brain, RouterBrain)


def test_build_brain_caps_model_steps_at_the_configured_limit_on_the_resources_redis(
    settings: Settings,
):
    from app.channel.model_budget import RedisModelBudget

    redis = object()
    keyring = type("K", (), {"phone_pepper": bytes(32)})()
    resources: Any = type(
        "R", (), {"teacher_store": object(), "keyring": keyring, "redis": redis}
    )()
    capped = settings.model_copy(update={"max_model_steps_per_day": 7})

    brain = worker.build_brain(resources, capped)

    budget = brain._budget  # type: ignore[attr-defined]
    assert isinstance(budget, RedisModelBudget)
    assert (budget._redis, budget._limit) == (redis, 7)


class _FakeTransaction:
    def __init__(self, log: list[str]) -> None:
        self._log = log

    async def __aenter__(self) -> str:
        self._log.append("begin")
        return "conn"

    async def __aexit__(self, *exc: object) -> None:
        self._log.append("commit" if exc[0] is None else "rollback")


class _FakeEngine:
    def __init__(self, log: list[str]) -> None:
        self._log = log

    def begin(self) -> _FakeTransaction:
        return _FakeTransaction(self._log)


async def test_purge_retention_runs_one_purge_in_one_transaction(monkeypatch: pytest.MonkeyPatch):
    log: list[str] = []

    async def fake_purge(conn: object, *, now: Any) -> PurgeReport:
        log.append(f"purge:{conn}:{now.tzinfo}")
        return PurgeReport(turns=3, sessions=1, mirror_clips=2)

    monkeypatch.setattr(worker, "purge_expired", fake_purge)
    resources: Any = type("R", (), {"engine": _FakeEngine(log)})()

    await worker.purge_retention({"resources": resources})

    assert log == ["begin", "purge:conn:UTC", "commit"]


async def test_a_failing_purge_rolls_back_and_lets_the_error_surface(
    monkeypatch: pytest.MonkeyPatch,
):
    log: list[str] = []

    async def failing_purge(conn: object, *, now: Any) -> PurgeReport:
        raise RuntimeError("db down")

    monkeypatch.setattr(worker, "purge_expired", failing_purge)
    resources: Any = type("R", (), {"engine": _FakeEngine(log)})()

    with pytest.raises(RuntimeError, match="db down"):
        await worker.purge_retention({"resources": resources})

    assert log == ["begin", "rollback"]


def _cron_job(coroutine: Any) -> Any:
    (job,) = (job for job in worker.WorkerSettings.cron_jobs if job.coroutine is coroutine)
    return job


def test_retention_purge_is_scheduled_hourly_on_the_hour():
    job = _cron_job(worker.purge_retention)

    assert (job.hour, job.minute) == (None, 0)


WEBHOOK_URL = "https://hooks.example/T000/B000"
REPORT = CostReport(
    start=datetime(2026, 10, 16, 18, 30, tzinfo=UTC),
    end=datetime(2026, 10, 17, 18, 30, tzinfo=UTC),
    llm_calls=2,
    llm_in_tok=10,
    llm_out_tok=5,
    llm_cost_usd=Decimal("0.5"),
    stt_seconds=Decimal(3),
    stt_cost_inr=Decimal(1),
    tts_chars=Decimal(40),
    tts_cost_inr=Decimal(1),
)


def _cost_report_ctx(
    settings: Settings, handler: Any, *, webhook: str | None = WEBHOOK_URL
) -> dict[str, Any]:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    resources: Any = type("R", (), {"engine": _FakeEngine([]), "http": http})()
    url = SecretStr(webhook) if webhook else None
    return {
        "resources": resources,
        "settings": settings.model_copy(update={"ops_webhook_url": url}),
    }


@pytest.fixture
def seen_windows(monkeypatch: pytest.MonkeyPatch) -> list[tuple[datetime, datetime]]:
    windows: list[tuple[datetime, datetime]] = []

    async def fake_build(conn: object, *, start: datetime, end: datetime) -> CostReport:
        windows.append((start, end))
        return REPORT

    monkeypatch.setattr(worker, "build_cost_report", fake_build)
    return windows


async def test_daily_cost_report_posts_yesterdays_spend_to_the_ops_webhook(
    settings: Settings, seen_windows: list[tuple[datetime, datetime]]
):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    await worker.daily_cost_report(_cost_report_ctx(settings, handler))

    (request,) = requests
    assert str(request.url) == WEBHOOK_URL
    assert json.loads(request.content) == {"text": render_cost_report(REPORT)}
    ((start, end),) = seen_windows
    assert end - start == timedelta(days=1)
    assert end.astimezone(IST).time() == time.min


async def test_daily_cost_report_without_a_webhook_only_logs(
    settings: Settings,
    seen_windows: list[tuple[datetime, datetime]],
    caplog: pytest.LogCaptureFixture,
):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    with caplog.at_level(logging.INFO, logger=worker.logger.name):
        await worker.daily_cost_report(_cost_report_ctx(settings, handler, webhook=None))

    assert requests == []
    assert "Anviq spend for" in caplog.text


async def test_a_rejected_webhook_lets_the_error_surface_without_the_secret_url(
    settings: Settings, seen_windows: list[tuple[datetime, datetime]]
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    with pytest.raises(worker.OpsWebhookError) as raised:
        await worker.daily_cost_report(_cost_report_ctx(settings, handler))

    assert "500" in str(raised.value)
    assert "hooks.example" not in str(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__


async def test_an_unreachable_webhook_surfaces_without_the_secret_url(
    settings: Settings, seen_windows: list[tuple[datetime, datetime]]
):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url}", request=request)

    with pytest.raises(worker.OpsWebhookError) as raised:
        await worker.daily_cost_report(_cost_report_ctx(settings, handler))

    assert "ConnectError" in str(raised.value)
    assert "hooks.example" not in str(raised.value)
    assert raised.value.__suppress_context__


def test_http_client_request_logs_are_silenced_so_the_webhook_url_is_not_logged():
    logging.getLogger("httpx").setLevel(logging.INFO)

    worker.quiet_http_logs()

    assert not logging.getLogger("httpx").isEnabledFor(logging.INFO)


def test_cost_report_runs_daily_at_0800_ist():
    job = _cron_job(worker.daily_cost_report)

    # arq schedules in UTC: 02:30 UTC is 08:00 IST.
    assert (job.hour, job.minute) == (2, 30)


WA_ID = "919999999999"


class _RecordingWhatsApp:
    def __init__(self, log: list[str], *, fail_for: set[str] | None = None) -> None:
        self._log = log
        self._fail_for = fail_for or set()
        self.sent: list[tuple[str, str, str]] = []

    async def send_template(self, to: str, name: str, language_code: str) -> str:
        self._log.append("send")
        if to in self._fail_for:
            raise WhatsAppError("Meta rejected the template")
        self.sent.append((to, name, language_code))
        return "wamid.out"


def _reminder_ctx(
    log: list[str],
    whatsapp: _RecordingWhatsApp | None,
    *,
    wa_ids: tuple[str, ...] = (WA_ID,),
    lang: str = "hi",
) -> tuple[dict[str, Any], list[DueReminder]]:
    cipher = FieldCipher(bytes(32))
    due = [
        DueReminder(
            teacher_id=uuid4(), lang=lang, wa_id_enc=cipher.encrypt(wa_id, context=WA_ID_CONTEXT)
        )
        for wa_id in wa_ids
    ]
    keyring: Any = type("K", (), {"field_cipher": cipher})()
    resources: Any = type(
        "R", (), {"engine": _FakeEngine(log), "whatsapp": whatsapp, "keyring": keyring}
    )()
    return {"resources": resources}, due


@pytest.fixture
def claimed() -> list[ReminderWindow]:
    return []


def _stub_claim(
    monkeypatch: pytest.MonkeyPatch,
    log: list[str],
    due: list[DueReminder],
    windows: list[ReminderWindow],
    unreachable: frozenset[object] = frozenset(),
) -> None:
    async def fake_claim(conn: object, window: ReminderWindow) -> list[DueReminder]:
        log.append("claim")
        windows.append(window)
        return due

    async def reachable(conn: object, teacher_id: object) -> bool:
        log.append("check")
        return teacher_id not in unreachable

    monkeypatch.setattr(worker, "claim_due_reminders", fake_claim)
    monkeypatch.setattr(worker, "still_reachable", reachable)


async def test_a_due_teacher_gets_the_reminder_template_in_their_language(
    monkeypatch: pytest.MonkeyPatch, claimed: list[ReminderWindow]
):
    log: list[str] = []
    whatsapp = _RecordingWhatsApp(log)
    ctx, due = _reminder_ctx(log, whatsapp, lang="en")
    _stub_claim(monkeypatch, log, due, claimed)

    await worker.send_daily_reminders(ctx)

    assert whatsapp.sent == [(WA_ID, "daily_plan_reminder_en", "en")]
    assert len(claimed) == 1


async def test_claims_are_committed_before_any_message_is_sent(
    monkeypatch: pytest.MonkeyPatch, claimed: list[ReminderWindow]
):
    log: list[str] = []
    ctx, due = _reminder_ctx(log, _RecordingWhatsApp(log))
    _stub_claim(monkeypatch, log, due, claimed)

    await worker.send_daily_reminders(ctx)

    assert log[:3] == ["begin", "claim", "commit"]
    assert log.index("send") > log.index("commit")


async def test_one_failed_send_does_not_stop_the_other_reminders(
    monkeypatch: pytest.MonkeyPatch, claimed: list[ReminderWindow]
):
    log: list[str] = []
    whatsapp = _RecordingWhatsApp(log, fail_for={"911111111111"})
    ctx, due = _reminder_ctx(log, whatsapp, wa_ids=("911111111111", "922222222222"))
    _stub_claim(monkeypatch, log, due, claimed)

    await worker.send_daily_reminders(ctx)

    assert [to for to, _, _ in whatsapp.sent] == ["922222222222"]


async def test_an_undecryptable_number_is_skipped_and_the_rest_still_sent(
    monkeypatch: pytest.MonkeyPatch, claimed: list[ReminderWindow]
):
    log: list[str] = []
    whatsapp = _RecordingWhatsApp(log)
    ctx, due = _reminder_ctx(log, whatsapp)
    broken = DueReminder(teacher_id=uuid4(), lang="hi", wa_id_enc=b"not-a-sealed-value-at-all")
    _stub_claim(monkeypatch, log, [broken, *due], claimed)

    await worker.send_daily_reminders(ctx)

    assert [to for to, _, _ in whatsapp.sent] == [WA_ID]


async def test_the_log_reports_counts_and_never_a_phone_number(
    monkeypatch: pytest.MonkeyPatch,
    claimed: list[ReminderWindow],
    caplog: pytest.LogCaptureFixture,
):
    log: list[str] = []
    whatsapp = _RecordingWhatsApp(log, fail_for={"911111111111"})
    ctx, due = _reminder_ctx(log, whatsapp, wa_ids=("911111111111", "922222222222"))
    _stub_claim(monkeypatch, log, due, claimed)

    with caplog.at_level(logging.INFO, logger=worker.logger.name):
        await worker.send_daily_reminders(ctx)

    assert "claimed=2 sent=1 failed=1" in caplog.text
    assert "9111" not in caplog.text
    assert "9222" not in caplog.text


async def test_without_whatsapp_credentials_nothing_is_claimed(
    monkeypatch: pytest.MonkeyPatch, claimed: list[ReminderWindow]
):
    log: list[str] = []
    ctx, due = _reminder_ctx(log, None)
    _stub_claim(monkeypatch, log, due, claimed)

    with pytest.raises(RuntimeError, match="WA_PHONE_NUMBER_ID"):
        await worker.send_daily_reminders(ctx)

    assert log == []


def test_reminders_are_checked_every_quarter_hour():
    job = _cron_job(worker.send_daily_reminders)

    assert (job.hour, job.minute) == (None, {0, 15, 30, 45})


def test_a_reminder_batch_gets_more_time_than_a_single_inbound_job():
    job = _cron_job(worker.send_daily_reminders)

    assert job.timeout_s > worker.JOB_TIMEOUT_S


async def test_a_teacher_who_withdrew_after_the_claim_is_not_messaged(
    monkeypatch: pytest.MonkeyPatch, claimed: list[ReminderWindow], caplog: pytest.LogCaptureFixture
):
    log: list[str] = []
    whatsapp = _RecordingWhatsApp(log)
    ctx, due = _reminder_ctx(log, whatsapp, wa_ids=("911111111111", "922222222222"))
    _stub_claim(monkeypatch, log, due, claimed, unreachable=frozenset({due[0].teacher_id}))

    with caplog.at_level(logging.INFO, logger=worker.logger.name):
        await worker.send_daily_reminders(ctx)

    assert [to for to, _, _ in whatsapp.sent] == ["922222222222"]
    assert "skipped=1" in caplog.text


async def test_an_unexpected_error_for_one_teacher_does_not_lose_the_rest_of_the_batch(
    monkeypatch: pytest.MonkeyPatch, claimed: list[ReminderWindow]
):
    log: list[str] = []
    whatsapp = _RecordingWhatsApp(log)
    ctx, due = _reminder_ctx(log, whatsapp, wa_ids=("911111111111", "922222222222"))
    _stub_claim(monkeypatch, log, due, claimed)
    original = whatsapp.send_template

    async def flaky(to: str, name: str, language_code: str) -> str:
        if to == "911111111111":
            raise KeyError("surprise")
        return await original(to, name, language_code)

    whatsapp.send_template = flaky  # type: ignore[method-assign]

    await worker.send_daily_reminders(ctx)

    assert [to for to, _, _ in whatsapp.sent] == ["922222222222"]


async def test_worker_startup_turns_on_error_reporting_with_the_deployed_environment(
    monkeypatch: pytest.MonkeyPatch,
):
    started: list[tuple[object, str]] = []
    settings: Any = type("S", (), {"sentry_dsn": "dsn", "app_env": "staging"})()

    @asynccontextmanager
    async def fake_resources(_: object) -> AsyncIterator[object]:
        yield type("R", (), {"whatsapp": object()})()

    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    monkeypatch.setattr(worker, "open_resources", fake_resources)
    monkeypatch.setattr(worker, "build_brain", lambda *_: object())
    monkeypatch.setattr(worker, "build_pipeline", lambda *_, **__: object())
    monkeypatch.setattr(
        worker, "init_sentry", lambda dsn, *, environment: started.append((dsn, environment))
    )
    ctx: dict[str, Any] = {}

    await worker.on_startup(ctx)
    await worker.on_shutdown(ctx)

    assert started == [("dsn", "staging")]


async def test_worker_starts_without_whatsapp_so_the_retention_purge_still_runs(
    monkeypatch: pytest.MonkeyPatch,
):
    settings: Any = type("S", (), {"sentry_dsn": None, "app_env": "staging"})()

    @asynccontextmanager
    async def fake_resources(_: object) -> AsyncIterator[object]:
        yield type("R", (), {"whatsapp": None})()

    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    monkeypatch.setattr(worker, "open_resources", fake_resources)
    monkeypatch.setattr(worker, "init_sentry", lambda dsn, *, environment: None)
    ctx: dict[str, Any] = {}

    await worker.on_startup(ctx)
    await worker.on_shutdown(ctx)

    assert ctx["pipeline"] is None


async def test_an_inbound_job_fails_loudly_when_there_is_no_whatsapp_pipeline():
    ctx: dict[str, Any] = {"pipeline": None}

    with pytest.raises(RuntimeError, match="WA_PHONE_NUMBER_ID"):
        await worker.handle_inbound(ctx, {})
