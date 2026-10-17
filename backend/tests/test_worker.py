from typing import Any

import pytest

from app import worker
from app.channel.job_queue import HANDLE_INBOUND_JOB
from app.channel.messages import InboundKind, InboundMessage
from app.config import Settings
from app.core.dialogue import EchoBrain
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


def test_retention_purge_is_scheduled_hourly_on_the_hour():
    (job,) = worker.WorkerSettings.cron_jobs

    assert job.coroutine is worker.purge_retention
    assert (job.hour, job.minute) == (None, 0)
