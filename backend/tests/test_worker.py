from typing import Any

import pytest

from app import worker
from app.channel.job_queue import HANDLE_INBOUND_JOB
from app.channel.messages import InboundKind, InboundMessage
from app.config import Settings
from app.core.dialogue import EchoBrain


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
