import json
from contextlib import ExitStack
from typing import Any

import fakeredis
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_inbound_guard, get_job_queue
from app.channel.inbound_guard import InboundGuard
from app.config import Settings, get_settings
from app.main import create_app
from app.privacy.crypto import decode_key, phone_hash
from tests.conftest import TEST_APP_SECRET, sign

URL = "/webhook/whatsapp"
SENDER = "919999999999"
PEPPER_B64 = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="


class FakeQueue:
    def __init__(self) -> None:
        self.jobs: list[tuple[dict[str, Any], str]] = []
        self.fail = False

    async def enqueue(self, envelope: dict[str, Any], *, job_id: str) -> None:
        if self.fail:
            raise ConnectionError("redis down")
        self.jobs.append((envelope, job_id))


def _payload(*messages: dict[str, Any]) -> bytes:
    return json.dumps({"entry": [{"changes": [{"value": {"messages": list(messages)}}]}]}).encode()


def _text(message_id: str, sender: str = SENDER) -> dict[str, Any]:
    return {"id": message_id, "from": sender, "type": "text", "text": {"body": "Namaste"}}


@pytest.fixture
def queue() -> FakeQueue:
    return FakeQueue()


@pytest.fixture
def server() -> fakeredis.FakeServer:
    return fakeredis.FakeServer()


@pytest.fixture
def make_client(queue: FakeQueue, server: fakeredis.FakeServer):
    # Entering each client keeps one event loop alive, which fakeredis' async queues require.
    with ExitStack() as stack:

        def _make(*, rate_limit: int = 60, pepper: str | None = PEPPER_B64) -> TestClient:
            settings = Settings(
                app_env="local",
                wa_verify_token="t",
                wa_app_secret=TEST_APP_SECRET,
                phone_pepper=pepper,
                _env_file=None,
            )
            guard = InboundGuard(fakeredis.FakeAsyncRedis(server=server), rate_limit=rate_limit)
            app = create_app(manage_resources=False)
            app.dependency_overrides[get_settings] = lambda: settings
            app.dependency_overrides[get_inbound_guard] = lambda: guard
            app.dependency_overrides[get_job_queue] = lambda: queue
            return stack.enter_context(TestClient(app))

        yield _make


def _post(client: TestClient, body: bytes):
    return client.post(URL, content=body, headers={"X-Hub-Signature-256": sign(body)})


def test_enqueues_new_message_with_wa_message_id_as_job_id(make_client, queue):
    response = _post(make_client(), _payload(_text("wamid.1")))

    assert response.status_code == 200
    assert [job_id for _, job_id in queue.jobs] == ["wamid.1"]
    assert queue.jobs[0][0]["text"] == "Namaste"


def test_duplicate_delivery_is_enqueued_once(make_client, queue):
    client = make_client()
    body = _payload(_text("wamid.1"))

    first, second = _post(client, body), _post(client, body)

    assert first.status_code == second.status_code == 200
    assert len(queue.jobs) == 1


def test_batch_with_one_repeat_enqueues_only_the_new_message(make_client, queue):
    client = make_client()
    _post(client, _payload(_text("wamid.1")))

    _post(client, _payload(_text("wamid.1"), _text("wamid.2")))

    assert [job_id for _, job_id in queue.jobs] == ["wamid.1", "wamid.2"]


def test_sender_over_rate_limit_is_dropped_but_acked(make_client, queue):
    client = make_client(rate_limit=2)

    responses = [_post(client, _payload(_text(f"wamid.{i}"))) for i in range(3)]

    assert [r.status_code for r in responses] == [200, 200, 200]
    assert len(queue.jobs) == 2


def test_rate_limit_is_per_sender(make_client, queue):
    client = make_client(rate_limit=1)
    _post(client, _payload(_text("wamid.1", "911111111111")))
    _post(client, _payload(_text("wamid.2", "922222222222")))

    assert len(queue.jobs) == 2


def test_duplicate_deliveries_do_not_consume_rate_limit_quota(make_client, queue):
    client = make_client(rate_limit=2)
    body = _payload(_text("wamid.1"))

    for _ in range(5):
        _post(client, body)
    _post(client, _payload(_text("wamid.2")))

    assert [job_id for _, job_id in queue.jobs] == ["wamid.1", "wamid.2"]


def test_status_only_payload_enqueues_nothing(make_client, queue):
    body = json.dumps(
        {"entry": [{"changes": [{"value": {"statuses": [{"id": "x", "status": "read"}]}}]}]}
    ).encode()

    response = _post(make_client(), body)

    assert response.status_code == 200
    assert queue.jobs == []


def test_unsupported_media_is_still_enqueued_so_worker_can_reply_politely(make_client, queue):
    image = {"id": "wamid.9", "from": SENDER, "type": "image", "image": {"id": "m"}}

    _post(make_client(), _payload(image))

    assert queue.jobs[0][0]["kind"] == "unsupported"


def test_enqueue_failure_returns_503_and_releases_dedupe_so_meta_retry_succeeds(make_client, queue):
    client = make_client()
    body = _payload(_text("wamid.1"))
    queue.fail = True

    failed = _post(client, body)
    queue.fail = False
    retried = _post(client, body)

    assert failed.status_code == 503
    assert retried.status_code == 200
    assert [job_id for _, job_id in queue.jobs] == ["wamid.1"]


def test_rate_limit_key_is_hash_not_raw_phone(make_client, server):
    _post(make_client(), _payload(_text("wamid.1")))

    keys = [k.decode() for k in fakeredis.FakeRedis(server=server).keys("ratelimit:*")]

    expected = phone_hash(decode_key(PEPPER_B64), SENDER).hex()
    assert keys == [f"ratelimit:{expected}"]
