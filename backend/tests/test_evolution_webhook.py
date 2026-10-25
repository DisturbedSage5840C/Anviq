import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_inbound_guard, get_job_queue
from app.channel.messages import InboundKind, InboundMessage
from app.config import Settings, get_settings
from app.main import create_app
from tests.conftest import AllowAllGuard

URL = "/webhook/evolution"
SECRET = "evolution-webhook-secret-0123456789"
HEADER = "X-Anviq-Webhook-Secret"
SENDER = "919800000001"
MESSAGE_ID = "3EB0A1B2C3D4E5F6"
TEXT = "How do I teach letter sounds?"

EVOLUTION = {
    "whatsapp_provider": "evolution",
    "evolution_base_url": "http://evolution:8080",
    "evolution_api_key": "evolution-global-api-key-value",
    "evolution_instance": "anviq-demo",
    "evolution_webhook_secret": SECRET,
}


def _upsert(message: dict[str, Any] | None = None, **key: Any) -> dict[str, Any]:
    return {
        "event": "messages.upsert",
        "instance": "anviq-demo",
        "data": {
            "key": {
                "remoteJid": f"{SENDER}@s.whatsapp.net",
                "fromMe": False,
                "id": MESSAGE_ID,
                **key,
            },
            "message": message if message is not None else {"conversation": TEXT},
            "messageTimestamp": 1_799_999_990,
        },
    }


class RecordingQueue:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.jobs: list[tuple[dict[str, Any], str]] = []

    async def enqueue(self, envelope: dict[str, Any], *, job_id: str) -> None:
        if self.fail:
            raise ConnectionError("redis down")
        self.jobs.append((envelope, job_id))


class SeenGuard(AllowAllGuard):
    async def claim_message(self, wa_message_id: str) -> bool:
        return False


class ClaimOnceGuard(AllowAllGuard):
    """Dedupes like the real guard: a claimed id is refused until it is released."""

    def __init__(self) -> None:
        self.claimed: set[str] = set()

    async def claim_message(self, wa_message_id: str) -> bool:
        if wa_message_id in self.claimed:
            return False
        self.claimed.add(wa_message_id)
        return True

    async def release_message(self, wa_message_id: str) -> None:
        self.claimed.discard(wa_message_id)


def _settings(**overrides: str) -> Settings:
    return Settings(
        app_env="local",
        wa_verify_token="v",
        wa_app_secret="s",
        _env_file=None,
        **{**EVOLUTION, **overrides},
    )


def _client(settings: Settings, queue: RecordingQueue, guard: Any = AllowAllGuard) -> TestClient:
    app = create_app(manage_resources=False)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_inbound_guard] = guard
    app.dependency_overrides[get_job_queue] = lambda: queue
    return TestClient(app)


def _post(client: TestClient, payload: Any, secret: str | None = SECRET) -> Any:
    headers = {HEADER: secret} if secret is not None else {}
    return client.post(URL, content=json.dumps(payload), headers=headers)


@pytest.fixture
def queue() -> RecordingQueue:
    return RecordingQueue()


@pytest.fixture
def evolution_client(queue: RecordingQueue) -> Iterator[TestClient]:
    with _client(_settings(), queue) as client:
        yield client


def test_a_text_message_with_the_secret_is_queued_and_acknowledged(
    evolution_client: TestClient, queue: RecordingQueue
) -> None:
    response = _post(evolution_client, _upsert())

    assert response.status_code == 200
    assert response.json() == {"queued": 1}
    [(envelope, job_id)] = queue.jobs
    assert job_id == MESSAGE_ID
    message = InboundMessage.from_envelope(envelope)
    assert (message.kind, message.sender_wa_id, message.text) == (InboundKind.TEXT, SENDER, TEXT)


