import logging
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_inbound_guard, get_job_queue
from app.channel.messages import InboundKind, InboundMessage
from app.channel.twilio_signature import twilio_signature
from app.config import Settings, get_settings
from app.main import create_app
from tests.conftest import AllowAllGuard

URL = "/webhook/twilio"
SID = "AC" + "1" * 32
TOKEN = "twilio-auth-token-value"
PUBLIC_URL = "https://demo.example.test/webhook/twilio"
SENDER = "919800000001"

TEXT_FORM = {
    "MessageSid": "SM0001",
    "From": f"whatsapp:+{SENDER}",
    "To": "whatsapp:+14155238886",
    "Body": "How do I teach letter sounds?",
    "NumMedia": "0",
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
    twilio = {
        "whatsapp_provider": "twilio",
        "twilio_account_sid": SID,
        "twilio_auth_token": TOKEN,
        "twilio_whatsapp_from": "+14155238886",
        "twilio_webhook_url": PUBLIC_URL,
    }
    return Settings(
        app_env="local",
        wa_verify_token="v",
        wa_app_secret="s",
        _env_file=None,
        **{**twilio, **overrides},
    )


def _client(settings: Settings, queue: RecordingQueue, guard: Any = AllowAllGuard) -> TestClient:
    app = create_app(manage_resources=False)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_inbound_guard] = guard
    app.dependency_overrides[get_job_queue] = lambda: queue
    return TestClient(app)


def _signed(form: dict[str, str], token: str = TOKEN, url: str = PUBLIC_URL) -> dict[str, str]:
    return {"X-Twilio-Signature": twilio_signature(token, url, list(form.items()))}


@pytest.fixture
def queue() -> RecordingQueue:
    return RecordingQueue()


@pytest.fixture
def twilio_client(queue: RecordingQueue) -> Iterator[TestClient]:
    with _client(_settings(), queue) as client:
        yield client


def test_a_signed_text_message_is_queued_and_answered_with_empty_twiml(
    twilio_client: TestClient, queue: RecordingQueue
) -> None:
    response = twilio_client.post(URL, data=TEXT_FORM, headers=_signed(TEXT_FORM))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert "<Response" in response.text and "<Message" not in response.text
    [(envelope, job_id)] = queue.jobs
    assert job_id == "SM0001"
    message = InboundMessage.from_envelope(envelope)
    assert (message.kind, message.sender_wa_id) == (InboundKind.TEXT, SENDER)
    assert message.text == TEXT_FORM["Body"]


def test_a_signed_voice_note_is_queued_as_audio_with_its_media_url(
    twilio_client: TestClient, queue: RecordingQueue
) -> None:
    form = {
        **TEXT_FORM,
        "Body": "",
        "NumMedia": "1",
        "MediaUrl0": "https://api.twilio.com/2010-04-01/Accounts/AC/Messages/MM1/Media/ME1",
        "MediaContentType0": "audio/ogg",
    }

    response = twilio_client.post(URL, data=form, headers=_signed(form))

    assert response.status_code == 200
    message = InboundMessage.from_envelope(queue.jobs[0][0])
    assert (message.kind, message.media_id) == (InboundKind.AUDIO, form["MediaUrl0"])


def test_a_wrong_signature_is_rejected_and_nothing_is_queued(
    twilio_client: TestClient, queue: RecordingQueue
) -> None:
    response = twilio_client.post(URL, data=TEXT_FORM, headers=_signed(TEXT_FORM, token="other"))

    assert response.status_code == 401
    assert queue.jobs == []


def test_a_missing_signature_is_rejected(twilio_client: TestClient, queue: RecordingQueue) -> None:
    response = twilio_client.post(URL, data=TEXT_FORM)

    assert response.status_code == 401
    assert queue.jobs == []


def test_a_form_changed_after_signing_is_rejected(
    twilio_client: TestClient, queue: RecordingQueue
) -> None:
    headers = _signed(TEXT_FORM)

    response = twilio_client.post(
        URL, data={**TEXT_FORM, "Body": "something else"}, headers=headers
    )

    assert response.status_code == 401
    assert queue.jobs == []


def test_a_signature_made_for_another_url_is_rejected(
    twilio_client: TestClient, queue: RecordingQueue
) -> None:
    headers = _signed(TEXT_FORM, url="https://evil.example.test/webhook/twilio")

    response = twilio_client.post(URL, data=TEXT_FORM, headers=headers)

    assert response.status_code == 401
    assert queue.jobs == []


def test_a_redelivered_message_is_acked_but_not_queued_again(queue: RecordingQueue) -> None:
    with _client(_settings(), queue, guard=SeenGuard) as client:
        response = client.post(URL, data=TEXT_FORM, headers=_signed(TEXT_FORM))

    assert response.status_code == 200
    assert queue.jobs == []


def test_a_signed_form_with_no_usable_message_is_acked_without_queueing(
    twilio_client: TestClient, queue: RecordingQueue
) -> None:
    status_callback = {"MessageStatus": "delivered", "SmsStatus": "delivered"}

    response = twilio_client.post(URL, data=status_callback, headers=_signed(status_callback))

    assert response.status_code == 200
    assert queue.jobs == []


def test_a_queue_failure_asks_the_teacher_to_resend_because_twilio_does_not_retry_5xx() -> None:
    failing = RecordingQueue(fail=True)
    with _client(_settings(), failing) as client:
        response = client.post(URL, data=TEXT_FORM, headers=_signed(TEXT_FORM))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert "<Message>" in response.text and "again" in response.text
    assert failing.jobs == []


def test_a_resend_after_a_queue_failure_is_queued_because_the_claim_was_released() -> None:
    guard = ClaimOnceGuard()
    with _client(_settings(), RecordingQueue(fail=True), lambda: guard) as client:
        client.post(URL, data=TEXT_FORM, headers=_signed(TEXT_FORM))
    healthy = RecordingQueue()
    with _client(_settings(), healthy, lambda: guard) as client:
        client.post(URL, data=TEXT_FORM, headers=_signed(TEXT_FORM))

    assert [job_id for _, job_id in healthy.jobs] == ["SM0001"]


def test_an_oversized_body_is_refused_before_anything_else(
    twilio_client: TestClient, queue: RecordingQueue
) -> None:
    response = twilio_client.post(
        URL,
        content=b"Body=" + b"a" * 70_000,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 413
    assert queue.jobs == []


def test_a_form_with_an_absurd_number_of_fields_is_refused(
    twilio_client: TestClient, queue: RecordingQueue
) -> None:
    many = {f"f{i}": "x" for i in range(500)}

    response = twilio_client.post(URL, data=many, headers=_signed(many))

    assert response.status_code == 400
    assert queue.jobs == []


def test_the_route_is_absent_when_the_provider_is_not_twilio(queue: RecordingQueue) -> None:
    meta = Settings(app_env="local", wa_verify_token="v", wa_app_secret="s", _env_file=None)
    with _client(meta, queue) as client:
        response = client.post(URL, data=TEXT_FORM, headers=_signed(TEXT_FORM))

    assert response.status_code == 404
    assert queue.jobs == []


def test_logs_carry_no_message_text_or_sender(
    twilio_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        twilio_client.post(URL, data=TEXT_FORM, headers=_signed(TEXT_FORM))
        twilio_client.post(URL, data=TEXT_FORM, headers=_signed(TEXT_FORM, token="other"))

    logged = " ".join(record.getMessage() for record in caplog.records)
    assert TEXT_FORM["Body"] not in logged
    assert SENDER not in logged
    assert TOKEN not in logged