def test_a_voice_note_is_queued_as_audio_keyed_by_its_message_id(
    evolution_client: TestClient, queue: RecordingQueue
) -> None:
    body = {"audioMessage": {"mimetype": "audio/ogg; codecs=opus", "ptt": True}}

    response = _post(evolution_client, _upsert(body))

    assert response.status_code == 200
    message = InboundMessage.from_envelope(queue.jobs[0][0])
    assert (message.kind, message.media_id) == (InboundKind.AUDIO, MESSAGE_ID)


@pytest.mark.parametrize("secret", [None, "", "wrong-secret-wrong-secret-wrong", SECRET + "x"])
def test_a_missing_or_wrong_secret_is_rejected_and_nothing_is_queued(
    evolution_client: TestClient, queue: RecordingQueue, secret: str | None
) -> None:
    response = _post(evolution_client, _upsert(), secret=secret)

    assert response.status_code == 401
    assert queue.jobs == []


def test_a_redelivered_message_is_acked_but_not_queued_again(queue: RecordingQueue) -> None:
    with _client(_settings(), queue, guard=SeenGuard) as client:
        response = _post(client, _upsert())

    assert response.status_code == 200
    assert response.json() == {"queued": 0}
    assert queue.jobs == []


@pytest.mark.parametrize(
    "payload",
    [
        {"event": "connection.update", "data": {"state": "open"}},
        {"event": "qrcode.updated", "data": {}},
        _upsert(fromMe=True),
        _upsert(remoteJid="120363000000000000@g.us"),
        {},
        [],
        "text",
    ],
)
def test_events_that_are_not_teacher_messages_are_acked_without_queueing(
    evolution_client: TestClient, queue: RecordingQueue, payload: Any
) -> None:
    response = _post(evolution_client, payload)

    assert response.status_code == 200
    assert queue.jobs == []


def test_a_queue_failure_answers_503_so_evolution_redelivers() -> None:
    failing = RecordingQueue(fail=True)
    with _client(_settings(), failing) as client:
        response = _post(client, _upsert())

    assert response.status_code == 503
    assert failing.jobs == []


def test_a_redelivery_after_a_queue_failure_is_queued_because_the_claim_was_released() -> None:
    guard = ClaimOnceGuard()
    with _client(_settings(), RecordingQueue(fail=True), lambda: guard) as client:
        _post(client, _upsert())
    healthy = RecordingQueue()
    with _client(_settings(), healthy, lambda: guard) as client:
        _post(client, _upsert())

    assert [job_id for _, job_id in healthy.jobs] == [MESSAGE_ID]


def test_a_body_that_is_not_json_is_refused(
    evolution_client: TestClient, queue: RecordingQueue
) -> None:
    response = evolution_client.post(URL, content=b"not json", headers={HEADER: SECRET})

    assert response.status_code == 400
    assert queue.jobs == []


def test_an_oversized_body_is_refused(evolution_client: TestClient, queue: RecordingQueue) -> None:
    response = evolution_client.post(
        URL, content=b'{"event":"' + b"a" * 300_000 + b'"}', headers={HEADER: SECRET}
    )

    assert response.status_code == 413
    assert queue.jobs == []


def test_the_secret_is_checked_before_the_body_is_read(
    evolution_client: TestClient, queue: RecordingQueue
) -> None:
    response = evolution_client.post(URL, content=b"a" * 300_000)

    assert response.status_code == 401


def test_the_route_is_absent_when_the_provider_is_not_evolution(queue: RecordingQueue) -> None:
    meta = Settings(app_env="local", wa_verify_token="v", wa_app_secret="s", _env_file=None)
    with _client(meta, queue) as client:
        response = _post(client, _upsert())

    assert response.status_code == 404
    assert queue.jobs == []


def test_logs_carry_no_message_text_sender_or_secret(
    evolution_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        _post(evolution_client, _upsert())
        _post(evolution_client, _upsert(), secret="wrong-secret-wrong-secret-wrong")

    logged = " ".join(record.getMessage() for record in caplog.records)
    assert TEXT not in logged
    assert SENDER not in logged
    assert SECRET not in logged
